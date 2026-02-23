"""Jellyfin library provider implementation."""

import base64
from collections.abc import Sequence
from datetime import datetime
from logging import getLogger
from typing import TYPE_CHECKING, cast

import requests
from anibridge.library import (
    HistoryEntry,
    LibraryEntry,
    LibraryEpisode,
    LibraryMedia,
    LibraryMovie,
    LibraryProvider,
    LibrarySeason,
    LibrarySection,
    LibraryShow,
    LibraryUser,
    MediaKind,
    library_provider,
)
from anibridge.library.base import MappingDescriptor

from anibridge_jellyfin_provider.client import JellyfinClient
from anibridge_jellyfin_provider.webhook import (
    JellyfinWebhook,
    JellyfinWebhookNotificationType,
)

# The jellyfin-sdk package uses dynamic imports that cannot be type-checked statically
if TYPE_CHECKING:
    from jellyfin.generated.api_10_11 import BaseItemDto
else:
    from jellyfin.generated import BaseItemDto

if TYPE_CHECKING:
    from starlette.requests import Request

_LOG = getLogger(__name__)

_PROVIDER_ID_MAP = {
    "movie": {
        "anidb": "anidb",
        "anilist": "anilist",
        "imdb": "imdb_movie",
        "tmdb": "tmdb_movie",
        "tvdb": "tvdb_movie",
    },
    "show": {
        "anidb": "anidb",
        "anilist": "anilist",
        "imdb": "imdb_show",
        "tmdb": "tmdb_show",
        "tvdb": "tvdb_show",
    },
}

_STRICT_FETCHER_TO_PROVIDER = {
    "AniDB": "anidb",
    "AniList": "anilist",
    "TheTVDB": "tvdb_show",
    "TheMovieDb": "tmdb_show",
    "IMDb": "imdb_show",
}


class JellyfinLibrarySection(LibrarySection["JellyfinLibraryProvider"]):
    """Concrete `LibrarySection` backed by a Jellyfin view."""

    def __init__(self, provider: JellyfinLibraryProvider, item: BaseItemDto) -> None:
        """Represent a Jellyfin library section.

        Args:
            provider (JellyfinLibraryProvider): The owning provider instance.
            item (BaseItemDto): The raw Jellyfin view payload.
        """
        self._provider = provider
        self._section = item
        self._key = str(item.id)
        self._title = str(item.name)
        collection = (item.collection_type or "").lower()
        self._media_kind = (
            MediaKind.SHOW if collection == "tvshows" else MediaKind.MOVIE
        )


class JellyfinLibraryMedia(LibraryMedia["JellyfinLibraryProvider"]):
    """Base class for Jellyfin media objects (metadata focused)."""

    def __init__(
        self,
        provider: JellyfinLibraryProvider,
        section: JellyfinLibrarySection,
        item: BaseItemDto,
        kind: MediaKind,
    ) -> None:
        """Initialize the media wrapper.

        Args:
            provider (JellyfinLibraryProvider): The owning provider.
            section (JellyfinLibrarySection): The parent library section.
            item (BaseItemDto): The underlying Jellyfin media item.
            kind (MediaKind): The kind of media represented.
        """
        self._provider = provider
        self._section = section
        self._item = item
        self._media_kind = kind
        self._key = str(item.id)
        self._title = str(item.name)

    @property
    def poster_image(self) -> str | None:
        """Return a base64 data URL for the item's poster artwork if available."""
        tags = self._item.image_tags or {}
        tag = tags.get("Primary") if isinstance(tags, dict) else None
        if not tag and isinstance(tags, dict):
            tag = tags.get("primary")
        if not tag:
            return None

        try:
            url = self._provider._client.build_image_url(
                str(self._item.id), tag=str(tag)
            )
            response = requests.get(
                url, headers=self._provider._client.auth_headers(), timeout=3
            )
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "image/jpeg")
            encoded = base64.b64encode(response.content).decode("utf-8")
            return f"data:{content_type};base64,{encoded}"
        except Exception:
            _LOG.debug("Failed to fetch Jellyfin poster", exc_info=True)
            return None

    @property
    def external_url(self) -> str | None:
        """URL to the Jellyfin page, if available."""
        item_id = self._item.id
        if item_id is None:
            return None
        return self._provider._client.build_item_url(str(item_id))


