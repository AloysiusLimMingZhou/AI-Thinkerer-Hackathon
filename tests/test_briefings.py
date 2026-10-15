import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from meeting_agent.briefings import BriefingService
from meeting_agent.knowledge import KnowledgeService
from meeting_agent.models import SessionCreate
from meeting_agent.repository import SQLiteRepository
from test_api import make_client


def harness(tmp_path):
    repo = SQLiteRepository(tmp_path/"briefings.db")
    knowledge = KnowledgeService(repo)
    return SimpleNamespace(repo=repo, knowledge=knowledge, service=BriefingService(repo,knowledge))


def test_additive_session_migration(tmp_path):
    path = tmp_path/"old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY,title TEXT,owner_name TEXT,agent_name TEXT,meeting_url TEXT,status TEXT,created_at TEXT)")
        db.execute("INSERT INTO sessions VALUES('old','History','Aloy','Alloy',NULL,'created','2026-10-15T00:00:00+00:00')")
    repo = SQLiteRepository(path)
    session = repo.get_session("old")
    assert session.title == "History"
    assert session.platform == "google_meet" and session.purpose == "meeting"
    assert session.source_briefing_id is None


@pytest.mark.asyncio
async def test_briefing_copy_survives_source_delete(tmp_path):
    h = harness(tmp_path)
    draft = h.service.create(SessionCreate(title="Launch brief", owner_name="Aloy"))
    text = "Launch facts. " * 600 + "Final deadline Friday."
    await h.knowledge.ingest(draft.id, text)
    assert h.service.list() == []
    h.service.prepare(draft.id)
    meeting = h.service.snapshot(draft.id, SessionCreate(title="Voice call",owner_name="ignored"))
    assert meeting.platform == "discord" and meeting.purpose == "meeting"
    assert meeting.owner_name == "Aloy" and meeting.source_briefing_id == draft.id
    with h.repo._connect() as db:
        original = db.execute("SELECT content FROM knowledge_sources WHERE session_id=?",(draft.id,)).fetchone()[0]
        copied = db.execute("SELECT content FROM knowledge_sources WHERE session_id=?",(meeting.id,)).fetchone()[0]
        original_locators = [r[0] for r in db.execute("SELECT locator FROM knowledge_chunks WHERE source_id IN (SELECT id FROM knowledge_sources WHERE session_id=?) ORDER BY locator",(draft.id,))]
        copied_locators = [r[0] for r in db.execute("SELECT locator FROM knowledge_chunks WHERE source_id IN (SELECT id FROM knowledge_sources WHERE session_id=?) ORDER BY locator",(meeting.id,))]
    assert copied == original == text
    assert original_locators == copied_locators
    h.service.delete(draft.id)
    assert h.repo.get_session(draft.id) is None
    assert h.knowledge.search(meeting.id, "deadline Friday")
    assert h.repo.get_session(meeting.id).source_briefing_id == draft.id


def test_empty_snapshot_and_only_explicit_ready_briefings(tmp_path):
    h = harness(tmp_path)
    ordinary = h.repo.create_session(SessionCreate(title="Old meeting",owner_name="Aloy"))
    draft = h.service.create(SessionCreate(title="Prepared",owner_name="Aloy"))
    assert h.service.list() == []
    with pytest.raises(HTTPException):
        h.service.snapshot(draft.id, SessionCreate(title="Call",owner_name="Aloy"))
    h.service.prepare(draft.id)
    assert [b.id for b in h.service.list(query="prep")] == [draft.id]
    with pytest.raises(HTTPException):
        h.service.snapshot(ordinary.id, SessionCreate(title="Call",owner_name="Aloy"))
    empty = h.service.snapshot(None, SessionCreate(title="Empty",owner_name="Aloy"))
    assert h.knowledge.list_sources(empty.id) == []
    assert empty.platform == "discord"


def test_failed_upload_stays_unselectable_and_can_recover(tmp_path):
    client, _ = make_client(tmp_path)
    created = client.post("/briefings", json={"title":"Brief","owner_name":"Aloy"})
    assert created.status_code == 201
    sid = created.json()["id"]
    assert client.post(f"/sessions/{sid}/knowledge", files={"files":("bad.exe",b"bad")}).status_code == 422
    assert client.get("/briefings").json() == []
    assert client.get("/briefings?include_drafts=true").json()[0]["id"] == sid
    assert client.post(f"/sessions/{sid}/knowledge", data={"text":"Budget is 500."}).status_code == 201
    assert client.post(f"/briefings/{sid}/prepare").status_code == 200
    assert client.get("/briefings").json()[0]["briefing_ready"] is True
    assert client.get(f"/sessions/{sid}/bot").status_code == 404
    patched = client.patch(f"/briefings/{sid}",json={"title":"Edited","owner_name":"Aloy","agent_name":"Note bot"})
    assert patched.json()["title"] == "Edited"
    assert client.delete(f"/briefings/{sid}").status_code == 204
    assert client.get(f"/sessions/{sid}").status_code == 404


def test_snapshot_failure_rolls_back_new_session(tmp_path, monkeypatch):
    h = harness(tmp_path)
    draft = h.service.create(SessionCreate(title="Prepared",owner_name="Aloy"))
    h.service.prepare(draft.id)
    def fail(*args, **kwargs):
        raise ValueError("copy failed")
    monkeypatch.setattr(h.knowledge, "copy_into", fail)
    with pytest.raises(ValueError):
        h.service.snapshot(draft.id, SessionCreate(title="Call",owner_name="Aloy"))
    assert len(h.repo.list_sessions()) == 1


def test_briefing_cannot_create_meeting_history_or_be_deleted_as_meeting(tmp_path):
    client, _ = make_client(tmp_path)
    sid = client.post("/briefings",json={"title":"Brief","owner_name":"Aloy"}).json()["id"]
    for path, body in [("utterances",{"speaker":"Guest","text":"Alloy, hi!"}), ("speak",{"text":"Hi!"}), ("coach",{"latest_message":"Hi!"})]:
        assert client.post(f"/sessions/{sid}/{path}",json=body).status_code == 409
    assert client.post(f"/sessions/{sid}/minutes").status_code == 409
    meeting = client.post("/sessions",json={"title":"Meeting","owner_name":"Aloy"}).json()["id"]
    assert client.delete(f"/briefings/{meeting}").status_code == 409
    assert client.post("/sessions",json={"title":"Bad","owner_name":"Aloy","platform":"discord","meeting_url":"https://meet.google.com/test"}).status_code == 422
