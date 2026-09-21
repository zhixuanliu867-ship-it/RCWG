"""Cancellation-aware bounded streams and shared CPU admission."""
import asyncio
from contextlib import asynccontextmanager
from collections import deque


class StreamClosed(RuntimeError):
    pass


class BoundedStream:
    def __init__(self, *, max_batches=2, target_bytes=8*1024*1024, max_object_bytes=64*1024*1024, on_event=None):
        if min(max_batches,target_bytes,max_object_bytes)<=0:raise ValueError('INVALID_STREAM_LIMIT')
        self.max_batches,self.target_bytes,self.max_object_bytes=max_batches,target_bytes,max_object_bytes
        self.queue=deque();self.bytes=0;self.peak_bytes=0;self.peak_batches=0
        self.condition=asyncio.Condition();self.closed=False;self.error=None;self.started=False
        self.on_event=on_event or (lambda *a,**k:None)

    async def put(self, batch, size):
        if type(size) is not int or size<0:raise ValueError('INVALID_BATCH_BYTES')
        if size>self.max_object_bytes:raise ValueError('OBJECT_LIMIT_EXCEEDED')
        async with self.condition:
            while not self.closed and (len(self.queue)>=self.max_batches or (self.queue and self.bytes+size>self.target_bytes)):
                self.on_event('stream_blocked',{'reason':'DOWNSTREAM_CAPACITY'})
                await self.condition.wait()
            if self.closed:raise StreamClosed('CONSUMER_CLOSED')
            self.queue.append((batch,size));self.bytes+=size
            self.peak_bytes=max(self.peak_bytes,self.bytes);self.peak_batches=max(self.peak_batches,len(self.queue))
            self.on_event('batch_enqueued',{'bytes':size,'queued_bytes':self.bytes,'oversized':size>self.target_bytes})
            self.condition.notify_all()

    def __aiter__(self):
        if self.started:raise StreamClosed('SINGLE_PASS_ALREADY_CONSUMED')
        self.started=True;return self

    async def __anext__(self):
        async with self.condition:
            while not self.queue and not self.closed:await self.condition.wait()
            if self.error is not None:raise self.error
            if not self.queue:raise StopAsyncIteration
            batch,size=self.queue.popleft();self.bytes-=size;self.condition.notify_all()
            return batch

    async def finish(self, error=None):
        async with self.condition:
            self.closed=True;self.error=error
            self.condition.notify_all()

    async def cancel(self):
        async with self.condition:
            self.closed=True;self.queue.clear();self.bytes=0
            self.condition.notify_all()


class CpuAdmission:
    def __init__(self, slots, instance_limit=4096):
        if type(slots) is not int or not 1<=slots<=8:raise ValueError('CPU_LIMIT')
        self.slots=slots;self.available=slots;self.instances=0;self.instance_limit=instance_limit
        self.condition=asyncio.Condition();self.peak_in_use=0

    def admit_instance(self):
        if self.instances>=self.instance_limit:raise RuntimeError('DYNAMIC_INSTANCE_LIMIT')
        self.instances+=1
        return self.instances

    @asynccontextmanager
    async def acquire(self, slots=1):
        if type(slots) is not int or not 1<=slots<=self.slots:raise ValueError('CPU_LIMIT')
        async with self.condition:
            while self.available<slots:await self.condition.wait()
            self.available-=slots;self.peak_in_use=max(self.peak_in_use,self.slots-self.available)
        try:yield
        finally:
            async with self.condition:self.available+=slots;self.condition.notify_all()


async def bounded_map(source, function, *, parallelism, admission):
    """Ordered bounded in-flight work. Nested maps share the passed admission.

    Waiting on a child or input never owns a CPU permit. The function acquires
    permits only for its actual compute sections, avoiding nested-map deadlock.
    """
    if type(parallelism) is not int or not 1<=parallelism<=8:raise ValueError('MAP_PARALLELISM')
    pending=deque()
    try:
        async for item in source:
            pending.append(asyncio.create_task(function(item)))
            if len(pending)>=parallelism:yield await pending.popleft()
        while pending:yield await pending.popleft()
    finally:
        for task in pending:task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)


async def tee(source, consumers):
    """Each consumer has a bounded cursor; the slowest applies backpressure."""
    try:
        async for batch in source:
            size=batch.nbytes if hasattr(batch,'nbytes') else len(batch)
            active=[stream for stream in consumers if not stream.closed]
            if not active:break
            await asyncio.gather(*(s.put(batch,size) for s in active))
    except BaseException as exc:
        await asyncio.gather(*(s.finish(exc) for s in consumers))
        raise
    finally:
        await asyncio.gather(*(s.finish(s.error) for s in consumers))
