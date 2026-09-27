from pathlib import Path
import unittest
from rcwg_full.acceptance_stages import negative_fixture_link


class Auto2AcceptanceLinks(unittest.TestCase):
    def test_inherited_negative_symlink_is_indexed_without_following(self):
        root=Path('/fixture/native-original');case=root/'results/test_source_symlink_rejected_without_spawn'
        record=negative_fixture_link(root,case/'alias.jsonl',str(case/'fixture/records.jsonl'))
        self.assertEqual(record['kind'],'EXPECTED_NEGATIVE_TEST_SYMLINK')
        self.assertEqual(record['target'],str(case/'fixture/records.jsonl'))

    def test_unrecognized_or_retargeted_symlinks_remain_rejected(self):
        root=Path('/fixture/native-original');case=root/'results/test_source_symlink_rejected_without_spawn'
        for file,target in [(case/'alias.jsonl','/outside/private'),(case/'other.jsonl',str(case/'fixture/records.jsonl'))]:
            with self.assertRaisesRegex(ValueError,'STAGE_SYMLINK'):negative_fixture_link(root,file,target)
