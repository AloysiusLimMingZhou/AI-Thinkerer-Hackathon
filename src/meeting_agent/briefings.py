"""Explicit, owner-prepared Discord knowledge templates and independent snapshots."""
from fastapi import HTTPException
from .models import SessionCreate


class BriefingService:
    def __init__(self, repository, knowledge):
        self.repository, self.knowledge = repository, knowledge

    def _require(self, id, *, ready=False, connection=None):
        if connection is not None:
            row = connection.execute("SELECT * FROM sessions WHERE id=?", (id,)).fetchone()
            session = self.repository._session_from_row(row) if row else None
        else:
            session = self.repository.get_session(id)
        if session is None:
            raise HTTPException(404, "Briefing not found")
        if session.platform != "discord" or session.purpose != "briefing":
            raise HTTPException(409, "Choose an explicitly prepared Discord briefing")
        if ready and not session.briefing_ready:
            raise HTTPException(409, "Finish saving this briefing before selecting it")
        return session

    def create(self, payload: SessionCreate):
        if payload.meeting_url:
            raise HTTPException(422, "Discord briefings do not use meeting URLs")
        payload = payload.model_copy(update={"platform":"discord","purpose":"briefing","briefing_ready":False,"source_briefing_id":None})
        return self.repository.create_session(payload)

    def list(self, query="", limit=25, *, include_drafts=False):
        if not 1 <= limit <= 25:
            raise ValueError("Briefing list limit must be 1-25")
        return [session for session in self.repository.list_sessions()
            if session.platform=="discord" and session.purpose=="briefing"
            and (include_drafts or session.briefing_ready)
            and query.casefold() in session.title.casefold()][:limit]

    def prepare(self, id):
        with self.repository._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(id,connection=db)
            db.execute("UPDATE sessions SET briefing_ready=1 WHERE id=?", (id,))
        return self._require(id)

    def update(self, id, *, title, owner_name, agent_name):
        payload = SessionCreate(title=title,owner_name=owner_name,agent_name=agent_name)
        with self.repository._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(id,connection=db)
            db.execute("UPDATE sessions SET title=?,owner_name=?,agent_name=? WHERE id=?",
                (payload.title,payload.owner_name,payload.agent_name,id))
        return self._require(id)

    def delete(self, id):
        with self.repository._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(id,connection=db)
            db.execute("DELETE FROM knowledge_chunks WHERE source_id IN (SELECT id FROM knowledge_sources WHERE session_id=?)",(id,))
            for table in ("knowledge_sources","context_notes","events"):
                db.execute(f"DELETE FROM {table} WHERE session_id=?",(id,))
            db.execute("DELETE FROM sessions WHERE id=?",(id,))

    def snapshot(self, id, payload: SessionCreate):
        if id:
            self.knowledge.sync_legacy(id)
        with self.repository._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            source = self._require(id,ready=True,connection=db) if id else None
            update = {"platform":"discord","purpose":"meeting","meeting_url":None,
                "briefing_ready":False,"source_briefing_id":id}
            if source:
                update.update(owner_name=source.owner_name,agent_name=source.agent_name)
            meeting = self.repository.create_session(payload.model_copy(update=update),connection=db)
            if source:
                self.knowledge.copy_into(id,meeting.id,connection=db)
        return meeting
