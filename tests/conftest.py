"""Pytest fixtures shared across the provider test-suite."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from anibridge_example_provider.example_library import ExampleLibraryProvider
from anibridge_example_provider.example_list import ExampleListProvider


@pytest.fixture()
def library_provider() -> ExampleLibraryProvider:
    """Return a fresh library provider instance."""
    return ExampleLibraryProvider()


@pytest_asyncio.fixture()
async def initialized_library_provider(
    library_provider: ExampleLibraryProvider,
) -> AsyncGenerator[ExampleLibraryProvider]:
    """Return a provider that has run its async initialize hook."""
    await library_provider.initialize()
    yield library_provider
    await library_provider.close()


@pytest_asyncio.fixture()
async def library_section(initialized_library_provider: ExampleLibraryProvider):
    """Return the single demo section exposed by the library provider."""
    sections = await initialized_library_provider.get_sections()
    assert len(sections)
    return sections[0]


@pytest.fixture()
def list_provider() -> ExampleListProvider:
    """Return a fresh list provider instance."""
    return ExampleListProvider()


@pytest_asyncio.fixture()
async def initialized_list_provider(
    list_provider: ExampleListProvider,
) -> AsyncGenerator[ExampleListProvider]:
    """Return a list provider after initialization and ensure cleanup."""
    await list_provider.initialize()
    yield list_provider
    await list_provider.close()
