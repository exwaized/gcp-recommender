"""
Oracle Autonomous Data Warehouse client — real cloud backend (Oracle Cloud "Always Free" tier).
Swaps in for the local SQLite mirror when WAREHOUSE_BACKEND=oracle.

Connection modes (picked automatically from env vars):
  1. Walletless TLS  — set ORACLE_CONNECT_STRING to the "TLS" connection descriptor
     from OCI Console > Autonomous Database > DB Connection (requires mTLS disabled
     on the ADB instance, i.e. "Allow only TLS connections"). No wallet files needed —
     this is the simplest option for a container/VM deployment.
  2. Wallet (mTLS)   — set TNS_ADMIN to the unzipped wallet directory and ORACLE_DSN
     to the TNS alias (e.g. "recowarehouse_high") from that wallet's tnsnames.ora.

Either way, ORACLE_USER / ORACLE_PASSWORD must be set.
"""
import os
import logging
import pandas as pd
import oracledb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SCHEMA = {
    "users": """
        CREATE TABLE users (
            user_id VARCHAR2(20) PRIMARY KEY,
            age_group VARCHAR2(20),
            city VARCHAR2(50),
            signup_date VARCHAR2(20),
            segment VARCHAR2(20)
        )""",
    "items": """
        CREATE TABLE items (
            item_id VARCHAR2(20) PRIMARY KEY,
            title VARCHAR2(200),
            category VARCHAR2(50),
            brand VARCHAR2(50),
            price NUMBER(10,2),
            avg_rating NUMBER(3,2)
        )""",
    "interactions": """
        CREATE TABLE interactions (
            interaction_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id VARCHAR2(20),
            item_id VARCHAR2(20),
            event_type VARCHAR2(20),
            rating NUMBER(3,2),
            timestamp VARCHAR2(30)
        )"""
}

ORA_NAME_IN_USE = 955  # ORA-00955: name is already used by an existing object


def _get_conn():
    user = os.environ["ORACLE_USER"]
    password = os.environ["ORACLE_PASSWORD"]
    connect_string = os.getenv("ORACLE_CONNECT_STRING")
    dsn = connect_string or os.environ["ORACLE_DSN"]
    return oracledb.connect(user=user, password=password, dsn=dsn)


def _ensure_schema(conn):
    cur = conn.cursor()
    for table, ddl in SCHEMA.items():
        try:
            cur.execute(ddl)
        except oracledb.DatabaseError as e:
            if e.args[0].code != ORA_NAME_IN_USE:
                raise
    conn.commit()
    cur.close()


def load_to_warehouse(users_df, items_df, interactions_df):
    """Creates tables if needed, replaces contents. Mirrors a BigQuery load job."""
    conn = _get_conn()
    _ensure_schema(conn)
    cur = conn.cursor()

    cur.execute("DELETE FROM interactions")
    cur.execute("DELETE FROM items")
    cur.execute("DELETE FROM users")

    cur.executemany(
        "INSERT INTO users (user_id, age_group, city, signup_date, segment) "
        "VALUES (:1, :2, :3, :4, :5)",
        list(users_df[["user_id", "age_group", "city", "signup_date", "segment"]].itertuples(index=False, name=None))
    )
    cur.executemany(
        "INSERT INTO items (item_id, title, category, brand, price, avg_rating) "
        "VALUES (:1, :2, :3, :4, :5, :6)",
        list(items_df[["item_id", "title", "category", "brand", "price", "avg_rating"]].itertuples(index=False, name=None))
    )
    interactions_rows = interactions_df[["user_id", "item_id", "event_type", "rating", "timestamp"]].copy()
    interactions_rows["rating"] = interactions_rows["rating"].where(interactions_rows["rating"].notna(), None)
    cur.executemany(
        "INSERT INTO interactions (user_id, item_id, event_type, rating, timestamp) "
        "VALUES (:1, :2, :3, :4, :5)",
        list(interactions_rows.itertuples(index=False, name=None))
    )
    conn.commit()
    cur.close()
    conn.close()
    log.info(f"Loaded {len(users_df)} users, {len(items_df)} items, "
             f"{len(interactions_df)} interactions -> Oracle Autonomous Database")


def query_warehouse(sql: str, params: dict = None) -> pd.DataFrame:
    """Drop-in replacement for bigquery.Client().query(sql).to_dataframe() / SQLite query_warehouse()."""
    conn = _get_conn()
    df = pd.read_sql(sql, conn, params=params or {})
    conn.close()
    df.columns = [c.lower() for c in df.columns]
    return df
