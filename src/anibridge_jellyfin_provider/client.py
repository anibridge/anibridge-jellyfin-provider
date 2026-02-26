"""Jellyfin client abstractions consumed by the library provider."""

import asyncio
import importlib.metadata
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode
from uuid import UUID

from anibridge.library import ProviderLogger

# The jellyfin-sdk package uses dynamic imports that cannot be type-checked statically
if TYPE_CHECKING:
    from jellyfin.generated.api_10_11 import (
        ApiClient,
        BaseItemDto,
        BaseItemKind,
        CollectionType,
        CollectionTypeOptions,
        Configuration,
        ItemFields,
        ItemsApi,
        LibraryStructureApi,
        TvShowsApi,
        UserApi,
        UserDto,
        UserItemDataDto,
        UserLibraryApi,
        UserViewsApi,
    )
else:
    from jellyfin.generated import (
        ApiClient,
        BaseItemDto,
        BaseItemKind,
        CollectionType,
        CollectionTypeOptions,
        Configuration,
        ItemFields,
        ItemsApi,
        LibraryStructureApi,
        TvShowsApi,
        UserApi,
        UserDto,
        UserItemDataDto,
        UserLibraryApi,
        UserViewsApi,
    )


__all__ = ["JellyfinClient"]


class JellyfinClient:
    """High-level Jellyfin client wrapper used by the library provider."""

    ITEM_FIELDS: ClassVar[tuple[ItemFields, ...]] = (
        ItemFields.PATH,
        ItemFields.GENRES,
        ItemFields.SORTNAME,
        ItemFields.TAGLINES,
        ItemFields.DATECREATED,
        ItemFields.DATELASTSAVED,
        ItemFields.OVERVIEW,
        ItemFields.PROVIDERIDS,
        ItemFields.PARENTID,
    )

    def __init__(
        self,
        *,
        logger: ProviderLogger,
        url: str,
        token: str,
        user: str,
        section_filter: Sequence[str] | None = None,
        genre_filter: Sequence[str] | None = None,
    ) -> None:
        """Initialize the session wrapper.

        Args:
            logger (ProviderLogger): Injected provider logger.
            url (str): Base Jellyfin server URL.
            token (str): Jellyfin API token.
            user (str): Jellyfin user name or id.
            section_filter (Sequence[str] | None): If provided, only sections whose
                names are in this list (case-insensitive) are included.
            genre_filter (Sequence[str] | None): If provided, only items matching one
                of these genres are included.
        """
        self.log = logger
        self._url = url
        self._token = token
        self._user = user
        self._section_filter = {value.lower() for value in section_filter or ()}
        self._genre_filter = {value.lower() for value in genre_filter or ()}

        self._api_client: ApiClient | None = None
        self._items_api: ItemsApi | None = None
        self._user_api: UserApi | None = None
        self._user_library_api: UserLibraryApi | None = None
        self._user_views_api: UserViewsApi | None = None
        self._library_structure_api: LibraryStructureApi | None = None
        self._tv_shows_api: TvShowsApi | None = None
        self._user_id: UUID | None = None
        self._user_name: str | None = None
        self._base_url = url.rstrip("/")
        self._sections: list[BaseItemDto] = []
        self._show_metadata_fetcher_by_section_id: dict[str, str] = {}

    async def initialize(self) -> None:
        """Authenticate and populate server metadata."""
        await asyncio.to_thread(self._configure_client)
        user = await asyncio.to_thread(self._resolve_user)

        self._user_id = user.id
        self._user_name = user.name or str(user.id)
        self._sections = await asyncio.to_thread(self._load_sections)
        self._show_metadata_fetcher_by_section_id = await asyncio.to_thread(
            self._load_show_metadata_fetchers
        )

    async def close(self) -> None:
        """Release any held resources."""
        self._api_client = None
        self._items_api = None
        self._user_api = None
        self._user_library_api = None
        self._user_views_api = None
        self._library_structure_api = None
        self._tv_shows_api = None
        self._user_id = None
        self._user_name = None
        self._sections.clear()
        self._show_metadata_fetcher_by_section_id.clear()

    def user_id(self) -> str:
        """Return the Jellyfin user id for the session."""
        if self._user_id is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        return str(self._user_id)

    def user_name(self) -> str:
        """Return the Jellyfin user display name for the session."""
        if self._user_id is None or self._user_name is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        return self._user_name

    def auth_headers(self) -> dict[str, str]:
        """Return request headers for authenticated Jellyfin calls."""
        return {"X-Emby-Token": self._token}

    def sections(self) -> Sequence[BaseItemDto]:
        """Return the cached Jellyfin library sections."""
        return tuple(self._sections)

    def show_metadata_fetcher_for_section(self, section_id: str) -> str | None:
        """Return the top-priority TV metadata fetcher for a section if known."""
        return self._show_metadata_fetcher_by_section_id.get(section_id)

    async def list_section_items(
        self,
        section: BaseItemDto,
        *,
        min_last_modified: datetime | None = None,
        require_watched: bool = False,
        keys: Sequence[str] | None = None,
    ) -> Sequence[BaseItemDto]:
        """Return Jellyfin items for the provided section with filtering applied."""
        items = await asyncio.to_thread(
            self._fetch_section_items,
            section,
            min_last_modified=min_last_modified,
            require_watched=require_watched,
            keys=keys,
        )
        filtered = list(items)

        if require_watched:
            filtered = [
                item
                for item in filtered
                if self._item_has_user_activity(
                    item,
                    section_collection_type=section.collection_type,
                )
            ]

        if keys is not None:
            allowed = set(keys)
            filtered = [item for item in filtered if item.id in allowed]

        return tuple(filtered)

    def list_show_seasons(self, show_id: UUID) -> Sequence[BaseItemDto]:
        """Return the seasons for a Jellyfin show."""
        if self._items_api is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        if self._user_id is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        items_api = self._items_api
        response = items_api.get_items(
            user_id=self._user_id,
            parent_id=show_id,
            include_item_types=[BaseItemKind.SEASON],
            recursive=True,
            fields=list(self.ITEM_FIELDS),
            enable_user_data=True,
            enable_images=True,
        )
        return tuple(response.items or []) if response else ()

    def list_show_episodes(
        self, *, show_id: UUID, season_id: UUID | None = None
    ) -> Sequence[BaseItemDto]:
        """Return the episodes for a Jellyfin show."""
        if self._items_api is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        if self._user_id is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        items_api = self._items_api
        response = items_api.get_items(
            user_id=self._user_id,
            parent_id=season_id or show_id,
            include_item_types=[BaseItemKind.EPISODE],
            recursive=True,
            fields=list(self.ITEM_FIELDS),
            enable_user_data=True,
            enable_images=True,
        )
        return tuple(response.items or []) if response else ()

    def get_item(self, item_id: UUID) -> BaseItemDto:
        """Fetch metadata for a single Jellyfin item."""
        if self._user_library_api is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        if self._user_id is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        return self._user_library_api.get_item(item_id, user_id=self._user_id)

    async def fetch_history(self, item: BaseItemDto) -> Sequence[tuple[str, datetime]]:
        """Return play history tuples for an item (item id, played timestamp)."""
        if item.id is None:
            return ()

        if item.type in {BaseItemKind.SEASON, BaseItemKind.SERIES}:
            episodes = self.list_show_episodes(
                show_id=item.id,
                season_id=item.id if item.type == BaseItemKind.SEASON else None,
            )
            history = []
            for episode in episodes:
                if not episode.id:
                    continue
                last_played = self._normalize_local_datetime(
                    episode.user_data.last_played_date if episode.user_data else None
                )
                if last_played is None:
                    continue
                history.append((str(episode.id), last_played))
        else:
            last_played = self._normalize_local_datetime(
                item.user_data.last_played_date if item.user_data else None
            )
            history = [(str(item.id), last_played)] if last_played is not None else []

        return tuple(history)

    def is_on_continue_watching(self, item: BaseItemDto) -> bool:
        """Determine whether the item appears in Jellyfin's Next Up deck."""
        if self._tv_shows_api is None or self._user_id is None:
            raise RuntimeError("Jellyfin client has not been initialized")

        series_id: UUID | None = None
        if item.type == BaseItemKind.SERIES:
            series_id = item.id
        elif item.type in {BaseItemKind.SEASON, BaseItemKind.EPISODE}:
            series_id = item.series_id

        if series_id is None:
            return False

        try:
            response = self._tv_shows_api.get_next_up(
                user_id=self._user_id,
                series_id=series_id,
                limit=1,
                enable_user_data=False,
            )
            return bool(response and response.items)
        except TypeError, ValueError:
            return False

    def is_on_watchlist(self, item: BaseItemDto) -> bool:
        """Determine whether the item is on the user's favorites list."""
        user_data = item.user_data
        return bool(user_data.is_favorite if user_data else False)

    def build_image_url(
        self, item_id: str, *, image_type: str = "Primary", tag: str | None = None
    ) -> str:
        """Construct an image URL."""
        base_url = self._base_url
        params = {
            "maxHeight": 400,
            "maxWidth": 300,
            "quality": 90,
            "api_key": self._token,
        }
        if tag:
            params["tag"] = tag
        return f"{base_url}/Items/{item_id}/Images/{image_type}?{urlencode(params)}"

    def build_item_url(self, item_id: str) -> str:
        """Construct a Jellyfin web URL for an item details page."""
        params = urlencode({"id": item_id})
        return f"{self._base_url}/web/#/details?{params}"

    def clear_cache(self) -> None:
        """Clear cached metadata (no-op for Jellyfin)."""
        return None

    def _configure_client(self) -> None:
        configuration = Configuration(host=self._base_url)
        configuration.api_key["CustomAuthentication"] = f'Token="{self._token}"'
        configuration.api_key_prefix["CustomAuthentication"] = "MediaBrowser"
        configuration.user_agent = (
            importlib.metadata.metadata("anibridge-jellyfin-provider").get(
                "Name", "anibridge-jellyfin-provider"
            )
            + "/"
            + importlib.metadata.version("anibridge-jellyfin-provider")
        )
        self._api_client = ApiClient(configuration)
        self._items_api = ItemsApi(self._api_client)
        self._user_api = UserApi(self._api_client)
        self._user_library_api = UserLibraryApi(self._api_client)
        self._user_views_api = UserViewsApi(self._api_client)
        self._library_structure_api = LibraryStructureApi(self._api_client)
        self._tv_shows_api = TvShowsApi(self._api_client)

    def _resolve_user(self) -> UserDto:
        if self._user_api is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        users = self._user_api.get_users() or []
        target = self._user.strip()
        if not target:
            raise ValueError("Jellyfin provider requires a non-empty user value")

        for user in users:
            if str(user.id or "").lower() == target.lower():
                return user
            if str(user.name or "").lower() == target.lower():
                return user

        raise ValueError(f"Unable to locate Jellyfin user: {self._user}")

    def _load_sections(self) -> list[BaseItemDto]:
        if self._user_views_api is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        if self._user_id is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        response = self._user_views_api.get_user_views(user_id=self._user_id)
        items = list(response.items or []) if response else []

        sections: list[BaseItemDto] = []
        for item in items:
            if item.collection_type not in {
                CollectionType.MOVIES,
                CollectionType.TVSHOWS,
            }:
                continue
            if (
                self._section_filter
                and (item.name or "").lower() not in self._section_filter
            ):
                continue
            sections.append(item)
        return sections

    def _fetch_section_items(
        self,
        section: BaseItemDto,
        *,
        min_last_modified: datetime | None = None,
        require_watched: bool = False,
        keys: Sequence[str] | None = None,
    ) -> list[BaseItemDto]:
        include_types = (
            [BaseItemKind.MOVIE]
            if section.collection_type == CollectionType.MOVIES
            else [BaseItemKind.SERIES]
        )
        if self._items_api is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        if self._user_id is None:
            raise RuntimeError("Jellyfin client has not been initialized")
        ids: list[UUID] | None = None
        if keys:
            parsed_ids: list[UUID] = []
            for key in keys:
                try:
                    parsed_ids.append(UUID(str(key)))
                except TypeError, ValueError:
                    self.log.warning("Invalid item id in keys filter: %s", key)
            if parsed_ids:
                ids = parsed_ids

        response = self._items_api.get_items(
            user_id=self._user_id,
            parent_id=section.id,
            include_item_types=include_types,
            recursive=True,
            fields=list(self.ITEM_FIELDS),
            enable_user_data=True,
            enable_images=True,
            min_date_last_saved=min_last_modified,
            genres=list(self._genre_filter) if self._genre_filter else None,
            ids=ids,
        )
        items: list[BaseItemDto] = list(response.items or []) if response else []

        if not self._genre_filter:
            return items

        return [
            item
            for item in items
            if any(genre.lower() in self._genre_filter for genre in (item.genres or []))
        ]

    def _load_show_metadata_fetchers(self) -> dict[str, str]:
        """Get the top-priority TV metadata fetcher for each section if known."""
        if self._library_structure_api is None:
            raise RuntimeError("Jellyfin client has not been initialized")

        section_metadata_fetchers: dict[str, str] = {}
        virtual_folders = self._library_structure_api.get_virtual_folders() or []
        for folder in virtual_folders:
            # For whatever reason, the API returns this as a string instead of a UUID
            section_id = str(UUID(str(folder.item_id or "")))

            if folder.collection_type != CollectionTypeOptions.TVSHOWS:
                continue

            library_options = folder.library_options
            type_options = library_options.type_options if library_options else None
            if not type_options:
                continue

            metadata_fetcher: str | None = None
            for option in type_options:
                if option.type != BaseItemKind.SERIES:
                    continue

                ordered_fetchers = option.metadata_fetcher_order or []
                enabled_fetchers = option.metadata_fetchers
                enabled_set = set(enabled_fetchers) if enabled_fetchers else None

                if ordered_fetchers:
                    for fetcher in ordered_fetchers:
                        if not fetcher:
                            continue
                        if enabled_set is not None and fetcher not in enabled_set:
                            continue
                        metadata_fetcher = fetcher
                        break
                else:
                    for fetcher in enabled_fetchers or []:
                        if fetcher:
                            metadata_fetcher = fetcher
                            break

                if metadata_fetcher:
                    break

            if metadata_fetcher:
                section_metadata_fetchers[section_id] = metadata_fetcher

        return section_metadata_fetchers

    def _item_has_user_activity(
        self, item: BaseItemDto, *, section_collection_type: CollectionType | None
    ) -> bool:
        """Return true if item has user activity (played, partial, favorite)."""
        if self._has_user_activity(item.user_data):
            return True

        if (
            section_collection_type != CollectionType.TVSHOWS
            or item.type != BaseItemKind.SERIES
            or item.id is None
        ):
            return False

        try:
            episodes = self.list_show_episodes(show_id=item.id)
        except Exception:
            self.log.exception(
                "Failed to load episodes while checking user activity for show %s",
                item.id,
            )
            return False

        return any(self._has_user_activity(e.user_data) for e in episodes)

    @staticmethod
    def _has_user_activity(user_data: UserItemDataDto | None) -> bool:
        """Return true when user data indicates any relevant user activity."""
        if user_data is None:
            return False
        return bool(
            user_data.played
            or user_data.play_count
            or user_data.playback_position_ticks
            or user_data.is_favorite
        )

    @staticmethod
    def _normalize_local_datetime(value: datetime | None) -> datetime | None:
        """Return a timezone-aware datetime."""
        if value is None:
            return value
        local_tz = datetime.now().astimezone().tzinfo or UTC
        if value.tzinfo is None:
            return value.replace(tzinfo=local_tz)
        return value.astimezone(local_tz)
