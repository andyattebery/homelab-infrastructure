# Tdarr iPad-kids flow

One flow, `tdarr-flow-ipad-kids.json`, carries two lanes — `standard` and `2d-animation` — across
two GPU vendors. It produces **travel copies for an iPad** and **never touches the originals**:
output goes to the library's `output_dir` with the relative path kept. A saving on this lane is
more hours that fit on the device, never library disk freed.

Every value comes from the recipe document, `media-library-discovery/TDARR-TRANSCODE-PLAN.md`,
which holds the measurements and their provenance. This page describes what the flow *does*; it is
not the place to change a number.

## The eight leaves

Three binary axes — dynamic range, path, GPU — give eight commands. All eight exist in the recipe
as tagged `# scenario:` blocks.

| lane | HDR | GPU | quality | geometry |
|---|---|---|---|---|
| `standard` | HDR | `hevc_nvenc` | `-preset p4 -cq 28` | `w=-2:h=min(1080,ih)` |
| `standard` | SDR | `hevc_nvenc` | `-preset p4 -cq 28` | `w=-2:h=min(1080,ih)` |
| `standard` | HDR | `hevc_vaapi` | `-global_quality 22` | `w=-2:h=min(1080,ih)` |
| `standard` | SDR | `hevc_vaapi` | `-global_quality 22` | `w=-2:h=min(1080,ih)` |
| `2d-animation` | HDR | `hevc_nvenc` | `-preset p3 -cq 34` | native — no scale |
| `2d-animation` | SDR | `hevc_nvenc` | `-preset p3 -cq 34` | native — no scale |
| `2d-animation` | HDR | `hevc_vaapi` | `-global_quality 26` | native — no scale |
| `2d-animation` | SDR | `hevc_vaapi` | `-global_quality 26` | native — no scale |

The `2d-animation` HDR leaves have no content in the library and are kept so the flow has no hole.
Their quality setting is the SDR leaf's; there is nothing to measure.

**All four `standard` leaves scale, and they must agree.** Any host may take any title, so a leaf
that emitted a different resolution would make the same title look different depending on which
node picked it up. On scope sources that means output *wider* than 1920 — a 2.39:1 title lands at
2582x1080 — which is accepted deliberately: aspect is preserved and the pixels stay square.

## Flow steps

```
Input File
  → Begin Command → Set Container (mp4)
  → Select Output Streams (local)      → no audio → Fail
  → Check HDR
      → Profile? (/2d-animation/)      × 2, one per HDR branch
          → VAAPI node?                × 4, one per lane/HDR pair
              → nvenc leaf   (output 2 — node has no hevc_vaapi)
              → Geometry (local) → vaapi leaf   (output 1)
                                 → no width/height → Fail
  → Selected audio is AAC?  → -c:a copy | -c:a aac -ac 2 -b:a 160k
  → Remove Subtitles → Remove Data Streams → Execute
  → Duration Ratio → Size Ratio → Health Check → Move To Directory
```

Branch order is HDR first, then path, then GPU. The GPU test sits **below** the path tests on
purpose: the recipe specifies one `checkHdr` node feeding two path tests, and putting the GPU test
above would give two HDR checks instead.

### The card branch reads Node Tags

Each node carries a tag naming its **card** — `a4000`, `5060ti`, `9070xt`, `b580` — and the
`checkNodeTag` local plugin matches `args.nodeTags`, the label on whichever node picked the job up.

| tag | node | result |
|---|---|---|
| `a4000` / `5060ti` | `media-01-a4000`, eta | the nvenc leaves |
| `9070xt` | htpc-01 | the vaapi leaves |
| `b580` | media-01's Arc server | **fails** — no Intel leaves exist |
| untagged | any | **fails** |

Tags are set with `POST /api/v2/update-node`
(`{"data":{"nodeID":"…","nodeUpdates":{"nodeTags":"mapped,a4000"}}}`). The Tdarr UI gates editing
that field; the API does not. ⚠ **Resolve the `nodeID` from `/api/v2/get-nodes` at run time — node
IDs are not stable across restarts.** Per-node config survives an ID change; it is keyed on name.