class JellyfinLibraryEntry(LibraryEntry["JellyfinLibraryProvider"]):
    """Common behaviour for Jellyfin-backed library objects."""

    def __init__(
        self,
        provider: JellyfinLibraryProvider,
        section: JellyfinLibrarySection,
        item: BaseItemDto,
        kind: MediaKind,
    ) -> None:
        """Initialize the entry wrapper.

        Args:
            provider (JellyfinLibraryProvider): The owning provider.
            section (JellyfinLibrarySection): The parent library section.
            item (BaseItemDto): The underlying Jellyfin media item.
            kind (MediaKind): The kind of media represented.
        """
        self._provider = provider
        self._section = section
        self._item = item
        self._media_kind = kind
        self._media = JellyfinLibraryMedia(provider, section, item, kind)
        self._key = str(item.id)
        self._title = str(item.name)

    def mapping_descriptors(self) -> Sequence[MappingDescriptor]:
        """Return mapping descriptors for this media item."""
        provider_ids = self._item.provider_ids or {}
        media_key = "show" if self._media_kind == MediaKind.SHOW else "movie"
        mapping = _PROVIDER_ID_MAP.get(media_key, {})
        descriptors: list[MappingDescriptor] = []

        for provider_key, value in provider_ids.items():
            if not value:
                continue
            normalized = str(provider_key).lower()
            mapped = mapping.get(normalized)
            if not mapped:
                continue
            descriptors.append((mapped, str(value), None))

        if self._media_kind == MediaKind.SHOW and self._provider._strict:
            required_provider = self._provider._strict_show_provider_by_section.get(
                self._section.key
            )
            if not required_provider:
                return ()
            descriptors = [
                descriptor
                for descriptor in descriptors
                if descriptor[0] == required_provider
            ]

        return tuple(descriptors)

    @property
    def on_watching(self) -> bool:
        """Check if the media item is on the user's current watching list."""
        return self._provider.is_on_continue_watching(self._item)

    @property
    def on_watchlist(self) -> bool:
        """Check if the media item is on the user's watchlist."""
        return self._provider.is_on_watchlist(self._item)

    @property
    def user_rating(self) -> int | None:
        """Return the user rating for this media item on a 0-100 scale."""
        user_data = self._item.user_data
        rating = user_data.rating if user_data else None
        if rating is None:
            return None
        try:
            return round(float(rating) * 10)
        except TypeError, ValueError:
            return None

    @property
    def view_count(self) -> int:
        """Return the number of times this media item has been viewed."""
        user_data = self._item.user_data
        try:
            return int((user_data.play_count if user_data else 0) or 0)
        except TypeError, ValueError:
            return 0

    async def history(self) -> Sequence[HistoryEntry]:
        """Fetch the viewing history for this media item."""
        entries = await self._provider.get_history(self._item)
        return entries

    def media(self) -> JellyfinLibraryMedia:
        """Return the media metadata for this item."""
        return self._media

    @property
    async def review(self) -> str | None:
        """Return the user's review text for this item, if any."""
        return None

    def section(self) -> JellyfinLibrarySection:
        """Return the library section this media item belongs to."""
        return self._section


class JellyfinLibraryMovie(
    JellyfinLibraryEntry, LibraryMovie["JellyfinLibraryProvider"]
):
    """Concrete `LibraryMovie` wrapper for Jellyfin movie objects."""

    def __init__(
        self,
        provider: JellyfinLibraryProvider,
        section: JellyfinLibrarySection,
        item: BaseItemDto,
    ) -> None:
        """Initialize the movie wrapper."""
        super().__init__(provider, section, item, MediaKind.MOVIE)

    def mapping_descriptors(self) -> Sequence[MappingDescriptor]:
        """Return mapping descriptors for this movie, with no scope."""
        descriptors: list[MappingDescriptor] = []
        for descriptor in super().mapping_descriptors():
            if descriptor[0] == "anidb":
                # The anidb plugin will always use the "REGULAR" scope for movies
                descriptors.append((descriptor[0], descriptor[1], "R"))
            else:
                descriptors.append(descriptor)
        return tuple(descriptors)


