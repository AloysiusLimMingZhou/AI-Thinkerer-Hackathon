from test_api import make_client


def test_missing_knowledge_defers_instead_of_inventing_answer(tmp_path):
    client,_=make_client(tmp_path)
    sid=client.post('/sessions',json={'title':'Planning','owner_name':'Aloy'}).json()['id']
    decision=client.post(f'/sessions/{sid}/utterances',json={'speaker':'Jamie','text':'Alloy, what is the budget?'}).json()
    assert decision['action']=='defer'
    assert decision['answer']=="I don't know based on the knowledge I have. Is this urgent?"
    assert decision['citations']==[]


def test_agent_voice_is_excluded_from_shared_ingestion(tmp_path):
    client,_=make_client(tmp_path)
    sid=client.post('/sessions',json={'title':'Planning','owner_name':'Aloy'}).json()['id']
    result=client.post(f'/sessions/{sid}/utterances',json={'speaker':'Alloy','text':'Alloy, what is the budget?'}).json()
    assert result['action']=='stay_silent'


def test_provider_event_replay_has_one_transcript_and_decision(tmp_path):
    client,_=make_client(tmp_path)
    sid=client.post('/sessions',json={'title':'Planning','owner_name':'Aloy'}).json()['id']
    body={'event_id':'provider-1','speaker':'Jamie','text':'Alloy, what is the budget?'}
    first=client.post(f'/sessions/{sid}/utterances',json=body)
    second=client.post(f'/sessions/{sid}/utterances',json=body)
    assert first.json()==second.json()
    assert len(client.get(f'/sessions/{sid}/transcript').json())==1
    assert len([e for e in client.get(f'/sessions/{sid}/events').json() if e['type']=='agent.decision'])==1
