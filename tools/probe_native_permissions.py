#!/usr/bin/env python3
"""Opt-in native permission matrix. Disposable authenticated loopback server only.

No model calls, credentials from the caller, existing sessions, or tool bodies.
Waits for the custom Agent before counting a permission decision as evidence.
"""
import argparse
import os,sys,json,tempfile,socket,subprocess,time,urllib.request,urllib.parse,base64,secrets
from pathlib import Path
sys.dont_write_bytecode = True  # Do not contaminate an unpacked release during diagnostics.
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'opencode-delegate/scripts'))
import opencode_adapter as a
from v2_config import resolved_agent
from process_control import terminate_group
from delegate_core import AGENT,GuardError
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--opencode', required=True, help='Exact native binary, not a credential wrapper')
parser.add_argument('--check-move', action='store_true', help='Also move only the disposable test Session and verify the frozen-location guard')
args=parser.parse_args()
BIN=str(Path(args.opencode).resolve(strict=True))
out={'model_calls':0,'scope':'one isolated loopback server; native permission decisions, not tool execution'}
with tempfile.TemporaryDirectory(prefix='policy-ready-') as tmp:
 root=Path(tmp);wt=root/'work';wt.mkdir()
 env={'PATH':os.environ['PATH'],'HOME':str(root/'home'),'PWD':str(wt),'PYTHONDONTWRITEBYTECODE':'1'}
 for k,n in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:env[k]=str(root/n);(root/n).mkdir()
 os.environ.clear();os.environ.update(env)
 info=a.probe(BIN);out.update(cli_version=info['version'],binary_sha256=info['binary_sha256'])
 c={'model':'openai/gpt-6.1-sol','allowed_paths':['allowed.txt'],'protected_paths':['protected.txt']};config,ak,pk=a.permission_config(c,2,wt);env=a.runtime_env(config,wt)
 # Ephemeral authentication for this disposable localhost test server only.
 password=secrets.token_urlsafe(32);env['OPENCODE_PASSWORD']=password
 authorization='Basic '+base64.b64encode(('opencode:'+password).encode()).decode()
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 log=open(root/'server.log','wb');p=subprocess.Popen([BIN,'serve','--hostname','127.0.0.1','--port',str(port)],env=env,cwd=wt,stdout=log,stderr=log,start_new_session=True)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def api(method,path,data=None):
  req=urllib.request.Request('http://127.0.0.1:'+str(port)+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':authorization},method=method)
  with opener.open(req,timeout=5) as f:
   raw=f.read();return json.loads(raw) if raw else None
 try:
  deadline=time.monotonic()+20
  while True:
   try:
    response=api('GET','/api/agent?directory='+urllib.parse.quote(str(wt),safe=''))
    agent=resolved_agent(response['data'],config);break
   except Exception as e:
    if time.monotonic()>deadline or p.poll() is not None:raise RuntimeError('Agent readiness failed '+type(e).__name__) from e
    time.sleep(.1)
  out['custom_agent_ready']=True
  session=api('POST','/api/session',{'agent':AGENT,'model':{'providerID':'openai','id':'gpt-6.1-sol'},'location':{'directory':str(wt)}})['data'];sid=session['id']
  matrix=[('read','allowed.txt','allow'),('glob','*','allow'),('edit','allowed.txt','allow'),('edit','protected.txt','deny'),('edit','other.txt','deny'),('read','.env','deny'),('read','.git/config','deny'),('shell','*','deny'),('subagent','*','deny'),('external_directory',str(root),'deny'),('webfetch','https://example.invalid','deny'),('websearch','*','deny'),('skill','*','deny'),('question','*','deny'),('execute','*','deny')]
  rows=[]
  for action,resource,expected in matrix:
   effect=api('POST','/api/session/'+sid+'/permission',{'action':action,'resources':[resource]})['data']['effect']
   rows.append({'action':action,'resource':'<outside-worktree>' if action=='external_directory' else resource,'expected':expected,'actual':effect})
  out['matrix']=rows;out['passed']=all(x['expected']==x['actual'] for x in rows)
  native=api('GET','/api/session/'+sid)['data'];out['tokens']=native['tokens'];out['cost']=native['cost']
  if args.check_move:
   a.check_session_binding(info,c,sid,wt,env)
   target=root/'moved';target.mkdir()
   api('POST','/api/session/'+sid+'/move',{'directory':str(target)})
   api('POST','/api/session/'+sid+'/interrupt?resume=true')
   deadline=time.monotonic()+10
   while True:
    moved=api('GET','/api/session/'+sid)['data']
    if moved['location']['directory']==str(target):break
    if time.monotonic()>deadline:raise RuntimeError('Move was admitted but not independently observed')
    time.sleep(.1)
   try:
    a.check_session_binding(info,c,sid,wt,env)
    raise AssertionError('Moved native session was accepted')
   except GuardError as exc:
    assert 'outside the frozen worktree' in str(exc)
   out['native_move']={'before_binding':'accepted','same_session_id':moved['id']==sid,
     'target_location_independently_observed':True,'original_worktree_still_exists':wt.is_dir(),
     'after_binding':'rejected','tokens':moved['tokens'],'cost':moved['cost']}
 finally:
  out['cleanup']=terminate_group(p);log.close()
print(json.dumps(out,indent=2))
if not out['passed'] or not out['cleanup']['process_group_quiescent']:sys.exit(1)
