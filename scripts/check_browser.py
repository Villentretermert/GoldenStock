"""Create a synthetic QA account, run browser smoke, then revoke that account."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import base64

DOCKER=['wsl','-d','Ubuntu','--','docker','compose','exec','-T','web','python','-c']
SEED='''
import json,sys
from sqlalchemy.orm import Session
from goldenstock.db import make_engine
from goldenstock.config import get_settings
from goldenstock.models import Organization,User
from goldenstock.auth import hash_password
data=json.load(sys.stdin)
with Session(make_engine(get_settings())) as db,db.begin():
 org=Organization(name='Synthetic browser QA - not a customer');db.add(org);db.flush()
 db.add(User(org_id=org.id,login=data['login'],password_hash=hash_password(data['password']),account_admin=True))
'''
REVOKE='''
import json,sys
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from goldenstock.db import make_engine
from goldenstock.config import get_settings
from goldenstock.models import User,LoginSession
data=json.load(sys.stdin)
with Session(make_engine(get_settings())) as db,db.begin():
 user=db.scalar(select(User).where(User.login==data['login']))
 if user:
  user.active=False
  db.execute(delete(LoginSession).where(LoginSession.user_id==user.id))
'''


def main():
    login='qa_'+secrets.token_hex(6)
    password=secrets.token_urlsafe(32)
    subprocess.run(DOCKER+[SEED],input=json.dumps(dict(login=login,password=password)),text=True,check=True)
    try:
        runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
        env=dict(os.environ,GS_QA_LOGIN=login,GS_QA_PASSWORD=password,GS_NODE_MODULES=str(runtime/'node_modules'),GS_APP_URL='http://127.0.0.1:8081')
        from extraction_fixtures import simple_pdf
        env['GS_QA_PDF']=base64.b64encode(simple_pdf()).decode('ascii')
        subprocess.run([str(runtime/'bin/node.exe'),'scripts/check_app.cjs'],env=env,check=True)
    finally:
        subprocess.run(DOCKER+[REVOKE],input=json.dumps(dict(login=login)),text=True,check=True)
        print('Synthetic QA account revoked; no credentials saved or printed.')


if __name__=='__main__':
    main()
