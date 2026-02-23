"""Tests for Jellyfin client internals."""

from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from jellyfin.generated import CollectionTypeOptions

from anibridge_jellyfin_provider.client import JellyfinClient


@dataclass(slots=True)
class _FakeTypeOption:
    type: str | None
    metadata_fetcher_order: list[str] | None
    metadata_fetchers: list[str] | None


@dataclass(slots=True)
class _FakeLibraryOptions:
    type_options: list[_FakeTypeOption] | None


@dataclass(slots=True)
class _FakeVirtualFolder:
    item_id: str | None
    collection_type: CollectionTypeOptions | None
    library_options: _FakeLibraryOptions | None


class _FakeLibraryStructureApi:
    def __init__(self, folders: list[_FakeVirtualFolder]) -> None:
        self._folders = folders

    def get_virtual_folders(self):
        return self._folders


def test_load_show_metadata_fetchers_uses_ordered_enabled_fetcher() -> None:
    """Top fetcher must be selected from order and also be enabled."""
    section_id = str(uuid4())
    folder = _FakeVirtualFolder(
        item_id=section_id,
        collection_type=CollectionTypeOptions.TVSHOWS,
        library_options=_FakeLibraryOptions(
            type_options=[
                _FakeTypeOption(
                    type="Series",
                    metadata_fetcher_order=["AniDb", "AniList"],
                    metadata_fetchers=["AniList"],
                )
            ]
        ),
    )

    client = JellyfinClient(url="http://jellyfin", token="token", user="demo")
    client._library_structure_api = cast(Any, _FakeLibraryStructureApi([folder]))

    assert client._load_show_metadata_fetchers() == {section_id: "AniList"}


def test_load_show_metadata_fetchers_uses_enabled_when_order_missing() -> None:
    """Enabled list is used when metadata fetcher order is absent."""
    section_id = str(uuid4())
    folder = _FakeVirtualFolder(
        item_id=section_id,
        collection_type=CollectionTypeOptions.TVSHOWS,
        library_options=_FakeLibraryOptions(
            type_options=[
                _FakeTypeOption(
                    type="Series",
                    metadata_fetcher_order=None,
                    metadata_fetchers=["AniDb", "AniList"],
                )
            ]
        ),
    )

    client = JellyfinClient(url="http://jellyfin", token="token", user="demo")
    client._library_structure_api = cast(Any, _FakeLibraryStructureApi([folder]))

    assert client._load_show_metadata_fetchers() == {section_id: "AniDb"}
