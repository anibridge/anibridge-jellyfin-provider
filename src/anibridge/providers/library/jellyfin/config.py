"""Jellyfin provider configuration."""

from pydantic import BaseModel, Field


class JellyfinProviderConfig(BaseModel):
    """Configuration for the Jellyfin provider."""

    url: str = Field(
        default=...,
        description="The base URL of the Jellyfin server.",
    )
    token: str = Field(
        default=...,
        description="The Jellyfin API token.",
    )
    user: str = Field(
        default=...,
        description="The Jellyfin user to synchronize.",
    )
    sections: list[str] = Field(
        default_factory=list,
        description=(
            "A list of Jellyfin library section names to constrain synchronization to."
        ),
    )
    genres: list[str] = Field(
        default_factory=list,
        description="A list of genres to constrain synchronization to.",
    )
    strict: bool = Field(
        default=True,
        description="Whether to enforce strict matching when resolving mappings.",
    )
