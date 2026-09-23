"""Deployment-neutral HTTP adapter. Authenticated claims come from middleware."""
from http import HTTPStatus
from rcwg_full.evidence import canonical
from rcwg_api.common import strict,ApiError
from rcwg_full.campaign.store import CampaignStore
from .api import ControlAPI


def application(api,authenticate):
    if not callable(authenticate):raise ValueError('AUTHENTICATION_MIDDLEWARE_REQUIRED')
    def app(environ,start_response):
        store=None
        try:
            principal=authenticate(environ)
            method=environ.get('REQUEST_METHOD','');length=int(environ.get('CONTENT_LENGTH') or 0)
            if not 0<=length<=131072:raise ValueError('BODY_LIMIT')
            if method=='POST':
                if environ.get('CONTENT_TYPE','').split(';')[0]!='application/json':raise ValueError('CONTENT_TYPE')
                raw=environ['wsgi.input'].read(length)
                if len(raw)!=length:raise ValueError('PARTIAL_BODY')
                body=strict(raw,limit=131072)
            else:body={}
            # One connection per request. A multithreaded WSGI deployment must
            # never share the dispatcher's SQLite transaction or thread owner.
            store=CampaignStore(api.store.path)
            request_api=ControlAPI(store,admission=api.admission,audit_release=api.audit_release)
            status,value=request_api.handle(method,environ.get('PATH_INFO',''),body,principal=principal,idempotency_key=environ.get('HTTP_IDEMPOTENCY_KEY'))
        except PermissionError:status,value=403,{'status':'DENIED','code':'AUTHENTICATION_REQUIRED'}
        except (ValueError,KeyError,ApiError):status,value=400,{'status':'INVALID','code':'HTTP_INPUT'}
        finally:
            if store is not None:store.close()
        raw=canonical(value)
        start_response(f'{status} {HTTPStatus(status).phrase}',[('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(raw))),('Cache-Control','no-store')])
        return [raw]
    return app