class JellyfinLibraryShow(JellyfinLibraryEntry, LibraryShow["JellyfinLibraryProvider"]):
    """Concrete `LibraryShow` wrapper for Jellyfin series objects."""

    def __init__(
        self,
        provider: JellyfinLibraryProvider,
        section: JellyfinLibrarySection,
        item: BaseItemDto,
    ) -> None:
        """Initialize the show wrapper."""
        super().__init__(provider, section, item, MediaKind.SHOW)

    def episodes(self) -> Sequence[JellyfinLibraryEpisode]:
        """Return all episodes belonging to the show."""
        if self._item.id is None:
            return ()
        episodes = self._provider._client.list_show_episodes(
            show_id=self._item.id,
        )
        return tuple(
            JellyfinLibraryEpisode(self._provider, self._section, episode)
            for episode in episodes
        )

    def seasons(self) -> Sequence[JellyfinLibrarySeason]:
        """Return all seasons belonging to the show."""
        if self._item.id is None:
            return ()
        seasons = self._provider._client.list_show_seasons(
            show_id=self._item.id,
        )
        return tuple(
            JellyfinLibrarySeason(self._provider, self._section, season, show=self)
            for season in seasons
        )


class JellyfinLibrarySeason(
    JellyfinLibraryEntry, LibrarySeason["JellyfinLibraryProvider"]
):
    """Concrete `LibrarySeason` wrapper for Jellyfin season objects."""

    def __init__(
        self,
        provider: JellyfinLibraryProvider,
        section: JellyfinLibrarySection,
        item: BaseItemDto,
        *,
        show: JellyfinLibraryShow | None = None,
    ) -> None:
        """Initialize the season wrapper."""
        super().__init__(provider, section, item, MediaKind.SEASON)
        self._show = show
        self.index = int(item.index_number or 0)

    def episodes(self) -> Sequence[JellyfinLibraryEpisode]:
        """Return the episodes belonging to this season."""
        if self._item.series_id is None or self._item.id is None:
            return ()
        episodes = self._provider._client.list_show_episodes(
            show_id=self._item.series_id,
            season_id=self._item.id,
        )
        return tuple(
            JellyfinLibraryEpisode(
                self._provider, self._section, episode, season=self, show=self._show
            )
            for episode in episodes
        )

    def show(self) -> LibraryShow:
        """Return the parent show."""
        if self._show is not None:
            return self._show
        if self._item.series_id is None:
            raise RuntimeError("Season is missing SeriesId")
        show_id = self._item.series_id
        raw_show = self._provider._client.get_item(show_id)
        self._show = JellyfinLibraryShow(self._provider, self._section, raw_show)
        return self._show

    def mapping_descriptors(self) -> Sequence[MappingDescriptor]:
        """Return mapping descriptors with season scopes applied."""
        descriptors: list[MappingDescriptor] = []
        for provider, entry_id, _ in self.show().mapping_descriptors():
            scope: str | None = f"s{self.index}"
            if provider == "anilist":
                scope = None
            elif provider == "anidb":
                # The anidb plugin maps the "SPECIAL" scope to season 0. It does not
                # support anything besides "SPECIAL" and "REGULAR" scopes
                scope = "S" if self.index == 0 else "R"
            descriptors.append((provider, entry_id, scope))
        return tuple(descriptors)


