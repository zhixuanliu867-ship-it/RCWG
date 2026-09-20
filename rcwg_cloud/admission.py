"""Shared GCS conditional-create admission, never process-local refund/retry."""
from rcwg_spec.common import canonical,digest

class AdmissionError(ValueError):pass
class AlreadyExists(AdmissionError):pass
class WriteUncertain(AdmissionError):pass

SLOTS=('p0.physical.count','p0.physical.generate','p1.logical.count','p1.logical.generate',
       'p1.physical.count','p1.physical.generate')
AMOUNTS={s:10000 if s.endswith('.count') else 250000 for s in SLOTS}
PREFIX='cloud001/'

class Admission:
    """store.create must use durable ifGenerationMatch=0 before returning.

    The phase claim has a fixed ticket path independent of manifest/batch ID.
    Even a new manifest, new container or partial failed execution cannot reset it.
    """
    def __init__(self,store,manifest_sha256,execution_id,phase):
        if phase not in ('replay','live'):raise AdmissionError('PHASE')
        if len(manifest_sha256)!=64 or any(c not in '0123456789abcdef' for c in manifest_sha256):raise AdmissionError('MANIFEST_SHA')
        self.store=store;self.manifest=manifest_sha256;self.execution=execution_id;self.phase=phase;self.claimed=False
    def claim(self):
        raw=canonical({'version':'CLOUD001_PHASE_CLAIM_1','phase':self.phase,'manifest_sha256':self.manifest,
                       'execution_id':self.execution,'automatic_retries':0})
        receipt=self.store.create(PREFIX+'claims/'+self.phase+'.json',raw)
        self.claimed=True
        return receipt
    def reserve(self,slot,request_sha256):
        if self.phase!='live' or not self.claimed:raise AdmissionError('UNCLAIMED_LIVE')
        if slot not in AMOUNTS:raise AdmissionError('UNREGISTERED_SLOT')
        record={'version':'CLOUD001_RESERVATION_1','slot':slot,'manifest_sha256':self.manifest,
                'execution_id':self.execution,'request_sha256':request_sha256,'reserved_microusd':AMOUNTS[slot],
                'status':'RESERVED_DISPATCH_MAY_REMAIN_UNKNOWN','reserved_before_dispatch':True}
        # A new hash/name is not an alternative slot and never bypasses an old reservation.
        receipt=self.store.create(PREFIX+'reservations/'+slot+'.json',canonical(record))
        return {'reservation':record,'gcs_receipt':receipt}
    def observe(self,slot,record):
        if slot not in AMOUNTS:raise AdmissionError('UNREGISTERED_SLOT')
        # Append-only observation; do not overwrite or delete the original reservation.
        return self.store.create(PREFIX+'reservations/'+slot+'.observation.json',canonical(record))
