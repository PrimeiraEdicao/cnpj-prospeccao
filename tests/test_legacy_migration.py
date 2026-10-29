from pathlib import Path
import sqlite3
from uuid import UUID
import pytest
from scripts.migrate_legacy_history import read_legacy,transfer
from scripts.backup_database import pg_environment

A=UUID('11111111-1111-4111-8111-111111111111')
CNPJ='00000000000191'
class Connection:
    def __init__(self):self.calls=[]
    def execute(self,sql,parameters):
        self.calls.append((sql,parameters));return self
    def fetchone(self):return {'email':'owner@example.test','email_confirmed_at':'2026-01-01'}

def test_owner_migration_dry_run_and_idempotent_writes(tmp_path):
    (tmp_path/'state').mkdir();(tmp_path/'state/contacted_cnpjs.csv').write_text('cnpj,status,source\n'+CNPJ+',contatado,legado\n')
    records=read_legacy(tmp_path)
    conn=Connection()
    assert transfer(conn,A,'owner@example.test',records)['applied'] is False
    assert len(conn.calls)==1
    transfer(conn,A,'owner@example.test',records,True)
    sql,params=conn.calls[-1]
    assert params[0]==A and 'on conflict(user_id,cnpj) do nothing' in sql

def test_migration_wrong_owner_stops_before_writing():
    conn=Connection()
    with pytest.raises(ValueError):transfer(conn,A,'other@example.test',([],[],[]),True)
    assert len(conn.calls)==1

def test_sqlite_read_only_no_file_created(tmp_path):
    assert read_legacy(tmp_path)==([],[],[])
    assert not (tmp_path/'data').exists()

def test_backup_credentials_use_environment_not_command_line():
    env=pg_environment('postgresql://postgres:p%40ss@db.example.com:5432/postgres?sslmode=verify-full')
    assert env['PGPASSWORD']=='p@ss' and env['PGSSLMODE']=='verify-full'
    assert env['PGHOST']=='db.example.com' and env['PGDATABASE']=='postgres'
    with pytest.raises(ValueError):pg_environment('https://db.example.com')
