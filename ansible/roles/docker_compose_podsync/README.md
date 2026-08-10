# docker_compose_podsync

Deploys Podsync: turns YouTube channels and playlists into podcast RSS feeds, downloading the
audio itself and serving both the feed XML and the enclosures over HTTP.

The point is to get shows that also publish to YouTube without the dynamic ad insertion their
regular podcast feeds carry. yt-dlp pulls the raw media stream, so only baked-in host reads
survive.

This role must run on a host with a **residential** internet connection. That is not a
preference — see *Downloads must not originate from a datacenter*. The feeds are then published
to the public internet by tsdproxy using Tailscale Funnel, so no inbound port, no port forward,
and no reverse proxy on a VPS is involved.

## Status: Production

## Inputs

Required:

- `podsync_public_url` — the base URL a podcast app reaches this instance on, e.g.
  `https://<tsdproxy name>.<tailnet>.ts.net`. Podsync writes it into every RSS enclosure link.
  Get it wrong and the feeds still parse while every episode download 404s.
- `podsync_youtube_api_key` — YouTube Data API v3 key, from vault. Podsync cannot build a
  YouTube feed without one; every feed errors on its first update. Quota is generous relative to
  this workload: a feed update costs a handful of units against 10,000/day.
- `podsync_feed_id_suffix` — random `[a-z0-9]` string, from vault, appended to every feed ID.
  Funnel is public and unauthenticated, so this is the only access control. Change it and every
  already-subscribed URL 404s.
- `podsync_feeds` — list of feeds. Per item: `id` (required, `[a-z0-9-]`), `url` (required), and
  optionally `title`, `page_size`, `update_period`, `keep_last` to override the role defaults for
  that one feed. An empty list makes podsync refuse to start — it rejects a config with no feeds.

Optional, all with defaults in `defaults/main.yaml`:

- `podsync_tsdproxy_name` — default `podsync`. The Tailscale device name tsdproxy creates,
  giving `<name>.<tailnet>.ts.net`. Must agree with `podsync_public_url`.
- `podsync_tsdproxy_funnel` — default `true`. Set false and the service is reachable only from
  inside the tailnet, which no podcast app can do.
- `podsync_web_hostname` — default `podsync`. Label before the domain in the internal Traefik
  route. Only affects LAN access; the public URL comes from tsdproxy.
- `podsync_image_tag` — default `nightly`. See *`:latest` is too old to use*. Pointing this at
  `latest` silently disables the access model.
- `podsync_update_period` — default `"6h"`. Weekly shows do not need faster; lowering it spends
  API quota for nothing, and raising it past a week risks missing an episode if `page_size` is
  small.
- `podsync_page_size` — default `10`. Episodes queried per update. Set below the show's release
  rate over one `update_period` and episodes are missed entirely. Set well above `keep_last` and
  podsync downloads episodes only to prune them.
- `podsync_keep_last` — default `10`. Episodes retained on disk per feed, newest first. Budget
  roughly 58 MB per hour of audio at YouTube's AAC bitrate.
- `podsync_youtube_dl_format` / `podsync_extension` — default `bestaudio[ext=m4a]` / `m4a`. See
  *Custom format avoids a re-encode*.
- `podsync_downloader_timeout` — default `30` minutes per episode. Too low and long episodes fail
  partway and retry next cycle; there is no partial resume.
- `podsync_cookies_file_path` — default empty, meaning no cookies are passed. A fallback only;
  see *Downloads must not originate from a datacenter*.

## Example

```yaml
- role: docker_compose_podsync
  tags: podsync
```

with, in `group_vars/all/vars.yaml`:

```yaml
# docker_compose_podsync
podsync_youtube_api_key: "{{ vault_podsync_youtube_api_key }}"
podsync_feed_id_suffix: "{{ vault_podsync_feed_id_suffix }}"
podsync_public_url: "https://podsync.{{ tailscale_tailnet }}"
podsync_feeds:
  - id: full-nerd
    url: "https://www.youtube.com/playlist?list=PLiZwoK8DQiwyP-kiDdsO3PD2_dmEkVKeT"
    title: "The Full Nerd (via Podsync)"
```

## Downloads must not originate from a datacenter

YouTube treats datacenter IP ranges as suspect. This was measured, not assumed: deployed to a
VPS, every one of 30 episodes failed with

```
ERROR: [youtube] <id>: Sign in to confirm you're not a bot.
```

while the feed XML built fine, because the YouTube Data API is a separate, key-authenticated
path that is not blocked. Nine yt-dlp player clients (`tv`, `tv_simply`, `web_embedded`, `ios`,
`mweb`, `android`, `web`, `web_safari`, `default`) were each tried and all failed identically, so
it is not a client-selection problem. The image was not the problem either — yt-dlp, deno and
ffmpeg were all current.

Hence the residential-host requirement. `podsync_cookies_file_path` exists as a fallback if the
home IP is ever flagged too: put a Netscape-format `cookies.txt` on the host and point the
variable at it, and every feed gains `youtube_dl_args = ["--cookies", "/app/cookies.txt"]`.
Use a secondary Google account if you ever need it — yt-dlp's own docs warn the account can be
banned — and expect to refresh it.

`[downloader] self_update = true` is on, so yt-dlp updates itself daily inside the container.
That handles yt-dlp bugs; it does not handle bot detection.

## The feed ID is the credential

