# anibridge-jellyfin-provider

Jellyfin library provider implementation for the AniBridge project.

## Configuration

### `url` (`str`)

The base URL of the Jellyfin server (e.g., http://localhost:8096).

### `token` (`str`)

The Jellyfin API token. You can generate this under the user settings in Jellyfin.

### `user` (`str`)

The Jellyfin user to synchronize. This can be a user id, username, or display name.

### `sections` (`list[str]`, optional)

A list of Jellyfin library section names to constrain synchronization to. Leave
empty/unset to include all sections.

### `genres` (`list[str]`, optional)

A list of genres to constrain synchronization to. Leave empty/unset to include all
genres.

```yaml
library_provider_config:
  jellyfin:
    url: ...
    token: ...
    user: ...
    # sections: []
    # genres: []
```
