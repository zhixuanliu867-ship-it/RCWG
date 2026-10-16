"""Local process-tree resource sampling; never interprets API wait as remote compute."""
import threading,time,os
class ResourceSampler:
    def __init__(self):
        import psutil
        self.psutil=psutil;self.root=psutil.Process();self.stop_event=threading.Event();self.maxrss=0;self.samples=0;self.initial={};self.latest={};self.missing=0
        self.sample();self.initial=dict(self.latest);self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def sample(self):
        try:procs=[self.root]+self.root.children(recursive=True)
        except self.psutil.Error:procs=[self.root]
        rss=0
        for p in procs:
            try:
                key=(p.pid,p.create_time());cpu=p.cpu_times();self.latest[key]=cpu.user+cpu.system;rss+=p.memory_info().rss
            except self.psutil.Error:self.missing+=1
        self.maxrss=max(rss,self.maxrss);self.samples+=1
    def loop(self):
        while not self.stop_event.wait(.02):self.sample()
    def stop(self):
        self.stop_event.set();self.thread.join(timeout=1);self.sample()
        return {'sampled_peak_process_tree_rss_bytes':self.maxrss,'sampled_process_tree_cpu_seconds_lower_bound':sum(max(0,v-self.initial.get(k,0)) for k,v in self.latest.items()),'sample_interval_seconds':.02,'samples':self.samples,'process_disappearance_events':self.missing,'scope':'local runner and descendants; shared process activity included; short-lived children may be undersampled','remote_llm_compute_seconds':None}
