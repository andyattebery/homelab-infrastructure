# Strata on htpc-01 or media-01 (2026-11-14)

Researched 2026-11-14. **[I]** marks inference. Every figure without it is a published measurement or a vendor spec,
cited.

**The questions:**
- What would Strata (Qwen3.8-Flash-Next) do on htpc-01, given 64 GB of RAM and an RX 9070 XT with no other workloads,
  against media-01's RTX A4000 with ~104 GiB? htpc-01's Ryzen 5 5600GE could be swapped for a Ryzen 5 5600X3D.
- What drives Strata's speed, and does an 8-channel CPU help?

## Bottom line

- **On every published run, a 16 GB card decodes IQ3_S / IQ3_XXS at about 45-58 tok/s.** That holds for NVIDIA and
  AMD, with 2- or 4-channel RAM and 6-24 cores (table below).
- **Strata's own profile of one decode step explains why** (QUANTS.md:108-115, R9700 32 GB with an 8-channel EPYC):
  - ~60-65% of the step is fixed per-step latency: the small GPU kernels and the MTP draft, "the same for every model".
  - The CPU's share, read at full RAM bandwidth, is **~1.2 ms of a 34.3 ms step**, run alongside the GPU's work.
- **VRAM is the lever that moves decode.** The same machine with a 32 GB card instead of a 16 GB one decoded 36-48%
  faster (AMD_HIP.md:429-436).
- **Memory channels are not, at these hit rates.**
  - The CPU pool is bandwidth-bound, but six Zen 3 threads already saturate dual-channel DDR4 (QUANTS.md:117-127).
  - On a 16 GB card the CPU path should still finish inside the GPU's part of the step **[I]**.
  - An 8-channel CPU would shorten a part that is mostly hidden.
- **So htpc-01, with either CPU, and media-01 would decode about the same [I].** htpc-01's link and RAM match the best
  16 GB row: RX 9070 + Ryzen 7 5800X3D, 64 GB dual-channel DDR4-3200, a 14.1 GB/s link, 58 tok/s on IQ3_XXS.
- **The 5600X3D is not worth buying for Strata alone [I].**
  - It adds 105 W clocks and PCIe 4.0, the latter only on a B550/X570 board. Neither is where Strata's decode time goes.
  - Without an iGPU, the 9070 XT also has to drive the desktop. Strata then keeps 3 GB of VRAM free, costing "a few %".
- **The differences that do matter are not speed.**
  - At 64 GB, htpc-01 realistically runs IQ3_XXS: IQ3_S is Strata's "64 GB PC with little else running" case
    (`setup.py:440-441`).
  - media-01 runs IQ3_S, is up 24/7, and needs nothing bought.
- **Recommendation: media-01.** It is deployed there; measured results follow.

## Measured on media-01 (2026-11-15)

The setup was Strata 0.2.13 (engine 0.1.59) in Docker, Qwen3.8-Flash-Next IQ3_S at 128K, `ple-io=direct`, on the RTX
A4000 with 102.2 GiB of RAM. Both runs are Strata's standard benchmark (`strata bench run`, protocol
`strata-qwen38-thinking-v1-draft.1`, corpus `standard-v1`), over loopback, each on a freshly loaded engine. Both are
**complete**, with 12 of 12 sanity checks, all four tool calls among them.
- In run #1, Obico ML still held 1,480 MiB, so the expert cache had 3,785 slots (7.23 GiB).
- In run #2, Strata had the card to itself: 4,553 slots (8.68 GiB).

Each cell is the median of three; time to first token is from run #2.

| Case | Prompt tok/s, #1 → #2 | Decode tok/s, #1 → #2 | Time to first token (#2) |
| --- | ---: | ---: | ---: |
| short (~80 tokens) | n/a | 38.3 → 49.8 | 0.85 s |
| 4K | 1,030 → 1,048 | 44.7 → 47.1 | 3.9 s |
| 16K | 1,428 → 1,646 | 46.4 → 41.1 | 10.0 s |

- **Decode landed in the 16 GB band** predicted above: 41-50 tok/s across both runs. That movement is within the
  10-15% run-to-run spread upstream reports.
- **Prompts read 2-4x faster than every 16 GB community row** (343-833 tok/s on engines 0.1.35-0.1.41). Newer engines
  and media-01's PCIe 4.0 x16 both plausibly contribute; these runs cannot separate them **[I]**. The larger cache added
  15% at 16K.
