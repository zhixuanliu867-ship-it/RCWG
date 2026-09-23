"""Trusted controller-side dispatch for sealed private verifier recipes."""
import json
from rcwg_full.evidence import read
from .compare import check_output


def check_prepared(actual,path):
    recipe=json.loads(read(path))
    if recipe['comparison'] in {'source_document_semantics_v1','source_mixed_semantics_v1'}:
        if recipe['comparison']=='source_document_semantics_v1':
            from .document_oracle import verify_document_result as verify
        else:
            from .mixed_oracle import verify_mixed_result as verify
        try:return verify(actual,recipe['expected'],recipe['documents'])
        except (KeyError,TypeError,IndexError,ValueError):
            return {'status':'FAIL','reason':'MALFORMED_SEMANTIC_OUTPUT','formal_gold_reviewed':False}
    if recipe['comparison']!='graph_sql_v1':return check_output(actual,recipe['expected'],recipe)
    from .graph_sql import check
    try:passed=check(actual,recipe,path)
    except (KeyError,TypeError,IndexError):passed=False
    # Identity/I/O failures deliberately propagate to the caller's UNKNOWN
    # verifier classification, never masquerade as a model output mismatch.
    return {'status':'PASS' if passed else 'FAIL','reason':None if passed else 'OUTPUT_MISMATCH'}
