"""Prospective trusted-controller deadlines; never a generated-plan field."""
import socket
import threading
import time
from copy import deepcopy

PROFILE={'revision':'HTTP_TIMEOUT_3','connect_seconds':20,'G_http_seconds':600,
         'COUNT_http_seconds':90,'G_watchdog_seconds':720,'COUNT_watchdog_seconds':210,'automatic_retries':0,
         'E_policy':'UNCHANGED_WORKFLOW_DEADLINE_NO_NEW_E'}

def validate(value):
    if value!=PROFILE:raise PermissionError('HTTP_TIMEOUT_PROFILE_NOT_FROZEN')
    return deepcopy(PROFILE)

class Deadline:
    """One monotonic end; the timer interrupts socket dribble, not DNS.

    A separately supervised process is required for OS/library hangs. A timer
    never records a result and never resends; the caller persists the failure.
    """
    def __init__(self,seconds,*,clock=None):
        self.clock=clock or time.monotonic;self.end=self.clock()+seconds
        self.sock=None;self.expired=False;self.timer=None
    def remaining(self):
        value=self.end-self.clock()
        if self.expired or value<=0:raise TimeoutError('HTTP_TOTAL_DEADLINE')
        return value
    def bind(self,sock):
        self.sock=sock
        sock.settimeout(self.remaining())
    def abort(self):
        self.expired=True
        if self.sock is not None:
            try:self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
    def start(self):
        self.timer=threading.Timer(self.remaining(),self.abort)
        self.timer.daemon=True;self.timer.start()
    def close(self):
        if self.timer:self.timer.cancel()