- From the engine's own log:
  - an expert cache of 3,785 slots in run #1 and 4,553 in run #2, with ~760 MiB of VRAM free with everything loaded
    both times;
  - decode hit rates of 61-87%, with a further 5-17% of routed experts fetched over PCIe;
  - KV streaming with 32,768 of 131,072 cells per layer in VRAM and 1.55 GiB pinned in RAM;
  - "PLE direct read probe: 19405 rows/s (fine)". The ZFS read path for the n-gram table is above Strata's 15K warning
    line.
- RAM: Strata added ~59 GiB to the VM's "used" (9 → 68 GiB of 102), in line with the ~64-66 GB estimate before its
  conversation cache fills.

## What matters most for speed, in order

1. **VRAM, i.e. the size of the expert cache.**
   - Same machine (AMD_HIP.md:429-436): an R9700 32 GB holds 12,288 slots and an RX 9070 XT 16 GB holds 4,931. Decode is
     45.5 vs 30.8 tok/s at 4K (+48%) and 48.3 vs 35.4 at 16K (+36%); prompt is +13-26%.
   - Strata's own cross-card estimates scale "the CPU part by how many more experts the card's VRAM holds"
     (DETAILS.md:1458).
   - Both hosts here have 16 GB (A4000 4,686-5,435 slots, 9070 XT 4,931-4,983).
2. **Per-step latency on the GPU side: small kernels and the MTP draft.**
   - "Decode runs at ~35-40% of that bound for every file, IQ3_S included: … the rest is the per-window latency of the
     small kernels and the draft, the same for every model" (QUANTS.md:114-115).
   - The engine is what moves it: the sm_86 kernel set alone gave the A4000 +13% (DETAILS.md:1521).
   - The host thread that drives those kernels plausibly matters too **[I]**.
3. **The quant.** On an RTX 5070: Q2_0 94, IQ3_XXS 62, IQ3_S 53 tok/s (MODELS.md history).
4. **Context length.** IQ3_S drops from 53 to 46 tok/s between a short chat and 128K (RTX 5070).
5. **The CPU pool that computes cache misses.**
   - It is bandwidth-bound, but small. Pool workers: 8 gave 36 tok/s, 15 gave 40, 24 gave 27 (AMD_HIP.md:522-528).
     Oversubscription hurts more than a few cores fewer.
6. **Keeping some VRAM free.** One 0 MiB-free run decoded at 13.7 tok/s against 102 (DETAILS.md:1500-1508).
7. **RAM is a cliff, not a slope.**
   - Below the experts + 10 GB, low-RAM mode reads experts from the SSD, "much slower".
   - Above it, extra RAM buys only the n-gram table tier: prompt +9-22% on an R9700, +2-18% on an RTX PRO 5000, decode
     +0.8%.
8. **The GPU's own class matters little for decode:** 448 GB/s NVIDIA and 640 GB/s AMD 16 GB cards cluster at 45-58. For
   **prompts**, GPU compute and PCIe matter more, because experts stream to the card in each 8K chunk.

## Context length: the model's limit and what it costs

**The model was trained on 262,144 positions (256K)** (DETAILS.md:627).
- Past that, Strata extends it with YaRN rope scaling, to 524,288 in its menu (`CONTEXTS`, `setup.py:684`). Engine tests
  have run 786K-1M (DETAILS.md:1494,1507).
- Scaling is **experimental**: "a scaled run is a slightly different model". The quality evidence is text only, and
  setup switches scaling on only past 256K (DETAILS.md:625-640).

**What limits it on media-01:**
1. **RAM, not VRAM.**
   - From 64K, the KV cache streams from RAM at ~13.7 KB per token with 8-bit KV: 1.8 GB at 128K, 3.6 GB at 256K,
     7.2 GB at 512K (`setup.py:6488-6492`). Past 256K, rope tables add ~0.26 KB per token, and q4_0 KV halves the cost.
   - VRAM keeps 32K positions per layer, so it stays flat. The share of KV reads served from VRAM falls with length:
     99% at 4K, 95% at 130K on the RX 9070.
   - Strata's own 128K default exists because "a 260K-token context brings a 64 GB PC to its memory limit"
     (DETAILS.md:78-79). At 104 GiB, 256K costs 1.8 GB more than 128K.
2. **Decode slows as the window fills.** IQ3_S went 52-53 → 48.3 (32K) → 45.5 tok/s (128K), and Q2_0 lost 31% by 262K
   (RTX 5070, DETAILS.md:64-70). IQ3_S at 262K is unmeasured.
3. **Fresh-prompt time.** Time to first token is the prompt length divided by prompt speed. Even on the RTX 5070 with
   Q2_0 that is "under 2 minutes at 128K and 4.5 minutes at 262K". On the A4000 it would be longer **[I]**.
   - Agents mostly avoid this, because Strata's prompt cache re-reads only each turn's new tokens.
   - A history rewrite, such as Hermes compacting, is a fresh read of whatever remains **[I]**.
