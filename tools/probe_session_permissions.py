#!/usr/bin/env python3
"""Opt-in native V2 permission metadata probe; no credential/model/tool calls.

Creates only disposable sessions in an isolated HOME/XDG state. Uses the exact
explicit binary; never installs software, changes existing sessions, or calls run.
"""
import argparse
import os,sys,json,subprocess,tempfile
from pathlib import Path
sys.dont_write_bytecode = True  # Do not contaminate an unpacked release during diagnostics.
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'opencode-delegate/scripts'))
import opencode_adapter as a
from delegate_core import AGENT,GuardError
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--opencode', required=True, help='Exact installed native binary, not a credential-loading wrapper')
args=parser.parse_args()
binary=str(Path(args.opencode).resolve(strict=True))
out={'scope':'native metadata and permission evaluator only; no tool execution or model request','model_calls':0,'cases':[]}
with tempfile.TemporaryDirectory(prefix='permission-native-') as temp:
 root=Path(temp);wt=root/'work';wt.mkdir()
 env={'PATH':os.environ['PATH'],'HOME':str(root/'home'),'PWD':str(wt),'PYTHONDONTWRITEBYTECODE':'1'}
 for k,n in [('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:env[k]=str(root/n);(root/n).mkdir()
 (root/'home').mkdir();os.environ.clear();os.environ.update(env)
 info=a.probe(binary);out.update(version=info['version'],binary_sha256=info['binary_sha256'])
 c={'model':'openai/gpt-4.1-mini','allowed_paths':['allowed.txt'],'protected_paths':['protected.txt']}
 config,ak,pk=a.permission_config(c,2,wt);env=a.runtime_env(config,wt)
 out['config_fingerprint']=a.check_effective_config(info,config,ak,pk,wt,env)
 def api(method,path,data=None):
  argv=[binary,'api',method,path,'--standalone']
  if data is not None:argv+=['--data',json.dumps(data)]
  p=subprocess.run(argv,cwd=wt,env=env,capture_output=True,timeout=20)
  if p.returncode:raise RuntimeError('API failed '+method+' '+path+' '+p.stderr.decode()[:500])
  return json.loads(p.stdout)['data']
 for name,permissions in [('absent',None),('empty',[]),('deny',[{'action':'shell','resource':'*','effect':'deny'}]),('allow',[{'action':'shell','resource':'*','effect':'allow'}])]:
  data={'agent':AGENT,'model':{'providerID':'openai','id':'gpt-4.1-mini','variant':'default'},'location':{'directory':str(wt)}}
  if permissions is not None:data['permissions']=permissions
  session=api('POST','/api/session',data);sid=session['id']
  decision=api('POST','/api/session/'+sid+'/permission',{'action':'shell','resources':['printf harmless']})
  try:
   result=a.check_session_binding(info,c,sid,wt,env);guard='accepted'
  except GuardError:guard='rejected'
  actual=api('GET','/api/session/'+sid)
  out['cases'].append({'case':name,'native_shell_decision':decision['effect'],'guard':guard,'permissions_unchanged':actual.get('permissions')==session.get('permissions'),'tokens':actual['tokens'],'cost':actual['cost']})
  assert guard==('rejected' if name=='allow' else 'accepted')
  assert decision['effect']==('allow' if name=='allow' else 'deny')
print(json.dumps(out,indent=2))

