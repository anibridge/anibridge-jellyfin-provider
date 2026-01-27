"""Example library provider using in-memory fixtures as a demo."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from anibridge.library import (
    HistoryEntry,
    LibraryMedia,
    LibraryMovie,
    LibraryProvider,
    LibrarySection,
    LibraryUser,
    MappingDescriptor,
    MediaKind,
    library_provider,
)
from starlette.requests import Request


class ExampleLibrarySection(LibrarySection["ExampleLibraryProvider"]):
    """Basic memory-based ``LibrarySection`` implementation."""

    def __init__(
        self,
        key: str,
        title: str,
        media_kind: MediaKind,
        _provider: ExampleLibraryProvider,
    ) -> None:
        """Construct the in-memory library section instance."""
        self._key = key
        self._title = title
        self._media_kind = media_kind
        self._provider = _provider

    def provider(self) -> ExampleLibraryProvider:
        """Return the provider that instantiated the section."""
        return self._provider


class ExampleLibraryMedia(LibraryMedia["ExampleLibraryProvider"]):
    """Basic memory-based ``LibraryMedia`` implementation."""

    def __init__(
        self,
        key: str,
        title: str,
        media_kind: MediaKind,
        _provider: ExampleLibraryProvider,
        _poster_image: str | None = None,
        _ids: dict[str, str] | None = None,
    ) -> None:
        """Construct the in-memory library media instance."""
        self._key = key
        self._title = title
        self._media_kind = media_kind
        self._provider = _provider
        self._poster_image = _poster_image
        self._ids = dict(_ids) if _ids is not None else {}

    @property
    def poster_image(self) -> str | None:
        """Return a poster URL if the provider has one."""
        return self._poster_image

    def ids(self) -> dict[str, str]:
        """Return the external IDs associated with the media."""
        return dict(self._ids)


class ExampleLibraryMovie(LibraryMovie["ExampleLibraryProvider"]):
    """Basic memory-based ``LibraryMovie`` implementation."""

    def __init__(
        self,
        key: str,
        title: str,
        section_ref: ExampleLibrarySection,
        last_modified: datetime,
        _provider: ExampleLibraryProvider,
        _poster_image: str | None = None,
        _user_rating: int | None = None,
        _view_count: int = 0,
        _history: Sequence[HistoryEntry] | None = None,
        _ids: dict[str, str] | None = None,
        _review: str | None = None,
        _on_watching: bool = False,
        _on_watchlist: bool = False,
    ) -> None:
        """Construct the in-memory library movie instance."""
        self._key = key
        self._title = title
        self._media_kind = MediaKind.MOVIE
        self.section_ref = section_ref
        self.last_modified = last_modified
        self._provider = _provider
        self._user_rating = _user_rating
        self._view_count = _view_count
        self._history = tuple(_history) if _history is not None else tuple()
        self._review = _review
        self._on_watching = _on_watching
        self._on_watchlist = _on_watchlist
        self._media = ExampleLibraryMedia(
            key=key,
            title=title,
            media_kind=MediaKind.MOVIE,
            _provider=_provider,
            _poster_image=_poster_image,
            _ids=_ids,
        )

    def provider(self) -> ExampleLibraryProvider:
        """Return the provider that owns the movie."""
        return self._provider

    @property
    def on_watching(self) -> bool:
        """Indicate whether the movie is considered 'watching'."""
        return self._on_watching

    @property
    def on_watchlist(self) -> bool:
        """Indicate whether the movie is on the user's planned/watchlist."""
        return self._on_watchlist

    @property
    def poster_image(self) -> str | None:
        """Return a poster URL if the provider has one."""
        return self._media.poster_image

    @property
    def user_rating(self) -> int | None:
        """Return the user's rating, normalized to 0-100."""
        return self._user_rating

    @property
    def view_count(self) -> int:
        """Return how many times the user watched the movie."""
        return self._view_count

    async def history(self) -> Sequence[HistoryEntry]:
        """Return stored play history entries."""
        return self._history

    def mapping_descriptors(self) -> Sequence[MappingDescriptor]:
        """Return mapping descriptors derived from stored external IDs."""
        items = sorted(self._media.ids().items())
        return tuple((provider, entry_id, None) for provider, entry_id in items)

    def ids(self) -> dict[str, str]:
        """Return the external IDs associated with the movie."""
        return self._media.ids()

    async def review(self) -> str | None:
        """Return the user's review text, if there is one."""
        return self._review

    def section(self) -> ExampleLibrarySection:
        """Return the section the movie belongs to."""
        return self.section_ref

    def media(self) -> ExampleLibraryMedia:
        """Return the media details for this entry."""
        return self._media


