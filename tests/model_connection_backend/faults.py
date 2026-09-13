"""Failure-injection acceptance for owned local containers, never a product runtime hook."""
import json
import subprocess
import uuid

BASE = '/api/v1/model-connections'

def operation(c, identity, verb, *, key=None, expected=None):
    key = key or str(uuid.uuid4())
    expected = c['generation']() if expected is None else expected
    code, result = c['api'](f'{BASE}/{identity}/{verb}', {'expected_generation': expected}, headers={'Idempotency-Key': key})
    assert code == 200, (verb, code, result)
    return result, key, expected

def completed(c, op_id):
    def check():
        code, result = c['api'](BASE+'/operations/'+op_id)
        assert code == 200
        op = result['operation']
        assert op['status'] not in {'FAILED', 'UNKNOWN'}, op
        return op if op['status'] == 'SUCCEEDED' else None
    return c['wait'](check, 'fault validation complete')

def restart(c):
    c['cmd'](['docker', 'restart', c['names']['backend']])
    # Docker may allocate a new ephemeral host port when restarting this container.
    c['base'] = 'http://127.0.0.1:'+c['port']('backend','8000/tcp')
    def ready():
        try: return c['api']('/health/ready')[0] == 200
        except OSError: return False
    c['wait'](ready, 'owned backend restart', 45)

def preflight(c):
    api, sql = c['api'], c['dbsql']
    relay = 'http://127.0.0.1:'+c['port']('relay','7411/tcp')
    code, status = api(BASE+'/status'); assert code == 200 and status['state'] == 'legacy'
    original = sql('select count(*) from model_connection_versions')
    keyfile = c['keys']/'v1.key'; hidden = c['keys']/'v1.key.off'
    keyfile.rename(hidden)
    try:
        code, failure = api(BASE+'/adopt-legacy', {'expected_generation': 0}, headers={'Idempotency-Key':str(uuid.uuid4())})
        assert code == 409 and failure['detail']['code'] == 'model_connection_secret_unavailable'
        assert sql('select count(*) from model_connection_versions') == original == '0'
        assert sql('select count(*) from model_connection_secrets') == '0'
        assert sql('select count(*) from model_connection_operations') == '0'
        assert api(BASE+'/status')[1]['state'] == 'legacy'
    finally: hidden.rename(keyfile)
    key = str(uuid.uuid4()); payload = {'expected_generation':0}
    code, adopted = api(BASE+'/adopt-legacy', payload, headers={'Idempotency-Key':key})
    assert code == 201 and not adopted['state']['adopted'] and adopted['state']['active_id'] is None
    identity = adopted['operation']['connection_id']; c['connections'].append(identity)
    restart(c)
    code, recovered = api(BASE+'/operations/recover/adopt', headers={'Idempotency-Key':key})
    assert code == 200 and recovered['operation']['id'] == adopted['operation']['id']
    code, replay = api(BASE+'/adopt-legacy', payload, headers={'Idempotency-Key':key})
    assert code == 200 and replay['operation']['id'] == adopted['operation']['id']
    assert sql('select count(*) from model_connection_versions') == '1'
    assert sql('select count(*) from model_connection_secrets') == '1'
    api('/fault', {'mode':'offline'}, url=relay)
    unknown, retry_key, expected = operation(c, identity, 'validate')
    assert unknown['operation']['status'] == 'UNKNOWN'
    op_id = unknown['operation']['id']
    run_id = sql(f"select agent_run_id from model_connection_operations where id='{op_id}'")
    count = sql('select count(*) from model_connection_operations')
    for _ in range(2):
        assert api(BASE+'/operations/'+op_id)[1]['operation']['status'] == 'UNKNOWN'
        assert api(BASE+'/operations/recover/validate', headers={'Idempotency-Key':retry_key})[1]['operation']['id'] == op_id
    assert sql('select count(*) from model_connection_operations') == count
    assert not any(row['rpc']=='StartAgentRun' for row in api('/stats',url=relay)[1]['calls'])
    api('/fault', {'mode':'none'}, url=relay)
    resumed, _, _ = operation(c, identity, 'validate', key=retry_key, expected=expected)
    assert resumed['operation']['id'] == op_id
    complete = completed(c, op_id)
    assert sql(f"select agent_run_id from model_connection_operations where id='{op_id}'") == run_id
    legacy = legacy_boundary(c, identity)
    blocked, _, _ = operation(c, identity, 'activate')
    assert blocked['operation']['status']=='FAILED' and blocked['operation']['error_code']=='legacy_binding_unknown'
    assert blocked['state']['active_id'] is None and not blocked['state']['adopted']
    legacy_boundary(c, identity, start=True)
    legacy_before = sql("select row_to_json(q)::text from model_qualification_results q where id='"+legacy['id']+"'")
    active, _, _ = operation(c, identity, 'activate')
    assert sql("select row_to_json(q)::text from model_qualification_results q where id='"+legacy['id']+"'") == legacy_before
    assert active['operation']['status']=='SUCCEEDED' and active['state']['active_id']==identity
    receipt={'status':'PASS','adopt_operation':adopted['operation']['id'],'validation_operation':op_id,
        'validation_run':run_id,'validation':complete,'missing_key_no_writes':True,'restart_same_adopt':True,
        'legacy_unknown_blocks_until_real_native_terminal':True,'legacy_failure_preserved':True,'unknown_get_did_not_start':True,'explicit_retry_same_operation':True}
    (c['root']/'fault-preflight.json').write_text(json.dumps(receipt,indent=2))
    print('Legacy import/missing master/restart and validation UNKNOWN recovery: PASS',flush=True)

