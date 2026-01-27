"""Tests for the example list provider."""

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from anibridge_example_provider.example_list import ExampleListProvider


@pytest.mark.asyncio
async def test_search_returns_partial_matches(
    initialized_list_provider: ExampleListProvider,
):
    """The case-insensitive search should accept substrings."""
    results = await initialized_list_provider.search("bebop")
    assert [entry.key for entry in results] == ["cowboy-bebop"]
    assert len(results) == 1
    entry = results[0]
    assert entry.progress == 26
    assert entry.status is not None and entry.status.name == "COMPLETED"


@pytest.mark.asyncio
async def test_backup_payload_and_manual_restore(
    initialized_list_provider: ExampleListProvider,
):
    """A backup blob should contain enough information to rebuild entries."""
    backup_blob = await initialized_list_provider.backup_list()
    payload = json.loads(backup_blob)

    assert payload["user"] == "demo-user"
    entries = payload["entries"]
    assert {entry["key"] for entry in entries} == {"cowboy-bebop", "your-name"}

    for media_key in ("cowboy-bebop", "your-name"):
        await initialized_list_provider.delete_entry(media_key)
        assert await initialized_list_provider.get_entry(media_key) is None

    for raw_entry in entries:
        entry = initialized_list_provider._decode_entry(raw_entry)
        await initialized_list_provider.update_entry(entry.key, entry)

    restored = await initialized_list_provider.get_entry("cowboy-bebop")
    assert restored is not None
    assert restored.progress == 26


@pytest.mark.asyncio
async def test_resolve_mapping_descriptors_returns_targets(
    initialized_list_provider: ExampleListProvider,
):
    """Descriptors matching the provider namespace should resolve to media keys."""
    descriptors = (
        (initialized_list_provider.NAMESPACE, "cowboy-bebop", None),
        ("unknown", "ghost", None),
    )

    resolved = await initialized_list_provider.resolve_mapping_descriptors(descriptors)

    assert len(resolved) == 1
    target = resolved[0]
    assert target.media_key == "cowboy-bebop"
    assert target.descriptor == descriptors[0]
