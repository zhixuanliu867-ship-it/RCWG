"""Re-readable bounded Arrow stream and committed JSON result handles."""
from pathlib import Path


class SpilledTable:
    def __init__(self, path, *, verify=None, format='arrow_stream', owner=None, rows=None):
        import pyarrow as pa
        self.path = Path(path); self.verify = verify; self.format = format;self.owner=owner;self._rows=rows
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

    @property
    def num_rows(self):
        return self._rows if self._rows is not None else sum(b.num_rows for b in self.batches())

    def to_pylist(self):
        """Explicit caller-requested materialization, never used by the runtime."""
        return [row for batch in self.batches() for row in batch.to_pylist()]

    def column(self,name):
        """Compatibility accessor materializes only the requested column."""
        import pyarrow as pa
        return pa.chunked_array([batch.column(name) for batch in self.batches()],type=self.schema.field(name).type)


class JsonResult:
    def __init__(self, path): self.path = Path(path)
