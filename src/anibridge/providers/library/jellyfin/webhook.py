"""Jellyfin webhook payload parsing helpers."""

from enum import StrEnum

import msgspec
from starlette.requests import Request


class JellyfinWebhookNotificationType(StrEnum):
    """Notification types relevant for library sync."""

    ITEM_ADDED = "ItemAdded"
    PLAYBACK_STOP = "PlaybackStop"
    USER_DATA_SAVED = "UserDataSaved"


class JellyfinWebhookPayload(
    msgspec.Struct,
    rename={
        "notification_type": "NotificationType",
        "user_id": "UserId",
        "notification_username": "NotificationUsername",
        "username": "Username",
        "item_type": "ItemType",
        "item_id": "ItemId",
        "series_id": "SeriesId",
    },
):
    """Jellyfin webhook payload."""

    notification_type: str
    user_id: str | None = None
    notification_username: str | None = None
    username: str | None = None
    item_type: str | None = None
    item_id: str | None = None
    series_id: str | None = None


class JellyfinWebhook(msgspec.Struct):
    """Represents a normalized Jellyfin webhook payload."""

    payload: JellyfinWebhookPayload

    @property
    def notification_type(self) -> str:
        """Raw notification type string from Jellyfin."""
        return self.payload.notification_type

    @property
    def user_id(self) -> str | None:
        """The webhook user's Jellyfin account ID, if present."""
        return self.payload.user_id

    @property
    def username(self) -> str | None:
        """The webhook username, if present."""
        return self.payload.notification_username or self.payload.username

    @property
    def top_level_item_id(self) -> str | None:
        """The top-level media item ID for the payload."""
        item_type = (self.payload.item_type or "").strip().lower()
        if item_type in {"episode", "season"} and self.payload.series_id:
            return self.payload.series_id
        return self.payload.item_id or self.payload.series_id

    @classmethod
    async def from_request(cls, request: Request) -> JellyfinWebhook:
        """Create a Jellyfin webhook instance from an incoming HTTP request."""
        return await WebhookParser.from_request(request)


class WebhookParser:
    """Parser for incoming Jellyfin webhooks."""

    @staticmethod
    def media_type(content_type: str | None) -> str:
        """Read the media type portion of a Content-Type header."""
        if not content_type:
            return ""
        return content_type.split(";", 1)[0].strip().lower()

    @classmethod
    async def from_request(cls, request: Request) -> JellyfinWebhook:
        """Create a Jellyfin webhook instance from an incoming HTTP request."""
        content_type = cls.media_type(request.headers.get("content-type"))

        if content_type in ("multipart/form-data", "application/x-www-form-urlencoded"):
            form = await request.form()
            payload_raw = form.get("payload")

            if payload_raw:
                if isinstance(payload_raw, bytes):
                    payload_raw = payload_raw.decode("utf-8", "replace")

                try:
                    payload = msgspec.json.decode(
                        str(payload_raw), type=JellyfinWebhookPayload
                    )
                except Exception as exc:
                    raise ValueError(f"Invalid payload JSON: {exc}") from exc
            else:
                try:
                    payload = msgspec.convert(dict(form), type=JellyfinWebhookPayload)
                except Exception as exc:
                    raise ValueError(
                        f"Invalid Jellyfin webhook payload: {exc}"
                    ) from exc

            return JellyfinWebhook(payload=payload)

        if content_type in ("application/json", "text/plain", ""):
            try:
                data = await request.json()
            except Exception as exc:
                raise ValueError(f"Invalid JSON body: {exc}") from exc

            if isinstance(data, str):
                try:
                    payload = msgspec.json.decode(data, type=JellyfinWebhookPayload)
                except Exception as exc:
                    raise ValueError(
                        f"Invalid Jellyfin webhook payload: {exc}"
                    ) from exc
                return JellyfinWebhook(payload=payload)

            if not isinstance(data, dict):
                raise ValueError("Invalid payload structure: expected JSON object")

            try:
                payload = msgspec.convert(data, type=JellyfinWebhookPayload)
            except Exception as exc:
                raise ValueError(f"Invalid Jellyfin webhook payload: {exc}") from exc

            return JellyfinWebhook(payload=payload)

        raise ValueError(
            f"Unsupported content type '{content_type}' for Jellyfin webhook "
            "(expected multipart/form-data or application/json)"
        )
