import asyncio
from datetime import UTC,datetime
from types import SimpleNamespace
from uuid import uuid4
import pytest
from meeting_agent.knowledge import KnowledgeService
from meeting_agent.meeting_models import BrainAnswer,AnswerEvidence,MeetingUtterance,UNKNOWN_ANSWER
from meeting_agent.meeting_service import MeetingService
from meeting_agent.models import SessionCreate,ContextNoteCreate
from meeting_agent.repository import SQLiteRepository


class FakePlayback:
    def __init__(self): self.queued=[]; self.live=True; self._muted=False
    async def is_live(self,sid): return self.live
    def muted(self,sid): return self._muted
    def available(self,sid): return True
    async def enqueue(self,sid,text,key): self.queued.append(SimpleNamespace(session_id=sid,text=text,key=key)); return key
    async def mute(self,sid,muted): self._muted=muted
    async def stop(self,sid): pass


class EvidenceBrain:
    async def answer(self,session,question,history,context):
        return BrainAnswer(kind='supported',text='Friday.',evidence=[AnswerEvidence(chunk_id=context[0].id,quote='Launch Friday.')])


def harness(tmp_path,knowledge=True):
    repo=SQLiteRepository(tmp_path/'meeting.db')
    sid=repo.create_session(SessionCreate(title='Launch',owner_name='Aloy')).id
    if knowledge: repo.add_context(sid,[ContextNoteCreate(title='Launch',content='Launch Friday.')])
    store=KnowledgeService(repo); playback=FakePlayback(); brain=EvidenceBrain()
    service=MeetingService(repo,brain,store,playback)
    def utterance(text='Alloy, when is launch?',**kwargs):
        values=dict(event_id=str(uuid4()),platform='google_meet',speaker='Jamie',participant_id='jamie',text=text)
        values.update(kwargs)
        return MeetingUtterance(**values)
    return SimpleNamespace(repo=repo,sid=sid,knowledge=store,playback=playback,brain=brain,service=service,utterance=utterance)


@pytest.mark.asyncio
async def test_supported_evidence_and_event_deduplication(tmp_path):
    h=harness(tmp_path); u=h.utterance(event_id='same-provider-id')
    decision=await h.service.ingest(h.sid,u)
    assert decision.action=='answer'
    assert decision.citations[0].quote=='Launch Friday.'
    assert decision.citations[0].locator.startswith('note')
    assert decision==await h.service.ingest(h.sid,u)
    assert len(h.playback.queued)==1
    assert h.repo.get_transcript(h.sid)[0].participant_id=='jamie'
    assert h.repo.get_transcript(h.sid)[0].spoken_at==u.spoken_at


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,quote',[('supported','invented fact'),('social','Launch Friday.')])
async def test_invalid_evidence_and_social_label_cannot_bypass_grounding(tmp_path,kind,quote):
    h=harness(tmp_path)
    async def answer(session,question,history,context):
        return BrainAnswer(kind=kind,text='Unapproved facts',evidence=[AnswerEvidence(chunk_id=context[0].id,quote=quote)])
    h.service.brain.answer=answer
    result=await h.service.ingest(h.sid,h.utterance())
    assert result.action=='defer'
    assert h.playback.queued[0].text==UNKNOWN_ANSWER
    assert result.citations==[]


@pytest.mark.asyncio
async def test_preview_never_plays_audio_and_force_cannot_invent(tmp_path):
    h=harness(tmp_path,knowledge=False)
    result=await h.service.ingest(h.sid,h.utterance(text='Tell me the budget',force_answer=True),preview=True)
    assert result.action=='defer'
    assert h.playback.queued==[]


@pytest.mark.asyncio
async def test_final_revision_of_partial_is_not_lost(tmp_path):
    h=harness(tmp_path)
    partial=h.utterance(text='Alloy, when',event_id='caption-1',is_final=False)
    assert (await h.service.ingest(h.sid,partial)).action=='stay_silent'
    final=h.utterance(event_id='caption-1')
    assert (await h.service.ingest(h.sid,final)).action=='answer'


@pytest.mark.asyncio
async def test_one_slow_meeting_does_not_block_another(tmp_path):
    h=harness(tmp_path)
    other=h.repo.create_session(SessionCreate(title='Other',owner_name='Aloy')).id
    h.repo.add_context(other,[ContextNoteCreate(title='Launch',content='Launch Friday.')])
    started,release=asyncio.Event(),asyncio.Event()
    original=h.brain.answer
    async def answer(session,*args):
        if session.id==h.sid: started.set(); await release.wait()
        return await original(session,*args)
    h.brain.answer=answer
    task=asyncio.create_task(h.service.ingest(h.sid,h.utterance()))
    await started.wait()
    try:
        result=await asyncio.wait_for(h.service.ingest(other,h.utterance()),2)
        assert result.action=='answer'
    finally:
        release.set(); await task


def test_repository_transcript_contract_without_app_initialization(tmp_path):
    from meeting_agent.models import UtteranceCreate
    repo=SQLiteRepository(tmp_path/'standalone.db')
    sid=repo.create_session(SessionCreate(title='Standalone',owner_name='Aloy')).id
    repo.add_transcript(sid,UtteranceCreate(speaker='Jamie',text='Hello'))
    assert repo.get_transcript(sid)[0].participant_id is None


@pytest.mark.asyncio
async def test_same_display_name_does_not_merge_speakers(tmp_path):
    h=harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance(text='Alloy',speaker='Jamie',participant_id='one'))
    other_participant_decision=await h.service.ingest(h.sid,h.utterance(text='When is launch?',speaker='Jamie',participant_id='two'))
    assert other_participant_decision.action=='stay_silent'
    await h.service.ingest(h.sid,h.utterance(text='Alloy',speaker='Jamie',participant_id='one'))
    renamed_same_participant_decision=await h.service.ingest(h.sid,h.utterance(text='When is launch?',speaker='Renamed',participant_id='one'))
    assert renamed_same_participant_decision.action=='answer'

@pytest.mark.asyncio
async def test_human_named_alloy_is_not_self_but_explicit_self_is(tmp_path):
    h=harness(tmp_path)
    assert (await h.service.ingest(h.sid,h.utterance(speaker='Alloy',participant_id='human'))).action=='answer'
    assert (await h.service.ingest(h.sid,h.utterance(speaker='Renamed bot',participant_id='bot',is_self=True))).action=='stay_silent'
