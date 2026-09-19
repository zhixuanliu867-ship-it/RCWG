"""Coverage derived from retained actual dispatch journals and passed method IDs."""
from pathlib import Path
from rcwg_spec.common import digest
from rcwg_exec.journal import read_json
from rcwg_exec.runner import SUPPORTED

R='test_exec001_reference.';S='test_exec001_supervisor.';C='test_exec001_campaign.'
def ids(prefix,cls,*methods):return [prefix+cls+'.test_'+method for method in methods]

GATE_METHODS={
 'X01':ids(S,'SupervisorTests','eight_branches_actually_dispatch')+ids(R,'KernelTests','projection_is_real_view','projection_copy_distinct','bounded_batch_filter'),
 'X02':ids(R,'KernelTests','property_against_independent_key','empty','k_zero_still_drains','fewer_than_k','tie_id','equal_all_keys_uses_ordinal','nulls_last_desc','nulls_first_asc','and_unknown_false','or_unknown_true')+ids(S,'JournalAndSourceTests','actual_registered_file_duplicate_and_bad_utf8_rejected'),
 'X03':ids(S,'SupervisorTests','wrong_choices_execute_unchanged_and_fail_semantics','eight_branches_actually_dispatch')+ids(C,'CampaignTests','mock_plan_not_replaced_by_successful_fixed_plan'),
 'X04':ids(S,'SupervisorTests','distinct_worker_process_and_fresh_repeat','real_hard_deadline_interrupts_uncooperative_worker','owner_cancel_is_unknown_not_model_failure','timeout_cleans_descendant_process_group','crash_and_nonzero_are_facility_failures','worker_does_not_inherit_credentials'),
 'X05':ids(S,'SupervisorTests','manifest_written_before_spawn_and_exact_request')+ids(C,'CampaignTests','manifest_is_snapshot_not_mutable_case_reference','missing_attempt_remains_in_denominator','parse_static_gap_and_crash_keep_predeclared_slots','execution_repeats_separate_from_generation_ids'),
 'X06':ids(S,'SupervisorTests','worker_artifact_metadata_fault_detected','worker_artifact_binding_fault_detected','interrupted_artifact_stays_private_and_unsealed','reread_rejects_content_metadata_and_context_swaps','reread_rejects_cross_execution_artifact_even_identical_result','rewriting_seal_cannot_replace_external_anchor','output_timestamp_cannot_predate_this_run','private_output_modes_and_exclusive_run'),
 'X07':ids(S,'JournalAndSourceTests','ancestor_directory_symlink_rejected','source_replaced_by_symlink_after_registration_rejected','source_changed_while_iterator_active_rejected','actual_registered_file_duplicate_and_bad_utf8_rejected','nonregular_fifo_rejected_without_waiting_for_writer')+ids(R,'SourceAndStoreTests','bad_file_hash','registry_unknown_identity','row_count_mismatch','bool_is_not_int')+ids(R,'ExecutionTests','input_task_registry_binding'),
 'X08':ids(S,'SupervisorTests','partial_journal_prefix_retained_after_crash','corrupt_complete_journal_is_facility_error','real_node_events_have_queue_ready_running_finished','node_event_drop_repeat_reorder_or_dispatch_change_rejected')+ids(S,'JournalAndSourceTests','journal_fsync_is_incremental_and_hash_chained','journal_rejects_foreign_clock_pid_or_context','rehashed_backwards_clock_and_wrong_node_status_rejected'),
 'X09':ids(S,'SupervisorTests','verifier_recipe_stays_parent_side','wrong_recipe_produces_unknown_not_repaired_gold','wrong_choices_execute_unchanged_and_fail_semantics')+ids(C,'CampaignTests','p0_p1_real_parser_compiler_worker_request_counts'),
 'X10':ids(S,'SupervisorTests','measurement_scope_censoring_and_missingness','memory_protection_cap_is_facility_not_oom','real_hard_deadline_interrupts_uncooperative_worker'),
 'X11':ids(S,'SupervisorTests','static_failure_and_profile_gap_do_not_spawn')+ids(R,'ExecutionTests','after_is_facility_gap_not_model_failure','dead_node_not_pruned','unsupported_algorithm_no_fallback','explicit_multiple_cpu_no_false_honor'),
 'X12':ids(C,'CampaignTests','p0_p1_real_parser_compiler_worker_request_counts','mock_plan_not_replaced_by_successful_fixed_plan','p1_invalid_logical_stops_before_second_request','execution_repeats_separate_from_generation_ids','changed_generation_or_expected_manifest_rejected'),
 'X14':ids(S,'SupervisorTests','source_closure_change_during_worker_rejects_success','verifier_recipe_stays_parent_side'),
}

BRANCH_METHODS={
 'scan':ids(R,'ExecutionTests','real_byte_count')+ids(S,'JournalAndSourceTests','source_changed_while_iterator_active_rejected'),
 'filter':ids(R,'KernelTests','scalar_filter','bounded_batch_filter','and_unknown_false')+ids(S,'SupervisorTests','dynamic_division_by_zero_is_model_failure'),
 'project':ids(R,'KernelTests','projection_is_real_view','projection_copy_distinct')+ids(S,'SupervisorTests','wrong_choices_execute_unchanged_and_fail_semantics'),
 'top_k':ids(R,'KernelTests','full_sort_really_materializes','heap_bound_and_dispatch','property_against_independent_key')+ids(S,'SupervisorTests','wrong_choices_execute_unchanged_and_fail_semantics'),
 'emit':ids(S,'SupervisorTests','worker_artifact_metadata_fault_detected','worker_artifact_binding_fault_detected','interrupted_artifact_stays_private_and_unsealed'),
}

