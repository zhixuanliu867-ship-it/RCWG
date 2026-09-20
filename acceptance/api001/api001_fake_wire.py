"""Windows-only offline fixture driver. Never reachable from the LIVE allowlist.

No SDK calls, credentials, network or fake-mode switch exist in the real helper.
This separate test executable imports its deployed bytes and replaces only the
two external boundaries, leaving host checks and exact pipe serialization real.
"""
import base64,importlib.util,json,pathlib,secrets,sys
from unittest.mock import patch
def main():
    if len(sys.argv)!=1:raise SystemExit(2)
    helper=pathlib.Path(__file__).with_name('api001_bridge.py')
    spec=importlib.util.spec_from_file_location('win01_deployed_helper',helper);h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    incoming=h.strict(sys.stdin.buffer.read(h.MAX_PIPE+1));value=incoming['envelope'];fake=incoming['fake_response']
    h.validate_envelope(value)
    token=secrets.token_hex(24)
    def identity(binding,audit):
        return {'principal':h.ACCOUNT,'principal_type':'USER','auth_mode':'GCLOUD_USER','project_id':h.PROJECT,
                'quota_project':h.PROJECT,'service_account':None,'proxy':binding['proxy'],'tls_trust':binding['tls_trust']}
    def sdk(binding,args,audit,resource=False):
        assert args==['auth','print-access-token']
        record={'operation':'SYNTHETIC_CREDENTIAL_NO_SDK','exit_code':0,'real_credential_commands':0}
        audit.append(record);return token.encode(),record
    def post(kind,raw,credential,binding):
        assert credential==token
        assert h.sha(raw)==value['body_sha256']
        return fake['status'],h.unbase(fake['body_b64'],h.MAX_RESPONSE),{'content-type':'application/json'},1
    def emit(obj):sys.stdout.buffer.write(h.encode(obj)+b'\n');sys.stdout.buffer.flush()
    with patch.object(h,'auth_preflight',side_effect=identity),patch.object(h,'sdk_call',side_effect=sdk),patch.object(h,'post',side_effect=post):
        result=h.handle(value,emit)
    result['synthetic_fixture']=True
    emit(result)
if __name__=='__main__':main()
