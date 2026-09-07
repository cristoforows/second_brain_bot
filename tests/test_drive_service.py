from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from second_brain.services.drive import DriveService


@pytest.fixture
def drive() -> DriveService:
    """Create a DriveService with mocked credentials loading and API client."""
    with (
        patch("second_brain.services.drive._load_credentials") as mock_load,
        patch("second_brain.services.drive.build") as mock_build,
    ):
        mock_load.return_value = MagicMock()
        service = DriveService("/fake/path.json")
        # Expose the mock service object for per-test configuration
        service._mock_api = mock_build.return_value
    return service


class TestListFiles:
    def test_returns_files(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.list.return_value.execute.return_value = {
            "files": [
                {"id": "f1", "name": "note.md", "mimeType": "text/markdown"},
            ],
        }

        result = drive.list_files("folder-abc")
        assert len(result) == 1
        assert result[0]["id"] == "f1"

    def test_paginates(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.list.return_value.execute.side_effect = [
            {
                "files": [{"id": "f1", "name": "a.md"}],
                "nextPageToken": "tok2",
            },
            {
                "files": [{"id": "f2", "name": "b.md"}],
            },
        ]

        result = drive.list_files("folder-abc")
        assert len(result) == 2

    def test_empty_folder(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.list.return_value.execute.return_value = {"files": []}

        result = drive.list_files("folder-abc")
        assert result == []


class TestReadFile:
    def test_returns_decoded_string(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.export.return_value.execute.return_value = b"# Hello"

        content = drive.read_file("file-123", "fake/path.md")
        assert content == "# Hello"


class TestReadFileRaw:
    def test_returns_decoded_string(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.get_media.return_value.execute.return_value = b"raw content"

        content = drive.read_file_raw("file-123", "fake/path.md")
        assert content == "raw content"


class TestFindFile:
    def test_found(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.list.return_value.execute.return_value = {
            "files": [{"id": "f1", "name": "target.md", "mimeType": "text/markdown"}],
        }

        result = drive.find_file("folder-abc", "target.md")
        assert result is not None
        assert result["id"] == "f1"

    def test_not_found(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.list.return_value.execute.return_value = {"files": []}

        result = drive.find_file("folder-abc", "nope.md")
        assert result is None


class TestWriteFile:
    def test_returns_file_id(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.create.return_value.execute.return_value = {"id": "new-id"}

        file_id = drive.write_file("folder-abc", "new.md", "# Content")
        assert file_id == "new-id"


class TestUpdateFile:
    def test_calls_update(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.update.return_value.execute.return_value = {}

        drive.update_file("file-123", "updated content", "fake/path.md")
        files_mock.update.assert_called_once()


class TestCreateFolder:
    def test_returns_folder_id(self, drive: DriveService) -> None:
        files_mock = drive._mock_api.files.return_value
        files_mock.create.return_value.execute.return_value = {"id": "folder-new"}

        folder_id = drive.create_folder("parent-id", "my-folder")
        assert folder_id == "folder-new"