@library_provider
class ExampleLibraryProvider(LibraryProvider):
    """Simple library provider that serves two hard-coded movies."""

    NAMESPACE = "example-library"

    def __init__(self, *, config: dict | None = None) -> None:
        """Construct the provider with optional configuration overrides."""
        self._config = config or {}
        self._user = LibraryUser(
            key=self._config.get("user_key", "demo-user"),
            title=self._config.get("user_title", "Demo Library User"),
        )
        self._sections: tuple[ExampleLibrarySection, ...] = tuple()
        self._items: tuple[ExampleLibraryMovie, ...] = tuple()
        self._build_fixtures()

    def _build_fixtures(self) -> None:
        movies = ExampleLibrarySection(
            key="movies",
            title="Demo Movies",
            media_kind=MediaKind.MOVIE,
            _provider=self,
        )
        now = datetime.now(UTC)
        self._sections = (movies,)
        self._items = (
            ExampleLibraryMovie(
                key="castle-in-the-sky",
                title="Castle in the Sky",
                section_ref=movies,
                last_modified=now - timedelta(days=3),
                _provider=self,
                _poster_image="https://example.invalid/castle.jpg",
                _user_rating=90,
                _view_count=2,
                _history=(
                    HistoryEntry(
                        library_key="castle-in-the-sky",
                        viewed_at=now - timedelta(days=10),
                    ),
                ),
                _ids={"anilist": "513"},
                _review="Still magical on every rewatch.",
            ),
            ExampleLibraryMovie(
                key="nausicaa",
                title="Nausicaä of the Valley of the Wind",
                section_ref=movies,
                last_modified=now - timedelta(days=1),
                _provider=self,
                _poster_image="https://example.invalid/nausicaa.jpg",
                _user_rating=None,
                _view_count=0,
                _history=tuple(),
                _ids={"imdb": "tt0085213"},
                _review=None,
                _on_watchlist=True,
            ),
        )

    async def get_sections(self) -> Sequence[LibrarySection[ExampleLibraryProvider]]:
        """Return the single in-memory section."""
        return self._sections

    async def list_items(
        self,
        section: LibrarySection,
        *,
        min_last_modified: datetime | None = None,
        require_watched: bool = False,
        keys: Sequence[str] | None = None,
    ) -> Sequence[ExampleLibraryMovie]:
        """Return the items for the supplied section while applying filters."""
        if section.key not in {sec.key for sec in self._sections}:
            return tuple()

        items = [item for item in self._items if item.section() == section]

        if min_last_modified is not None:
            items = [item for item in items if item.last_modified >= min_last_modified]

        if require_watched:
            items = [item for item in items if item.view_count > 0]

        if keys is not None:
            allowed = set(keys)
            items = [item for item in items if item.key in allowed]

        return tuple(items)

    async def parse_webhook(self, request: Request) -> tuple[bool, Sequence[str]]:
        """Indicate that webhooks are not supported by the example provider."""
        raise NotImplementedError("Webhooks are not supported by the example provider.")

    ###########################################################################
    ### Anything beyond this point does not implement required API methods. ###
    ###########################################################################

    async def initialize(self) -> None:
        """No-op initialize hook because the provider is in-memory."""
        return None

    def user(self) -> LibraryUser | None:
        """Return the static user descriptor."""
        return self._user

    async def clear_cache(self) -> None:
        """No caching is used, so the hook is a no-op."""
        return None

    async def close(self) -> None:
        """Release resources; nothing to do for the example provider."""
        return None
