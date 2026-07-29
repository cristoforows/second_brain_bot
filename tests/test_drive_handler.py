from drive_handler import FOLDER_MIME_TYPE, list_folder_contents, verify_folder


class _FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeFiles:
    def __init__(self, get_result=None, list_result=None):
        self._get_result = get_result
        self._list_result = list_result

    def get(self, **kwargs):
        return _FakeExecute(self._get_result)

    def list(self, **kwargs):
        return _FakeExecute(self._list_result)


class _FakeService:
    def __init__(self, get_result=None, list_result=None):
        self._files = _FakeFiles(get_result, list_result)

    def files(self):
        return self._files


# --- verify_folder ---


def test_verify_folder_true_for_existing_untrashed_folder():
    service = _FakeService(get_result={"mimeType": FOLDER_MIME_TYPE, "trashed": False})
    assert verify_folder(service, "f1") is True


def test_verify_folder_false_when_trashed():
    service = _FakeService(get_result={"mimeType": FOLDER_MIME_TYPE, "trashed": True})
    assert verify_folder(service, "f1") is False


def test_verify_folder_false_when_not_a_folder():
    service = _FakeService(get_result={"mimeType": "text/markdown", "trashed": False})
    assert verify_folder(service, "f1") is False


def test_verify_folder_false_on_api_error():
    service = _FakeService(get_result=Exception("404: not found"))
    assert verify_folder(service, "bad-id") is False


# --- list_folder_contents ---


def test_list_folder_contents_returns_children():
    children = [{"id": "1", "name": "a.md", "mimeType": "text/markdown"}]
    service = _FakeService(list_result={"files": children})
    assert list_folder_contents(service, "root") == children


def test_list_folder_contents_returns_empty_on_api_error():
    service = _FakeService(list_result=Exception("boom"))
    assert list_folder_contents(service, "root") == []
