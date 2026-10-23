import pytest

from data import oracle_warehouse as ow


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql):
        self.log.append(sql)

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.log = []
        self.closed = False

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_conn(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ow.oracledb, "connect", lambda **kw: conn)
    monkeypatch.setenv("ORACLE_USER", "RECO_APP")
    monkeypatch.setenv("ORACLE_PASSWORD", "x")
    monkeypatch.setenv("ORACLE_CONNECT_STRING", "dsn")
    return conn


def test_sets_current_schema(fake_conn, monkeypatch):
    monkeypatch.setenv("ORACLE_SCHEMA", "ADMIN")
    ow._get_conn()
    assert fake_conn.log == ["ALTER SESSION SET CURRENT_SCHEMA = ADMIN"]


def test_no_schema_no_alter(fake_conn, monkeypatch):
    monkeypatch.delenv("ORACLE_SCHEMA", raising=False)
    ow._get_conn()
    assert fake_conn.log == []


@pytest.mark.parametrize("bad", ["ADMIN; DROP TABLE users", "a b", "1abc", 'x"y'])
def test_rejects_bad_schema(fake_conn, monkeypatch, bad):
    monkeypatch.setenv("ORACLE_SCHEMA", bad)
    with pytest.raises(ValueError):
        ow._get_conn()
    assert fake_conn.closed and fake_conn.log == []
