# Test results (evidence: <projects>\<project>\orch_journal.json, logs\, reports\)

## 2026-10-21 — self-test sword (`forge_selftest`, Blender 5.2.2 headless)

| step | result | time | note |
|---|---|---|---|
| make (procedural sword) | ok | 2.8 s | the work .blend did not exist: started with `--factory-startup` and saved to FORGE_WORK |
| s0_adopt | REVIEW (expected) | 2.0 s | was 3.5 min in the UI Blender (viewport recompiling materials) |
| approve s0 | ok | 1.9 s | |
| s1_highpoly | **ERROR → stop** (first run) | — | real bug: inspection camera missing after reload. Fixed in forge_render (camera re-created when missing) |
| s1 resume after fix | REVIEW (expected) | 5.7 s | the orchestrator **skipped** make/s0/approve (same fingerprint) and resumed at s1 |
| s2_variants with injected TRANSIENT failure | attempt 1 failed, **attempt 2 ok** | 34.9 s | the .blend was restored from the pre-step backup before the retry |
| fatal_probe (s4_bake_check without a bake) | **ERROR, not retried** (non-transient) → stop | 1.7 s | clear traceback in logs\fatal_probe_*.log |

Variant metrics on the self-test sword (ray-cast, 10 views):

| tag | tris | IoU min | depth p95 worst (mm) | normal p95 worst (deg) | critical |
|---|---|---|---|---|---|
| A_3k | 2998 | 0.995 | 0.66 | 26.7 | – |
| B_3k (voxel) | 3000 | 0.974 | 4.84 | 51.2 | nonmanifold, folds |
| A_1.5k | 1498 | 0.958 | 1.51 | 42.6 | nonmanifold (rule now relative to edge count) |
| C_3k | ERROR | | | | vertex group removed after apply. Fixed: removed by name |

Conclusions so far:
- Orchestrator mechanics pass: retry of transient errors, stop on fatal ones, resume with skip, review stops, ledger lines.
- On a simple sword, voxel remesh (B) is clearly worse than direct decimation (A).

## 2026-10-21 — Inferno Dragon Sword: low-poly method and budget (same 1.5M-tri high poly, headless)

Ray-cast metrics over 10 views (worst view). Deviation is a two-sided surface distance (p99).

| tag | tris | folds >150° | IoU min | depth p95 (mm) | normal p95 (deg) | dev p99 low→high / high→low (mm) | critical |
|---|---|---|---|---|---|---|---|
| **A_10k** | 10 000 | 6 | 0.9909 | 0.444 | 26.9 | 0.42 / 0.40 | – |
| **A_18k** | 18 000 | 8 | 0.9945 | 0.317 | 22.1 | 0.25 / 0.24 | – |
| **A_25k** | 25 000 | 11 | 0.9959 | 0.238 | 19.9 | 0.19 / 0.18 | – |
| B_18k (voxel) | 18 000 | 14 | 0.9917 | 0.354 | 24.4 | 0.27 / **5.87** | – (loses thin details: high→low) |
| C_10k (weighted) | 10 000 | 8 | 0.9709 | 1.879 | 37.1 | 1.22 / 1.28 | – |
| C_18k (weighted) | 18 000 | 4 | 0.9669 | 1.571 | 32.5 | 0.97 / 0.96 | – |
| C_25k (weighted) | 25 000 | 5 | 0.9798 | 1.453 | 30.6 | 0.85 / 0.87 | – |
| old low poly (SMv3, before forge) | 17 945 | 286 | – | – | – | 2.5 (p99) | – |

Time per candidate: about 60 s to build and measure. The comparison sheet added about 100 s. The 18K step took 865 s, the budgets step 1121 s.

Findings:
1. Method **A (symmetric collapse + fold repair) wins clearly** at every budget. C's weights (decimate the blade/grip more) cost more than they gave. B (voxel) loses thin features (high→low p99 5.9 mm).
2. A_18k is 10× more accurate than the low poly we had used for all previous bakes, with 35× fewer folds. The earlier seam/crease problems started there.
3. Budget: 10K→18K is a large gain, 18K→25K a small one. The rule "fewest tris within 20 % depth / 15 % normal of the best" is provisional: it picked A_25k inside the budgets step and A_18k inside the 18K step. Final weights wait for calibration on more swords.

Bug found by the run: a name clash (`_aim` defined in forge_render and in media_kit). The full-length views rendered empty. Metrics were unaffected (independent ray model). Fixed, and the loader now refuses to run with name clashes (lesson 14).


