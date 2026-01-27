"""Example list provider using in-memory fixtures as a demo."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from anibridge.list import (
    ListEntry,
    ListMedia,
    ListMediaType,
    ListProvider,
    ListStatus,
    ListTarget,
    ListUser,
    MappingDescriptor,
    list_provider,
)


class ExampleListMedia(ListMedia["ExampleListProvider"]):
    """Basic memory-based ``ListMedia`` implementation."""

    def __init__(
        self,
        key: str,
        title: str,
        media_type: ListMediaType,
        _provider: ExampleListProvider,
        _poster_image: str | None = None,
        _total_units: int | None = None,
    ) -> None:
        """Initialize the ExampleListMedia instance."""
        self._key = key
        self._title = title
        self._media_type = media_type
        self._provider = _provider
        self._poster_image = _poster_image
        self._total_units = _total_units

    @property
    def media_type(self) -> ListMediaType:
        """Return the media type of the media."""
        return self._media_type

    def provider(self) -> ExampleListProvider:
        """Return the provider that created the media instance."""
        return self._provider

    @property
    def poster_image(self) -> str | None:
        """Return a poster URL if the provider has one."""
        return self._poster_image

    @property
    def total_units(self) -> int | None:
        """Return the recorded episode count for the media."""
        return self._total_units


class ExampleListEntry(ListEntry["ExampleListProvider"]):
    """Basic memory-based ``ListEntry`` implementation."""

    def __init__(
        self,
        key: str,
        title: str,
        _provider: ExampleListProvider,
        _media: ExampleListMedia,
        _progress: int | None = None,
        _repeats: int | None = None,
        _review: str | None = None,
        _status: ListStatus | None = None,
        _user_rating: int | None = None,
        _started_at: datetime | None = None,
        _finished_at: datetime | None = None,
    ) -> None:
        """Initialize the ExampleListEntry instance."""
        self._key = key
        self._title = title
        self._provider = _provider
        self._media = _media
        self._progress = _progress
        self._repeats = _repeats
        self._review = _review
        self._status = _status
        self._user_rating = _user_rating
        self._started_at = _started_at
        self._finished_at = _finished_at

    def provider(self) -> ExampleListProvider:
        """Return the provider that owns the entry."""
        return self._provider

    @property
    def progress(self) -> int | None:
        """Return the tracked progress."""
        return self._progress

    @progress.setter
    def progress(self, value: int | None) -> None:
        """Update the tracked progress."""
        self._progress = value

    @property
    def repeats(self) -> int | None:
        """Return the number of repeats."""
        return self._repeats

    @repeats.setter
    def repeats(self, value: int | None) -> None:
        """Update the repeat count."""
        self._repeats = value

    @property
    def review(self) -> str | None:
        """Return the stored review text."""
        return self._review

    @review.setter
    def review(self, value: str | None) -> None:
        """Update the review text."""
        self._review = value

    @property
    def status(self) -> ListStatus | None:
        """Return the current list status."""
        return self._status

    @status.setter
    def status(self, value: ListStatus | None) -> None:
        """Update the list status."""
        self._status = value

    @property
    def user_rating(self) -> int | None:
        """Return the normalized rating."""
        return self._user_rating

    @user_rating.setter
    def user_rating(self, value: int | None) -> None:
        """Update the rating."""
        self._user_rating = value

    @property
    def started_at(self) -> datetime | None:
        """Return when the user started the entry."""
        return self._started_at

    @started_at.setter
    def started_at(self, value: datetime | None) -> None:
        """Update the start timestamp."""
        self._started_at = value

    @property
    def finished_at(self) -> datetime | None:
        """Return when the user first finished the entry."""
        return self._finished_at

    @finished_at.setter
    def finished_at(self, value: datetime | None) -> None:
        """Update the finish timestamp."""
        self._finished_at = value

    @property
    def total_units(self) -> int | None:
        """Mirror the total units from the media object."""
        return self._media.total_units

    def media(self) -> ExampleListMedia:
        """Return the media associated with the entry."""
        return self._media


@list_provider
class ExampleListProvider(ListProvider):
    """Simple provider that stores two entries in memory."""

    NAMESPACE = "example-list"
    MAPPING_PROVIDERS = frozenset({NAMESPACE})

    def __init__(self, *, config: dict | None = None) -> None:
        """Construct the provider and seed its demo entries."""
        self._config = config or {}
        self._user = ListUser(
            key=self._config.get("user_key", "demo-user"),
            title=self._config.get("user_title", "Demo List User"),
        )
        self._entries: dict[str, ListEntry] = {}
        self._build_example_entries()

    async def backup_list(self) -> str:
        """Serialize all entries into a JSON blob."""
        payload = {
            "user": self._user.key,
            "entries": [self._encode_entry(entry) for entry in self._entries.values()],
        }
        return json.dumps(payload, separators=(",", ":"))

    async def build_entry(self, key: str) -> ListEntry[ExampleListProvider]:
        """Return an entry ready for creation, building media on the fly."""
        media = ExampleListMedia(
            key=key,
            title=self._config.get("default_title", key.replace("-", " ").title()),
            media_type=ListMediaType.TV,
            _provider=self,
        )
        return ExampleListEntry(
            key=key,
            title=media.title,
            _provider=self,
            _media=media,
        )

    async def delete_entry(self, key: str) -> None:
        """Delete the entry if it exists."""
        self._entries.pop(key, None)

    async def get_entry(self, key: str) -> ListEntry[ExampleListProvider] | None:
        """Return a stored entry by its media key."""
        return self._entries.get(key)

    async def resolve_mapping_descriptors(
        self, descriptors: Sequence[MappingDescriptor]
    ) -> Sequence[ListTarget]:
        """Resolve mapping descriptors into local media keys.

        The example implementation only resolves descriptors that target this
        provider namespace and already exist in memory.
        """
        resolved: list[ListTarget] = []
        for descriptor in descriptors:
            provider, entry_id, _scope = descriptor
            if provider != self.NAMESPACE:
                continue
            if entry_id not in self._entries:
                continue
            resolved.append(ListTarget(descriptor=descriptor, media_key=entry_id))
        return tuple(resolved)

    async def restore_list(self, backup: str) -> None:
        """Optionally deserialize and restore serialized backup entries."""
        raise NotImplementedError("List restore not implemented for this provider.")

    async def search(self, query: str) -> Sequence[ListEntry[ExampleListProvider]]:
        """Return entries whose titles contain the substring query."""
        needle = query.lower()
        results = [
            entry for entry in self._entries.values() if needle in entry.title.lower()
        ]
        return tuple(results)

    async def update_entry(
        self, key: str, entry: ListEntry
    ) -> ListEntry[ExampleListProvider] | None:
        """Store the provided entry and return it."""
        self._entries[key] = entry
        return entry

    ###########################################################################
    ### Anything beyond this point does not implement required API methods. ###
    ###########################################################################

    async def clear_cache(self) -> None:
        """The provider is cache-less, so nothing needs to happen here."""
        return None

    async def close(self) -> None:
        """Release resources; there are none for the example provider."""
        return None

    async def initialize(self) -> None:
        """No-op initialize hook for the in-memory provider."""
        return None

    def user(self) -> ListUser | None:
        """Return the static user descriptor."""
        return self._user

    def _encode_entry(self, entry: ListEntry[ExampleListProvider]) -> dict[str, Any]:
        """Return a JSON-serializable dictionary for the entry."""
        return {
            "key": entry.key,
            "title": entry.title,
            "status": entry.status.value if entry.status else None,
            "progress": entry.progress,
            "repeats": entry.repeats,
            "review": entry.review,
            "user_rating": entry.user_rating,
            "started_at": entry.started_at.isoformat() if entry.started_at else None,
            "finished_at": entry.finished_at.isoformat() if entry.finished_at else None,
            "media_type": entry.media().media_type.value,
            "total_units": entry.media().total_units,
        }

    def _decode_entry(self, data: dict[str, Any]) -> ListEntry[ExampleListProvider]:
        """Convert a serialized dictionary back into an entry instance."""
        media = ExampleListMedia(
            key=data["key"],
            title=data.get("title", data["key"]),
            media_type=ListMediaType(data.get("media_type", ListMediaType.TV.value)),
            _provider=self,
            _total_units=data.get("total_units"),
        )
        entry = ExampleListEntry(
            key=data["key"],
            title=data.get("title", data["key"]),
            _provider=self,
            _media=media,
            _progress=data.get("progress"),
            _repeats=data.get("repeats"),
            _review=data.get("review"),
            _status=ListStatus(data["status"]) if data.get("status") else None,
            _user_rating=data.get("user_rating"),
            _started_at=self._parse_date(data.get("started_at")),
            _finished_at=self._parse_date(data.get("finished_at")),
        )
        return entry

    def _parse_date(self, value: str | None) -> datetime | None:
        """Parse an ISO timestamp if one is supplied."""
        if value is None:
            return None
        return datetime.fromisoformat(value)

    def _build_example_entries(self) -> None:
        """Populate two static entries used throughout the example."""
        watch_media = ExampleListMedia(
            key="cowboy-bebop",
            title="Cowboy Bebop",
            media_type=ListMediaType.TV,
            _provider=self,
            _poster_image="https://example.invalid/bebop.jpg",
            _total_units=26,
        )
        movie_media = ExampleListMedia(
            key="your-name",
            title="Your Name",
            media_type=ListMediaType.MOVIE,
            _provider=self,
            _poster_image="https://example.invalid/your-name.jpg",
            _total_units=1,
        )
        now = datetime.now(UTC)
        self._entries = {
            watch_media.key: ExampleListEntry(
                key=watch_media.key,
                title=watch_media.title,
                _provider=self,
                _media=watch_media,
                _progress=26,
                _status=ListStatus.COMPLETED,
                _user_rating=95,
                _started_at=now.replace(month=1, day=5),
                _finished_at=now.replace(month=2, day=1),
            ),
            movie_media.key: ExampleListEntry(
                key=movie_media.key,
                title=movie_media.title,
                _provider=self,
                _media=movie_media,
                _progress=None,
                _status=ListStatus.PLANNING,
                _user_rating=None,
            ),
        }
