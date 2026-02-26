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
    last_played_date: datetime | None = None


@dataclass(slots=True)
class _FakeItem:
    id: UUID | str | None
    type: BaseItemKind | str
    collection_type: CollectionType | str | None = None
    parent_id: UUID | None = None
    series_id: UUID | None = None
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


def test_is_on_continue_watching_checks_next_up_for_series() -> None:
    """Series should be considered on continue watching when present in Next Up."""
    series_id = uuid4()

    class _FakeTvShowsApi:
        def get_next_up(self, **kwargs):
            assert kwargs["series_id"] == series_id
            response = type(
                "_Response",
                (),
                {"items": [cast(Any, _FakeItem(id="ep", type=BaseItemKind.EPISODE))]},
            )
            return cast(
                Any,
                response(),
            )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._tv_shows_api = cast(Any, _FakeTvShowsApi())
    client._user_id = series_id

    series = cast(Any, _FakeItem(id=series_id, type=BaseItemKind.SERIES))
    assert client.is_on_continue_watching(series) is True


def test_is_on_continue_watching_checks_next_up_for_episode_series() -> None:
    """Episodes should resolve their parent series when checking Next Up."""
    user_id = uuid4()
    series_id = uuid4()

    class _FakeTvShowsApi:
        def get_next_up(self, **kwargs):
            assert kwargs["series_id"] == series_id
            return cast(Any, type("_Response", (), {"items": []})())

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._tv_shows_api = cast(Any, _FakeTvShowsApi())
    client._user_id = user_id

    episode = cast(
        Any,
        _FakeItem(id=uuid4(), type=BaseItemKind.EPISODE, series_id=series_id),
    )
    assert client.is_on_continue_watching(episode) is False


@pytest.mark.asyncio
async def test_list_section_items_require_watched_includes_series_with_activity():
    """TV watched filtering should prefetch watched episodes and hydrate root shows."""
    show_1_id = uuid4()
    show_2_id = uuid4()
    episode_1_id = uuid4()
    episode_2_id = uuid4()

    watched_episode_1 = _FakeItem(
        id=episode_1_id,
        type=BaseItemKind.EPISODE,
        collection_type=CollectionType.TVSHOWS,
    )
    watched_episode_1.parent_id = show_1_id
    watched_episode_2 = _FakeItem(
        id=episode_2_id,
        type=BaseItemKind.EPISODE,
        collection_type=CollectionType.TVSHOWS,
    )
    watched_episode_2.parent_id = show_2_id

    show_1 = _FakeItem(id=show_1_id, type=BaseItemKind.SERIES)
    show_2 = _FakeItem(id=show_2_id, type=BaseItemKind.SERIES)

    section = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.TVSHOWS,
    )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    calls: list[dict[str, Any]] = []

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            calls.append(kwargs)

            include_types = kwargs.get("include_item_types")
            if include_types == [BaseItemKind.EPISODE]:
                return cast(
                    Any,
                    type(
                        "_Response",
                        (),
                        {"items": [watched_episode_1, watched_episode_2]},
                    )(),
                )

            return cast(Any, type("_Response", (), {"items": [show_1, show_2]})())

    client._items_api = cast(Any, _FakeItemsApi())
    client._user_id = uuid4()

    items = await client.list_section_items(cast(Any, section), require_watched=True)

    assert [item.id for item in items] == [show_1_id, show_2_id]
    assert len(calls) == 2
    assert calls[0].get("include_item_types") == [BaseItemKind.EPISODE]
    assert calls[0].get("is_played") is True
    assert set(calls[1].get("ids") or []) == {show_1_id, show_2_id}


