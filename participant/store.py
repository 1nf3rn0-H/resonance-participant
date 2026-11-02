"""Private per-device SQLite with durable transactions and immutable captured records."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import json
import os
from contracts.offline_bundle.v1.canonical import dumps,record_hash

SCHEMA='''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,record_hash TEXT NOT NULL,ordinal INTEGER NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,version TEXT NOT NULL,event_refs TEXT NOT NULL,time_quality TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,input_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS slots(collection_day TEXT NOT NULL,slot INTEGER NOT NULL,assignment_id TEXT NOT NULL REFERENCES records(id),PRIMARY KEY(collection_day,slot));
CREATE TABLE IF NOT EXISTS locks(prompt_id TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES records(id),lock_id TEXT NOT NULL REFERENCES records(id));
CREATE TABLE IF NOT EXISTS followup_drafts(prompt_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(prompt_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,preview_id TEXT NOT NULL UNIQUE,bundle_id TEXT NOT NULL,document TEXT NOT NULL,cipher BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,preview_hash TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_submission_stage ON records(json_extract(payload,'$.prompt_packet_id'),json_extract(payload,'$.stage')) WHERE kind='submissions';
CREATE UNIQUE INDEX IF NOT EXISTS one_lock_per_prompt ON records(json_extract(payload,'$.prompt_packet_id')) WHERE kind='locks';
CREATE TRIGGER IF NOT EXISTS captured_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'Captured records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS captured_delete BEFORE DELETE ON records WHEN erase_enabled()=0 BEGIN SELECT RAISE(ABORT,'Captured records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS lock_update BEFORE UPDATE ON locks BEGIN SELECT RAISE(ABORT,'Neutral responses are locked'); END;
CREATE TRIGGER IF NOT EXISTS lock_delete BEFORE DELETE ON locks WHEN erase_enabled()=0 BEGIN SELECT RAISE(ABORT,'Neutral responses are locked'); END;
CREATE TRIGGER IF NOT EXISTS draft_insert BEFORE INSERT ON drafts WHEN EXISTS(SELECT 1 FROM locks WHERE prompt_id=NEW.prompt_id) BEGIN SELECT RAISE(ABORT,'Neutral responses are locked'); END;
CREATE TRIGGER IF NOT EXISTS draft_update BEFORE UPDATE ON drafts WHEN EXISTS(SELECT 1 FROM locks WHERE prompt_id=NEW.prompt_id) BEGIN SELECT RAISE(ABORT,'Neutral responses are locked'); END;
CREATE TRIGGER IF NOT EXISTS run_update BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT,'Frozen sampler runs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS run_delete BEFORE DELETE ON runs WHEN erase_enabled()=0 BEGIN SELECT RAISE(ABORT,'Frozen sampler runs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS session_update BEFORE UPDATE ON sessions BEGIN SELECT RAISE(ABORT,'Session membership is immutable'); END;
CREATE TRIGGER IF NOT EXISTS session_delete BEFORE DELETE ON sessions WHEN erase_enabled()=0 BEGIN SELECT RAISE(ABORT,'Session membership is immutable'); END;
CREATE TRIGGER IF NOT EXISTS slot_update BEFORE UPDATE ON slots BEGIN SELECT RAISE(ABORT,'Assigned slots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS slot_delete BEFORE DELETE ON slots WHEN erase_enabled()=0 BEGIN SELECT RAISE(ABORT,'Assigned slots are immutable'); END;
'''

class LocalConnection(sqlite3.Connection):
    def __exit__(self,kind,value,traceback):
        try:return super().__exit__(kind,value,traceback)
        finally:self.close()

class Store:
    def __init__(self,directory):
        self.directory=Path(directory)
        if self.directory.exists() and any(self.directory.iterdir()) and not (self.directory/'participant.sqlite3').is_file():raise ValueError('Choose an empty, dedicated local-data directory')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.directory.chmod(0o700);self.path=self.directory/'participant.sqlite3'
        with self.connect() as c:
            version=c.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise ValueError('Unsupported local database version; keep your data and use a compatible release')
            c.executescript(SCHEMA);c.execute('PRAGMA user_version=1')
        self.path.chmod(0o600)
    def connect(self,erase=False):
        c=sqlite3.connect(self.path,timeout=30,isolation_level=None,factory=LocalConnection)
        c.row_factory=sqlite3.Row;c.create_function('erase_enabled',0,lambda:int(erase))
        c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA secure_delete=ON')
        return c
    @contextmanager
    def transaction(self):
        c=self.connect()
        try:c.execute('BEGIN IMMEDIATE');yield c;c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()
    def get(self,c,key,default=None):
        row=c.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def set(self,c,key,value):c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,dumps(value).decode()))
    def revision(self,c):return self.get(c,'revision',0)
    def changed(self,c):self.set(c,'revision',self.revision(c)+1)
    def records(self,c,kind):return [json.loads(r[0]) for r in c.execute('SELECT payload FROM records WHERE kind=? ORDER BY ordinal',(kind,))]
    def record(self,c,record_id):
        row=c.execute('SELECT payload FROM records WHERE id=?',(record_id,)).fetchone()
        if row is None:raise ValueError('Record not found')
        return json.loads(row[0])
    def add(self,c,kind,record):
        record={**record,'record_hash':record_hash(record)}
        existing=c.execute('SELECT payload FROM records WHERE id=?',(record['record_id'],)).fetchone()
        if existing:
            if existing[0]!=dumps(record).decode():raise ValueError('Immutable source identity conflicts')
            return record
        ordinal=c.execute('SELECT coalesce(max(ordinal),0)+1 FROM records').fetchone()[0]
        c.execute('INSERT INTO records VALUES(?,?,?,?,?)',(record['record_id'],kind,dumps(record).decode(),record['record_hash'],ordinal))
        return record
    def erase(self):
        c=self.connect(erase=True)
        try:
            c.execute('BEGIN IMMEDIATE')
            for table in ['drafts','followup_drafts','previews','exports','locks','slots','sessions','runs','records','meta']:c.execute('DELETE FROM '+table)
            c.commit();result=c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if result[0]:raise ValueError('Close other instances and retry local erasure')
        finally:c.close()
