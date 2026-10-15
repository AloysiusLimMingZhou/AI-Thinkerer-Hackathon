from datetime import UTC,datetime,timedelta
import pytest
from fastapi import HTTPException
from meeting_agent.minutes import MinutesService
from meeting_agent.models import TranscriptEntry
from test_urgency import urgency_harness


class Summarizer:
    def __init__(self): self.calls=[]; self.fail=False
    async def summarize_minutes(self,session,material,*,synthesis):
        self.calls.append((material,synthesis))
        if self.fail: raise RuntimeError('provider secret must not be saved')
        return '# Summary\nDecision: launch Friday.'


def entry(index,text):
    return TranscriptEntry(id=str(index),speaker='Jamie',text=text,is_final=True,spoken_at=datetime(2026,10,15,tzinfo=UTC)+timedelta(seconds=index))


def minutes_harness(tmp_path):
    h=urgency_harness(tmp_path); h.summarizer=Summarizer()
    h.minutes=MinutesService(h.repo,h.summarizer,h.escalations)
    return h


@pytest.mark.asyncio
async def test_whole_transcript_and_question_reply_appendices_survive(tmp_path):
    h=minutes_harness(tmp_path)
    question=h.escalations.open_question(h.sid,h.utterance('What is the budget?'),'prompt','utterance')
    h.escalations.store.execute("INSERT INTO owner_replies VALUES('owner-1',?,'Budget is 500.','2026-10-15','saved_after_end',NULL)",(question['id'],))
    entries=[entry(0,'Decision: launch Friday.')]+[entry(i,'Meeting discussion. '*12) for i in range(1,601)]
    result=await h.minutes.finalize(h.sid,list(reversed(entries)))
    segments=[text for text,synthesis in h.summarizer.calls if not synthesis]
    assert 'Decision: launch Friday.' in segments[0]
    assert all(len(text)<=30000 for text,_ in h.summarizer.calls)
    assert 'What is the budget?' in h.summarizer.calls[-1][0]
    assert 'Budget is 500.' in h.summarizer.calls[-1][0]
    assert 'What is the budget?' in result.content and 'Budget is 500.' in result.content
    assert h.minutes.status(h.sid)['state']=='ready'
    count=len(h.summarizer.calls)
    await h.minutes.finalize(h.sid,entries)
    assert len(h.summarizer.calls)==count


@pytest.mark.asyncio
async def test_oversize_utterance_keeps_every_character_and_provenance(tmp_path):
    h=minutes_harness(tmp_path)
    text='a'*70000+' final decision'
    await h.minutes.finalize(h.sid,[entry(1,text)])
    inputs=[s for s,final in h.summarizer.calls if not final]
    assert sum(s.count('a') for s in inputs)>=70000
    assert all('Jamie' in s and '2026-10-15' in s for s in inputs)
    assert 'final decision' in inputs[-1]
    assert all(len(s)<=30000 for s,_ in h.summarizer.calls)


@pytest.mark.asyncio
async def test_failure_is_visible_retryable_and_empty_transcript_fails(tmp_path):
    h=minutes_harness(tmp_path)
    with pytest.raises(HTTPException): await h.minutes.finalize(h.sid,[])
    assert h.minutes.status(h.sid)['state']=='failed'
    h.summarizer.fail=True
    with pytest.raises(Exception): await h.minutes.finalize(h.sid,[entry(0,'Decision approved.')])
    state=h.minutes.status(h.sid)
    assert state['state']=='failed' and 'secret' not in state['error']
    h.summarizer.fail=False
    await h.minutes.finalize(h.sid,[entry(0,'Decision approved.')])
    assert h.minutes.status(h.sid)['state']=='ready'


@pytest.mark.asyncio
async def test_post_call_answer_schedules_new_minutes_without_rejoining(tmp_path):
    from test_owner_replies import reply_harness
    from dataclasses import replace
    h=await reply_harness(tmp_path); summarizer=Summarizer()
    minutes=MinutesService(h.repo,summarizer,h.escalations)
    h.service.minutes=minutes
    minutes.transcript=lambda sid:[entry(0,'Budget discussion.')]
    await minutes.finalize(h.sid,minutes.transcript(h.sid))
    h.playback.live=False
    await h.escalations.receive_owner_reply(replace(h.reply,text='Budget is 500.'))
    assert minutes.status(h.sid)['state']=='processing'
    await minutes.run_once()
    assert minutes.status(h.sid)['state']=='ready'
    assert 'Budget is 500.' in h.repo.get_minutes(h.sid).content
    assert h.playback.queued==[]


def test_waiting_transcript_times_out_visibly_and_recovery_does_not_hang(tmp_path):
    h=minutes_harness(tmp_path)
    h.minutes.wait_for_transcript(h.sid)
    assert h.minutes.status(h.sid)['state']=='processing'
    h.minutes.clock=lambda:10**12
    assert h.minutes.status(h.sid)['state']=='failed'
    h.minutes.schedule(h.sid)
    h.minutes.store.execute("UPDATE finalizations SET pending=0,waiting_until=NULL")
    h.minutes.recover()
    assert h.minutes.status(h.sid)['state']=='failed'


@pytest.mark.asyncio
async def test_hierarchical_synthesis_keeps_every_request_bounded(tmp_path):
    h=minutes_harness(tmp_path)
    calls=[]
    async def summarize(session,material,*,synthesis):
        calls.append((material,synthesis))
        return ('Summary. '*1000) if not synthesis else '# Summary'
    h.summarizer.summarize_minutes=summarize
    await h.minutes.finalize(h.sid,[entry(i,'discussion '*100) for i in range(150)])
    assert len(calls)>8
    assert all(len(material)<=30000 for material,_ in calls)
    assert calls[-1][1] is True


def test_multiple_final_artifacts_are_chronological_and_deduplicate(tmp_path):
    import json
    from test_recall import make_backend,session
    client,recall,_=make_backend(tmp_path); sid=session(client)
    def artifact(stamp,text): return json.dumps([{'participant':{'name':'Jamie'},'words':[{'text':text,'start_timestamp':{'absolute':stamp}}]}])
    for tid,stamp,text in [('later','2026-10-15T10:00:01Z','Later item'),('earlier','2026-10-15T10:00:00Z','Early decision'),('duplicate','2026-10-15T10:00:00Z','Early decision')]:
        recall.store.execute('INSERT INTO recall_transcripts VALUES(?,?,?,?,?)',(tid,sid,None,stamp,artifact(stamp,text)))
    assert [t.text for t in recall.final_transcript(sid)]==['Early decision','Later item']
