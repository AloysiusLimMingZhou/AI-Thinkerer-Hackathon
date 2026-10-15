import sys,json
for line in sys.stdin:
    item=json.loads(line)
    if item['type']=='config': continue
    if item['type']=='leave': continue
    if item['request_id']=='trigger': print(json.dumps(dict(protocol_version=1,type='command',interaction_id='interaction',command='status',guild_id='guild',actor_id='owner')),flush=True)
    if item['type']=='stop':
        print(json.dumps(dict(protocol_version=1,type='disconnected',session_id='s',generation='old',reason='ended')),flush=True)
        print('x'*70000,file=sys.stderr,flush=True)
    print(json.dumps(dict(protocol_version=1,type='response',request_id=item['request_id'],ok=True,data={})),flush=True)
