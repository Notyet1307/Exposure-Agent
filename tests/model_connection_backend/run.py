"""Real managed backend/Pi acceptance using only local fixed-response providers."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

RUNTIME='chaitin/agent-compose@sha256:092f8c4fbf7254ddd200a36d99ae6583cd08f5ddeda9cafd559b3636890c9670'
image=json.loads(Path(os.environ['MODEL_BACKEND_IMAGE_CONTEXT']).read_text())
tag=image['tag'];backend_image='backend:'+tag
root=Path(tempfile.mkdtemp(prefix='expux02-api-',dir=os.environ.get('EXPUX02_PROBE_ROOT')));root.chmod(0o700)
name=root.name;network=name+'-net';volume=name+'-state'
names={role:name+'-'+role for role in ['db','backend','daemon','provider-a','provider-b']}
key_a,key_b,password,app_secret,control_token,admin_password=[secrets.token_hex(32) for _ in range(6)]
secret_values=[key_a,key_b,password,app_secret,control_token,admin_password]
connections=[];receipts=[];base='';token=''
faults = os.environ.get('EXPUX02_FAULTS') == '1'
if faults: names['relay'] = name+'-relay'


def cmd(args,data=None,check=True):
    proc=subprocess.run(args,input=data,capture_output=True,timeout=240)
    if check and proc.returncode:
        message=proc.stderr.decode(errors='replace')[-1500:]
        for value in secret_values:message=message.replace(value,'[REDACTED]')
        raise RuntimeError('command failed: '+' '.join(args[:3])+' '+message)
    return proc.stdout


def port(role,p):return cmd(['docker','port',names[role],p]).decode().strip().rsplit(':',1)[1]

def api(path,body=None,*,url=None,headers=None):
    data=None if body is None else json.dumps(body).encode()
    h={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {}),**(headers or {})}
    request=urllib.request.Request((url or base)+path,data=data,headers=h)
    try:
        with urllib.request.urlopen(request,timeout=150) as response:raw=response.read();code=response.status
    except urllib.error.HTTPError as exc:raw=exc.read();code=exc.code
    assert not any(v.encode() in raw for v in [key_a,key_b]),'original_key_in_http_response'
    try:result=json.loads(raw)
    except ValueError:result={}
    return code,result


def wait(check,label,timeout=170):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=check()
        if value:return value
        time.sleep(.3)
    raise RuntimeError('timeout '+label)


def dbsql(query):return cmd(['docker','exec','-i',names['db'],'psql','-U','app','-d','app','-qAt','-v','ON_ERROR_STOP=1'],query.encode()).decode().strip()

def envfile(role,data):
    p=root/(role+'.env');p.write_text(''.join(k+'='+str(v)+'\n' for k,v in data.items()));p.chmod(0o600);return str(p)

def generation():return api('/api/v1/model-connections')[1]['generation']

def save(version):
    key=key_a if version=='a' else key_b
    code,data=api('/api/v1/model-connections',{'expected_generation':generation(),'name':'Managed '+version,
        'endpoint':'http://provider-'+version+':8080/v1','protocol':'chat_completions','model_identity':'model-'+version,'api_key':key},headers={'Idempotency-Key':'save-'+version})
    assert code==201,(code,data)
    identity=data['operation']['connection_id'];connections.append(identity);return identity

def action(identity,verb):
    return api('/api/v1/model-connections/'+identity+'/'+verb,{'expected_generation':generation()},headers={'Idempotency-Key':verb+'-'+identity})

def ready(identity):
    code,data=action(identity,'validate');assert code==200,(code,data)
    operation=data['operation']['id']
    def completed():
        code,response=api('/api/v1/model-connections/operations/'+operation)
        assert code==200,(code,response)
        result=response['operation']
        if result['status'] in {'FAILED','UNKNOWN'}:
            receipts.append(result)
            raise RuntimeError('validation not established '+json.dumps(result))
        return result if result['status']=='SUCCEEDED' else None
    result=wait(completed,'validation');receipts.append(result)
    code,data=action(identity,'activate');assert code==200 and data['operation']['status']=='SUCCEEDED',(code,data)
    assert data['state']['active_id']==identity


def snapshot():return cmd(['docker','ps','-a','--format','{{.ID}} {{.Names}} {{.Image}} {{.State}}']).decode().splitlines()
before=snapshot();root.joinpath('protected.json').write_text(json.dumps(before))
print('Managed backend evidence:',root,flush=True)
try:
    cmd(['docker','network','create',network]);cmd(['docker','volume','create',volume])
    keys=root/'keys';keys.mkdir(mode=0o700);(keys/'v1.key').write_bytes(secrets.token_bytes(32));(keys/'v1.key').chmod(0o600)
    artifacts=root/'artifacts';artifacts.mkdir()
    env={'PROJECT_NAME':'EXP-UX-02 backend acceptance','ENVIRONMENT':'local','NETFLOW_MAX_BYTES':'52428800',
        'POSTGRES_SERVER':'db','POSTGRES_USER':'app','POSTGRES_DB':'app','POSTGRES_PASSWORD':password,'POSTGRES_PORT':'5432',
        'SECRET_KEY':app_secret,'FIRST_SUPERUSER':'admin@connection.example','FIRST_SUPERUSER_PASSWORD':admin_password,
        'AGENT_COMPOSE_URL':'http://daemon:7410','AGENT_COMPOSE_AUTH_TOKEN':control_token,'AGENT_COMPOSE_RUNTIME_VERSION':RUNTIME.split('@')[1],
        'RUNNER_BUILD_VERSION':tag,'DOCKER_IMAGE_RUNNER':'governance-runner','MODEL_CONNECTION_KEY_DIRECTORY':'/run/model-keys',
        'MODEL_CONNECTION_KEY_ID':'v1','MODEL_CONNECTION_INTERNAL_URL':'http://backend:8000',
        'AI_ANALYSIS_REPORT_TIMEOUT_SECONDS':'300','ARTIFACT_ROOT':'/app/artifacts'}
    cmd(['docker','run','-d','--name',names['db'],'--network',network,'--network-alias','db','--tmpfs','/var/lib/postgresql',
        '--env-file',envfile('db',{k:env[k] for k in ['POSTGRES_USER','POSTGRES_DB','POSTGRES_PASSWORD']}),'-p','127.0.0.1::5432','postgres:18'])
    wait(lambda:subprocess.run(['docker','exec',names['db'],'sh','-ec','PGPASSWORD="$POSTGRES_PASSWORD" psql -h127.0.0.1 -Uapp -dapp -Atqc "select 1"'],capture_output=True).returncode==0,'database',45)
    provider=Path(__file__).with_name('provider.py').resolve()
    for v,key in [('a',key_a),('b',key_b)]:
        role='provider-'+v
        cmd(['docker','run','-d','--name',names[role],'--network',network,'--network-alias',role,
            '--env-file',envfile(role,{'PROVIDER_KEY':key,'MODEL_IDENTITY':'model-'+v}),'-v',str(provider)+':/fixture.py:ro',
            '-p','127.0.0.1::8080','--entrypoint','python',backend_image,'/fixture.py'])
    cmd(['docker','run','-d','--name',names['daemon'],'--network',network,'--network-alias','daemon',
        '--env-file',envfile('daemon',{'AGENT_COMPOSE_AUTH_TOKEN':control_token}),'-v','/var/run/docker.sock:/var/run/docker.sock','-v',volume+':/data',RUNTIME])
    wait(lambda:subprocess.run(['docker','exec',names['daemon'],'sh','-ec','agent-compose --host http://127.0.0.1:7410 auth login --token "$AGENT_COMPOSE_AUTH_TOKEN" >/dev/null && agent-compose --host http://127.0.0.1:7410 status --json >/dev/null'],capture_output=True).returncode==0,'daemon',45)
    if faults:
        env.update(AGENT_COMPOSE_URL='http://relay:7411', MODEL_API_ENDPOINT='http://provider-a:8080/v1',
            MODEL_API_PROTOCOL='chat_completions', MODEL_IDENTITY='model-a', MODEL_API_KEY=key_a,
            AI_INVESTIGATION_TIMEOUT_SECONDS='300')
        cmd(['docker','run','-d','--name',names['relay'],'--network',network,'--network-alias','relay',
            '-v',str(Path(__file__).with_name('relay.py').resolve())+':/relay.py:ro',
            '-p','127.0.0.1::7411','--entrypoint','python',backend_image,'/relay.py'])
    cmd(['docker','run','-d','--name',names['backend'],'--network',network,'--network-alias','backend','--env-file',envfile('backend',env),
        '-v',str(keys)+':/run/model-keys:ro','-v',str(artifacts)+':/app/artifacts','-p','127.0.0.1::8000',backend_image])
    cmd(['docker','exec',names['backend'],'bash','scripts/prestart.sh'])
    base='http://127.0.0.1:'+port('backend','8000/tcp')
    wait(lambda:api('/health/ready')[0]==200,'backend',45)
    login=urllib.request.Request(base+'/api/v1/login/access-token',data=urllib.parse.urlencode({'username':env['FIRST_SUPERUSER'],'password':admin_password}).encode())
    with urllib.request.urlopen(login) as response:token=json.load(response)['access_token']
    secret_values.append(token)
    # Published deterministic fixture only; all subsequent AI runs are real.
    child=os.environ.copy();child.update({k:str(v) for k,v in env.items()})
    child['PYTHONPATH']=str(Path('backend').resolve())
    child.update(POSTGRES_SERVER='127.0.0.1',POSTGRES_PORT=port('db','5432/tcp'),SEED_ARTIFACT_ROOT=str(artifacts),SEED_RESULT=str(root/'seed.json'))
    with (root/'seed.log').open('wb') as log:
        done=subprocess.run([str(Path.cwd()/'.venv/bin/python'),str(Path(__file__).with_name('seed.py').resolve())],cwd=Path('backend'),env=child,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    assert done.returncode==0,'seed failed; inspect sanitized local seed log'
    fixture=json.loads((root/'seed.json').read_text());project=fixture['project_id'];run=fixture['run_id']
    provider_a='http://127.0.0.1:'+port('provider-a','8080/tcp');provider_b='http://127.0.0.1:'+port('provider-b','8080/tcp')
    if faults:
        from faults import preflight
        preflight(locals())
    a=save('a');ready(a);print('Connection A validated and activated',flush=True)
    reports='/api/v1/projects/'+project+'/analysis-reports'
    def report(key):
        code,value=api(reports,{'run_id':run},headers={'Idempotency-Key':key});assert code==201,(code,value)
        return value['id']
    def finished(identity,status):
        def poll():
            code,value=api(reports+'/'+identity);assert code==200,(code,value)
            if value['status']=='FAILED' and status!='FAILED':raise RuntimeError('report failed '+str(value.get('failure_code')))
            return value if value['status']==status else None
        return wait(poll,'report '+status)
    api('/hold',{},url=provider_a);old_report=report('a-held')
    wait(lambda:api('/stats',url=provider_a)[1]['waiting'],'A held')
    b=save('b');ready(b);print('Connection B validated and activated while A in flight',flush=True)
    api('/release',{},url=provider_a);finished(old_report,'DRAFT')
    new_report=report('b-new');finished(new_report,'DRAFT')
    assert dbsql(f"select connection_version_id from analysis_reports where id='{old_report}'")==a
    assert dbsql(f"select connection_version_id from analysis_reports where id='{new_report}'")==b
    # A fresh A-bound report was established before switching to B in the probe;
    # product revoke refusal is also exercised through an existing lease below.
    code,data=action(a,'revoke');assert code==200 and data['state']['active_id']==b
    another=report('b-after-revoke');finished(another,'DRAFT')
    fault_receipt = None
    if faults:
        from faults import exercise
        fault_receipt = exercise(locals())
    browser_receipt = None
    if os.environ.get('MODEL_CONNECTION_BROWSER_URL'):
        browser_input = {'ui':os.environ['MODEL_CONNECTION_BROWSER_URL'], 'api':base,
            'token':token, 'key':key_a, 'output':str(root/'browser-result.json')}
        try:
            cmd(['node',str(Path(__file__).with_name('browser.mjs').resolve())],json.dumps(browser_input).encode())
            browser_receipt=json.loads((root/'browser-result.json').read_text())
        finally:
            code, observed = api('/api/v1/model-connections')
            if code == 200:
                for version in observed['connections']:
                    if version['id'] not in connections: connections.append(version['id'])
    stats_a=api('/stats',url=provider_a)[1];stats_b=api('/stats',url=provider_b)[1]
    assert all(c['accepted'] for stats in [stats_a,stats_b] for c in stats['calls'])
    # Scan the *owned* runtime state, not only redacted API projections.
    scanner='''import json,sys,pathlib; keys=[v.encode() for v in json.load(sys.stdin)]; files=0; hits=0
for p in pathlib.Path('/scan').rglob('*'):
 if p.is_file():
  data=p.read_bytes(); files+=1; hits+=sum(k in data for k in keys)
print(json.dumps({'files':files,'original_key_hits':hits})); assert hits==0
'''
    scan=json.loads(cmd(['docker','run','--rm','-i','--network','none','-v',volume+':/scan:ro','--entrypoint','python',backend_image,'-c',scanner],json.dumps([key_a,key_b]).encode()))
    for role in ['backend','daemon']:
        p=subprocess.run(['docker','logs',names[role]],capture_output=True)
        assert not any(k.encode() in p.stdout+p.stderr for k in [key_a,key_b])
    result={'status':'PASS','image_tag':tag,'version_a':a,'version_b':b,'old_report':old_report,'new_report':new_report,
        'faults':fault_receipt,'browser':browser_receipt,'runtime_state_scan':scan,'provider_a':stats_a,'provider_b':stats_b,'validation_receipts':receipts}
    root.joinpath('result.json').write_text(json.dumps(result,indent=2));print('Managed backend/Pi/proxy: PASS',flush=True)
except Exception as error:
    logs={}
    for role in ['backend','daemon']:
        p=subprocess.run(['docker','logs',names[role]],capture_output=True);text=(p.stdout+p.stderr).decode(errors='replace')[-16000:]
        for v in secret_values:text=text.replace(v,'[REDACTED]')
        logs[role]=text
    message=str(error)
    for v in secret_values:message=message.replace(v,'[REDACTED]')
    if connections:
        diagnostic = """import json,uuid,sys
