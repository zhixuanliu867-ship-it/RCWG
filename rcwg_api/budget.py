"""Durable pre-dispatch reservations, bounded by approved manifest, never refunded.

This local admission ledger is not a Google Cloud billing hard cap.
"""
from __future__ import annotations
import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from .common import fail,private_path,integer,ID,digest

class Budget:
    def __init__(self,path:Path,manifest_hash:str,config:dict):
        self.path=private_path(path);self.config=config;self.manifest_hash=manifest_hash
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not self.path.exists():
            try:
                fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600);os.close(fd)
            except FileExistsError:pass
        if self.path.is_symlink():fail('BUDGET_SYMLINK')
        if self.path.stat().st_mode&0o077:fail('BUDGET_PERMISSIONS')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY CHECK(id=1), manifest TEXT, config TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY,kind TEXT,amount INTEGER,status TEXT,created_ns INTEGER,observation TEXT)')
            row=db.execute('SELECT manifest,config FROM binding WHERE id=1').fetchone()
            desired=(manifest_hash,digest(config))
            if row is None:db.execute('INSERT INTO binding VALUES(1,?,?)',desired)
            elif row!=desired:fail('BUDGET_BINDING')
    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA journal_mode=DELETE')
        try:
            with db:
                yield db
        finally:
            db.close()
    def reserve(self,request_id,kind):
        if type(request_id) is not str or not ID.fullmatch(request_id):fail('REQUEST_ID_INVALID')
        if kind not in self.config['max_requests']:fail('REQUEST_KIND_INVALID')
        amount=self.config['reservation_microusd'][kind]
        if not integer(amount,1,1000000):fail('RESERVATION_INVALID')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM reservations WHERE id=?',(request_id,)).fetchone():fail('REQUEST_ALREADY_RESERVED')
            count,total=db.execute('SELECT COUNT(*),COALESCE(SUM(amount),0) FROM reservations').fetchone()
            kinds=db.execute('SELECT COUNT(*) FROM reservations WHERE kind=?',(kind,)).fetchone()[0]
            if kinds>=self.config['max_requests'][kind] or total+amount>self.config['ceiling_microusd']:fail('ADMISSION_LIMIT')
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,NULL)',(request_id,kind,amount,'RESERVED_BEFORE_IO',time.time_ns()))
        return amount
    def observe(self,request_id,status,observation_hash):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status FROM reservations WHERE id=?',(request_id,)).fetchone()
            if row is None or row[0]!='RESERVED_BEFORE_IO':fail('RESERVATION_STATE')
            db.execute('UPDATE reservations SET status=?,observation=? WHERE id=?',(status,observation_hash,request_id))
    def summary(self):
        with self._db() as db:
            rows=db.execute('SELECT id,kind,amount,status,observation FROM reservations ORDER BY created_ns,id').fetchall()
        return {'manifest_hash':self.manifest_hash,'reservations':[dict(zip(('request_id','kind','microusd','status','observation_sha256'),r)) for r in rows],
                'reserved_microusd':sum(r[2] for r in rows),'invoice_cost_usd':None,
                'invoice_cost_reason':'LOCAL_RESERVATIONS_ARE_NOT_BILLING_EVIDENCE'}
