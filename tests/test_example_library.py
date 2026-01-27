"""Tests for the example library provider."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from anibridge_example_provider.example_library import ExampleLibrarySection

if TYPE_CHECKING:
    from anibridge_example_provider.example_library import ExampleLibraryProvider


@pytest.mark.asyncio
async def test_get_sections_returns_single_demo_section(
    initialized_library_provider: ExampleLibraryProvider,
):
    """The provider exposes one demo section describing the movie fixtures."""
    sections = await initialized_library_provider.get_sections()
    assert len(sections) == 1
    section = sections[0]
    assert isinstance(section, ExampleLibrarySection)
    assert section.title == "Demo Movies"
    assert section.media_kind.name == "MOVIE"


@pytest.mark.asyncio
async def test_list_items_supports_common_filters(
    initialized_library_provider: ExampleLibraryProvider,
    library_section: ExampleLibrarySection,
):
    """Query filters should trim the in-memory dataset as expected."""
    cutoff = datetime.now(UTC) - timedelta(days=2)
    recent = await initialized_library_provider.list_items(
        library_section,
        min_last_modified=cutoff,
    )
    assert [item.key for item in recent] == ["nausicaa"]

    watched_only = await initialized_library_provider.list_items(
        library_section,
        require_watched=True,
    )
    assert [item.key for item in watched_only] == ["castle-in-the-sky"]

    subset = await initialized_library_provider.list_items(
        library_section,
        keys=("castle-in-the-sky",),
    )
    assert [item.key for item in subset] == ["castle-in-the-sky"]


@pytest.mark.asyncio
async def test_library_items_expose_mapping_descriptors(
    initialized_library_provider: ExampleLibraryProvider,
    library_section: ExampleLibrarySection,
):
    """Mapping descriptors should mirror stored external IDs."""
    items = await initialized_library_provider.list_items(library_section)
    by_key = {item.key: item for item in items}

    castle = by_key["castle-in-the-sky"]
    assert castle.mapping_descriptors() == (("anilist", "513", None),)

    nausicaa = by_key["nausicaa"]
    assert nausicaa.mapping_descriptors() == (("imdb", "tt0085213", None),)
