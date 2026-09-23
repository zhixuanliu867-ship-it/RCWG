import unittest
import test_reference_runtime as fixture


class StreamCandidates(unittest.TestCase):
    setUpClass=classmethod(fixture.CandidateRuntime.setUpClass.__func__)
    run_variants=fixture.CandidateRuntime.run_variants


for number in range(1,13):
    setattr(StreamCandidates,f'test_F4_{number:02d}_eight_candidates',fixture.case(f'F4-{number:02d}'))