def exercise(c):
    api, sql, cmd, wait = c['api'], c['dbsql'], c['cmd'], c['wait']
    relay='http://127.0.0.1:'+c['port']('relay','7411/tcp')
    paused=[]
    def new_version(side):
        code, result=api(BASE, {'expected_generation':c['generation'](),'name':'Fault '+side,
            'endpoint':'http://provider-'+side+':8080/v1','protocol':'chat_completions',
            'model_identity':'model-'+side,'api_key':c['key_a'] if side=='a' else c['key_b']},
            headers={'Idempotency-Key':str(uuid.uuid4())})
        assert code==201, result
        identity=result['operation']['connection_id'];c['connections'].append(identity)
        result,_,_=operation(c,identity,'validate');completed(c,result['operation']['id'])
        result,_,_=operation(c,identity,'activate')
        assert result['operation']['status']=='SUCCEEDED'
        return identity
    def identity(table, record):
        return json.loads(sql(f"select json_build_object('version',connection_version_id,'run',agent_compose_run_id,'session',session_id,'fingerprint',config_fingerprint)::text from {table} where id='{record}'"))
    def park(table, record):
        row=wait(lambda: (value if value['session'] else None) if (value:=identity(table,record)) else None,'bound sandbox')
        containers=cmd(['docker','ps','--filter','ancestor=governance-runner:'+c['tag'],'--format','{{.ID}} {{.Names}}']).decode().splitlines()
        matched=[line.split()[0] for line in containers if line.split()[1]=='agent-compose-'+row['session'][:12]]
        assert len(matched)==1, {'sandbox':row['session'],'owned_image_container_names':containers}
        container=matched[0];cmd(['docker','pause',container]);paused.append(container)
        api('/release',{},url=c['provider_a'])
        wait(lambda: sql(f"select request_count from model_connection_leases where task_id='{record}'")=='1','first provider request committed')
        return container,row
    def finish(path, wanted):
        def check():
            code, result=api(path);assert code==200
            if result['status']=='FAILED' and wanted!='FAILED':raise AssertionError(result.get('failure_code'))
            return result if result['status']==wanted else None
        return wait(check,'fault task '+wanted)
    def resume(container):
        cmd(['docker','unpause',container]);paused.remove(container)
    try:
        a=new_version('a')
        draft_url='/api/v1/projects/'+c['project']+'/governance-reports/'+c['fixture']['report_id']+'/ai-governance-drafts'
        draft_key=str(uuid.uuid4());draft_body={'finding_ids':[c['fixture']['finding_id']]}
        draft_calls=len(api('/stats',url=c['provider_a'])[1]['calls'])
        draft_starts=sum(x['rpc']=='StartAgentRun' for x in api('/stats',url=relay)[1]['calls'])
        code,draft=api(draft_url,draft_body,headers={'Idempotency-Key':draft_key})
        if code==503 and draft.get('detail',{}).get('code')=='agent_compose_session_pending':
            # This explicit same-intent recovery observes the accepted Run; no new key.
            def recover_draft():
                status,value=api(draft_url,draft_body,headers={'Idempotency-Key':draft_key})
                assert status==200 or (status==503 and value.get('detail',{}).get('code')=='agent_compose_session_pending'), (status,value)
                return value if status==200 else None
            draft=wait(recover_draft,'accepted draft sandbox identity')
        else:
            assert code==202, (code,draft)
        assert sum(x['rpc']=='StartAgentRun' for x in api('/stats',url=relay)[1]['calls'])==draft_starts+1
        draft_binding=identity('ai_governance_drafts',draft['id'])
        assert draft_binding['version']==a and draft_binding['session']
        assert len(api('/stats',url=c['provider_a'])[1]['calls'])==draft_calls

        investigations='/api/v1/projects/'+c['project']+'/ai-investigations'
        scope={'resource_id':c['fixture']['resource_id'],'run_id':c['run']}
        api('/hold',{},url=c['provider_a'])
        starts_before=sum(x['rpc']=='StartAgentRun' for x in api('/stats',url=relay)[1]['calls'])
        api('/fault',{'mode':'drop_start_response'},url=relay)
        intent=str(uuid.uuid4())
        code, inv=api(investigations,scope,headers={'Idempotency-Key':intent})
        assert code==201 and inv['status']=='GENERATING', inv
        wait(lambda:api('/stats',url=c['provider_a'])[1]['waiting'],'investigation provider barrier')
        code,replay=api(investigations,scope,headers={'Idempotency-Key':intent})
        assert code==200 and replay['id']==inv['id']
        assert sum(x['rpc']=='StartAgentRun' for x in api('/stats',url=relay)[1]['calls'])==starts_before+1
        inv_box,inv_binding=park('ai_investigations',inv['id'])
        api('/hold',{},url=c['provider_a'])
        report=c['report']('fault-a-revoke')
        wait(lambda:api('/stats',url=c['provider_a'])[1]['waiting'],'report provider barrier')
        report_box,report_binding=park('analysis_reports',report)
        b=new_version('b')
        restart(c)
        code,replay=api(investigations,scope,headers={'Idempotency-Key':intent})
        assert code==200 and replay['id']==inv['id']
        assert identity('ai_investigations',inv['id'])==inv_binding
        assert inv_binding['version']==report_binding['version']==a
        resume(inv_box)
        done=finish(investigations+'/'+inv['id'],'COMPLETED')
        assert identity('ai_investigations',inv['id'])==inv_binding
        assert sql(f"select request_count from model_connection_leases where task_id='{inv['id']}'")=='2'
        revoked,_,_=operation(c,a,'revoke')
        assert revoked['operation']['status']=='SUCCEEDED' and revoked['state']['active_id']==b
        code,draft_replay=api(draft_url,draft_body,headers={'Idempotency-Key':draft_key})
        assert code==200 and draft_replay['id']==draft['id']
        assert identity('ai_governance_drafts',draft['id'])==draft_binding
        before=len(api('/stats',url=c['provider_a'])[1]['calls'])
        resume(report_box)
        failed=finish(c['reports']+'/'+report,'FAILED')
        assert len(api('/stats',url=c['provider_a'])[1]['calls'])==before
        assert identity('analysis_reports',report)==report_binding
        assert sql(f"select request_count from model_connection_leases where task_id='{report}'")=='1'
        newer=c['report']('fault-b-after-revoke');c['finished'](newer,'DRAFT')
        assert identity('analysis_reports',newer)['version']==b
        (c['root']/'fault-progress.json').write_text(json.dumps({'investigation_recovery':'PASS','revoke_no_next_egress':'PASS','b_continuity':'PASS','investigation':inv['id'],'report':report,'failure_code':failed.get('failure_code')}))
        keyfile=c['keys']/'v1.key';hidden=c['keys']/'v1.key.off';keyfile.rename(hidden)
        try:
            wait(lambda: subprocess.run(['docker','exec',c['names']['backend'],'test','!','-e','/run/model-keys/v1.key'],capture_output=True).returncode==0,'missing master visible in owned container',10)
            code,status=api(BASE+'/status')
            assert code==200 and status['state']=='unavailable' and not status['ready'] and status['active_version_id']==b, status
            count=len(api('/stats',url=c['provider_b'])[1]['calls'])
            code,denied=api(c['reports'],{'run_id':c['run']},headers={'Idempotency-Key':str(uuid.uuid4())})
            assert code==201 and denied['status']=='FAILED' and denied['failure_code']=='model_connection_secret_unavailable', (code,denied)
            assert identity('analysis_reports',denied['id'])['version']==b
            assert len(api('/stats',url=c['provider_b'])[1]['calls'])==count
        finally:hidden.rename(keyfile)
        wait(lambda: subprocess.run(['docker','exec',c['names']['backend'],'test','-e','/run/model-keys/v1.key'],capture_output=True).returncode==0,'restored master visible in owned container',10)
        code,status=api(BASE+'/status');assert code==200 and status['ready'] and status['active_version_id']==b, status
        preserved=api(c['reports']+'/'+denied['id'])[1]
        assert preserved['status']=='FAILED' and preserved['failure_code']==denied['failure_code']
        restored=c['report']('fault-b-after-master-restore');c['finished'](restored,'DRAFT')
        assert identity('analysis_reports',restored)['version']==b
        receipt={'status':'PASS','managed_draft':draft['id'],'managed_draft_identity':draft_binding,'managed_draft_zero_model_requests':True,'version_a':a,'version_b':b,'investigation':inv['id'],'investigation_identity':inv_binding,
            'start_reply_lost_same_key_no_second_start':True,'same_sandbox_after_backend_restart':True,
            'investigation_model_requests':2,'revoked_report':report,'revoked_report_identity':report_binding,
            'revoked_report_failure':failed.get('failure_code'),'revoked_report_requests':1,
            'provider_a_no_additional_call_after_revoke':True,'new_b_report':newer,
            'master_missing_failed_report':denied['id'],'master_restored_new_report':restored,'master_missing_no_egress_and_pointer_unchanged':True,'result_status':done['status']}
        (c['root']/'fault-results.json').write_text(json.dumps(receipt,indent=2))
        print('Actual investigation A recovery / report A revoke / B continuity: PASS',flush=True)
        return receipt
    finally:
        for container in paused:cmd(['docker','unpause',container],check=False)
        api('/release',{},url=c['provider_a'])