class JellyfinLibraryEpisode(
    JellyfinLibraryEntry, LibraryEpisode["JellyfinLibraryProvider"]
):
    """Concrete `LibraryEpisode` wrapper for Jellyfin episode objects."""

    def __init__(
        self,
        provider: JellyfinLibraryProvider,
        section: JellyfinLibrarySection,
        item: BaseItemDto,
        *,
        season: JellyfinLibrarySeason | None = None,
        show: JellyfinLibraryShow | None = None,
    ) -> None:
        """Initialize the episode wrapper."""
        super().__init__(provider, section, item, MediaKind.EPISODE)
        self._season = season
        self._show = show
        self.index = int(item.index_number or 0)
        self.season_index = int(item.parent_index_number or 0)

    def season(self) -> LibrarySeason:
        """Return the parent season."""
        if self._season is not None:
            return self._season
        if self._item.season_id is None:
            raise RuntimeError("Episode is missing SeasonId")
        season_id = self._item.season_id
        raw_season = self._provider._client.get_item(season_id)
        self._season = JellyfinLibrarySeason(
            self._provider,
            self._section,
            raw_season,
            show=cast(JellyfinLibraryShow, self.show()),
        )
        return self._season

    def show(self) -> LibraryShow:
        """Return the parent show."""
        if self._show is not None:
            return self._show
        if self._item.series_id is None:
            raise RuntimeError("Episode is missing SeriesId")
        show_id = self._item.series_id
        raw_show = self._provider._client.get_item(show_id)
        self._show = JellyfinLibraryShow(self._provider, self._section, raw_show)
        return self._show

    def mapping_descriptors(self) -> Sequence[MappingDescriptor]:
        """Return mapping descriptors with season scopes applied."""
        return self.season().mapping_descriptors()


