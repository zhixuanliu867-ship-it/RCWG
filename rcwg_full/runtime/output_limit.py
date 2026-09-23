"""Observed per-run output watchdog; not a filesystem quota or storage estimate."""
import os,stat
from pathlib import Path


class OutputWatchdog:
    def __init__(self,root,limit):
        if type(limit) is not int or limit<1:raise ValueError('OUTPUT_LIMIT_POSITIVE_INTEGER')
        self.root=Path(root);self.limit=limit;self.peak=0;self.observations=0

    def sample(self):
        total=0
        for current,dirs,files in os.walk(self.root):
            for name in dirs+files:
                path=Path(current)/name
                try:info=path.lstat()
                except FileNotFoundError:continue  # Atomic artifact rename between snapshots.
                if stat.S_ISLNK(info.st_mode):raise ValueError('OUTPUT_SYMLINK_FORBIDDEN')
                if stat.S_ISREG(info.st_mode):total+=info.st_size
        self.peak=max(self.peak,total);self.observations+=1
        return total>self.limit

    def snapshot(self):
        return {'scope':'RUN_DIRECTORY_BYTES_OBSERVED_BY_CONTROLLER','limit_bytes':self.limit,
            'observed_peak_bytes':self.peak,'observations':self.observations,'hard_filesystem_quota':False,
            'policy':'stop and drain on observed threshold; retain overrun and final evidence; no storage-budget PASS claim'}
