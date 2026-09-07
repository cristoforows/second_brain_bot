import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from second_brain.bot.capture import FOLDER_MIME_TYPE, _download_file_content, list_folder_contents, verify_folder
from second_brain.core.timeutil import capture_date

SG = "Asia/Singapore"  # UTC+8, no DST


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


# --- capture_date ---


def test_capture_date_disabled_cutoff_uses_calendar_date():
    """day_cutoff_hour=0 means disabled — always the local calendar date,
    even right at midnight."""
    now = datetime(2026, 6, 12, 0, 0, tzinfo=ZoneInfo(SG))
    assert capture_date(now, SG, 0) == date(2026, 6, 12)


def test_capture_date_just_before_cutoff_uses_previous_day():
    """A message at 03:59 local time, with a 04:00 cutoff, belongs to
    yesterday's file."""
    now = datetime(2026, 6, 12, 3, 59, tzinfo=ZoneInfo(SG))
    assert capture_date(now, SG, 4) == date(2026, 6, 11)


def test_capture_date_at_cutoff_hour_uses_current_day():
    """Exactly at the cutoff hour, the cutoff no longer applies."""
    now = datetime(2026, 6, 12, 4, 0, tzinfo=ZoneInfo(SG))
    assert capture_date(now, SG, 4) == date(2026, 6, 12)


def test_capture_date_just_after_midnight_before_cutoff():
    """01:00 local, cutoff at 4 — still belongs to the previous day."""
    now = datetime(2026, 6, 12, 1, 0, tzinfo=ZoneInfo(SG))
    assert capture_date(now, SG, 4) == date(2026, 6, 11)


def test_capture_date_well_after_cutoff_uses_current_day():
    now = datetime(2026, 6, 12, 14, 30, tzinfo=ZoneInfo(SG))
    assert capture_date(now, SG, 4) == date(2026, 6, 12)


def test_capture_date_converts_utc_to_local_timezone():
    """A UTC timestamp is converted to the configured timezone before
    applying the cutoff — this is the fix for using the container clock."""
    # 20:30 UTC == 04:30 SGT (UTC+8) the next day — after the 04:00 cutoff,
    # so it belongs to that next SGT day, not the UTC day.
    now = datetime(2026, 6, 11, 20, 30, tzinfo=timezone.utc)
    assert capture_date(now, SG, 4) == date(2026, 6, 12)


def test_capture_date_naive_datetime_assumed_to_already_be_local():
    now = datetime(2026, 6, 12, 2, 0)  # naive
    assert capture_date(now, SG, 4) == date(2026, 6, 11)
