"""Re-readable bounded Arrow stream and committed JSON result handles."""
from pathlib import Path


class SpilledTable:
    def __init__(self, path, *, verify=None):
        import pyarrow as pa
        self.path = Path(path); self.verify = verify
        with self.path.open('rb') as file: self.schema = pa.ipc.open_stream(file).schema

    def batches(self):
        import pyarrow as pa
        if self.verify: self.verify()
        with self.path.open('rb') as file:
            reader = pa.ipc.open_stream(file)
            for batch in reader: yield batch


class JsonResult:
    def __init__(self, path): self.path = Path(path)
