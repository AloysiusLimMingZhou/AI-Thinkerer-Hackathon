import pytest
from test_api import make_client
from test_meeting_service import harness


def test_question_status_route_exists_and_preview_has_no_escalation(tmp_path):
    client,_=make_client(tmp_path)
    sid=client.post('/sessions',json={'title':'Planning','owner_name':'Aloy'}).json()['id']
    client.post(f'/sessions/{sid}/utterances',json={'speaker':'Jamie','text':'Alloy, what is the budget?'})
    result=client.get(f'/sessions/{sid}/questions')
    assert result.status_code==200
    assert result.json()==[]


class FakeNotifier:
    configured=True
    def __init__(self): self.sent=[]
    async def send_question(self,question):
        from meeting_agent.escalations import DiscordQuestionRef
        self.sent.append(question['id'])
        return DiscordQuestionRef(parent_message_id='parent',thread_id='thread')


def urgency_harness(tmp_path):
    from meeting_agent.escalations import EscalationService
    h=harness(tmp_path,knowledge=False)
    h.notifier=FakeNotifier()
    h.escalations=EscalationService(h.repo,h.service,notifier=h.notifier)
    h.service.escalations=h.escalations
    return h


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['No, it is not urgent','No rush',"Don't contact them",'Yeah, not urgent',"It isn't urgent",'It is not really urgent',"We don't need an urgent response"])
async def test_negative_confirmation_never_notifies(tmp_path,text):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.ingest(h.sid,h.utterance(text))
    await h.escalations.run_once()
    assert h.notifier.sent==[]
    assert h.escalations.questions(h.sid)[0]['state']=='not_urgent'


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['Is it urgent?', 'I wonder whether it is urgent', 'Maybe it is urgent'])
async def test_uncertain_urgency_does_not_notify(tmp_path,text):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.ingest(h.sid,h.utterance(text))
    await h.escalations.run_once()
    assert h.notifier.sent==[]


@pytest.mark.asyncio
async def test_muted_bot_does_not_accept_urgency_confirmation(tmp_path):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    h.playback.muted=lambda _:True
    await h.service.ingest(h.sid,h.utterance('Yes, urgent'))
    await h.escalations.run_once()
    assert h.notifier.sent==[]


@pytest.mark.asyncio
async def test_confirmed_urgent_question_has_one_persisted_outbox(tmp_path):
    from meeting_agent.escalations import EscalationService
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    assert h.escalations.questions(h.sid)[0]['state']=='awaiting_urgency'
    await h.service.ingest(h.sid,h.utterance('Yes, it is urgent'))
    await h.escalations.run_once()
    await h.service.ingest(h.sid,h.utterance('Yes, urgent'))
    await h.escalations.run_once()
    assert len(h.notifier.sent)==1
    reopened=EscalationService(h.repo,h.service,notifier=h.notifier)
    assert reopened.questions(h.sid)[0]['state']=='awaiting_owner'


@pytest.mark.asyncio
async def test_other_speaker_generic_yes_and_expiry_do_not_ping(tmp_path):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.ingest(h.sid,h.utterance('Yes',speaker='Sam',participant_id='sam'))
    assert h.escalations.questions(h.sid)[0]['state']=='awaiting_urgency'
    now=h.escalations.clock()
    h.escalations.clock=lambda: now+61
    await h.service.ingest(h.sid,h.utterance('Yes, urgent'))
    await h.escalations.run_once()
    assert h.notifier.sent==[]
    assert h.escalations.questions(h.sid)[0]['state']=='urgency_expired'


@pytest.mark.asyncio
async def test_ambiguous_questions_ask_for_clarification(tmp_path):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the catering menu?'))
    decision=await h.service.ingest(h.sid,h.utterance('Yes, urgent'))
    assert 'which question' in decision.answer.lower()
    await h.escalations.run_once()
    assert h.notifier.sent==[]


@pytest.mark.asyncio
async def test_failed_prompt_cancels_urgency_and_missing_discord_is_truthful(tmp_path):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.playback_failed(h.sid,h.playback.queued[0].key)
    await h.service.ingest(h.sid,h.utterance('Yes, urgent'))
    assert not h.escalations.store.all("SELECT * FROM escalation_outbox")
    h.escalations.notifier=None
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the launch date?'))
    result=await h.service.ingest(h.sid,h.utterance('Yes, urgent'))
    assert "couldn't reach Aloy" in result.answer
