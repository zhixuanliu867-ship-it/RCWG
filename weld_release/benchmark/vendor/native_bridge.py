"""Native AppWorld in an isolated release-local workspace. JSON stdout protocol."""
import os,sys,json,re,hashlib
from pathlib import Path
R=Path(os.environ['RCWG_RELEASE_ROOT']);os.environ['APPWORLD_ROOT']=str(R/'local_only/appworld_workspace');os.environ['APPWORLD_CACHE']=str(R/'local_only/cache');os.environ['PYTHONUTF8']='1'
sys.stdout.reconfigure(encoding='utf-8');sys.stdin.reconfigure(encoding='utf-8')
from appworld import AppWorld
def evaluate(w):
    result=w.evaluate().to_dict();result['native_success']=result['success']
    from appworld.task import Task
    from appworld.apps.model_lib import get_db_home_path
    from appworld.collections.models import ModelCollection,ModelCollectionPair
    t=Task.load(w.task_id);start=t.model_collection;ep=get_db_home_path(storage_type='memory',type='task_output',task_id=w.task_id)
    end=ModelCollection.load(to_db_home_path=ep,from_db_home_path=w.output_db_home_path_on_disk,load_apps=t.allowed_apps)
    pair=ModelCollectionPair(start_db_home_path=start.from_db_home_path,start_model_collection=start,end_db_home_path=ep,end_model_collection=end)
    if w.task_id=='b0a8eae_1':
        private=json.loads((R/f'local_only/appworld_workspace/data/tasks/{w.task_id}/ground_truth/private_data.json').read_text())
        user=end.spotify.User.find_from(t.supervisor);initial_user=start.spotify.User.find_from(t.supervisor);player=end.spotify.MusicPlayer.find_one(user_id=user.id)
        queue=player.queue_songs;queue_ids=sorted(x.id for x in queue);eligible=[]
        for playlist in initial_user.playlists:
            songs=playlist.songs
            if sum(x.duration for x in songs)>=60*private['workout_duration_mins']:eligible.append(sorted(x.id for x in songs))
        changed=pair.changed_model_names(ignore=['supervisor.Task','admin.PaymentCard']);collateral={}
        for model in sorted(changed-{'spotify.MusicPlayer'}):
            a,u,d=pair.changed_records(model);collateral[model]={'added':len(a),'updated':len(u),'removed':len(d)}
        count=sum(sum(x.values()) for x in collateral.values());checks={'playing':bool(player.is_playing),'duration_requirement':sum(x.duration for x in queue)>=60*private['workout_duration_mins'],'whole_eligible_library_playlist':queue_ids in eligible,'unrelated_state_preserved':count==0,'task_marked_complete':any(x.status=='success' for x in end.supervisor.Task.all())}
        result.update(additional_contract_checks=checks,collateral_changes=collateral,collateral_change_count=count,eligible_playlist_count=len(eligible),required_duration_seconds=60*private['workout_duration_mins'],queue_duration_seconds=sum(x.duration for x in queue),dataset_revision='MUSIC_SECONDS_V2',success=all(checks.values()),contract_adaptation='Any whole eligible playlist from the original library is accepted. The original stricter song-set result remains native_success.')
        return result
    if w.task_id!='22cc237_1':return result
    added,updated,removed=pair.changed_records('venmo.PaymentRequest')
    g=json.loads((R/f'local_only/appworld_workspace/data/tasks/{w.task_id}/ground_truth/private_data.json').read_text())['pending_user_id_to_share'];g={str(k).removeprefix('{_INT_}:'):v for k,v in g.items()}
    rows=[{'receiver_id':x.receiver_id,'amount':x.amount,'description':x.description} for x in added];ids=[str(x['receiver_id']) for x in rows]
    checks={'exact_request_multiplicity':len(rows)==len(g) and len(set(ids))==len(rows),'exact_recipients':set(ids)==set(g),'amounts_to_cent':all(str(x['receiver_id']) in g and abs(x['amount']-g[str(x['receiver_id'])])<.005 for x in rows),'required_description':all(x['description']=='Work Dinner' for x in rows),'existing_requests_preserved':not updated and not removed}
    changed=pair.changed_model_names(ignore=['supervisor.Task','admin.PaymentCard'])
    collateral={}
    for model in sorted(changed-{'venmo.PaymentRequest','venmo.Notification'}):
        a,u,d=pair.changed_records(model);collateral[model]={'added':len(a),'updated':len(u),'removed':len(d)}
    count=sum(sum(x.values()) for x in collateral.values())+len(updated)+len(removed)
    checks['unrelated_state_preserved']=count==0
    result.update(additional_contract_checks=checks,added_request_count=len(rows),expected_request_count=len(g),protected_request_changes=len(updated)+len(removed),collateral_changes=collateral,collateral_change_count=count,added_requests=rows,success=result['success'] and all(checks.values()))
    return result
