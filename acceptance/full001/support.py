"""Keep actual run journals and failed outputs when the acceptance runner requests it."""
from pathlib import Path
import os
import tempfile
import hashlib


class EvidenceDirectory:
    def __init__(self,test_id):
        root=os.environ.get('RCWG_FULL_TEST_EVIDENCE')
        self.temporary=None
        if root:
            # Keep artifact hash filenames below Windows' path limit without
            # changing any test ID, assertion or recorded source identity.
            name='case-'+hashlib.sha256(test_id.encode()).hexdigest()[:16] if os.name=='nt' else test_id
            path=Path(root)/name;path.mkdir(parents=True,exist_ok=False);self.name=str(path)
            (path/'TEST_ID.txt').write_text(test_id+'\n',encoding='utf-8')
        else:self.temporary=tempfile.TemporaryDirectory();self.name=self.temporary.name
    def cleanup(self):
        if self.temporary:self.temporary.cleanup()