⚠⚠ **It keys on the card, not the encoder or the vendor, because the card is what was measured.**
`-qp 15` is a property of an A4000, not of `hevc_nvenc`. `a4000` and `5060ti` share the nvenc
leaves only because the recipe gives both the same `-cq`, both marked `measured` — the one place
sharing is licensed.

⚠ **Deliberately not `checkNodeHardwareEncoder`.** It answers by running a real one-second test
encode on every job, and it is blind to vendor: an Intel Arc and an AMD card **both** pass a
`hevc_vaapi` probe, so the Arc would take leaves whose `-global_quality` was measured on RDNA.

**A card with no leaf fails rather than falling through.** With every node tagged and the Arc
paused that terminal is unreachable, so if it fires the configuration is wrong — an untagged node,
a new card, a typo in a tag. It must never become the expected path for a class of titles.

### Subtitles

Text subtitles are kept and encoded to `mov_text`; bitmap ones are removed, by
`selectOutputStreams`. ⚠ A bitmap subtitle reaching `-c:s mov_text` **fails the whole encode**
rather than being skipped — *"Subtitle encoding currently only possible from text to text or bitmap
to bitmap."* Kept: `subrip`, `ass`, `ssa`, `mov_text`, `webvtt`, `text`. A title with no text
subtitles ends with none mapped, the same as `-sn`.


## Stream selection, and the silent-file defect it fixes

`ffmpegCommandStart` maps **every** stream as `-map 0:<index>`. There is no way to write
`-map 0:a:N` in a flow, so selection is done by marking streams removed.

The previous version of this flow used the community `Remove Stream By Property` node with
`disposition.default != 1`. That plugin only skips a stream when the property is absent — and
`disposition.default` is `0`, not absent, on a file that flags no default. **Roughly a fifth of
this library flags no default audio at all, and every `avi` file is in that set.** Every audio
stream matched, every one was removed, the video stream survived so nothing threw, and the file
shipped silent.

`selectOutputStreams` (local) does the same selection **with the fallback the recipe requires**:
keep every stream flagged default, or the first audio stream if none is flagged. It also keeps
only the first video stream and drops attachments, which is the `-map 0:v:0` the recipe asks for.

It publishes `selectedAudioCodec` — the codec of the stream actually kept — and the copy-vs-encode
branch tests that. The community `checkAudioCodec` node asks whether the *file* has an aac stream
anywhere, which would send an AC3-default / AAC-commentary source down the copy branch and ship
AC3.

A file flagging two defaults ships two audio tracks. That is the recipe's stated behaviour for
this lane; `selectOutputStreams` has a `firstOnly` mode if that ever needs narrowing.

## The vaapi geometry pair

`pad_vaapi` and `-bsf:v hevc_metadata` are one fix and neither half is optional: the filter aligns
the coded geometry, the bitstream filter restores the display dimensions, and without both, Apple
players reject the file.

The display dimensions are not always 1920x1080, so they cannot be hardcoded. `setScaledGeometry`
(local) computes them from ffprobe data and publishes `bsfW`/`bsfH`, which the leaves interpolate.
It has two modes — `scaled1080` for `standard`, `native` for `2d-animation` — and it sits on the
vaapi branch only, because an nvenc job never needs the values and must not fail for their absence.

If width or height is missing it **fails the flow** rather than emitting blanks. Execute drops an
empty argument *token* but keeps an argument with an empty *value*, so
`hevc_metadata=width=:height=` would reach ffmpeg intact and produce a file that muxes and does
not play.

### The HDR vaapi leaves need three things the SDR ones must not have

- **`-init_hw_device vulkan=vk@dr -filter_hw_device vk`**, on a DRM-rooted device topology.
  `libplacebo` is a Vulkan filter; without a device the encode writes no output at all. A
  standalone Vulkan device cannot derive back to VAAPI, hence `drm=dr` first.
- **`color_primaries=bt709:color_trc=bt709:colorspace=bt709` pinned on `libplacebo`.** It does not
  relabel its own output, so without these the file carries HDR tags over pixels already tonemapped
  to SDR — correct picture, wrong labels, no error anywhere. On an SDR leaf pinning them would be
  the same lie in the other direction, so the SDR leaves must not carry them.
- **`AMD_DEBUG=noefc`**, which is *not* in the flow — see below.