def main(episode,tid):
    with AppWorld(task_id=tid,experiment_name=episode,timeout_seconds=None,raise_on_unsafe_syntax=True,null_patch_unsafe_execution=True) as w:
        initialized=False
        for line in sys.stdin:
            req=json.loads(line)
            if req['op']=='close':break
            if req['op']=='evaluate':
                print(json.dumps({'evaluation':evaluate(w)},default=str),flush=True);continue
            before=len(w.requester.request_tracker.requests);path=Path(w.output_db_home_path_on_disk)/'model_hashes.json';old=json.loads(path.read_text()) if path.exists() else {}
            try:
                op=req['op'];app=req.get('app','');api=req.get('api','')
                if op in ('app_call','api_doc') and (not re.fullmatch('[a-z][a-z0-9_]*',app) or api and not re.fullmatch('[a-z][a-z0-9_]*',api)):raise ValueError('Invalid app or API name')
                if op=='profile':code='print(apis.supervisor.show_profile())'
                elif op=='list_apps':code='print(apis.api_docs.show_app_descriptions())'
                elif op=='api_doc':code=f'print(apis.api_docs.show_api_doc(app_name={app!r},api_name={api!r}))' if api else f'print(apis.api_docs.show_api_descriptions(app_name={app!r}))'
                elif op=='app_call':
                    args=req.get('arguments',{}).copy()
                    if not initialized:w.execute("profile=apis.supervisor.show_profile(); passwords={x['account_name']:x['password'] for x in apis.supervisor.show_account_passwords()}; session_tokens={}");initialized=True
                    if api=='login' or app=='supervisor' and api=='show_account_passwords':raise ValueError('Authentication is handled by the bridge')
                    docpath=R/f'local_only/appworld_workspace/data/api_docs/standard/{app}.json'
                    doc=json.loads(docpath.read_text()) if docpath.exists() else {}
                    needs_auth=any(x['name']=='access_token' for x in doc.get(api,{}).get('parameters',[]))
                    if app in ('phone','simple_note','venmo','spotify') and needs_auth:
                        login=f"\nif {app!r} not in session_tokens: session_tokens[{app!r}]=apis.{app}.login(username=profile['phone_number' if {app!r}=='phone' else 'email'],password=passwords[{app!r}])['access_token']\n"
                        args.pop('access_token',None);code=login+f"call_arguments={args!r}; call_arguments['access_token']=session_tokens[{app!r}]; print(apis.{app}.{api}(**call_arguments))"
                    else:code=f'print(apis.{app}.{api}(**{args!r}))'
                else:raise ValueError('Unknown typed operation')
                result=w.execute(code)
            except Exception as exc:result='Execution failed. '+type(exc).__name__+': '+str(exc)
            current=json.loads(path.read_text()) if path.exists() else {};calls=w.requester.request_tracker.requests[before:]
            committed=old.get('venmo',{}).get('PaymentRequest')!=current.get('venmo',{}).get('PaymentRequest') and any(x['url']=='/venmo/payment_requests' and x['method']=='post' for x in calls)
            print(json.dumps({'output':result,'api_calls':len(calls),'business_committed':committed,'native_calls':[{'method':x['method'],'url':x['url']} for x in calls],'failed':result.startswith('Execution failed.'),'state_hash':hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()},default=str),flush=True)
if __name__=='__main__':main(*sys.argv[1:3])
