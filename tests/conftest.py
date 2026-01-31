"""Pytest fixtures shared across the provider test-suite."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from anibridge_jellyfin_provider.library import JellyfinLibraryProvider


@pytest.fixture()
def library_provider() -> JellyfinLibraryProvider:
    """Return a fresh library provider instance."""
    return JellyfinLibraryProvider(
        config={
            "url": "http://jellyfin.example",
            "token": "token",
            "user": "demo",
        }
    )


@pytest_asyncio.fixture()
async def initialized_library_provider(
    library_provider: JellyfinLibraryProvider,
) -> AsyncGenerator[JellyfinLibraryProvider]:
    """Return a provider that has run its async initialize hook."""
    await library_provider.initialize()
    yield library_provider
    await library_provider.close()


@pytest_asyncio.fixture()
async def library_section(initialized_library_provider: JellyfinLibraryProvider):
    """Return the first available section exposed by the provider."""
    sections = await initialized_library_provider.get_sections()
    assert len(sections)
    return sections[0]