from sqlmodel import Session
from app.core.db import engine
from app.domain.model_connections import get_version
from app.integrations.model_connection_runtime import client_for_version,project_spec
with Session(engine) as s:
 v=get_version(s,uuid.UUID(sys.argv[1]));c=client_for_version(v);spec=project_spec(v)
 dry=c._request('/agentcompose.v2.ProjectService/ApplyProject',{'spec':spec,'dryRun':True})
 observed=c._request('/agentcompose.v2.ProjectService/GetProject',{'project':{'projectId':c.project_id},'includeSpec':True},missing_ok=True)
 print(json.dumps({'dry':dry,'observed':observed}))
"""
        proc=subprocess.run(['docker','exec',names['backend'],'python','-c',diagnostic,connections[-1]],capture_output=True)
        detail=(proc.stdout+proc.stderr).decode(errors='replace')
        for value in secret_values:detail=detail.replace(value,'[REDACTED]')
        root.joinpath('project-diagnostic.json').write_text(detail)
    root.joinpath('failure.json').write_text(json.dumps({'error':message,'logs':logs,'receipts':receipts},indent=2))
    print('Managed backend: FAIL',message[:600],flush=True)
    raise
finally:
    for identity in connections:
        cmd(['docker','exec',names['daemon'],'agent-compose','--host','http://127.0.0.1:7410','-p','exposure-model-'+identity,'down'],check=False)
    if faults:
        cmd(['docker','exec',names['daemon'],'agent-compose','--host','http://127.0.0.1:7410','-p','exposure-agent-governance','down'],check=False)
        cmd(['docker','rm','-f',names['relay']],check=False)
    for role in ['backend','provider-a','provider-b','daemon','db']:cmd(['docker','rm','-f',names[role]],check=False)
    cmd(['docker','volume','rm',volume],check=False);cmd(['docker','network','rm',network],check=False)
    for p in root.glob('*.env'):p.unlink()
    (keys/'v1.key').unlink(missing_ok=True)
    assert set(before)==set(snapshot()),'container inventory changed'
    root.joinpath('cleanup.json').write_text(json.dumps({'original_containers_unchanged':True,'owned_resources_removed':True}))
    print('Owned stack removed; original container inventory unchanged',flush=True)
