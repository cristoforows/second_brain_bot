import psycopg2

from second_brain.bot.google_auth import (
    TokenStorage,
    _POOL_MAX_SIZE,
    has_calendar_scope,
    has_drive_read_scope,
)


class _FakeTokenStorage:
    def __init__(self, token_data):
        self._token_data = token_data

    def get_user_token(self, user_id):
        return self._token_data


def test_has_drive_read_scope_true_when_granted():
    storage = _FakeTokenStorage({"scopes": ["https://www.googleapis.com/auth/drive.readonly"]})
    assert has_drive_read_scope(1, storage) is True


def test_has_drive_read_scope_false_when_missing():
    storage = _FakeTokenStorage({"scopes": ["https://www.googleapis.com/auth/drive.file"]})
    assert has_drive_read_scope(1, storage) is False


def test_has_drive_read_scope_false_when_no_token():
    storage = _FakeTokenStorage(None)
    assert has_drive_read_scope(1, storage) is False


def test_has_calendar_scope_true_when_granted():
    storage = _FakeTokenStorage({"scopes": ["https://www.googleapis.com/auth/calendar.events"]})
    assert has_calendar_scope(1, storage) is True


def test_has_calendar_scope_false_when_missing():
    storage = _FakeTokenStorage({"scopes": []})
    assert has_calendar_scope(1, storage) is False


# --- TokenStorage._checkout ---


class _FakeCursor:
    def __init__(self, raise_on_execute=None):
        self._raise_on_execute = raise_on_execute

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, query, params=None):
        if self._raise_on_execute is not None:
            raise self._raise_on_execute


class _FakeConnection:
    """A connection whose cursor() raises `fails_with` on execute(), if set."""

    def __init__(self, name, fails_with=None):
        self.name = name
        self._fails_with = fails_with

    def cursor(self):
        return _FakeCursor(raise_on_execute=self._fails_with)

    def __repr__(self):
        return f"<_FakeConnection {self.name}>"


class _FakePool:
    """Hands out queued connections in order; records putconn() calls."""

    def __init__(self, connections):
        self._connections = list(connections)
        self.putconn_calls = []

    def getconn(self):
        return self._connections.pop(0)

    def putconn(self, conn, close=False):
        self.putconn_calls.append((conn, close))


def _make_token_storage(fake_pool):
    storage = TokenStorage.__new__(TokenStorage)  # bypass __init__/real pool
    storage.connection_pool = fake_pool
    storage.fernet = None
    return storage


def test_checkout_uses_healthy_connection_as_is():
    healthy = _FakeConnection("healthy")
    pool = _FakePool([healthy])
    storage = _make_token_storage(pool)

    conn = storage._checkout()

    assert conn is healthy
    assert pool.putconn_calls == []


def test_checkout_discards_stale_connection_and_retries_once():
    stale = _FakeConnection("stale", fails_with=psycopg2.OperationalError("connection lost"))
    healthy = _FakeConnection("healthy")
    pool = _FakePool([stale, healthy])
    storage = _make_token_storage(pool)

    conn = storage._checkout()

    assert conn is healthy
    assert pool.putconn_calls == [(stale, True)]


def test_checkout_discards_connection_raising_interface_error():
    stale = _FakeConnection("stale", fails_with=psycopg2.InterfaceError("cursor already closed"))
    healthy = _FakeConnection("healthy")
    pool = _FakePool([stale, healthy])
    storage = _make_token_storage(pool)

    conn = storage._checkout()

    assert conn is healthy
    assert pool.putconn_calls == [(stale, True)]


def test_checkout_discards_databaseerror_connection_regression_incident_2026_09_08():
    """Regression test for the 2026-09-08 /search outage.

    The connection actually raised psycopg2.DatabaseError (the PARENT class
    of OperationalError/InterfaceError) after a 17h+ Fly machine suspend.
    _checkout() used to only catch the two subclasses, so this exact
    exception sailed past the stale-connection handling and reached the
    Telegram handler as an unhandled "Oops! Something went wrong". It must
    be caught, the connection discarded, and a healthy one returned.
    """
    stale = _FakeConnection("stale", fails_with=psycopg2.DatabaseError("could not send data to server: Connection timed out"))
    healthy = _FakeConnection("healthy")
    pool = _FakePool([stale, healthy])
    storage = _make_token_storage(pool)

    conn = storage._checkout()

    assert conn is healthy
    assert pool.putconn_calls == [(stale, True)]


def test_checkout_discards_several_consecutive_stale_connections():
    stale_conns = [
        _FakeConnection(f"stale{i}", fails_with=psycopg2.OperationalError("connection lost"))
        for i in range(3)
    ]
    healthy = _FakeConnection("healthy")
    pool = _FakePool([*stale_conns, healthy])
    storage = _make_token_storage(pool)

    conn = storage._checkout()

    assert conn is healthy
    assert pool.putconn_calls == [(c, True) for c in stale_conns]


def test_checkout_all_connections_stale_raises_last_error_and_closes_every_one():
    # A long enough suspend can leave every pooled connection dead. The loop
    # is bounded by the pool's max size + 1 (one extra for the connection
    # the pool creates fresh once it's empty), so that many stale
    # connections should exhaust the loop and the last error should propagate.
    stale_conns = [
        _FakeConnection(f"stale{i}", fails_with=psycopg2.OperationalError(f"connection lost {i}"))
        for i in range(_POOL_MAX_SIZE + 1)
    ]
    pool = _FakePool(stale_conns)
    storage = _make_token_storage(pool)

    try:
        storage._checkout()
        assert False, "expected psycopg2.OperationalError to propagate"
    except psycopg2.OperationalError as e:
        assert str(e) == f"connection lost {_POOL_MAX_SIZE}"

    assert pool.putconn_calls == [(c, True) for c in stale_conns]
    assert len(pool.putconn_calls) == _POOL_MAX_SIZE + 1


def test_psycopg2_error_covers_databaseerror_operationalerror_interfaceerror():
    """Guard against narrowing the except clause back to a subset of psycopg2.Error.

    This is exactly what caused the 2026-09-08 incident: DatabaseError is
    the parent of OperationalError and InterfaceError, so catching only the
    two subclasses misses it (and any other psycopg2.Error subclass).
    """
    assert issubclass(psycopg2.DatabaseError, psycopg2.Error)
    assert issubclass(psycopg2.OperationalError, psycopg2.Error)
    assert issubclass(psycopg2.InterfaceError, psycopg2.Error)
    # The specific defect: OperationalError/InterfaceError do NOT cover
    # DatabaseError, since it's their parent, not a sibling or child.
    assert not issubclass(psycopg2.DatabaseError, (psycopg2.OperationalError, psycopg2.InterfaceError))
