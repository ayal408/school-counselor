"""Upgrade an existing synthetic database without touching an installation."""
import os, sys, sqlite3, subprocess
from pathlib import Path
from cryptography.fernet import Fernet

def test_upgrade_preserves_existing_records(tmp_path):
    root=Path(__file__).resolve().parents[1]
    path=tmp_path/'migration.sqlite'
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(path),'DATA_ENCRYPTION_KEY':Fernet.generate_key().decode(),'JWT_SECRET':'test-only-'+40*'x','INTERNAL_SERVICE_KEY':'test-only-'+40*'y'}
    def migrate(revision):
        result=subprocess.run([sys.executable,'-m','alembic','upgrade',revision],cwd=root,env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    migrate('0003')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO users VALUES ('old','old@example.test','Existing','test-hash',1)")
        db.execute("INSERT INTO students VALUES ('s','old','encrypted-name','encrypted-class','encrypted-referral',0,'2026-10-07')")
    migrate('head')
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT role,session_version,recovery_hashes FROM users WHERE id='old'").fetchone()==('admin',0,'[]')
        assert db.execute("SELECT name FROM students WHERE id='s'").fetchone()==('encrypted-name',)
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()==('0006',)
