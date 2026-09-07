from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from second_brain.tools import drive_tools
from second_brain.tools.drive_tools import (
    _resolve_folder,
    create_new_category,
    init_tools,
    list_folder,
    read_category_summary,
    read_directory_index,
    read_file,
    update_category_summary,
    update_directory_index,
    write_to_category,
)


@pytest.fixture(autouse=True)
def _setup_drive_tools() -> None:
    """Inject a mock DriveService into the tools module for every test."""
    mock_drive = MagicMock()
    init_tools(mock_drive, "output-root")
    yield
    # Reset after test
    drive_tools._drive = None
    drive_tools._output_folder_id = ""


def _drive() -> MagicMock:
    return drive_tools._drive  # type: ignore[return-value]


# ------------------------------------------------------------------
# _resolve_folder
# ------------------------------------------------------------------


class TestResolveFolder:
    def test_single_segment(self) -> None:
        _drive().find_file.return_value = {
            "id": "section-id",
            "mimeType": "application/vnd.google-apps.folder",
        }
        result = _resolve_folder("projects")
        assert result == "section-id"
        _drive().find_file.assert_called_once_with("output-root", "projects")

    def test_two_segments(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "section-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "topic-id", "mimeType": "application/vnd.google-apps.folder"},
        ]
        result = _resolve_folder("projects/dashboard-redesign")
        assert result == "topic-id"
        assert _drive().find_file.call_count == 2

    def test_segment_not_found(self) -> None:
        _drive().find_file.return_value = None
        with pytest.raises(ValueError, match="not found"):
            _resolve_folder("projects/nope")

    def test_segment_not_a_folder(self) -> None:
        _drive().find_file.return_value = {"id": "file-id", "mimeType": "text/plain"}
        with pytest.raises(ValueError, match="not found"):
            _resolve_folder("projects")


# ------------------------------------------------------------------
# read_directory_index
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# list_folder
# ------------------------------------------------------------------


class TestListFolder:
    def test_root_empty(self) -> None:
        _drive().list_files.return_value = []
        result = list_folder.invoke({"path": ""})
        assert "empty" in result
        _drive().list_files.assert_called_once_with("output-root")

    def test_root_lists_folders_then_files(self) -> None:
        _drive().list_files.return_value = [
            {"name": "projects", "mimeType": "application/vnd.google-apps.folder", "modifiedTime": "2026-01-01"},
            {"name": "directory.md", "mimeType": "text/markdown", "modifiedTime": "2026-01-02"},
            {"name": "areas", "mimeType": "application/vnd.google-apps.folder", "modifiedTime": "2026-01-01"},
        ]
        result = list_folder.invoke({"path": ""})
        lines = result.splitlines()
        assert lines[0].startswith("[folder] areas")
        assert lines[1].startswith("[folder] projects")
        assert lines[2].startswith("[file]   directory.md")

    def test_nested_path(self) -> None:
        _drive().find_file.return_value = {
            "id": "section-id",
            "mimeType": "application/vnd.google-apps.folder",
        }
        _drive().list_files.return_value = [
            {"name": "dashboard-redesign", "mimeType": "application/vnd.google-apps.folder", "modifiedTime": "2026-01-01"},
        ]
        result = list_folder.invoke({"path": "projects"})
        assert "[folder] dashboard-redesign" in result
        _drive().list_files.assert_called_once_with("section-id")

    def test_path_not_found(self) -> None:
        _drive().find_file.return_value = None
        result = list_folder.invoke({"path": "nonexistent"})
        assert "does not exist" in result


# ------------------------------------------------------------------
# read_directory_index
# ------------------------------------------------------------------


class TestReadDirectoryIndex:
    def test_fresh_knowledge_base(self) -> None:
        _drive().find_file.return_value = None
        result = read_directory_index.invoke({})
        assert "does not exist yet" in result

    def test_existing_directory(self) -> None:
        _drive().find_file.return_value = {"id": "dir-id"}
        _drive().read_file_raw.return_value = "# Directory\n- work\n- health"
        result = read_directory_index.invoke({})
        assert "# Directory" in result


# ------------------------------------------------------------------
# read_category_summary
# ------------------------------------------------------------------


class TestReadCategorySummary:
    def test_category_not_found(self) -> None:
        _drive().find_file.return_value = None
        result = read_category_summary.invoke({"category_name": "nope"})
        assert "does not exist" in result

    def test_summary_found(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "summary-id"},
        ]
        _drive().read_file_raw.return_value = "# Work\nSummary here."
        result = read_category_summary.invoke({"category_name": "work"})
        assert "# Work" in result

    def test_no_directory_yaml(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            None,
        ]
        result = read_category_summary.invoke({"category_name": "work"})
        assert "no Directory.yaml yet" in result

    def test_nested_path_summary_found(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "section-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "topic-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "summary-id"},
        ]
        _drive().read_file_raw.return_value = "# Dashboard\nNotes here."
        result = read_category_summary.invoke(
            {"category_name": "projects/dashboard-redesign"}
        )
        assert "# Dashboard" in result


# ------------------------------------------------------------------
# read_file
# ------------------------------------------------------------------