@pytest.mark.asyncio
async def test_list_section_items_require_watched_uses_episode_activity_for_cutoff():
    """TV watched cutoff should be applied to watched episodes, not series metadata."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=1)

    old_series_id = uuid4()
    recent_series_id = uuid4()

    watched_old = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.EPISODE,
        parent_id=old_series_id,
        user_data=_FakeUserData(last_played_date=now - timedelta(days=2)),
        date_last_media_added=now - timedelta(days=3),
        date_created=now - timedelta(days=5),
    )
    watched_recent = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.EPISODE,
        parent_id=recent_series_id,
        user_data=_FakeUserData(last_played_date=now),
        date_last_media_added=now - timedelta(days=7),
        date_created=now - timedelta(days=9),
    )

    old_series = _FakeItem(
        id=old_series_id,
        type=BaseItemKind.SERIES,
        date_last_media_added=now - timedelta(days=30),
        date_created=now - timedelta(days=60),
    )
    recent_series = _FakeItem(
        id=recent_series_id,
        type=BaseItemKind.SERIES,
        date_last_media_added=now - timedelta(days=30),
        date_created=now - timedelta(days=60),
    )

    section = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.TVSHOWS,
    )

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            include_types = kwargs.get("include_item_types")
            if include_types == [BaseItemKind.EPISODE]:
                return cast(
                    Any,
                    type("_Response", (), {"items": [watched_old, watched_recent]})(),
                )
            ids = set(kwargs.get("ids") or [])
            series_items = [
                item
                for item in [old_series, recent_series]
                if not ids or item.id in ids
            ]
            return cast(
                Any,
                type("_Response", (), {"items": series_items})(),
            )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._items_api = cast(Any, _FakeItemsApi())
    client._user_id = uuid4()

    items = await client.list_section_items(
        cast(Any, section), require_watched=True, min_last_modified=cutoff
    )

    assert [item.id for item in items] == [recent_series_id]


@pytest.mark.asyncio
async def test_list_section_items_min_last_modified_filters_client_side():
    """Incremental filtering should use item/user timestamps on the client side."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=1)

    stale_item = _FakeItem(
        id="show-old",
        type=BaseItemKind.SERIES,
        date_last_media_added=now - timedelta(days=3),
        date_created=now - timedelta(days=5),
        user_data=_FakeUserData(last_played_date=now - timedelta(days=2)),
    )
    recently_added = _FakeItem(
        id="show-added",
        type=BaseItemKind.SERIES,
        date_last_media_added=now,
        date_created=now - timedelta(days=10),
    )
    recently_watched = _FakeItem(
        id="show-watched",
        type=BaseItemKind.SERIES,
        date_last_media_added=now - timedelta(days=10),
        date_created=now - timedelta(days=10),
        user_data=_FakeUserData(last_played_date=now),
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
            return cast(
                Any,
                type(
                    "_Response",
                    (),
                    {"items": [stale_item, recently_added, recently_watched]},
                )(),
            )

    client._items_api = cast(Any, _FakeItemsApi())
    client._user_id = cast(Any, "user-1")

    items = await client.list_section_items(
        cast(Any, section), min_last_modified=cutoff
    )

    assert [entry.id for entry in items] == ["show-added", "show-watched"]
    assert captured_kwargs.get("min_date_last_saved") is None


@pytest.mark.asyncio
async def test_list_section_items_passes_supported_server_filters():
    """Server-side get_items args should include supported filters when available."""
    section = _FakeItem(
        id=str(uuid4()),
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.MOVIES,
    )
    key = uuid4()
    item = _FakeItem(
        id=key,
        type=BaseItemKind.MOVIE,
        user_data=_FakeUserData(is_favorite=True),
        genres=["action"],
    )

    captured_calls: list[dict[str, object]] = []

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            captured_calls.append(kwargs)

            include_types = kwargs.get("include_item_types")
            if (
                include_types == [BaseItemKind.MOVIE]
                and kwargs.get("is_played") is True
            ):
                return cast(Any, type("_Response", (), {"items": [item]})())

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
        keys=(str(key),),
    )

    assert [entry.id for entry in items] == [key]
    assert len(captured_calls) == 1
    assert captured_calls[0].get("is_played") is True
    assert captured_calls[0].get("genres") == ["action"]
    assert captured_calls[0].get("ids") == [key]