4. **Hermes compacts its own history** at a threshold `strata connect` derives from the window (`harness.py:157-159`).
   A larger window means fewer compactions, but each turn runs closer to full.

**Setting `CONTEXT` explicitly matters.** Left empty it means "the largest that fits". Setup's RAM rule (arena + KV +
24 GB, `setup.py:6672-6690`) would allow 512K at 104 GiB, which is past 256K and so with YaRN **[I: before the GPU-side
cap it also applies]**.

## Memory bandwidth and channel count

**What Strata measured** (QUANTS.md:93-127). The box was an R9700 32 GB with an EPYC 7452: 8 channels of DDR4-2400, 106
GB/s measured. The model was UD-Q4_K_XL at 2.0 tokens per step.
- A step took 34.3 ms against a ~12.5 ms bandwidth bound.
- The CPU pool's experts took **1.2 ms of it, in parallel with the GPU**.
- The pool's kernels run at 84-97% of RAM bandwidth.
- Pool efficiency at 1 token and at 3 tokens per expert:

| CPU | Threads | 1 token per expert | 3 tokens per expert |
| --- | ---: | ---: | ---: |
| EPYC 7452 | 32 | 96-97% | 80-93% |
| **Ryzen 5600X (6-core Zen 3)** | 6 | **100%** | **85-100%** |
| Xeon E5-2643 v3 | 12 | 94-99% | 36-64% |

**On a 16 GB card [I].**
- The cache holds ~20% of the experts rather than ~50%, so the CPU path does perhaps 2-4x more:
  - ~6-11 ms per step at dual-channel DDR4-3200;
  - ~3-6 ms at media-01's ~72-85 GB/s.
- Steps run ~50-60 ms (~50 tok/s at 2.5-3 tokens per step), and the CPU path runs alongside the GPU's work. It stays
  hidden unless it grows longer than the GPU's part.
- The measured rows agree. The quad-channel, 24-core Threadripper with a 9070 XT (IQ3_S 45.2) did not beat the
  dual-channel 8-core boxes: the 5060 Ti + 3700X ran IQ3_S at 47.7-48.2, and the 9070 + 5800X3D ran IQ3_XXS at 58.

**When channels would matter [I]:** when the CPU path becomes the long one. That happens with a much lower hit rate (a
smaller card, or a model whose experts far exceed VRAM), or in the RAM-budget and low-RAM modes.

**media-01's 8 channels deliver ~72-85 GB/s, not 204.** The EPYC 7282 is capped by its two CCD links: AMD rates it
85.3 GB/s and "optimized for 4 channels" (WikiChip, ServeTheHome). That bandwidth is also shared with nas-01.

## Published measurements (Strata, 16 GB cards)

| Card | CPU | RAM | Model, context | Engine | Decode tok/s | Prompt tok/s | Expert cache | Source |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| RTX A4000 | not stated (slow pool: 97-115 µs per expert) | not stated | IQ3_XXS | 0.1.45.3 | **51.2 → 57.8** (sm_86 switch set) | - | - | DETAILS.md:1520-1521 |
| RTX A4000 | not stated | not stated | IQ3_XXS, 65K | 0.1.45 | 46.0-48.4 | - | 4,686-5,435 slots | DETAILS.md:1453 |
| RTX 5060 Ti 16 GB (448 GB/s, like the A4000), Gen4 x8 at 14.1 GB/s | Ryzen 7 3700X, 8C Zen 2, 2-ch | 78 GiB (WSL2) | IQ3_S, 131K | 0.1.41 | 47.7-48.2 | 343 (4K), 598 (20K) | 3,627 slots | bench/results/2026-10-09-community-rtx-5060ti-wsl2-iq3_s-0141 |
| RX 9070 XT, 28.6 GB/s link | Threadripper 3960X, 24C | 128 GiB, **4-ch** DDR4-3200 | IQ3_S, 65K | 0.1.35 | 45.2 | 370 (4K), 601 (32K) | 4,983 slots | bench/results/2026-10-02-community-rx9070xt-windows |
| **RX 9070 (non-XT), 14.1 GB/s link** | **Ryzen 7 5800X3D, 8C Zen 3** | **64 GB, 2-ch DDR4-3200** | IQ3_XXS, 131K | 0.1.41 | **57.9-58.7** | **586 (4K), 804 (33K), 833 (130K)** | 4,776 slots | bench/results/2026-10-10-community-rx-9070 |
| RX 9070 XT | Ryzen 9 3900X | 47 GB, Linux VM | Coder IQ1_M, 32K | 0.1.30 | 30.8-35.4 | 782 (4K), 1,235 (16K) | 4,931 slots | AMD_HIP.md:429-436 |
| RTX 5070 12 GB | Ryzen 5 7600, 6C Zen 4 | 64 GB DDR5-5200 | IQ3_S / IQ3_XXS, short chat | 0.1.26 | 53 / 62 | - | - | MODELS.md history; DETAILS.md:44 |

