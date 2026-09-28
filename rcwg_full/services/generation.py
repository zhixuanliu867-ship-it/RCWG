"""Catalog-bound generation and proof of a resolved facility attempt.

The retry is a new generation attempt. Its actual COUNT/G request IDs and paid
reservations are new; the previous attempt and every response remain immutable.
No callback here can reconcile an uncertain provider send by assumption.
"""
import json
from pathlib import Path
from rcwg_full.evidence import digest,read,sha,write,source_hashes,canonical
from rcwg_full.campaign.store import Conflict
from .client import generate


class PreparedGenerator:
    def __init__(self,catalog,clients,*,local_counters=None):
        self.catalog=catalog;self.clients=clients;self.local_counters=local_counters or {}

    def context(self,slot):
        item=self.catalog[slot['task_id']];raw=read(item['task_path'])
        if sha(raw)!=item['task_sha256']:raise ValueError('TASK_SOURCE_CHANGED')
        client=self.clients[slot['generator']]
        return json.loads(raw),client,{'task_sha256':sha(raw),'source_hash':digest(source_hashes()),
            'binding_hash':digest(client.binding),'mode':client.mode,'slot_hash':digest(slot)}

    def __call__(self,slot,attempt_id,dependencies,directory):
        task,client,context=self.context(slot)
        from rcwg_full.campaign.transforms import public_guidance
        result=generate(task,slot,client,attempt_id,local_counter=self.local_counters.get(slot['generator']),
            guidance=public_guidance(task) if slot.get('generation_stage')=='GUIDED_PHYSICAL' else None)
        if result['status'] in {'MODEL_FAILURE','PLAN_INVALID'}:result['failure_class']='CONFIRMED_PLAN'
        elif result['status']=='INFRA_FAILURE':result['failure_class']='INFRASTRUCTURE'
        request_ids=set()
        for record in result['records']:
            response=record.get('response',{});measurement=record.get('input_measurement') or {}
            if response.get('request_id'):request_ids.add(response['request_id'])
            if measurement.get('count_request_id'):request_ids.add(measurement['count_request_id'])
        proof={'revision':'FULL001_GENERATION_REQUEST_SET_1','attempt_id':attempt_id,'context':context,
               'request_ids':sorted(request_ids),'result_hash':digest(result),'handler_returned':True}
        proof_hash=write(Path(directory)/'generation-requests.json',proof)
        return {**result,'generation_context_hash':digest(context),'generation_requests_sha256':proof_hash}

    def reconcile(self,slot,outcome,directory):
        _,client,context=self.context(slot);path=Path(directory)/'generation-requests.json';raw=read(path)
        if sha(raw)!=outcome.get('generation_requests_sha256'):raise Conflict('RETRY_GENERATION_PROOF_CHANGED')
        proof=json.loads(raw)
        if (proof.get('context')!=context or proof.get('attempt_id')!=outcome.get('attempt_id') or
            outcome.get('generation_context_hash')!=digest(context) or proof.get('handler_returned') is not True):
            raise Conflict('RETRY_GENERATION_CONTEXT_CHANGED')
        if not proof['request_ids']:raise Conflict('RETRY_GENERATION_REQUEST_EVIDENCE_MISSING')
        files={};observed_failure=False
        # A synchronous handler return is insufficient: inspect the durable index
        # and the immutable raw provider response for every G and COUNT request.
        with client.index.lock:
            if client.index.active_operations:raise Conflict('RETRY_REQUEST_NOT_RECONCILED')
            for request_id in proof['request_ids']:
                row=client.index.db.execute('SELECT payload_hash,status,result FROM requests WHERE id=?',(request_id,)).fetchone()
                if row is None or row[1] not in {'COMPLETED','INFRA_FAILURE'} or not row[2]:raise Conflict('RETRY_REQUEST_NOT_RECONCILED')
                request_path=client.index.root/request_id/'request.json';request_raw=read(request_path);request=json.loads(request_raw)
                response=json.loads(row[2]);response_path=client.index.root/request_id/(row[1].lower()+'.json')
                if (digest(request)!=row[0] or request.get('generation_attempt_id')!=proof['attempt_id'] or
                    request.get('binding_hash')!=context['binding_hash'] or request.get('task_hash')!=digest(json.loads(read(self.catalog[slot['task_id']]['task_path']))) or
                    response.get('sent') is not True or response.get('request_id')!=request_id or
                    json.loads(read(response_path))!=response):raise Conflict('RETRY_REQUEST_BINDING')
                raw_path=client.index.root/request_id/'response.raw'
                if sha(read(raw_path))!=response.get('response_raw_hash'):raise Conflict('RETRY_RESPONSE_CHANGED')
                files[request_id]={'request_sha256':sha(request_raw),'response_sha256':sha(read(response_path)),
                                   'raw_sha256':sha(read(raw_path)),'status':row[1]}
                observed_failure|=row[1]=='INFRA_FAILURE'
        if not observed_failure:raise Conflict('RETRY_GENERATION_FAILURE_UNPROVED')
        return {'parent_attempt_id':proof['attempt_id'],'context_hash':digest(context),'requests':files,
                'generation_requests_sha256':sha(raw),'worker_stopped':True,'request_uncertain':False}