tsdproxy's own docs are blunt about what Funnel means: *"Funnel bypasses Tailscale
authentication. Anyone on the internet can reach your service. Ensure your backend has its own
authentication."* Podsync has none. The three settings this role turns on are what stands in for
it, and none is a password:

- `no_listing = true` — podsync's file server returns 404 for any directory, so `GET /` and
  `GET /<feed-id>/` give nothing. This is the control that matters: without it a single request
  lists every feed and every episode file.
- `no_index = true` — serves `robots.txt` with `Disallow: /` and adds `X-Robots-Tag: noindex,
  nofollow` to every response.
- `private_feed = true` per feed — emits `itunes:block`, which asks podcast directories not to
  list the feed, and which apps such as Overcast use to suppress share and recommend buttons.

The hostname cannot be kept secret. Tailscale issues a Let's Encrypt certificate for the Funnel
name, and every LE certificate is published to Certificate Transparency logs — permanently,
publicly, machine-readable. Assume `<name>.<tailnet>.ts.net` is known. That is exactly why the
feed IDs carry a random suffix: a discovered host plus a guessable feed name (`/full-nerd.xml`)
is two steps from the content, and a wordlist covers the second step.

Anyone handed a URL gets the audio.

## Funnel constraints that shape this role

- Funnel can only listen on ports `443`, `8443` and `10000`, so the tsdproxy port label must map
  `443/https` to podsync's `8080/http`. It cannot be any other public port.
- Funnel can only use names in the tailnet's own domain. There is no custom-domain option, so
  `podsync_public_url` is always a `.ts.net` name.
- Funnel requires the `funnel` node attribute in the tailnet policy file. That lives in the
  Tailscale admin console, not in this repo. Without it the device comes up but is not published,
  and the failure is silent from Ansible's side.
- Traffic over Funnel is subject to undisclosed, non-configurable bandwidth limits. Tailscale's
  Funnel acceptable-use policy has no clause on bandwidth, data volume, media serving or content
  distribution, so there is no policy problem here — but the throttle is real and unquantified.
  This workload is light: the back catalogue once, then roughly one episode a day.

Note the traffic split. Episodes are downloaded *from YouTube over the host's own connection* and
never touch Funnel. Only what a podcast app fetches goes through Tailscale's relay.

## `server.path` does not work — do not try it

Podsync's config has a `[server] path` option that looks like the right way to put an unguessable
prefix on every URL. It is broken upstream. `services/web/server.go` registers the file server as
`mux.Handle(fmt.Sprintf("/%s", cfg.Path), fileServer)`, and there is no `http.StripPrefix`
anywhere in the file. A Go `ServeMux` pattern with no trailing slash matches that exact path only,
so with `path = "abc"` a request for `/abc/feed.xml` is a 404. The option appears to work when
unset purely because the empty value produces the pattern `/`, which *is* a subtree.

## `:latest` is too old to use

The upstream release workflow only pushes images on `v*` tags, and the newest tag is v2.8.0 from
2025-07-14. `:latest` is that image. Two things rule it out:

- Neither `no_index` nor `no_listing` exists in it. Its `web.Config` struct has eight fields and
  neither is among them, so both settings are silently ignored and `GET /` lists everything.
- Its Alpine base predates the `deno` package the current Dockerfile installs specifically for
  yt-dlp, which needs a JS runtime for YouTube's challenge.

`:nightly` is rebuilt daily from `main` and has both. The cost is that the digest changes every
night, which is why the compose file sets `diun.enable=false`: Diun watches by default on these
hosts and would otherwise notify every morning. Diun honours the label regardless of
`watchByDefault`.

The trade is real — nothing pins the version, and Diun is muted, so a regression on `main` lands
without warning. Read the container logs after any restart.

## Custom format avoids a re-encode

`format = "custom"` with `bestaudio[ext=m4a]` downloads YouTube's AAC stream as-is. The obvious
alternative, `format = "audio"`, makes podsync pass `--extract-audio --audio-format mp3`, which
re-encodes every episode with ffmpeg on the deploying host. For multi-hour talk shows that is a
lot of CPU for a quality loss.

## Playlists, not channels

Prefer a playlist URL over a channel URL when a channel carries more than one show, or posts
clips and shorts alongside full episodes — a channel URL resolves to its uploads playlist and
takes everything. The cost is that a playlist is maintained by hand: if a show stops adding new
uploads to it, the feed goes quiet with no error.

Podsync's `playlist_sort` defaults to `asc`, which reads from the start of the playlist. Verify
which end a given playlist appends to before trusting it — fetch
`https://www.youtube.com/feeds/videos.xml?playlist_id=<id>` and check whether the newest episode
is the first entry.

## The feed ID is a path component

Episodes land in `/app/data/<feed-id>/` and the feed XML is `/app/data/<feed-id>.xml`, where
`<feed-id>` is the item's `id` plus `podsync_feed_id_suffix`. Renaming either half repoints
podsync at a fresh directory: the feed re-downloads from scratch, the old directory is orphaned
and has to be deleted by hand, and every subscriber's URL breaks.

## config.toml holds two secrets

It is deployed mode `0600`. The container runs as root — the image sets no `USER` — so it can
still read a file owned by the deploying user. Do not add a `user:` to the compose file without
also fixing the mode and pre-creating the data and db directories, which Docker otherwise creates
as root.
