"""Reconstruct full worker intervals, including failed resolutions/transforms."""
def worker_spans(events):
 active={};spans=[];unmatched=[];attempts=0
 for e in events:
  if e.get('inherited_from'):continue
  tid=e.get('task_id')
  if e['kind']=='worker_started':
   if tid in active:unmatched.append(tid)
   active[tid]=e['monotonic_start'];attempts+=1
  elif e['kind'] in ('worker_finished','worker_failed'):
   start=active.pop(tid,None)
   if start is None:unmatched.append(tid)
   else:spans.append((start,e['monotonic_end']))
 return spans,attempts,unmatched+list(active)
def union(spans):
 end=None;total=0
 for a,b in sorted(spans):
  if end is None or b>end:total+=b-max(a,end if end is not None else a)
  end=max(b,end if end is not None else b)
 return total
