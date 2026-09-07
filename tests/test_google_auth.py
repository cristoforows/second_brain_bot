from google_auth import has_calendar_scope, has_drive_read_scope


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
