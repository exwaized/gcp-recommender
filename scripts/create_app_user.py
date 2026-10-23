"""
Creates the least-privilege database user the API and training run as.

The user can connect and SELECT from the warehouse tables — nothing else (no DDL,
no INSERT/UPDATE/DELETE, no other schemas). Run once as the table owner (ADMIN),
after scripts/seed_warehouse.py has created the tables; safe to re-run (re-grants
and resets the password).

Usage:
    WAREHOUSE_BACKEND=oracle ORACLE_USER=ADMIN ORACLE_PASSWORD=... ORACLE_CONNECT_STRING=... \
    APP_DB_USER=RECO_APP APP_DB_PASSWORD=... python scripts/create_app_user.py

Then set, for the app: ORACLE_USER=$APP_DB_USER, ORACLE_PASSWORD=$APP_DB_PASSWORD,
ORACLE_SCHEMA=<owner schema, e.g. ADMIN>.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import oracledb

from data.oracle_warehouse import _get_conn, SCHEMA

IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")
ORA_USER_EXISTS = 1920  # ORA-01920: user name conflicts with another user or role name


def run():
    app_user = os.environ["APP_DB_USER"].upper()
    app_password = os.environ["APP_DB_PASSWORD"]
    if not IDENT.match(app_user):
        sys.exit(f"Invalid APP_DB_USER: {app_user!r}")
    if '"' in app_password or len(app_password) < 12:
        sys.exit("APP_DB_PASSWORD must be at least 12 characters and contain no double quotes")

    conn = _get_conn()
    owner = conn.username.upper()
    if app_user == owner:
        sys.exit("APP_DB_USER must differ from the owner running this script")
    cur = conn.cursor()
    try:
        cur.execute(f'CREATE USER {app_user} IDENTIFIED BY "{app_password}"')
    except oracledb.DatabaseError as e:
        if e.args[0].code != ORA_USER_EXISTS:
            raise
        cur.execute(f'ALTER USER {app_user} IDENTIFIED BY "{app_password}"')
    cur.execute(f"GRANT CREATE SESSION TO {app_user}")
    for table in SCHEMA:
        cur.execute(f"GRANT SELECT ON {owner}.{table} TO {app_user}")
    conn.commit()
    cur.close()
    conn.close()
    print(f"{app_user} can connect and SELECT from {', '.join(SCHEMA)} in schema {owner}.")
    print(f"Set ORACLE_USER={app_user}, ORACLE_PASSWORD=<APP_DB_PASSWORD>, ORACLE_SCHEMA={owner} for the app.")


if __name__ == "__main__":
    run()
