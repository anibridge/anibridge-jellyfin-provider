"""Jellyfin webhook payload parsing helpers."""

import json
from collections.abc import Mapping
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request


class JellyfinWebhookNotificationType(StrEnum):
    """Notification types relevant for library sync."""

    ITEM_ADDED = "ItemAdded"
    PLAYBACK_STOP = "PlaybackStop"
    USER_DATA_SAVED = "UserDataSaved"


class JellyfinWebhook:
    """Represents a Jellyfin webhook event payload."""

    def __init__(self, data: Mapping[str, object]) -> None:
        """Initialize the webhook wrapper.

        Args:
            data (Mapping[str, object]): Raw payload mapping.
        """
        self._data = {str(key).lower(): value for key, value in data.items()}

    @cached_property
    def notification_type(self) -> str | None:
        """Return the webhook notification type, if present."""
        value = self._string_value("notificationtype")
        return value if value else None

    @cached_property
    def user_id(self) -> str | None:
        """Return the webhook user id, if present."""
        value = self._string_value("userid")
        return value if value else None

    @cached_property
    def username(self) -> str | None:
        """Return the webhook username, if present."""
        return self._string_value("notificationusername") or self._string_value(
            "username"
        )

    @cached_property
    def item_type(self) -> str | None:
        """Return the Jellyfin item type, if present."""
        return self._string_value("itemtype")

    @cached_property
    def item_id(self) -> str | None:
        """Return the webhook item id, if present."""
        value = self._string_value("itemid")
        return value if value else None

    @cached_property
    def series_id(self) -> str | None:
        """Return the webhook series id, if present."""
        value = self._string_value("seriesid")
        return value if value else None

    @cached_property
    def top_level_item_id(self) -> str | None:
        """Return the top-level item id suitable for library sync keys."""
        item_type = (self.item_type or "").lower()
        if item_type in {"episode", "season"} and self.series_id:
            return self.series_id
        return self.item_id or self.series_id

    @classmethod
    async def from_request(cls, request: Request) -> JellyfinWebhook:
        """Create a webhook payload from an incoming HTTP request."""
        content_type = request.headers.get("content-type", "").lower()

        if content_type.startswith(
            ("multipart/form-data", "application/x-www-form-urlencoded")
        ):
            form = await request.form()
            payload_raw = form.get("payload")
            if payload_raw:
                try:
                    data = json.loads(str(payload_raw))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid payload JSON: {exc}") from exc
            else:
                data = {str(key): value for key, value in form.items()}
        else:
            try:
                data = await request.json()
            except Exception as exc:
                raise ValueError(f"Invalid JSON body: {exc}") from exc

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON payload: {exc}") from exc

        if not isinstance(data, Mapping):
            raise ValueError("Invalid payload structure: expected a JSON object")

        return cls(data)

    def _string_value(self, key: str) -> str | None:
        """Return a string value for a key if present and non-empty."""
        value = self._data.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None