OBLIGATIONS={
 'GLOBAL_CPU_SLOTS':('ENGINEERING_SERIAL_SINGLE_WORKER','One Python compute thread; OS CPU quota and formal isolation are NOT_VERIFIED.'),
 'GLOBAL_INSTANCE_COUNTER':('ROOT_CHAIN_STATIC_AND_OBSERVED','Static node cap and unique queued node instances; no regions or repeated instances admitted.'),
 'WORKER_MEMORY_LIMIT':('UNKNOWN_NOT_ISOLATED','No cgroup writes or isolated RAM observation; budget_within remains null.'),
 'WALL_TIMEOUT':('PARENT_DEADLINE_TESTED','Parent monotonic deadline, process-group termination; incomplete completed_wall_ns is null.'),
 'PREDICATE_THREE_VALUED_EVALUATION':('REFERENCE_AST_TESTED','Actual bounded AST evaluation and Bool/Int/null/overflow contract regressions.'),
 'EXACT_OUTPUT_AND_TIE_CHECK':('INDEPENDENT_ORACLE_TESTED','Independent fixed task recipe, exact canonical rows and order; plan choices preserved.'),
 'RESULT_ARTIFACT_HASH':('SEALED_AND_REOPENED','Actual bytes, metadata, execution identity and external seal anchor.'),
 'INDEPENDENT_VERIFICATION':('PARENT_VERIFIER_TESTED','Parent after worker exit; PASS, FAIL, UNKNOWN and separate clocks.'),
}


def runtime_coverage(directory,passed_ids):
    directory=Path(directory);passed=set(passed_ids);summary=read_json(directory/'campaign.json')
    observed={};obligations={};cases=[];violations=[]
    for record in summary['records']:
        ident=record['attempt_id'];folder=directory/ident;attempt=read_json(folder/'attempt.json');result=attempt['result']
        if 'seal_sha256' not in result:continue
        execution=folder/'execution';plan=read_json(execution/'plan.json');compiled=read_json(execution/'compiler_report.json')
        lines=(execution/'worker.journal.jsonl').read_bytes().splitlines() if (execution/'worker.journal.jsonl').exists() else []
        import json
        events=[]
        for line in lines:
            try:item=json.loads(line)
            except (ValueError,UnicodeError):continue
            if isinstance(item,dict) and 'event' in item:events.append(item)
        started={e['payload']['node_instance_id']:e for e in events if e['event']=='node_started'}
        finished={e['payload']['node_instance_id']:e for e in events if e['event']=='node_finished' and e['status']=='COMPLETED'}
        if result['terminal_status']=='COMPLETED' and attempt['verification']=='PASS':
            for node in plan['nodes']:
                key='root/'+node['id']+'#0';pair=node['operator']+':'+node['implementation']
                if key not in started or key not in finished:violations.append(ident+':MISSING_NODE:'+key);continue
                observed.setdefault(pair,[]).append({'attempt_id':ident,'node_instance_id':key,
                    'plan_hash':digest(plan),'execution_key':result['execution_key'],'journal':'./'+ident+'/execution/worker.journal.jsonl',
                    'start_sequence':started[key]['sequence'],'finish_sequence':finished[key]['sequence'],
                    'counters':finished[key]['payload']['counters']})
        for obligation in compiled['runtime_obligations']:
            code=obligation['code'];obligations.setdefault(code,[]).append({'attempt_id':ident,'declaration':obligation})
        queued=[e for e in events if e['event']=='node_queued']
        if len(queued)>plan.get('limits',{}).get('max_node_instances',4096):violations.append(ident+':INSTANCE_LIMIT')
        cases.append({'attempt_id':ident,'terminal_status':result['terminal_status'],'verification':attempt['verification'],
                      'data_hashes':[s['data_sha256'] for s in read_json(execution/'task.json')['datasets']],
                      'plan_hash':digest(plan),'expected_manifest_hash':result['expected_manifest_hash'],
                      'queued_instance_count':len(queued),'seal_sha256':result['seal_sha256']})
    branches=[]
    for op,implementations in SUPPORTED.items():
        for implementation in sorted(implementations):
            pair=op+':'+implementation;required=BRANCH_METHODS[op]+GATE_METHODS['X01'][:1]
            missing=sorted(set(required)-passed)
            branches.append({'operator':op,'implementation':implementation,'status':'COVERED' if observed.get(pair) and not missing else 'MISSING',
                             'required_test_ids':required,'missing_test_ids':missing,'actual_dispatch':observed.get(pair,[])})
    gate_tests={gate:{'required_test_ids':methods,'missing_test_ids':sorted(set(methods)-passed),
                           'status':'PASS' if set(methods)<=passed else 'FAIL'} for gate,methods in GATE_METHODS.items()}
    return {'status':'EXEC001_RUNTIME_COVERAGE_PASS' if all(b['status']=='COVERED' for b in branches)
             and all(g['status']=='PASS' for g in gate_tests.values()) and not violations else 'EXEC001_RUNTIME_COVERAGE_FAILED',
            'operator_count':len(SUPPORTED),'reference_branch_count':len(branches),'branches':branches,
            'gate_test_coverage':gate_tests,'violations':violations,'actual_cases':cases,
            'runtime_obligations':[{'code':code,'status':OBLIGATIONS.get(code,('NOT_DISCHARGED','Unknown obligation'))[0],
                'scope':OBLIGATIONS.get(code,('NOT_DISCHARGED','Unknown obligation'))[1],'actual_declarations':rows}
                 for code,rows in sorted(obligations.items())],
            'unsupported':['general DAG','fanout/dead nodes','after','regions','disk','node parallelism',
                           'graph/document/control kernels','native backend','isolated cgroup RAM'],
            'full_workir_runtime':False,'formal_ready':False}
