"""Jellyfin provider configuration."""

from typing import Annotated

import msgspec


class JellyfinProviderConfig(msgspec.Struct, kw_only=True):
    """Configuration for the Jellyfin provider."""

    url: Annotated[
        str,
        msgspec.Meta(description="The base URL of the Jellyfin server."),
    ]
    token: Annotated[
        str,
        msgspec.Meta(description="The Jellyfin API token."),
    ]
    user: Annotated[
        str,
        msgspec.Meta(description="The Jellyfin user to synchronize."),
    ]
    sections: Annotated[
        list[str],
        msgspec.Meta(
            description=(
                "A list of Jellyfin library section names "
                "to constrain synchronization to."
            )
        ),
    ] = msgspec.field(default_factory=list)
    genres: Annotated[
        list[str],
        msgspec.Meta(description="A list of genres to constrain synchronization to."),
    ] = msgspec.field(default_factory=list)
    strict: Annotated[
        bool,
        msgspec.Meta(
            description="Whether to enforce strict matching when resolving mappings."
        ),
    ] = True
