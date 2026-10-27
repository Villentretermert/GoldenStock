"""Interactive local bootstrap. Passwords never enter command-line arguments."""
import argparse
import getpass
import re
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from goldenstock.auth import hash_password
from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.models import Organization, User, LoginSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['create-admin', 'reset-password'])
    parser.add_argument('--login', required=True)
    parser.add_argument('--organization', default='Pilot fund')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9@._-]{1,120}', args.login):
        parser.error('Invalid login')
    password = getpass.getpass('New password (12–128 characters): ')
    if password != getpass.getpass('Repeat password: '):
        parser.error('Passwords do not match')
    engine = make_engine(get_settings())
    with Session(engine) as db, db.begin():
        user = db.scalar(select(User).where(User.login == args.login.lower()))
        if args.action == 'create-admin':
            if user:
                parser.error('Login already exists')
            org = Organization(name=args.organization[:120])
            db.add(org)
            db.flush()
            db.add(User(org_id=org.id, login=args.login.lower(), password_hash=hash_password(password), account_admin=True))
        else:
            if not user:
                parser.error('Account does not exist')
            user.password_hash = hash_password(password)
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    engine.dispose()
    print('Account updated. Password was not printed.')


if __name__ == '__main__':
    main()
