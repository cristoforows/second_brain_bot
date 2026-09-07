import json

from googleapiclient.errors import HttpError

from drive_handler import FOLDER_MIME_TYPE, _download_file_content, list_folder_contents, verify_folder


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


class _FakeResp:
    def __init__(self, status=403, reason="Forbidden"):
        self.status = status
        self.reason = reason


def _http_error(reason: str) -> HttpError:
    """Build an HttpError shaped like a real Drive API error body, where the
    machine-readable `reason` lives in error.errors[].reason (not just in the
    human-readable top-level message)."""
    content = json.dumps({
        "error": {
            "errors": [{"domain": "global", "reason": reason, "message": reason}],
            "code": 403,
            "message": reason,
        }
    }).encode("utf-8")
    return HttpError(_FakeResp(), content)


class _FakeDownloadFiles:
    """Fake files() resource supporting get_media/export, for
    _download_file_content tests."""

    def __init__(self, get_media_result=None, export_result=None):
        self._get_media_result = get_media_result
        self._export_result = export_result
        self.export_called_with = None

    def get_media(self, fileId):
        return _FakeExecute(self._get_media_result)

    def export(self, fileId, mimeType):
        self.export_called_with = {"fileId": fileId, "mimeType": mimeType}
        return _FakeExecute(self._export_result)


class _FakeDownloadService:
    def __init__(self, get_media_result=None, export_result=None):
        self._files = _FakeDownloadFiles(get_media_result, export_result)

    def files(self):
        return self._files


# --- _download_file_content ---


def test_download_file_content_normal_path_bytes():
    service = _FakeDownloadService(get_media_result=b"hello world")
    assert _download_file_content(service, "f1") == "hello world"
    assert service._files.export_called_with is None


def test_download_file_content_normal_path_str():
    service = _FakeDownloadService(get_media_result="hello world")
    assert _download_file_content(service, "f1") == "hello world"
    assert service._files.export_called_with is None


def test_download_file_content_falls_back_to_export_on_file_not_downloadable():
    service = _FakeDownloadService(
        get_media_result=_http_error("fileNotDownloadable"),
        export_result=b"exported note text",
    )

    result = _download_file_content(service, "f1")

    assert result == "exported note text"
    assert service._files.export_called_with == {"fileId": "f1", "mimeType": "text/plain"}


def test_download_file_content_returns_none_on_other_http_error():
    service = _FakeDownloadService(get_media_result=_http_error("insufficientFilePermissions"))

    result = _download_file_content(service, "f1")

    assert result is None
    assert service._files.export_called_with is None


def test_download_file_content_returns_none_when_export_itself_fails():
    service = _FakeDownloadService(
        get_media_result=_http_error("fileNotDownloadable"),
        export_result=Exception("export boom"),
    )

    result = _download_file_content(service, "f1")

    assert result is None


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
