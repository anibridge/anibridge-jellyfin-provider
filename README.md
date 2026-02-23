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

### `strict` (`bool`, optional)

When enabled, show/season/episode mappings are restricted to the section's highest-priority TV show metadata downloader from Jellyfin library options. For example, if the top TV metadata downloader is AniDB, only AniDB mapping descriptors will be considered for matching. When disabled, all metadata downloaders will be considered for matching. This option is enabled by default.

```yaml
library_provider_config:
  jellyfin:
    url: ...
    token: ...
    user: ...
    # sections: []
    # genres: []
    # strict: true
```
