import unittest
import test_reference_runtime as fixture


class GraphCandidateRuntime(unittest.TestCase):
    setUpClass=classmethod(fixture.CandidateRuntime.setUpClass.__func__)
    run_variants=fixture.CandidateRuntime.run_variants


for number in range(1,13):
    setattr(GraphCandidateRuntime,f'test_F3_{number:02d}_eight_candidates',fixture.case(f'F3-{number:02d}'))
