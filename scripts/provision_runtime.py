"""Run via the migration container on operator request. The credential is passed by environment."""
import os
import re
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

role = "goldenstock_runtime"
password = os.environ["GS_RUNTIME_PASSWORD"]
if not re.fullmatch("[a-fA-F0-9]{64}", password):
    raise SystemExit("Use a 32-byte random runtime credential encoded as 64 hex characters")
url = make_url(os.environ["GS_DATABASE_URL"])
with psycopg.connect(host=url.host, port=url.port or 5432, dbname=url.database,
                     user=url.username, password=url.password) as db:
    existing = db.execute("SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls "
                          "FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
    if existing and any(existing):
        raise SystemExit("Existing runtime role has unexpected elevated privileges")
    if existing and db.execute("SELECT 1 FROM pg_auth_members WHERE member=%s::regrole LIMIT 1",
                               (role,)).fetchone():
        raise SystemExit("Existing runtime role has unexpected memberships")
    if not existing:
        db.execute("CREATE ROLE goldenstock_runtime")
    db.execute(sql.SQL("ALTER ROLE goldenstock_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                       "NOREPLICATION NOBYPASSRLS PASSWORD {}").format(sql.Literal(password)))
    db.execute("GRANT USAGE ON SCHEMA public TO goldenstock_runtime")
    if any(db.execute("SELECT has_schema_privilege(%s,'public','CREATE'), "
                      "has_database_privilege(%s,current_database(),'CREATE')", (role,role)).fetchone()):
        raise SystemExit("Remove unexpected CREATE privileges before enabling remote mode")
    db.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO goldenstock_runtime")
    db.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO goldenstock_runtime")
    db.execute("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM goldenstock_runtime")
    db.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE "
               "ON TABLES TO goldenstock_runtime")
    db.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO goldenstock_runtime")
print("Runtime role prepared for application DML. Migrations use the operator account.")
