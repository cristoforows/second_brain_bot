import psycopg2

from google_auth import TokenStorage, has_calendar_scope, has_drive_read_scope


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