@library_provider
class JellyfinLibraryProvider(LibraryProvider):
    """Default Jellyfin `LibraryProvider` backed by a Jellyfin server."""

    NAMESPACE = "jellyfin"

    def __init__(self, *, config: dict | None = None) -> None:
        """Parse configuration and prepare provider defaults."""
        self.config = config or {}

        url = self.config.get("url") or ""
        token = self.config.get("token") or ""
        user = self.config.get("user") or ""
        if not url or not token or not user:
            raise ValueError(
                "The Jellyfin provider requires 'url', 'token', and 'user' "
                "configuration values"
            )

        self._client_url = str(url)
        self._client_token = str(token)
        self._client_user = str(user)
        self._section_filter = list(self.config.get("sections") or [])
        self._genre_filter = list(self.config.get("genres") or [])
        self._strict = bool(self.config.get("strict") or True)
        self._client = self._create_client()
        self._user: LibraryUser | None = None

        self._sections: list[JellyfinLibrarySection] = []
        self._section_map: dict[str, JellyfinLibrarySection] = {}
        self._strict_show_provider_by_section: dict[str, str] = {}

    async def initialize(self) -> None:
        """Connect to Jellyfin and prepare provider state."""
        await self._client.initialize()
        self._user = LibraryUser(
            key=self._client.user_id(), title=self._client.user_name()
        )
        self._sections = self._build_sections()
        self._strict_show_provider_by_section.clear()
        if self._strict:
            for section in self._sections:
                if section.media_kind != MediaKind.SHOW:
                    continue
                metadata_fetcher = self._client.show_metadata_fetcher_for_section(
                    section.key
                )
                if not metadata_fetcher:
                    continue
                if provider := _STRICT_FETCHER_TO_PROVIDER.get(metadata_fetcher):
                    self._strict_show_provider_by_section[section.key] = provider
        await self.clear_cache()

    async def close(self) -> None:
        """Release any resources held by the provider."""
        await self._client.close()
        self._sections.clear()
        self._section_map.clear()
        self._strict_show_provider_by_section.clear()

    def user(self) -> LibraryUser | None:
        """Return the Jellyfin user represented by this provider."""
        return self._user

    async def get_sections(self) -> Sequence[LibrarySection]:
        """Enumerate Jellyfin library sections visible to the provider user."""
        return tuple(self._sections)

    async def list_items(
        self,
        section: LibrarySection,
        *,
        min_last_modified: datetime | None = None,
        require_watched: bool = False,
        keys: Sequence[str] | None = None,
    ) -> Sequence[LibraryEntry]:
        """List items in a Jellyfin library section matching the provided criteria."""
        if not isinstance(section, JellyfinLibrarySection):
            raise TypeError(
                "Jellyfin providers expect section objects created by the provider"
            )

        raw_items = await self._client.list_section_items(
            section._section,
            min_last_modified=min_last_modified,
            require_watched=require_watched,
            keys=keys,
        )
        return tuple(self._wrap_entry(section, item) for item in raw_items)

    async def parse_webhook(self, request: Request) -> tuple[bool, Sequence[str]]:
        """Parse a Jellyfin webhook request and determine affected media items."""
        payload = await JellyfinWebhook.from_request(request)

        if not payload.notification_type:
            _LOG.debug("Webhook: No notification type found in payload")
            raise ValueError("No notification type found in webhook payload")

        if not payload.top_level_item_id:
            _LOG.debug("Webhook: No item ID found in payload")
            raise ValueError("No item ID found in webhook payload")

        sync_events = {
            JellyfinWebhookNotificationType.ITEM_ADDED,
            JellyfinWebhookNotificationType.PLAYBACK_STOP,
            JellyfinWebhookNotificationType.USER_DATA_SAVED,
        }

        try:
            notification_type = JellyfinWebhookNotificationType(
                payload.notification_type
            )
        except ValueError:
            _LOG.debug(
                "Webhook: Ignoring unsupported event type %s",
                payload.notification_type,
            )
            return (False, tuple())

        if notification_type not in sync_events:
            _LOG.debug("Webhook: Ignoring event type %s", notification_type)
            return (False, tuple())

        if notification_type != JellyfinWebhookNotificationType.ITEM_ADDED:
            if not self._user:
                _LOG.debug("Webhook: Provider user has not been initialized")
                return (False, tuple())

            user_id_match = (
                payload.user_id and payload.user_id.lower() == self._user.key.lower()
            )
            user_name_match = (
                payload.username
                and self._user.title
                and payload.username.lower() == self._user.title.lower()
            )
            if not (user_id_match or user_name_match):
                _LOG.debug(
                    "Webhook: Ignoring event %s for user ID %s",
                    notification_type,
                    payload.user_id,
                )
                return (False, tuple())

        _LOG.info(
            "Webhook: Matched webhook event %s for sync key %s",
            notification_type,
            payload.top_level_item_id,
        )
        return (True, (payload.top_level_item_id,))

    async def clear_cache(self) -> None:
        """Reset any cached Jellyfin responses maintained by the provider."""
        self._client.clear_cache()

    def is_on_continue_watching(self, item: BaseItemDto) -> bool:
        """Determine whether the given item appears in Continue Watching."""
        return self._client.is_on_continue_watching(item)

    def is_on_watchlist(self, item: BaseItemDto) -> bool:
        """Determine whether the given item appears in the user's favorites list."""
        return self._client.is_on_watchlist(item)

    async def get_history(self, item: BaseItemDto) -> Sequence[HistoryEntry]:
        """Return the watch history for the given Jellyfin item."""
        history = await self._client.fetch_history(item)
        return tuple(
            HistoryEntry(library_key=entry_id, viewed_at=timestamp)
            for entry_id, timestamp in history
        )

    def _build_sections(self) -> list[JellyfinLibrarySection]:
        """Construct the list of Jellyfin library sections available to the user."""
        sections: list[JellyfinLibrarySection] = []
        self._section_map.clear()

        for raw in self._client.sections():
            wrapper = JellyfinLibrarySection(self, raw)
            self._section_map[wrapper.key] = wrapper
            sections.append(wrapper)
        return sections

    def _wrap_entry(
        self, section: JellyfinLibrarySection, item: BaseItemDto
    ) -> LibraryEntry:
        """Wrap a Jellyfin item in the appropriate library entry class."""
        item_type = item.type
        if item_type == "Episode":
            return JellyfinLibraryEpisode(self, section, item)
        if item_type == "Season":
            return JellyfinLibrarySeason(self, section, item)
        if item_type == "Series":
            return JellyfinLibraryShow(self, section, item)
        if item_type == "Movie":
            return JellyfinLibraryMovie(self, section, item)
        raise TypeError(f"Unsupported Jellyfin media type: {item_type!r}")

    def _create_client(self) -> JellyfinClient:
        """Construct and return a Jellyfin client for this provider."""
        return JellyfinClient(
            url=self._client_url,
            token=self._client_token,
            user=self._client_user,
            section_filter=self._section_filter,
            genre_filter=self._genre_filter,
        )
