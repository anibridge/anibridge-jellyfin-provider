"""Tests for Jellyfin client internals."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from jellyfin.generated import BaseItemKind, CollectionType, CollectionTypeOptions

from anibridge.providers.library.jellyfin.client import (
    JellyfinClient,
    _FrozenCacheEntry,
)


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
    logger = logging.getLogger("tests.anibridge.client")
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

    assert client._load_show_metadata_fetcher_orders() == {section_id: ("AniList",)}
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

    assert client._load_show_metadata_fetcher_orders() == {
        section_id: ("AniDb", "AniList")
    }
    assert client._load_show_metadata_fetchers() == {section_id: "AniDb"}


def test_is_on_continue_watching_checks_next_up_for_series() -> None:
    """Series should be considered on continue watching when present in Next Up."""
    user_id = uuid4()
    section_id = uuid4()
    series_id = uuid4()

    class _FakeTvShowsApi:
        def get_next_up(self, **kwargs):
            assert kwargs["user_id"] == user_id
            assert kwargs["parent_id"] == section_id
            response = type(
                "_Response",
                (),
                {
                    "items": [
                        cast(
                            Any,
                            _FakeItem(
                                id="ep",
                                type=BaseItemKind.EPISODE,
                                series_id=series_id,
                            ),
                        )
                    ]
                },
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
    client._user_id = user_id

    section = cast(
        Any,
        _FakeItem(
            id=section_id,
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
        ),
    )

    series = cast(Any, _FakeItem(id=series_id, type=BaseItemKind.SERIES))
    assert client.is_on_continue_watching(section, series) is True


def test_is_on_continue_watching_checks_next_up_for_episode_series() -> None:
    """Episodes should resolve their parent series when checking Next Up."""
    user_id = uuid4()
    section_id = uuid4()
    series_id = uuid4()

    class _FakeTvShowsApi:
        def get_next_up(self, **kwargs):
            assert kwargs["user_id"] == user_id
            assert kwargs["parent_id"] == section_id
            return cast(Any, type("_Response", (), {"items": []})())

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._tv_shows_api = cast(Any, _FakeTvShowsApi())
    client._user_id = user_id

    section = cast(
        Any,
        _FakeItem(
            id=section_id,
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
        ),
    )

    episode = cast(
        Any,
        _FakeItem(id=uuid4(), type=BaseItemKind.EPISODE, series_id=series_id),
    )
    assert client.is_on_continue_watching(section, episode) is False


def test_is_on_continue_watching_reuses_cache_when_item_not_updated() -> None:
    """Cache should be reused when item timestamps are not newer than cache."""
    user_id = uuid4()
    section_id = uuid4()
    series_id = uuid4()
    calls = {"count": 0}

    class _FakeTvShowsApi:
        def get_next_up(self, **kwargs):
            calls["count"] += 1
            assert kwargs["user_id"] == user_id
            assert kwargs["parent_id"] == section_id
            return cast(
                Any,
                type(
                    "_Response",
                    (),
                    {
                        "items": [
                            cast(
                                Any,
                                _FakeItem(
                                    id="ep",
                                    type=BaseItemKind.EPISODE,
                                    series_id=series_id,
                                ),
                            )
                        ]
                    },
                )(),
            )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._tv_shows_api = cast(Any, _FakeTvShowsApi())
    client._user_id = user_id

    section = cast(
        Any,
        _FakeItem(
            id=section_id,
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
        ),
    )
    series = cast(
        Any,
        _FakeItem(
            id=series_id,
            type=BaseItemKind.SERIES,
            date_created=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )

    assert client.is_on_continue_watching(section, series) is True
    assert client.is_on_continue_watching(section, series) is True
    assert calls["count"] == 1


def test_is_on_continue_watching_refreshes_cache_when_item_is_newer() -> None:
    """Cache should refresh when the checked item changed since cache creation."""
    user_id = uuid4()
    section_id = uuid4()
    series_id = uuid4()
    calls = {"count": 0}

    class _FakeTvShowsApi:
        def get_next_up(self, **kwargs):
            calls["count"] += 1
            assert kwargs["user_id"] == user_id
            assert kwargs["parent_id"] == section_id

            if calls["count"] == 1:
                return cast(
                    Any,
                    type(
                        "_Response",
                        (),
                        {
                            "items": [
                                cast(
                                    Any,
                                    _FakeItem(
                                        id="ep1",
                                        type=BaseItemKind.EPISODE,
                                        series_id=uuid4(),
                                    ),
                                )
                            ]
                        },
                    )(),
                )

            return cast(
                Any,
                type(
                    "_Response",
                    (),
                    {
                        "items": [
                            cast(
                                Any,
                                _FakeItem(
                                    id="ep2",
                                    type=BaseItemKind.EPISODE,
                                    series_id=series_id,
                                ),
                            )
                        ]
                    },
                )(),
            )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._tv_shows_api = cast(Any, _FakeTvShowsApi())
    client._user_id = user_id

    section = cast(
        Any,
        _FakeItem(
            id=section_id,
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
        ),
    )
    series = cast(
        Any,
        _FakeItem(
            id=series_id,
            type=BaseItemKind.SERIES,
            date_last_media_added=datetime.now(UTC) + timedelta(seconds=1),
        ),
    )

    assert client.is_on_continue_watching(section, series) is False
    assert client.is_on_continue_watching(section, series) is True
    assert calls["count"] == 2


def test_is_on_continue_watching_refreshes_cache_when_ttl_expires() -> None:
    """Cache should refresh once the continue-watching TTL has expired."""
    user_id = uuid4()
    section_id = uuid4()
    series_id = uuid4()
    calls = {"count": 0}

    class _FakeTvShowsApi:
        def get_next_up(self, **kwargs):
            calls["count"] += 1
            assert kwargs["user_id"] == user_id
            assert kwargs["parent_id"] == section_id

            return cast(
                Any,
                type(
                    "_Response",
                    (),
                    {
                        "items": [
                            cast(
                                Any,
                                _FakeItem(
                                    id=f"ep-{calls['count']}",
                                    type=BaseItemKind.EPISODE,
                                    series_id=series_id,
                                ),
                            )
                        ]
                    },
                )(),
            )

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._tv_shows_api = cast(Any, _FakeTvShowsApi())
    client._user_id = user_id

    section = cast(
        Any,
        _FakeItem(
            id=section_id,
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
        ),
    )
    series = cast(Any, _FakeItem(id=series_id, type=BaseItemKind.SERIES))

    client._continue_cache[section_id] = _FrozenCacheEntry(
        keys=frozenset({uuid4()}),
        cached_at=datetime.now(UTC)
        - JellyfinClient._CONTINUE_CACHE_TTL
        - timedelta(seconds=1),
    )

    assert client.is_on_continue_watching(section, series) is True
    assert calls["count"] == 1


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
async def test_list_section_items_require_watched_with_series_keys_uses_parent_query():
    """TV keyed watched lookups should treat keys as series ids, not episode ids."""
    series_id = uuid4()
    section = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.TVSHOWS,
    )
    watched_episode = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.EPISODE,
        series_id=series_id,
        user_data=_FakeUserData(played=True, play_count=1),
        date_created=datetime.now(UTC),
    )
    show = _FakeItem(
        id=series_id,
        type=BaseItemKind.SERIES,
        date_created=datetime.now(UTC),
    )

    captured_calls: list[dict[str, object]] = []

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            captured_calls.append(kwargs)
            include_types = kwargs.get("include_item_types")
            if include_types == [BaseItemKind.EPISODE]:
                return cast(Any, type("_Response", (), {"items": [watched_episode]})())
            return cast(Any, type("_Response", (), {"items": [show]})())

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._items_api = cast(Any, _FakeItemsApi())
    client._user_id = uuid4()

    items = await client.list_section_items(
        cast(Any, section),
        require_watched=True,
        keys=(str(series_id),),
    )

    assert [item.id for item in items] == [series_id]
    assert captured_calls[0].get("parent_id") == series_id
    assert captured_calls[0].get("ids") is None
    assert captured_calls[0].get("include_item_types") == [BaseItemKind.EPISODE]
    assert captured_calls[1].get("ids") == [series_id]


@pytest.mark.asyncio
async def test_list_section_items_matches_raw_webhook_series_keys():
    """Post-fetch key filtering should accept Jellyfin webhook ids without hyphens."""
    series_id = uuid4()
    section = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.COLLECTIONFOLDER,
        collection_type=CollectionType.TVSHOWS,
    )
    watched_episode = _FakeItem(
        id=uuid4(),
        type=BaseItemKind.EPISODE,
        series_id=series_id,
        user_data=_FakeUserData(played=True, play_count=1),
        date_created=datetime.now(UTC),
    )
    show = _FakeItem(
        id=series_id,
        type=BaseItemKind.SERIES,
        date_created=datetime.now(UTC),
    )

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            include_types = kwargs.get("include_item_types")
            if include_types == [BaseItemKind.EPISODE]:
                return cast(Any, type("_Response", (), {"items": [watched_episode]})())
            return cast(Any, type("_Response", (), {"items": [show]})())

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._items_api = cast(Any, _FakeItemsApi())
    client._user_id = uuid4()

    items = await client.list_section_items(
        cast(Any, section),
        require_watched=True,
        keys=(series_id.hex,),
    )

    assert [item.id for item in items] == [series_id]


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


@pytest.mark.asyncio
async def test_initialize_and_close_manage_client_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """initialize/close should populate and then clear runtime state."""
    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )

    async def inline_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "anibridge.providers.library.jellyfin.client.asyncio.to_thread",
        inline_to_thread,
    )
    monkeypatch.setattr(client, "_configure_client", lambda: None)
    monkeypatch.setattr(
        client,
        "_resolve_user",
        lambda: cast(Any, SimpleNamespace(id=uuid4(), name="Demo")),
    )
    monkeypatch.setattr(
        client,
        "_load_sections",
        lambda: [cast(Any, _FakeItem(id=uuid4(), type=BaseItemKind.COLLECTIONFOLDER))],
    )
    monkeypatch.setattr(
        client,
        "_load_show_metadata_fetcher_orders",
        lambda: {"sec": ("AniDb", "AniList")},
    )

    await client.initialize()
    assert client.user_name() == "Demo"
    assert len(client.sections()) == 1
    assert client.show_metadata_fetchers_for_section("sec") == ("AniDb", "AniList")
    assert client.show_metadata_fetcher_for_section("sec") == "AniDb"

    await client.close()
    assert client.sections() == ()
    with pytest.raises(RuntimeError):
        client.user_id()


def test_runtime_errors_before_initialize() -> None:
    """Methods requiring initialized state should raise when not ready."""
    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )

    with pytest.raises(RuntimeError):
        client.user_id()
    with pytest.raises(RuntimeError):
        client.user_name()
    with pytest.raises(RuntimeError):
        client.list_show_seasons(uuid4())
    with pytest.raises(RuntimeError):
        client.list_show_episodes(show_id=uuid4())
    with pytest.raises(RuntimeError):
        client.get_item(uuid4())


def test_url_and_header_helpers() -> None:
    """Header and URL helper methods should include expected parameters."""
    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token123",
        user="demo",
    )

    assert client.auth_headers() == {"X-Emby-Token": "token123"}
    image_url = client.build_image_url("item-1", tag="abc")
    assert "/Items/item-1/Images/Primary" in image_url
    assert "api_key=token123" in image_url
    assert "tag=abc" in image_url
    assert client.build_item_url("item-1").endswith("id=item-1")
    assert client.clear_cache() is None


def test_resolve_user_matches_by_id_and_name() -> None:
    """_resolve_user should match configured target by id or username."""
    user_by_id = cast(Any, SimpleNamespace(id="abc", name="Person A"))
    user_by_name = cast(Any, SimpleNamespace(id="def", name="Demo"))

    class _FakeUserApi:
        def __init__(self, users):
            self._users = users

        def get_users(self):
            return self._users

    client_by_id = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="ABC",
    )
    client_by_id._user_api = cast(Any, _FakeUserApi([user_by_id, user_by_name]))
    assert client_by_id._resolve_user().id == "abc"

    client_by_name = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client_by_name._user_api = cast(Any, _FakeUserApi([user_by_id, user_by_name]))
    assert client_by_name._resolve_user().id == "def"

    client_empty = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="   ",
    )
    client_empty._user_api = cast(Any, _FakeUserApi([user_by_id]))
    with pytest.raises(ValueError):
        client_empty._resolve_user()


def test_load_sections_applies_filters() -> None:
    """_load_sections should include only supported collection types and filters."""
    movies = cast(
        Any,
        SimpleNamespace(
            id=uuid4(),
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.MOVIES,
            name="Movies",
        ),
    )
    shows = cast(
        Any,
        SimpleNamespace(
            id=uuid4(),
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
            name="Anime",
        ),
    )
    music = cast(
        Any,
        SimpleNamespace(
            id=uuid4(),
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.BOXSETS,
            name="Box",
        ),
    )

    class _FakeViewsApi:
        def get_user_views(self, **kwargs):
            return cast(Any, SimpleNamespace(items=[movies, shows, music]))

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
        section_filter=["anime"],
    )
    client._user_views_api = cast(Any, _FakeViewsApi())
    client._user_id = cast(Any, uuid4())

    sections = client._load_sections()
    assert [s.name for s in sections] == ["Anime"]


def test_parse_uuid_keys_and_user_activity_helpers() -> None:
    """UUID key parsing and user activity helpers should handle edge values."""
    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    first = uuid4()
    parsed = client._parse_uuid_keys([str(first), "bad-uuid", str(uuid4())])
    assert parsed is not None and parsed[0] == first
    assert client._parse_uuid_keys(None) is None

    assert client._has_user_activity(None) is False
    assert client._has_user_activity(cast(Any, _FakeUserData())) is False
    assert client._has_user_activity(cast(Any, _FakeUserData(play_count=1))) is True


def test_item_has_user_activity_for_series_uses_episode_fallback() -> None:
    """Series user activity checks should fall back to episode activity when needed."""
    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    series = cast(
        Any, _FakeItem(id=uuid4(), type=BaseItemKind.SERIES, user_data=_FakeUserData())
    )

    client.list_show_episodes = lambda **kwargs: [  # type: ignore
        cast(
            Any,
            _FakeItem(
                id=uuid4(),
                type=BaseItemKind.EPISODE,
                user_data=_FakeUserData(playback_position_ticks=1),
            ),
        )
    ]
    assert (
        client._item_has_user_activity(
            series, section_collection_type=CollectionType.TVSHOWS
        )
        is True
    )


def test_show_episode_and_item_lookup_success_paths() -> None:
    """Season/episode/item helpers should proxy through initialized API clients."""
    show_id = uuid4()
    season_id = uuid4()
    episode_id = uuid4()

    season_item = cast(Any, _FakeItem(id=season_id, type=BaseItemKind.SEASON))
    episode_item = cast(Any, _FakeItem(id=episode_id, type=BaseItemKind.EPISODE))

    class _FakeItemsApi:
        def get_items(self, **kwargs):
            include_item_types = kwargs.get("include_item_types")
            if include_item_types == [BaseItemKind.SEASON]:
                return cast(Any, SimpleNamespace(items=[season_item]))
            return cast(Any, SimpleNamespace(items=[episode_item]))

    class _FakeUserLibraryApi:
        def get_item(self, item_id, **kwargs):
            return cast(Any, _FakeItem(id=item_id, type=BaseItemKind.MOVIE))

    client = JellyfinClient(
        logger=cast(Any, _test_logger()),
        url="http://jellyfin",
        token="token",
        user="demo",
    )
    client._items_api = cast(Any, _FakeItemsApi())
    client._user_library_api = cast(Any, _FakeUserLibraryApi())
    client._user_id = cast(Any, uuid4())

    seasons = client.list_show_seasons(show_id)
    episodes = client.list_show_episodes(show_id=show_id, season_id=season_id)
    item = client.get_item(show_id)

    assert len(seasons) == 1 and seasons[0].id == season_id
    assert len(episodes) == 1 and episodes[0].id == episode_id
    assert item.id == show_id


@pytest.mark.asyncio
async def test_fetch_history_and_continue_watching_paths() -> None:
    """History and continue watching helpers should handle common branches."""
    section_id = uuid4()
    series_id = uuid4()
    episode_id = uuid4()

    section = cast(
        Any,
        _FakeItem(
            id=section_id,
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
        ),
    )
    series = cast(Any, _FakeItem(id=series_id, type=BaseItemKind.SERIES))
    movie = cast(
        Any,
        _FakeItem(
            id=uuid4(),
            type=BaseItemKind.MOVIE,
            user_data=_FakeUserData(last_played_date=datetime.now(UTC)),
        ),
    )
    episode = cast(
        Any,
        _FakeItem(
            id=episode_id,
            type=BaseItemKind.EPISODE,
            user_data=_FakeUserData(last_played_date=datetime.now(UTC)),
        ),
    )

    class _FakeTvShowsApi:
        def __init__(self):
            self.calls = 0

        def get_next_up(self, **kwargs):
            self.calls += 1
            return cast(
                Any,
                SimpleNamespace(
                    items=[
                        cast(
                            Any,
                            _FakeItem(
                                id=episode_id,
                                type=BaseItemKind.EPISODE,
                                series_id=series_id,
                            ),
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
    client._user_id = cast(Any, uuid4())
    client._tv_shows_api = cast(Any, _FakeTvShowsApi())
    client.list_show_episodes = lambda **kwargs: [episode]  # type: ignore

    history_series = await client.fetch_history(series)
    history_movie = await client.fetch_history(movie)
    assert history_series and history_series[0][0] == str(episode_id)
    assert history_movie and history_movie[0][0] == str(movie.id)

    assert client.is_on_continue_watching(section, series) is True
    # Cached path should still be true.
    assert client.is_on_continue_watching(section, series) is True

    empty_section = cast(
        Any,
        _FakeItem(
            id=None,
            type=BaseItemKind.COLLECTIONFOLDER,
            collection_type=CollectionType.TVSHOWS,
        ),
    )
    assert client.is_on_continue_watching(empty_section, movie) is False
