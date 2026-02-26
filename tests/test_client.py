"""Tests for Jellyfin client internals."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from jellyfin.generated import BaseItemKind, CollectionType, CollectionTypeOptions

from anibridge_jellyfin_provider.client import JellyfinClient


@dataclass(slots=True)
class _FakeTypeOption:
    type: BaseItemKind | str | None
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


def _test_logger() -> logging.Logger:
    logger = logging.getLogger("tests.anibridge_jellyfin_provider.client")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    return logger


@dataclass(slots=True)
class _FakeUserData:
    played: bool = False
    play_count: int = 0
    playback_position_ticks: int = 0
    is_favorite: bool = False


@dataclass(slots=True)
class _FakeItem:
    id: str | None
    type: BaseItemKind | str
    collection_type: CollectionType | str | None = None
    user_data: _FakeUserData | None = None
    date_last_media_added: datetime | None = None
    date_created: datetime | None = None
    genres: list[str] | None = None


def test_load_show_metadata_fetchers_uses_ordered_enabled_fetcher() -> None:
    """Top fetcher must be selected from order and also be enabled."""
    section_id = str(uuid4())
    folder = _FakeVirtualFolder(
        item_id=section_id,
        collection_type=CollectionTypeOptions.TVSHOWS,
        library_options=_FakeLibraryOptions(
            type_options=[
                _FakeTypeOption(
                    type=BaseItemKind.SERIES,
                    metadata_fetcher_order=["AniDb", "AniList"],
                    metadata_fetchers=["AniList"],
                )
            ]
        ),
    )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
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
                    type=BaseItemKind.SERIES,
                    metadata_fetcher_order=None,
                    metadata_fetchers=["AniDb", "AniList"],
                )
            ]
        ),
    )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._library_structure_api = cast(Any, _FakeLibraryStructureApi([folder]))

    assert client._load_show_metadata_fetchers() == {section_id: "AniDb"}


@pytest.mark.asyncio
async def test_list_section_items_require_watched_includes_series_with_activity():
    """TV shows should match when any user activity exists on show or episodes."""
    watched_by_episode = _FakeItem(
        id="show-1",
        type=BaseItemKind.SERIES,
        user_data=_FakeUserData(played=False, play_count=0),
    )
    watched_by_show = _FakeItem(
        id="show-2",
        type=BaseItemKind.SERIES,
        user_data=_FakeUserData(played=True, play_count=1),
    )
    unwatched = _FakeItem(
        id="show-3",
        type=BaseItemKind.SERIES,
        user_data=_FakeUserData(played=False, play_count=0),
    )
    partial_by_show = _FakeItem(
        id="show-4",
        type=BaseItemKind.SERIES,
        user_data=_FakeUserData(playback_position_ticks=10),
    )
    favorite_by_show = _FakeItem(
        id="show-5",
        type=BaseItemKind.SERIES,
        user_data=_FakeUserData(is_favorite=True),
    )
    section = _FakeItem(
        id="section-1",
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.TVSHOWS,
    )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._fetch_section_items = cast(
        Any,
        lambda _section, *, min_last_modified=None, require_watched=False, keys=None: [
            watched_by_episode,
            watched_by_show,
            unwatched,
            partial_by_show,
            favorite_by_show,
        ],
    )
    client.list_show_episodes = cast(
        Any,
        lambda *, show_id, season_id=None: (
            [
                _FakeItem(
                    id="episode-1",
                    type=BaseItemKind.EPISODE,
                    user_data=_FakeUserData(play_count=1),
                )
            ]
            if show_id == "show-1"
            else []
        ),
    )

    items = await client.list_section_items(cast(Any, section), require_watched=True)

    assert [item.id for item in items] == [
        "show-1",
        "show-2",
        "show-4",
        "show-5",
    ]


@pytest.mark.asyncio
async def test_list_section_items_min_last_modified_prefers_date_last_saved():
    """Incremental filtering should use Jellyfin's min_date_last_saved argument."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=1)

    item = _FakeItem(
        id="show-1",
        type=BaseItemKind.SERIES,
        date_last_media_added=now,
        date_created=now,
    )
    section = _FakeItem(
        id="section-1",
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.TVSHOWS,
    )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    captured_kwargs: dict[str, object] = {}

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            captured_kwargs.update(kwargs)
            return cast(Any, type("_Response", (), {"items": [item]})())

    client._items_api = cast(Any, _FakeItemsApi())
    client._user_id = cast(Any, "user-1")

    items = await client.list_section_items(
        cast(Any, section), min_last_modified=cutoff
    )

    assert [entry.id for entry in items] == ["show-1"]
    assert captured_kwargs.get("min_date_last_saved") == cutoff


@pytest.mark.asyncio
async def test_list_section_items_passes_supported_server_filters():
    """Server-side get_items args should include supported filters when available."""
    section = _FakeItem(
        id=str(uuid4()),
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.MOVIES,
    )
    key = str(uuid4())
    item = _FakeItem(
        id=key,
        type=BaseItemKind.MOVIE,
        user_data=_FakeUserData(is_favorite=True),
        genres=["action"],
    )

    captured_kwargs: dict[str, object] = {}

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            captured_kwargs.update(kwargs)
            return cast(Any, type("_Response", (), {"items": [item]})())

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
        genre_filter=["Action"],
    )
    client._items_api = cast(Any, _FakeItemsApi())
    client._user_id = cast(Any, uuid4())

    items = await client.list_section_items(
        cast(Any, section),
        require_watched=True,
        keys=(key,),
    )

    assert [entry.id for entry in items] == [key]
    assert captured_kwargs.get("genres") == ["action"]
    assert captured_kwargs.get("is_played") is None
    assert captured_kwargs.get("ids") == [UUID(key)]
