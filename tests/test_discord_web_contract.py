from fastapi.testclient import TestClient
from meeting_agent.api import create_app
from meeting_agent.config import Settings

def test_no_key_briefing_and_budget_contract(tmp_path):
    app=create_app(settings=Settings(database_path=tmp_path/'web.db',backend_api_token='private'))
    client=TestClient(app,headers={'Authorization':'Bearer private'})
    b=client.post('/briefings',json={'title':'Launch','owner_name':'Aloy'}).json()
    sid=b['id']
    assert b['platform']=='discord' and b['purpose']=='briefing'
    assert client.get('/briefings').json()==[]
    assert client.post(f'/sessions/{sid}/knowledge',data={'text':'Launch Friday.'}).status_code==201
    assert client.post(f'/briefings/{sid}/prepare').status_code==200
    assert client.get('/briefings').json()[0]['id']==sid
    assert client.post(f'/sessions/{sid}/bot',json={'idempotency_key':'blocked-briefing','consent_confirmed':True}).status_code==409
    budget=client.get('/budget/status').json()
    assert budget['soft_limit_micro_usd']==5000000 and budget['hard_limit_micro_usd']==8000000
    assert budget['available_micro_usd']==8000000
    assert budget['timezone']=='Asia/Kuala_Lumpur'
    assert client.get('/budget/status',headers={'Authorization':'wrong'}).status_code==401
