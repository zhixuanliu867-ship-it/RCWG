"""Concrete bounded state descriptors remain local to the FULL001 profile."""
import unittest
from rcwg_spec.common import ContractError
from rcwg_spec.typesystem import parse_type as old_parse
from rcwg_full.compiler.typesystem import parse_type,type_json,same_type,check_declared
from rcwg_full.runtime.values import validate


class BoundedTypes(unittest.TestCase):
    def descriptor(self,bound=3):return {'kind':'List','item':'Int64','max_length':bound}
    def test_explicit_bound_roundtrip(self):
        t=parse_type(self.descriptor());self.assertEqual(type_json(t),{'kind':'List','item':{'kind':'Int64'},'max_length':3})
        self.assertTrue(same_type(t,parse_type(type_json(t))))
    def test_original_profile_rejects_new_list(self):
        with self.assertRaises(ContractError):old_parse(self.descriptor())
    def test_list_rejects_unknown_unbounded_and_boolean_bounds(self):
        for descriptor in [{'kind':'List','item':'Int64'},self.descriptor(-1),self.descriptor(4097),self.descriptor(True),'List[Int64]']:
            with self.assertRaises(ContractError):parse_type(descriptor)
    def test_list_bounds_participate_in_type_identity(self):
        a=parse_type(self.descriptor(2));b=parse_type(self.descriptor(3))
        self.assertFalse(same_type(a,b));check_declared(a,type_json(b))
        with self.assertRaises(ContractError):check_declared(b,type_json(a))
    def test_runtime_list_count_and_elements(self):
        t=type_json(parse_type(self.descriptor()));validate([1,2,3],t,None)
        with self.assertRaisesRegex(ValueError,'LIST_LIMIT'):validate([1,2,3,4],t,None)
        with self.assertRaisesRegex(ValueError,'RUNTIME_TYPE'):validate([True],t,None)
    def test_nested_record_lists_keep_independent_bounds(self):
        t=parse_type({'kind':'Record','schema':{'a':self.descriptor(2),'b':self.descriptor(1)}})
        validate({'a':[1,2],'b':[3]},type_json(t),None)
        with self.assertRaisesRegex(ValueError,'LIST_LIMIT'):validate({'a':[1],'b':[2,3]},type_json(t),None)
