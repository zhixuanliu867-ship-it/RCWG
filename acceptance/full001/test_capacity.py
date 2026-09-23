import unittest
from rcwg_full.data.capacity import capacity_plan
from rcwg_full.evidence import digest


class CapacityTests(unittest.TestCase):
    def test_all_parameters_and_counts_are_predeclared_without_allocating_data(self):
        plan=capacity_plan();self.assertEqual(plan['counts'],{'templates':72,'instances':1440,'development':480,'test':960})
        self.assertEqual(len(plan['instances']),1440);self.assertFalse(plan['data_allocation_performed'])
        self.assertEqual(plan['parameter_table_hash'],digest(plan['parameter_table']))
        self.assertEqual(plan,capacity_plan());self.assertFalse(plan['host_load_authorized'])

    def test_exact_primary_scale_and_single_axis_conditions(self):
        plan=capacity_plan();by_id={r['task_id']:r for r in plan['instances']}
        for item in plan['parameter_table']:
            prefix=item['template_id']+'-b0-';base=by_id[prefix+'C0'];low=by_id[prefix+'C2'];layout=by_id[prefix+'C3']
            self.assertEqual(base['data_parameters'],low['data_parameters']);self.assertEqual(base['data_parameters'],layout['data_parameters'])
            self.assertEqual(base['cpu_slots'],low['cpu_slots']);self.assertEqual(base['worker_memory_limit_bytes'],4*low['worker_memory_limit_bytes'])
        self.assertEqual(by_id['F1-01-b0-C1']['data_parameters']['rows'],1000000)
        self.assertEqual(by_id['F1-02-b0-C1']['data_parameters']['rows'],100000)
        self.assertEqual(by_id['F2-01-b0-C1']['data_parameters']['right_rows'],10000)
        self.assertEqual(by_id['F3-01-b0-C1']['data_parameters'],{'nodes':100000,'edges_upper':800000})
        self.assertEqual(by_id['F4-01-b0-C1']['data_parameters']['object_target_bytes'],4*1024**3)

    def test_unknown_source_and_host_capacity_are_not_zero_or_accepted(self):
        plan=capacity_plan();self.assertEqual(plan['source_payload_estimate_unknown_instances'],480)
        self.assertIsNone(plan['aggregate_disk_upper_bytes']);self.assertIsNone(plan['aggregate_builder_ram_upper_bytes'])
        self.assertTrue(all(r['builder_peak_ram_bytes'] is None for r in plan['instances']))
        self.assertTrue(all(r['formal_reference_feasibility']=='NOT_VALIDATED' for r in plan['instances']))
        self.assertTrue(all(not r['formal_frozen'] for r in plan['parameter_table']));self.assertFalse(plan['implicit_shrink_allowed'])
