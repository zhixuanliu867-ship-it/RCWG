"""Automatic labels preserve source alternatives and enforce public isolation."""
import unittest
from rcwg_full.auto2.data import label_record,public_export,check_source_answers,check_source_set
from rcwg_full.evidence import digest


class Auto2Data(unittest.TestCase):
    def test_original_is_not_a_new_human_review(self):
        label=label_record('SOURCE_ANNOTATED',{'release':'immutable'})
        self.assertEqual(label['new_human_reviews'],0);self.assertTrue(label['automatic_label_admission'])
    def test_program_derivation_requires_dependencies_and_operation(self):
        with self.assertRaises(ValueError):label_record('PROGRAM_DERIVED',{})
        label=label_record('PROGRAM_DERIVED',{},dependencies=['source-label'],operation={'count':1})
        self.assertEqual(label['label_class'],'PROGRAM_DERIVED')
    def test_controlled_requires_fact_structure(self):
        with self.assertRaises(ValueError):label_record('CONTROLLED_TEXT_GRAPH',{})
        self.assertEqual(label_record('CONTROLLED_TEXT_GRAPH',{},facts={'a':1})['facts_hash'],digest({'a':1}))
    def test_unreviewed_extension_is_not_automatically_scored(self):
        self.assertFalse(label_record('UNREVIEWED_EXTENSION',{})['automatic_label_admission'])
    def test_document_metadata_cannot_export_answers(self):
        with self.assertRaises(ValueError):public_export({'documents':[{'metadata':{'answer':'CANARY'}}]})
    def test_top_level_private_is_rejected(self):
        with self.assertRaises(ValueError):public_export({'private':{'gold':'CANARY'}})
    def test_source_metadata_cannot_export_annotator_identity(self):
        with self.assertRaises(ValueError):public_export({'provenance':{'nested':[{'annotator_id':'CANARY'}]}})
    def test_public_text_remains_content_even_if_it_mentions_gold(self):
        self.assertEqual(public_export({'documents':[{'canonical_text':'The word gold is ordinary source text.'}]}),{'documents':[{'canonical_text':'The word gold is ordinary source text.'}]})
    def recipe(self):
        doc={'document_id':'p','revision':'r','canonical_text':'A is 1. B is 2.'}
        def alt(value,start,end):
            return {'fields':{'answer':{'acceptable_values':[value],'critical':True}},'exact_fields':True,
                'evidence_obligations':[{'id':'source','acceptable_witness_sets':[[{'document_id':'p','revision':'r','start_cp':start,'end_cp':end,'quote':doc['canonical_text'][start:end]}]]}]}
        return {'document':doc,'alternatives':[alt('A',0,7),alt('B',8,15)]}
    def row(self,answer,start,end):
        return {'answer':answer,'evidence':[{'document_id':'p','revision':'r','start_cp':start,'end_cp':end,'quote':self.recipe()['document']['canonical_text'][start:end]}]}
    def test_any_complete_original_alternative_is_accepted(self):
        self.assertEqual(check_source_answers([self.row('B',8,15)],self.recipe())['status'],'PASS')
    def test_different_annotators_answer_and_witness_cannot_be_mixed(self):
        self.assertEqual(check_source_answers([self.row('A',8,15)],self.recipe())['status'],'FAIL')
    def test_wrong_unicode_source_coordinates_fail(self):
        row=self.row('A',0,7);row['evidence'][0]['quote']='different'
        self.assertEqual(check_source_answers([row],self.recipe())['status'],'FAIL')
    def test_finite_candidate_domain_does_not_treat_missing_as_negative(self):
        recipe={'members':[{'query_id':'q','paper_id':'p','recipe':self.recipe()}]}
        self.assertEqual(check_source_set([],recipe)['status'],'FAIL')