class TestReadFile:
    def test_category_not_found(self) -> None:
        _drive().find_file.return_value = None
        result = read_file.invoke({"category_name": "nope", "filename": "x.md"})
        assert "does not exist" in result

    def test_file_not_found(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            None,
        ]
        result = read_file.invoke({"category_name": "work", "filename": "x.md"})
        assert "not found" in result

    def test_file_found(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "file-id"},
        ]
        _drive().read_file_raw.return_value = "File content here."
        result = read_file.invoke({"category_name": "work", "filename": "notes.md"})
        assert result == "File content here."

    def test_nested_path_file_found(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "section-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "topic-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "file-id"},
        ]
        _drive().read_file_raw.return_value = "Nested content."
        result = read_file.invoke(
            {"category_name": "projects/dashboard-redesign", "filename": "notes.md"}
        )
        assert result == "Nested content."


# ------------------------------------------------------------------
# write_to_category
# ------------------------------------------------------------------


class TestWriteToCategory:
    def test_category_missing(self) -> None:
        _drive().find_file.return_value = None
        result = write_to_category.invoke(
            {"category_name": "nope", "filename": "x.md", "content": "hi"}
        )
        assert "does not exist" in result

    def test_creates_new_file(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            None,  # file doesn't exist yet
        ]
        _drive().write_file.return_value = "new-file-id"
        result = write_to_category.invoke(
            {"category_name": "work", "filename": "new.md", "content": "content"}
        )
        assert "Created" in result
        _drive().write_file.assert_called_once()

    def test_updates_existing_file(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "existing-id"},
        ]
        result = write_to_category.invoke(
            {"category_name": "work", "filename": "old.md", "content": "updated"}
        )
        assert "Updated" in result
        _drive().update_file.assert_called_once_with("existing-id", "updated", "work/old.md")

    def test_nested_path_creates_file(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "section-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "topic-id", "mimeType": "application/vnd.google-apps.folder"},
            None,  # file doesn't exist yet
        ]
        _drive().write_file.return_value = "new-file-id"
        result = write_to_category.invoke(
            {
                "category_name": "projects/dashboard-redesign",
                "filename": "notes.md",
                "content": "content",
            }
        )
        assert "Created" in result
        _drive().write_file.assert_called_once_with(
            "topic-id", "notes.md", "content", "projects/dashboard-redesign/notes.md"
        )


# ------------------------------------------------------------------
# update_category_summary
# ------------------------------------------------------------------


class TestUpdateCategorySummary:
    def test_category_missing(self) -> None:
        _drive().find_file.return_value = None
        result = update_category_summary.invoke(
            {"category_name": "nope", "summary": "x"}
        )
        assert "does not exist" in result

    def test_creates_summary(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            None,
        ]
        _drive().write_file.return_value = "new-id"
        result = update_category_summary.invoke(
            {"category_name": "work", "summary": "# Work\nOverview."}
        )
        assert "Created directory" in result
        _drive().write_file.assert_called_once_with(
            "folder-id", "Directory.yaml", "# Work\nOverview.", "work/Directory.yaml"
        )

    def test_updates_summary(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "folder-id", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "summary-id"},
        ]
        result = update_category_summary.invoke(
            {"category_name": "work", "summary": "updated"}
        )
        assert "Updated directory" in result
        _drive().update_file.assert_called_once_with("summary-id", "updated", "work/Directory.yaml")


# ------------------------------------------------------------------
# update_directory_index
# ------------------------------------------------------------------


class TestUpdateDirectoryIndex:
    def test_creates_directory(self) -> None:
        _drive().find_file.return_value = None
        _drive().write_file.return_value = "new-id"
        result = update_directory_index.invoke({"content": "# Dir"})
        assert "Created" in result

    def test_updates_directory(self) -> None:
        _drive().find_file.return_value = {"id": "dir-id"}
        result = update_directory_index.invoke({"content": "# Dir updated"})
        assert "Updated" in result
        _drive().update_file.assert_called_once_with("dir-id", "# Dir updated", "Directory.yaml")


# ------------------------------------------------------------------
# create_new_category
# ------------------------------------------------------------------


class TestCreateNewCategory:
    def test_already_exists(self) -> None:
        _drive().find_file.return_value = {
            "id": "folder-id",
            "mimeType": "application/vnd.google-apps.folder",
        }
        result = create_new_category.invoke(
            {"category_name": "work", "description": "Work stuff"}
        )
        assert "already exists" in result

    def test_creates_flat_folder(self) -> None:
        _drive().find_file.return_value = None
        _drive().create_folder.return_value = "new-folder-id"
        result = create_new_category.invoke(
            {"category_name": "health", "description": "Health stuff"}
        )
        assert "Created category" in result
        _drive().create_folder.assert_called_once_with("output-root", "health")
        _drive().write_file.assert_not_called()

    def test_creates_nested_folder(self) -> None:
        _drive().find_file.side_effect = [
            {"id": "section-id", "mimeType": "application/vnd.google-apps.folder"},
            None,  # topic doesn't exist yet
        ]
        _drive().create_folder.return_value = "topic-id"
        result = create_new_category.invoke(
            {
                "category_name": "projects/dashboard-redesign",
                "description": "Dashboard redesign project",
            }
        )
        assert "Created category" in result
        _drive().create_folder.assert_called_once_with("section-id", "dashboard-redesign")
        _drive().write_file.assert_not_called()

    def test_parent_not_found(self) -> None:
        _drive().find_file.return_value = None
        result = create_new_category.invoke(
            {
                "category_name": "nonexistent/dashboard-redesign",
                "description": "Something",
            }
        )
        assert "does not exist" in result
        _drive().create_folder.assert_not_called()
