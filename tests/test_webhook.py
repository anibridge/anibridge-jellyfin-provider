"""Tests for Jellyfin webhook parser helpers."""

from typing import cast

import pytest
from starlette.requests import Request

from anibridge.providers.library.jellyfin.webhook import JellyfinWebhook


class _FakeRequest:
    def __init__(
        self, *, headers: dict[str, str], json_payload=None, form_payload=None
    ):
        self.headers = headers
        self._json_payload = json_payload
        self._form_payload = form_payload or {}

    async def json(self):
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload

    async def form(self):
        return self._form_payload


@pytest.mark.asyncio
async def test_webhook_from_json_body() -> None:
    """JSON requests should parse directly into webhook fields."""
    request = _FakeRequest(
        headers={"content-type": "application/json"},
        json_payload={
            "NotificationType": "ItemAdded",
            "ItemType": "Episode",
            "ItemId": "episode-1",
            "SeriesId": "show-1",
            "UserId": "user-1",
            "NotificationUsername": "demo",
        },
    )

    webhook = await JellyfinWebhook.from_request(cast(Request, request))
    assert webhook.notification_type == "ItemAdded"
    assert webhook.user_id == "user-1"
    assert webhook.username == "demo"
    assert webhook.top_level_item_id == "show-1"


@pytest.mark.asyncio
async def test_webhook_from_form_payload_json_string() -> None:
    """Form payloads should parse JSON in the payload key."""
    request = _FakeRequest(
        headers={"content-type": "multipart/form-data; boundary=abc"},
        form_payload={
            "payload": (
                '{"NotificationType":"PlaybackStop","ItemType":"Movie","ItemId":"m1"}'
            )
        },
    )

    webhook = await JellyfinWebhook.from_request(cast(Request, request))
    assert webhook.notification_type == "PlaybackStop"
    assert webhook.top_level_item_id == "m1"


@pytest.mark.asyncio
async def test_webhook_string_json_payload() -> None:
    """String JSON payloads in request.json should be decoded."""
    request = _FakeRequest(
        headers={"content-type": "application/json"},
        json_payload='{"NotificationType":"UserDataSaved","ItemType":"Season","SeriesId":"s1"}',
    )

    webhook = await JellyfinWebhook.from_request(cast(Request, request))
    assert webhook.notification_type == "UserDataSaved"
    assert webhook.top_level_item_id == "s1"


@pytest.mark.asyncio
async def test_webhook_invalid_form_payload_raises() -> None:
    """Invalid JSON in multipart payload should raise ValueError."""
    request = _FakeRequest(
        headers={"content-type": "application/x-www-form-urlencoded"},
        form_payload={"payload": "{not-valid-json"},
    )

    with pytest.raises(ValueError, match="Invalid payload JSON"):
        await JellyfinWebhook.from_request(cast(Request, request))


@pytest.mark.asyncio
async def test_webhook_invalid_json_body_raises() -> None:
    """Invalid JSON body should raise ValueError."""
    request = _FakeRequest(
        headers={"content-type": "application/json"},
        json_payload=RuntimeError("bad body"),
    )

    with pytest.raises(ValueError, match="Invalid JSON body"):
        await JellyfinWebhook.from_request(cast(Request, request))


@pytest.mark.asyncio
async def test_webhook_invalid_payload_structure_raises() -> None:
    """Non-object payloads should be rejected."""
    request = _FakeRequest(
        headers={"content-type": "application/json"},
        json_payload=["not", "an", "object"],
    )

    with pytest.raises(ValueError, match="Invalid payload structure"):
        await JellyfinWebhook.from_request(cast(Request, request))
