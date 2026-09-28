"""Bounded transport observations, without credentials or exception messages."""
import http.client
import urllib.request
from rcwg_api.common import ApiError

PROFILE = 'FULL001_HTTP_EVIDENCE_2'


class TransportFailure(ApiError):
    def __init__(self, code, evidence):
        super().__init__(code)
        self.transport_evidence = evidence
        self.confirmed_not_sent = evidence['sent'] is False


class EvidenceHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, observer=None, **kwargs):
        self.observer = observer or (lambda *a: None)
        self.inside_connect = False
        self.request_write_started = False
        super().__init__(*args, **kwargs)

    def connect(self):
        self.observer('CONNECTING', self.request_write_started)
        self.inside_connect = True
        try:
            super().connect()
        finally:
            self.inside_connect = False
        self.observer('CONNECTED', self.request_write_started)

    def send(self, data):
        # Proxy CONNECT bytes are not the inference POST. A connection failure
        # before this branch proves that no inference bytes were written.
        if self.inside_connect:
            return super().send(data)
        if self.sock is None:
            self.connect()
        self.request_write_started = True
        self.observer('REQUEST_WRITE', True)
        return super().send(data)

    def getresponse(self):
        self.observer('WAIT_RESPONSE', True)
        return super().getresponse()


class EvidenceHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        observer = getattr(request, '_rcwg_transport_observer', None)
        def connection(host, **kwargs):
            return EvidenceHTTPSConnection(host, observer=observer, **kwargs)
        return self.do_open(connection, request, context=self._context)


def exception_fields(error):
    # Do not serialize str(error), args, request objects, URLs or traceback locals.
    cause = getattr(error, 'reason', error)
    number = getattr(cause, 'errno', None)
    return {'exception_type': type(error).__name__, 'cause_type': type(cause).__name__,
            'errno': number if type(number) is int else None}
