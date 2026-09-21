"""Actual Arrow slice sizes bound rows and bytes; one oversized row is explicit."""
def arrow_batches(value,*,max_rows=1024,target_bytes=4*1024*1024,max_object_bytes=64*1024*1024):
    import pyarrow as pa
    if min(max_rows,target_bytes,max_object_bytes)<=0:raise ValueError('BATCH_LIMIT')
    source=value.to_batches(max_chunksize=max_rows) if isinstance(value,pa.Table) else [value]
    for batch in source:
        offset=0
        while offset<batch.num_rows:
            count=min(max_rows,batch.num_rows-offset);piece=batch.slice(offset,count)
            if piece.nbytes>target_bytes:
                lo,hi=1,count
                while lo<hi:
                    middle=(lo+hi+1)//2
                    if batch.slice(offset,middle).nbytes<=target_bytes:lo=middle
                    else:hi=middle-1
                count=lo;piece=batch.slice(offset,count)
            if piece.nbytes>max_object_bytes:raise ValueError('OBJECT_LIMIT_EXCEEDED')
            yield piece;offset+=count
