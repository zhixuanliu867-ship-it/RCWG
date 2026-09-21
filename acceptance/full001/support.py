"""Keep actual run journals and failed outputs when the acceptance runner requests it."""
from pathlib import Path
import os
import tempfile


class EvidenceDirectory:
    def __init__(self,test_id):
        root=os.environ.get('RCWG_FULL_TEST_EVIDENCE')
        self.temporary=None
        if root:
            path=Path(root)/test_id;path.mkdir(parents=True,exist_ok=False);self.name=str(path)
        else:self.temporary=tempfile.TemporaryDirectory();self.name=self.temporary.name
    def cleanup(self):
        if self.temporary:self.temporary.cleanup()