10-15% between sessions of the same configuration has been reported (RX 9070 report). Gaps smaller than that across
rows mean nothing.

## How the hosts differ

| | media-01 | htpc-01, 5600GE (today) | htpc-01, 5600X3D |
| --- | --- | --- | --- |
| GPU | RTX A4000 16 GB, 448 GB/s | RX 9070 XT 16 GB, 640 GB/s | same |
| Link to the GPU | PCIe 4.0 x16 [I: card and board are Gen4; not probed] | PCIe 3.0 x16 (AMD spec), ≈ the 14.1 GB/s of the best 16 GB row | PCIe 4.0 **on a B550/X570 board**; 3.0 on B450/A520. The board is not recorded |
| CPU pool | 24 vCPU of an EPYC 7282 (Zen 2) on a host shared with nas-01 (40 vCPU on 32 threads) | 6C/12T Zen 3 at 35 W: enough threads to saturate its RAM (5600X row above); the 35 W cap's effect on the host thread is unmeasured | 6C/12T Zen 3 at 105 W, 96 MB L3 |
| Memory bandwidth | ~72-85 GB/s per socket, shared | 2-channel DDR4-3200, 51.2 GB/s theoretical | same |
| Display | none | the iGPU can carry it | **the 9070 XT**, so Strata reserves 3,072 MiB: "~2.3 GB less [cache], a few % of speed" (`setup.py:8083-8101`) |
| RAM for Strata | ~104 GiB VM: IQ3_S with ~14 GiB spare over the 22.8 GiB measured peak of everything else | 64 GB minus the iGPU carve-out and the desktop: IQ3_XXS in practice | 64 GB minus the desktop: IQ3_XXS in practice. IQ3_S at ≥ 96 GB (max 128 GB [I: aggregator spec]) |
| n-gram table (28.8 GB of random 90-byte rows) | guest ZFS dataset `data`: 64K records, lz4, `direct=standard` (measured 2026-11-15), on a zvol on the Optane 905P. Strata reads 4 KiB pages directly, 16 in flight, so each read likely pulls a whole 64K block **[I]**. Probe: 19,405 rows/s | SK hynix P41 NVMe, Gen3 lanes | P41 on Gen4 lanes (board permitting) |
| Up | 24/7 VM | HTPC that sleeps (Wake-on-LAN ~12 s) | same |
| Strata path | CUDA; the A4000 is measured by Strata's maintainers | HIP gfx1201; the 9070 XT is maintainer-tested; Linux `rx9070` uses plain hipBLAS | same |
| What it displaces | the A4000's workloads (Immich ML, Obico, Whisper, the Tdarr node, gpu-encoder-sweep, kohya_ss) | the 9070 XT's: llama-swap (local-deep-research's backend), ComfyUI, gaming | same, plus the iGPU's work |
| Cost | none (RAM reallocation) | 32 → 64 GB of DDR4 | the CPU (end-of-life, US-only launch) + RAM |

## Decision: which host

**The question:** run Strata on media-01 or on htpc-01, and is a 5600X3D worth buying for it?

**htpc-01 with the 5600GE.**
- For:
  - the strongest GPU;
  - its link and RAM match the best 16 GB row's;
  - an NVMe drive for the n-gram table;
  - no hypervisor.
- Against:
  - 64 GB means IQ3_XXS;
  - it is the HTPC and sleeps;
  - it displaces llama-swap, ComfyUI and gaming;
  - the RAM must be bought;
  - the 35 W cap and the Podman/SELinux path are untried for Strata.

**htpc-01 with a 5600X3D.**
- For: higher clocks, and PCIe 4.0 on a B550/X570 board.
- Against:
  - neither is where Strata's decode time goes **[I]**;
  - the 9070 XT then drives the display (a few %);
  - the CPU must be bought, and it is end-of-life.
- Not worth it for Strata alone.

**media-01.**
- For:
  - IQ3_S fits with room;
  - it is up 24/7;
  - nothing to buy;
  - the exact card has maintainer measurements;
  - the documented Docker path.
- Against:
  - a weaker GPU on paper (measured above, it decodes in the band and reads prompts faster than any published 16 GB
    row);
  - a host shared with nas-01;
  - a ZFS read path for the table (measured since at 19,405 rows/s, "fine");
  - ~40 GiB of nas-host-01's RAM;
  - it displaces the A4000's workloads.

**Recommendation: media-01.** On the evidence it decodes as fast, it serves the better quant, it is always on, and it
costs nothing.

**What would change it:**
- **htpc-01 at ≥ 96 GB and kept awake.** IQ3_S then fits there too.
- **The owner preferring to keep media-01's A4000 workloads** over htpc-01's llama-swap, ComfyUI and gaming.
- **A measured htpc-01 figure >15% above media-01's** on the same quant.
- **For speed itself, a card with more VRAM**, the one lever that moved decode materially: +36-48% at 32 GB.

## Open questions (unmeasured)

- htpc-01's speed with engine 0.2.13. media-01 is measured above, and every published row is 0.1.26-0.1.45; later
  engines are faster (AMD_HIP.md:438).
- htpc-01: the board's chipset and DIMM slots, the desktop's RAM use, and whether the 5600GE's 35 W cap slows the host
  thread.
- media-01: the pool-worker count on 24 vCPUs. 24 workers was slower than 15 on the 6900 XT box.
- media-01: what the 64K records cost the n-gram reads.
  - Strata reads 4 KiB pages directly, 16 in flight (`src/ngram/ple_reader.cpp`).
  - ZFS checksums whole blocks (OpenZFS "Checksums"), so each 4 KiB read likely pulls a 64K block **[I]**.
  - The probe measured 19,405 rows/s. That is "fine" by Strata's 15K line, but a fifth of the ">100k" its source
    expects from "a healthy NVMe" (`src/program/generate.cpp:5978`). 19,405 × 64 KiB ≈ 1.3 GB/s of physical reads.
  - The ceiling on any gain is Strata's own table-in-RAM A/B: prompt time −2% to −18%, decode ~0-0.8%.
  - Untested: a dataset with 4-16K records holding the table, and the host zvol's `volblocksize`.
- The CPU path's real share of a step on a 16 GB card. `STRATA_DECODE_TIMING=1 STRATA_VERIFY_PROFILE=1` prints it
  (QUANTS.md:108).

## Sources

- Strata at commit `baf16363` (`main`, 2026-11-15). Line numbers are from that commit, because `main` moves daily:
  - docs/DOCKER.md, MODELS.md, DETAILS.md, AMD_HIP.md, QUANTS.md (93-127), TROUBLESHOOTING.md, LLAMA_SWAP.md,
    VRAM_ELASTIC.md;
  - `setup.py`: `MODELS` (IQ3_S at 440-441), `CONTEXTS` 684, `ram_gb` 1089-1106, `LOW_RAM_HEADROOM_GB` 6405,
    `low_ram_gpu_gb` 6434-6442, `kv_streaming_ram_gb` 6488-6492, `ctx_ram_need` / `ram_ctx` 6672-6690, display reserves
    8083-8101;
  - `strata_control/setup_config.py:274-290`;
  - the bench/results READMEs named in the table.
- Ryzen 5 5600GE, AMD spec via [cpu-monkey](https://www.cpu-monkey.com/en/cpu-amd_ryzen_5_5600ge): PCIe 3.0, 2-channel
  DDR4-3200, 35 W.
- Ryzen 5 5600X3D: [TechSpot](https://www.techspot.com/specs/cpu/282921-amd-ryzen-5-5600x3d.html),
  [KitGuru](https://www.kitguru.net/components/cpu/leo-waldock/amd-ryzen-5-5600x3d-review-a-new-zen-3-cpu-in-2023/all/1/),
  [SHI](https://www.shi.com/product/46460183/AMD-Ryzen-5-5600X3D-3.3-GHz): PCIe 4.0, 105 W, 96 MB L3, no iGPU.
- EPYC 7282 bandwidth: [WikiChip](https://en.wikichip.org/wiki/amd/epyc/7282),
  [ServeTheHome](https://www.servethehome.com/amd-epyc-7002-rome-cpus-with-half-memory-bandwidth/),
  [ahelpme MLC run](https://ahelpme.com/ai/llm-inference-benchmarks-with-llamacpp-and-amd-epyc-7282-cpu/).
- OpenZFS [zfsprops(7)](https://openzfs.github.io/openzfs-docs/man/master/7/zfsprops.7.html), `direct`.
- This repo: hardware/host-inventory.md:119-130,163; research/local-llm/docs/README.md:79-86.
