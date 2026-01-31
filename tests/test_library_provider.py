"""Tests for the Jellyfin library provider integration."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

import anibridge_jellyfin_provider.library as library_module


class FakeJellyfinClient:
    """Stub for a Jellyfin client session."""

    def __init__(self, *, sections: list[FakeItem], items: dict[str, list[FakeItem]]):
        self._sections = sections
        self._items = items
        self._user_id = "user-1"
        self._user_name = "Demo User"
        self.closed = False

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    def user_id(self) -> str:
        return self._user_id

    def user_name(self) -> str:
        return self._user_name

    def sections(self):
        return tuple(self._sections)

    async def list_section_items(
        self,
        section: FakeItem,
        *,
        min_last_modified: datetime | None = None,
        require_watched: bool = False,
        keys: list[str] | None = None,
    ):
        items = list(self._items.get(section.id, []))
        if min_last_modified is not None:
            items = [
                item
                for item in items
                if _parse_date(item.date_last_saved) >= min_last_modified
            ]
        if require_watched:
            items = [
                item
                for item in items
                if int((item.user_data.play_count if item.user_data else 0) or 0) > 0
            ]
        if keys is not None:
            allowed = set(keys)
            items = [item for item in items if item.id in allowed]
        return tuple(items)

    def list_show_seasons(self, show_id: str):
        return tuple(self._items.get(f"seasons:{show_id}", []))

    def list_show_episodes(self, *, show_id: str, season_id: str | None = None):
        key = f"episodes:{season_id or show_id}"
        return tuple(self._items.get(key, []))

    def get_item(self, item_id: str):
        for items in self._items.values():
            for item in items:
                if item.id == item_id:
                    return item
        raise KeyError(item_id)

    async def fetch_history(self, item: FakeItem):
        if item.type in {"Season", "Series"}:
            episodes = self._items.get("episodes:season-1", [])
            history = [_history_tuple(ep) for ep in episodes]
        else:
            history = [_history_tuple(item)]
        return tuple(entry for entry in history if entry is not None)

    def is_on_continue_watching(self, item: FakeItem) -> bool:
        user_data = item.user_data
        return bool(
            user_data and not user_data.played and user_data.playback_position_ticks
        )

    def is_on_watchlist(self, item: FakeItem) -> bool:
        user_data = item.user_data
        return bool(user_data and user_data.is_favorite)

    def build_image_url(
        self, item_id: str, *, image_type: str = "Primary", tag: str | None = None
    ) -> str:
        return f"http://example.invalid/{item_id}/{image_type}?tag={tag or ''}"

    def clear_cache(self) -> None:
        return None


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _history_tuple(item: FakeItem):
    last_played = item.user_data.last_played_date if item.user_data else None
    if not last_played:
        return None
    return (item.id, _parse_date(last_played))


@dataclass(slots=True)
class FakeUserData:
    """Fake user data payload."""

    played: bool = False
    play_count: int = 0
    rating: float | None = None
    is_favorite: bool = False
    playback_position_ticks: int = 0
    last_played_date: str | None = None


@dataclass(slots=True)
class FakeItem:
    """Fake BaseItemDto-like object."""

    id: str
    name: str
    type: str
    provider_ids: dict[str, str] | None = None
    user_data: FakeUserData | None = None
    date_last_saved: str | None = None
    date_created: str | None = None
    image_tags: dict[str, str] | None = None
    collection_type: str | None = None
    series_id: str | None = None
    season_id: str | None = None
    index_number: int | None = None
    parent_index_number: int | None = None
    genres: list[str] | None = None


@pytest.fixture()
def library_setup(monkeypatch: pytest.MonkeyPatch):
    """Set up a JellyfinLibraryProvider with stubbed dependencies."""
    movie = FakeItem(
        id="movie-1",
        name="Movie One",
        type="Movie",
        provider_ids={"Imdb": "tt123", "Tmdb": "789"},
        user_data=FakeUserData(
            played=True,
            play_count=2,
            rating=8.0,
            is_favorite=True,
            playback_position_ticks=0,
            last_played_date="2025-01-01T12:00:00Z",
        ),
        date_last_saved="2025-01-05T12:00:00Z",
        image_tags={"Primary": "tag"},
    )
    show = FakeItem(
        id="show-1",
        name="Show One",
        type="Series",
        provider_ids={"Tvdb": "55"},
        user_data=FakeUserData(
            played=False,
            play_count=0,
            is_favorite=False,
            playback_position_ticks=123,
        ),
        date_last_saved="2025-01-10T12:00:00Z",
    )
    season = FakeItem(
        id="season-1",
        name="Season 1",
        type="Season",
        series_id="show-1",
        index_number=1,
    )
    episode = FakeItem(
        id="episode-1",
        name="Episode 1",
        type="Episode",
        series_id="show-1",
        season_id="season-1",
        index_number=1,
        parent_index_number=1,
        user_data=FakeUserData(last_played_date="2025-01-11T12:00:00Z"),
    )

    sections = [
        FakeItem(
            id="sec-movies",
            name="Movies",
            type="CollectionFolder",
            collection_type="movies",
        ),
        FakeItem(
            id="sec-shows",
            name="Shows",
            type="CollectionFolder",
            collection_type="tvshows",
        ),
    ]
    items = {
        "sec-movies": [movie],
        "sec-shows": [show],
        "seasons:show-1": [season],
        "episodes:season-1": [episode],
    }

    fake_client = FakeJellyfinClient(sections=sections, items=items)

    monkeypatch.setattr(
        library_module.JellyfinLibraryProvider,
        "_create_client",
        lambda self: fake_client,
    )

    provider = library_module.JellyfinLibraryProvider(
        config={"url": "http://jellyfin", "token": "token", "user": "demo"}
    )
    return provider, fake_client, movie, show


@pytest.mark.asyncio
async def test_get_sections_returns_movie_and_show_sections(library_setup):
    """The provider exposes Jellyfin view sections."""
    provider, _client, *_ = library_setup
    await provider.initialize()
    sections = await provider.get_sections()
    assert len(sections) == 2
    assert [section.title for section in sections] == ["Movies", "Shows"]


@pytest.mark.asyncio
async def test_list_items_supports_common_filters(library_setup):
    """Query filters should trim the dataset as expected."""
    provider, _client, movie, _show = library_setup
    await provider.initialize()
    movie_section = (await provider.get_sections())[0]

    cutoff = datetime.now(UTC) - timedelta(days=1)
    recent = await provider.list_items(movie_section, min_last_modified=cutoff)
    assert len(recent) == 0

    watched_only = await provider.list_items(movie_section, require_watched=True)
    assert [item.key for item in watched_only] == [movie.id]

    subset = await provider.list_items(movie_section, keys=(movie.id,))
    assert [item.key for item in subset] == [movie.id]


@pytest.mark.asyncio
async def test_mapping_descriptors_and_watch_state(library_setup):
    """Mapping descriptors should mirror provider ids, and watch state is surfaced."""
    provider, _client, _movie, _show = library_setup
    await provider.initialize()
    movie_section, show_section = await provider.get_sections()

    movie_item = (await provider.list_items(movie_section))[0]
    show_item = (await provider.list_items(show_section))[0]

    assert movie_item.mapping_descriptors() == (
        ("imdb_movie", "tt123", None),
        ("tmdb_movie", "789", None),
    )
    assert show_item.mapping_descriptors() == (("tvdb_show", "55", None),)
    assert show_item.on_watching is True
    assert movie_item.on_watchlist is True
    assert movie_item.user_rating == 80
    assert movie_item.view_count == 2


@pytest.mark.asyncio
async def test_season_and_episode_mapping_scopes(library_setup):
    """Season and episode entries should scope mappings to the season index."""
    provider, _client, _movie, _show = library_setup
    await provider.initialize()
    _movie_section, show_section = await provider.get_sections()

    show_item = (await provider.list_items(show_section))[0]
    seasons = show_item.seasons()
    assert len(seasons) == 1
    season = seasons[0]
    assert season.index == 1

    descriptors = season.mapping_descriptors()
    assert descriptors == (("tvdb_show", "55", "s1"),)

    episodes = season.episodes()
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.mapping_descriptors() == descriptors


@pytest.mark.asyncio
async def test_history_uses_last_played_timestamp(library_setup):
    """History entries should use Jellyfin's LastPlayedDate data."""
    provider, _client, movie, _show = library_setup
    await provider.initialize()
    movie_section = (await provider.get_sections())[0]
    movie_item = (await provider.list_items(movie_section))[0]

    history = await movie_item.history()
    assert len(history) == 1
    assert history[0].library_key == movie.id