The nvenc leaves need no equivalent: `tonemap_cuda` relabels its own output. The two chains are
asymmetric on purpose.

## `AMD_DEBUG=noefc` cannot live in the flow

The Execute plugin spawns ffmpeg with an argument list and no environment override, and
`AMD_DEBUG` is not an ffmpeg flag. It reaches ffmpeg by inheritance from the container instead,
set through `podman_quadlet_tdarr_extra_env` on htpc-01. EFC is unstable in upstream Mesa; this is
a stability setting, not a correctness one.

## Worker type is a gate

A transcode **CPU** worker reads the ffmpeg arguments and refuses any job containing `nvenc`,
`cuda` or `vaapi`. A node left CPU-only registers, reports healthy, and silently takes no work from
this library at all.

All three hosts therefore run **1 GPU / 0 CPU** transcode workers, which is also the count the
recipe gives them on both kids lanes. All three come from Ansible:

| host | set in | mechanism |
|---|---|---|
| htpc-01 | `playbook-htpc-01.yaml` | `Environment=` on the quadlet unit |
| media-01 Arc server | `playbook-media-01.yaml`, via `docker_compose_tdarr_server_manage_workers` | compose `environment:` |
| `media-01-a4000` | `playbook-media-01.yaml` | compose `environment:` |
| eta | `host_vars/eta/vars.yaml`, via `tdarr_node_win_workers` | user-level environment variables |

⚠ **media-01 runs two components with a worker each**, so it can hold two concurrent jobs. Only the
A4000 takes work from this flow — the Arc fails at the GPU guard — so the effective count here is
one. The recipe's worker table predates the two-card split and has not caught up.

**There is no config-file route.** `Tdarr_Node_Config.json` has no worker key — Tdarr documents
these separately, under *"Worker Configuration (Node Only - Environment Variables)"* — so an
environment variable is the only way to set them from configuration. The precedence is
*"Environment Variables take precedence, followed by JSON files, then defaults"*, which is why
setting them takes the counts away from the UI rather than merely seeding it.

⚠ **eta needs a logoff/logon, not a node restart.** A user-level variable is not visible to a
running session. Since the node autostarts from that account's Startup folder, one logoff/logon
applies the variable and restarts the node together.

⚠ **One thing unconfirmed on the box:** whether the server container's internal node honours these
four variables. Tdarr documents them as *Node only* and its variables page does not mention
`internalNode` at all, though third-party compose files do set them on the server. If media-01's
counts do not move, that is the reason.

## Per-lane concurrency, when the M4 lane arrives

Worker counts are per **node**, not per library, and Tdarr has no native library-to-node
assignment. The kids lanes want 1/1/1 and the M4 lane wants 2/3/1, and one node cannot hold both.

The options, labelled honestly:

| mechanism | what it is |
|---|---|
| Library schedules — non-overlapping hours | built-in, coarse, no code |
| The `Process Library` toggle | built-in, manual. What `tdarr-av1-flow.md` already does for the AV1 flows |
| One node instance per lane per host, pinned with node tags and `tagsRequeue` | gives real per-lane counts. Needs an instance suffix in the roles, and does **not** by itself stop the two lanes running at once |
| A flow-level lock | does not work. Tdarr assigns a worker before the flow runs, so a lock inside a flow idles a claimed worker instead of freeing the GPU |

## Files

| Path | Purpose |
|------|---------|
| `ansible/files/media-01/tdarr/tdarr-flow-ipad-kids.json` | The flow. **Imported through the Tdarr UI** — nothing deploys it |
| `.../tdarr-plugins/.../LocalFlowPlugins/tools/selectOutputStreams/` | Audio/video selection with the default-audio fallback |
| `.../tdarr-plugins/.../LocalFlowPlugins/tools/setScaledGeometry/` | `bsfW`/`bsfH` for the vaapi bitstream filter |
| `ansible/playbook-media-01.yaml` | Deploys both plugins to the server, which distributes them to nodes |
| `ansible/playbook-htpc-01.yaml` | htpc-01 worker type and `AMD_DEBUG` |
| `ansible/host_vars/eta/vars.yaml` | eta's worker counts |
| `media-library-discovery/TDARR-TRANSCODE-PLAN.md` | The recipe — every number, with provenance |