## 2026-10-21 — trial tooling on the self-test sword (A_3k vs D_3k, 256 px bakes)
| run | finding |
|---|---|
| 4 | trials ran end to end, but lit renders were unlit → inspection lights missing (lesson 19), fixed |
| 5 | lit high OK, lit low black → s1-type bug: shared material left disconnected by the baker (lesson 17), fixed + repair step |
| 6 | low still black on metal → DIFFUSE bake is black for metals (lesson 18), BaseColor now baked by emission |
| 7 | **lit low matches lit high** (SSIM ≈ 1.0 on all 9 views for A_3k); D_3k slightly worse (0.92–0.98) on the simple sword |

## UV recipe port (1.1.3) — 2026-10-21

### Container, same mesh as the old 74 % tool (old dragon low poly SMv4, 17 945 tris), audited with `uv_audit`
| layout | coverage (area sum) | coverage (raster 4K) | min gap px @4K | pairs < 16 px | overlap px | flips | aniso p95 | texel p95/p5 |
|---|---|---|---|---|---|---|---|---|
| old uvpack4 "74 % / 16 px" (q2048_74) | 0.7374 | 0.7305 | **10.47** | 402 | 0 | 0 | 1.511 | 1.825 |
| old charts + new packer (Euclidean padding) | 0.6977 | 0.6909 | 17.04 | 0 | 0 | 0 | 1.511 | 1.822 |
| new charts + new packer | 0.7000 | 0.6934 | 17.20 | 0 | 0 | 0 | 1.329 | 1.995 |
74 % with a true 16 px gap does not fit on this sword: 0.74 and 0.72 failed, 0.70 packed.

### Blender 5.2.2, self-test sword (2 998 tris, straight_simple)
| | smart-project (1.1.2) | forge recipe |
|---|---|---|
| coverage (area) | 0.311 | 0.550 (gate FAIL for straight_simple: thin strips + 16 px padding) |
| overlap px @4K / flips / zero-area | 598 / 6 / 1 | 0 / 0 / 0 |
| min gap px | 30.0 | 17.3 |
| applied in Blender = packed | — | max diff 3e-8, islands 55/55 |
| 256 px trial, mean SSIM lit / metal+normal (same code, `trial_rescore`) | 0.9277 / 0.9432 | 0.9264 / 0.9422 |

## 1.2 — weapon fit, candidates and edits (2026-10-21)

### Three AI versions of the dragon sword (source/01-03.glb), same code and cameras
| | 01 (the version used until now) | 02 (chosen) | 03 |
|---|---|---|---|
| grip | 14.8 cm | 11.8 cm | 13.6 cm |
| solid-steel mass | 25.0 kg | 30.4 kg | 40.3 kg |
| mirror deviation p50 | 1.05 mm | 0.66 mm | 0.46 mm |
| close-ups | segmented gem ring, wavy junction, dotted pommel ridges | smoothest gem ring and junction | melted lump mid-blade, specks |

### Version 02 edits (project inferno_dragon_v2)
| | before | after |
|---|---|---|
| grip | 11.8 cm | 20.1 cm (stretch x1.88 of the wrap) |
| blade / guard volume | 1.58 L / 1.96 L | 0.63 L / 1.15 L (blade x0.4, guard x0.5, gem protected) |
| solid-steel mass | 30.5 kg | 16.7 kg |
| front extents | 0.460 x 1.259 m | unchanged |
| per-slab ratio error vs requested profile | — | p95 0.0, max 0.0006 |


## 1.2.1 — dark dots on the dragon v2 bake (2026-10-21)
| | 1K before | after fix_folds | after fix_folds + fix_sliver_normals |
|---|---|---|---|
| folded edges > 90° (high) | 95 | 0 | 0 |
| vertices changed | — | 140 moved ≤ 0.3 mm | + 244 shading normals |
| dark dots in the trial views (blade_mid, tip, pommel) | 4 | 1 | 0 |
| SSIM metal+normal (mean of 9 views) | 0.9149 | 0.9139 | 0.9138 |
| UV coverage (s3) | 0.68 | 0.65 | 0.65 |
Remaining: one small light speck on the guard (guard_left view), light pixels along the guard opening edge at 1K,
stair-stepped blade edges (geometry from the AI model, unchanged).
Experiments: exp_20261021_171006_c48a, exp_20261021_175346_72f7.