def legacy_boundary(c, version, start=False):
    code = r"""
import hashlib,json,sys,uuid
from sqlmodel import Session
from app.core.config import settings
from app.core.db import engine
from app.domain.models import ModelQualificationResult
from app.domain.model_connections import get_version
from app.integrations.agent_compose import AgentComposeClient
from app.integrations.model_connection_runtime import project_spec
client=AgentComposeClient()
run=client._expected_run_id(agent_name='model-qualification',client_request_id='legacy-boundary')
if sys.argv[2]=='seed':
 with Session(engine) as s:
  q=ModelQualificationResult(model_endpoint_sha256=hashlib.sha256(settings.MODEL_API_ENDPOINT.encode()).hexdigest(),
   model_identity='synthetic-legacy',config_fingerprint='0'*64,fixture_version='expux02-legacy-boundary-v1',
   status='FAIL',availability_numerator=0,availability_denominator=4,traceable_citations=0,total_citations=0,
   hallucination_count=0,finding_modification_count=0,unauthorized_side_effect_count=0,
   failure_code='synthetic_prior_failure',agent_compose_run_id=run)
  s.add(q);s.commit();s.refresh(q);print(json.dumps({'id':str(q.id),'run':run}))
else:
 import time
 with Session(engine) as s:
  spec=project_spec(get_version(s,uuid.UUID(sys.argv[1])))
 spec['name']=settings.AGENT_COMPOSE_PROJECT_NAME
 spec['agents']=spec['agents'][:1]
 spec['agents'][0].update(name='model-qualification',env=[])
 checked=client._request('/agentcompose.v2.ProjectService/ValidateProject',{'spec':spec})
 assert checked['valid']
 client._request('/agentcompose.v2.ProjectService/ApplyProject',{'spec':spec})
 client._start_run(agent_name='model-qualification',client_request_id='legacy-boundary',environment={},
  command='/app/.venv/bin/python -c \'print("synthetic terminal session boundary")\'')
 end=time.monotonic()+30
 while time.monotonic()<end:
  observed=client.get_run(run)
  if observed and observed.is_terminal:break
  time.sleep(.2)
 assert observed and observed.is_terminal
 print(json.dumps({'run':run,'session':observed.session_id,'terminal':True}))
"""
    return json.loads(c['cmd'](['docker','exec','-i',c['names']['backend'],'python','-',version,'start' if start else 'seed'],code.encode()))
