import pytest
from test_urgency import urgency_harness


@pytest.mark.asyncio
async def test_interrupted_send_is_visible_and_not_automatically_repeated(tmp_path):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.ingest(h.sid,h.utterance('Yes, urgent'))
    h.escalations.store.execute("UPDATE escalation_outbox SET state='processing'")
    h.escalations.recover()
    await h.escalations.run_once()
    assert h.notifier.sent==[]
    question=h.escalations.questions(h.sid)[0]
    assert question['state']=='delivery_failed'
    assert question['error']


@pytest.mark.asyncio
async def test_unknown_identity_cannot_confirm_even_with_question_reference(tmp_path):
    h=urgency_harness(tmp_path)
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.ingest(h.sid,h.utterance('Alloy, the budget is urgent',speaker='Unknown participant',participant_id=None))
    await h.escalations.run_once()
    assert not h.notifier.sent
