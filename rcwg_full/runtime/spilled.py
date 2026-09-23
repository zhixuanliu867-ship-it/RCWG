"""Re-readable bounded Arrow stream and committed JSON result handles."""
from pathlib import Path


class SpilledTable:
    def __init__(self, path, *, verify=None, format='arrow_stream'):
        import pyarrow as pa
        self.path = Path(path); self.verify = verify; self.format = format
        if format == 'parquet':
            import pyarrow.parquet as pq
            self.schema = pq.ParquetFile(self.path).schema_arrow
        else:
            with self.path.open('rb') as file:
                self.schema = (pa.ipc.open_stream(file) if format == 'arrow_stream' else pa.ipc.open_file(file)).schema

    def batches(self):
        import pyarrow as pa
        if self.verify: self.verify()
        if self.format == 'parquet':
            import pyarrow.parquet as pq
            yield from pq.ParquetFile(self.path).iter_batches(batch_size=1024,use_threads=False)
            return
        with self.path.open('rb') as file:
            if self.format == 'arrow_stream':
                yield from pa.ipc.open_stream(file)
            else:
                reader = pa.ipc.open_file(file)
                for index in range(reader.num_record_batches):yield reader.get_batch(index)


class JsonResult:
    def __init__(self, path): self.path = Path(path)
