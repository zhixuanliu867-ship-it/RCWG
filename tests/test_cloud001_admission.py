import concurrent.futures,json,threading,unittest
from rcwg_cloud.admission import Admission,AdmissionError,AlreadyExists,WriteUncertain,SLOTS,AMOUNTS

class DurableStore:
    """Shared server simulation; clients/process lifetimes do not reset objects."""
    def __init__(self):self.objects={};self.lock=threading.Lock();self.lose_ack=False
    def create(self,key,raw):
        with self.lock:
            if key in self.objects:raise AlreadyExists(key)
            self.objects[key]=raw
            if self.lose_ack:raise WriteUncertain('acknowledgement lost after durable commit')
            return {'object':key,'generation':str(len(self.objects)),'ifGenerationMatch':0}

class CloudAdmissionTests(unittest.TestCase):
    def setUp(self):self.store=DurableStore()
    def client(self,phase='live',manifest='a'*64,execution='live-00001'):
        return Admission(self.store,manifest,execution,phase)
    def test_concurrent_executions_only_one_claim_succeeds(self):
        def attempt(i):
            try:self.client(execution='live-'+str(i)).claim();return 1
            except AlreadyExists:return 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            outcomes=list(pool.map(attempt,range(64)))
        self.assertEqual(sum(outcomes),1);self.assertEqual(len(self.store.objects),1)
    def test_new_manifest_and_process_cannot_reset_ticket(self):
        self.client().claim()
        with self.assertRaises(AlreadyExists):self.client(manifest='b'*64,execution='another-process').claim()
    def test_lost_claim_acknowledgement_blocks_dispatch_and_restart(self):
        a=self.client();self.store.lose_ack=True
        with self.assertRaises(WriteUncertain):a.claim()
        with self.assertRaises(AdmissionError):a.reserve(SLOTS[0],'b'*64)
        self.store.lose_ack=False
        with self.assertRaises(AlreadyExists):self.client().claim()
    def test_lost_reservation_acknowledgement_retains_charge_and_no_dispatch(self):
        a=self.client();a.claim();self.store.lose_ack=True;dispatches=[]
        with self.assertRaises(WriteUncertain):
            a.reserve(SLOTS[0],'c'*64);dispatches.append('HTTP')
        self.assertEqual(dispatches,[]);self.assertIn('cloud001/reservations/'+SLOTS[0]+'.json',self.store.objects)
        self.store.lose_ack=False
        with self.assertRaises(AlreadyExists):a.reserve(SLOTS[0],'c'*64)
    def test_new_request_hash_is_not_new_slot(self):
        a=self.client();a.claim();a.reserve(SLOTS[1],'a'*64)
        with self.assertRaises(AlreadyExists):a.reserve(SLOTS[1],'b'*64)
    def test_fixed_six_reservations_are_below_model_ceiling(self):
        a=self.client();a.claim()
        for s in SLOTS:a.reserve(s,'a'*64)
        self.assertEqual(sum(AMOUNTS.values()),780000)
        self.assertEqual(sum(s.endswith('.generate') for s in SLOTS),3)
        with self.assertRaises(AdmissionError):a.reserve('p0.physical.generate2','a'*64)
    def test_replay_cannot_reserve_model_slots(self):
        a=self.client('replay');a.claim()
        with self.assertRaises(AdmissionError):a.reserve(SLOTS[0],'a'*64)
        b=self.client();b.claim();self.assertEqual(len(self.store.objects),2)
    def test_observation_does_not_refund_or_replace_reservation(self):
        a=self.client();a.claim();a.reserve(SLOTS[0],'a'*64)
        before=self.store.objects['cloud001/reservations/'+SLOTS[0]+'.json']
        a.observe(SLOTS[0],{'status':'HTTP_500','refund':False})
        self.assertEqual(self.store.objects['cloud001/reservations/'+SLOTS[0]+'.json'],before)
        with self.assertRaises(AlreadyExists):a.reserve(SLOTS[0],'a'*64)
        with self.assertRaises(AlreadyExists):a.observe(SLOTS[0],{'status':'changed'})
    def test_reservation_requires_this_client_successful_claim(self):
        a=self.client();a.claim()
        with self.assertRaises(AdmissionError):self.client().reserve(SLOTS[0],'a'*64)
    def test_invalid_phase_or_hash_rejected(self):
        for phase,sha in [('other','a'*64),('live','b'*63),('live','X'*64)]:
            with self.assertRaises(AdmissionError):self.client(phase,sha)

if __name__=='__main__':unittest.main()
