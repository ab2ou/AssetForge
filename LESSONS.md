# Lessons → the gate that now prevents them

From the Inferno Dragon Sword (October 2026). Each mistake cost a re-bake, a re-export or hours. Each one now has a check.

| # | what went wrong | cost | where it is caught now |
|---|---|---|---|
| 1 | Decimating to 18k left folded triangles (inward creases > 150°): a crumpled surface and dark shards in close-ups. | 3 full bakes and a lava pass on bad geometry | s2: `concave_folds` + fold repair + flat-shaded compare sheet |
| 2 | Smooth-by-angle (40°) left 6,862 hard edges *inside* UV islands. The normal map cannot fix a hard edge without a seam, so lines and creases showed after baking. | found last | s3: `hard_edges_inside_islands == 0`; hard edges only on seams |
| 3 | UV coverage pushed to 80 %: the packer cut more islands, giving more visible seams. Then we went back to 74 %. | 1 repack, 1 bake | s3: coverage target 0.65–0.78, REVIEW of seams on smooth faces |
| 4 | Seams across a glossy sphere (the gem) showed as lines. | 2 bakes | s3 REVIEW `seam_placement`; s4 close-up `guard_center` |
| 5 | Hidden but still selected objects (collars, then the 750k high poly) went into the GLB/OBJ. A 137 MB GLB, and Blender stuck for 75 min. | ~1.5 h | s7 deselects every object first; GLB size check; re-import validate |
| 6 | The lava V-arms were missing on the high poly, and dotted ridges went unnoticed. The user found them. | trust | s1/s4: mandatory close-up compare sheets (10 views) before any report |
| 7 | Long Cycles renders were used for diagnosis (4 min each). | hours | EEVEE inspection renders; Cycles only in s8 |
| 8 | 39 checkpoints of 0.8 GB filled drive C. Blender froze and had to be killed. | 1 restart | checkpoints: last 2 per stage, older ones to `archive/`; projects live on D |
| 9 | File transfers sometimes delivered an old copy. | several retries | write under a new name and verify inside Blender (MD5, or pixels for PNG) |
| 10 | The high-poly lava preview was baked into the textures. | — | `before_bake` / `after_bake` hooks switch preview overlays off and on |
| 11 | The edge glow was added, then removed, by request. The lava was drawn in the wrong zones. | 3 passes | s5 REVIEW with images *before* exporting |
| 12 | Repairs were applied to one area only (the gem) when the defect was everywhere. | — | fix the cause, re-run the stage gate on the whole mesh |
| 13 | A diagnostic render picked up the wrong object because visibility was not restored. | confusion | `render_views` sets visibility explicitly and restores it |
| 14 | Two files defined `_aim`. In the one shared namespace the later one silently won, so full-length views rendered empty. | 1 re-render | the loader lists name clashes and `check_environment` refuses to run |
| 15 | We assumed the existing 18k low poly was "good enough" and spent days fixing its bakes. A measured comparison showed a fresh symmetric decimation was 10× more accurate. | days | s2 variants: build candidates and measure them before UV/bake |
| 16 | Diagnostics in the UI Blender froze the viewport for minutes and twice hung Blender. | hours | the orchestrator runs every step headless (forge_orch.py) |
| 17 | The baker rerouted a material shared by two objects twice, then failed to restore it. `B_ferrule_metal` (both collars) was left with no Surface link, so every bake since the first one saw broken collars. | all previous bakes | baker routes each material once and restores in reverse order; s1 gate `materials_connected` + `repair_disconnected_materials` |
| 18 | BaseColor was baked with the DIFFUSE colour pass, which is black on metallic surfaces. Metals came out black or too dark. | all previous bakes | BaseColor is baked by an emission reroute of the Base Color socket; trial renders compare lit low vs high |
| 19 | Lights and camera of the inspection scene did not survive save/reload, so lit renders were unlit. | 2 reruns | `_inspect_scene` re-creates them on every call |
| 20 | The old packer's "16 px padding" was a 4-cell *diamond* dilation. Measured exactly, the closest islands were 10.5 px apart (402 island pairs under 16 px). The "74 %" coverage was partly bought with missing padding. | a bleed risk in every bake | `uv_pack` dilates with a Euclidean disk; s3 measures the exact boundary-to-boundary gap (`uv_min_gap_px`) |
| 21 | Coverage numbers were compared without checking the definition (area sum vs pixel raster). | wrong comparisons | `uv_audit` reports both and states each definition |
| 22 | Long thin pieces (thin blade sides) longer than the texture made the packer fail on the self-test sword. | 2 failed runs | long pieces are cut across, placed first; unsplittable slivers are scaled and listed; blade / edges / gem are never shrunk to fit (lower coverage instead) |
| 23 | Smart-project UVs on an ornate sword: 25 % coverage, 837 islands, overlaps. | 1 trial bake | the forge UV recipe (charts by class + LSCM + FFT packing) is the s3 default |
| 24 | The weapon itself was never checked: the dragon sword went through low poly, UV and bakes before anyone measured it (as solid steel 18 kg, balance behind the guard; the AI original's grip did not fit two hands). | a stopped UV queue | `s0_spec` before any work; s1 requires it |
| 25 | A statement about the geometry ("the dimensions did not change") was made without measuring; the real changes were +7.5 cm length, +5.3 cm grip. | trust | evidence first: measure, then speak (`record_experiment`, lessons need evidence files) |
| 26 | Imported GLBs split vertices at UV/normal seams: 1 520 "open edges" on a closed test sword. | false alarms | candidates are welded before counting holes |
| 27 | A model in wrong units (x100) made the volume grid explode (9+ min, killed). | 1 hung run | grid cell = max(2 mm, length/600); scale_plausible FAIL suggests the factor |
| 28 | A killed orchestrator left its lock file and blocked the project for 6 h. | manual unlock | the lock is taken over when its process is not running |
| 29 | `forge_specs` re-implemented weight/balance while `scripts/mass_balance.py` already existed with sourced ranges and the agreed rule "fantasy = warning band only"; fantasy swords were wrongly FAILed on weight. | a wrong decision path for the user | audit existing modules first (CONTRIBUTING 2); fantasy physics = REVIEW band; balance ranges from mass_balance.py |
| 30 | Thinning only the guard left the thick blade next to it: a visible shade line at the junction. | 1 redo | `thin_profile`: one smooth thickness profile over the whole length, self-checked per slab |
| 31 | New work files from factory startup kept the default Cube / Camera / Light. | a stray cube in candidate files | forge_cli removes them when the work file is new (files made before the fix still contain them: clean before s9) |
| 32 | Hand-typed MD5 values in transfer checks were wrong several times (refused a correct file). | retries | always copy the hash from the tool output, never type it |
| 33 | The dark dots on the 1K bake were assumed to be pits; measuring showed 95 folded micro-edges and no pits. After fixing them one dot stayed: a near-flat sliver standing at 89.5°, just under the 90° rule, that tilts the angle-weighted vertex normal. | 2 runs | find each remaining dot by casting the camera ray to the mesh (`dot_probe`), then measure there; `fix_folds` + `fix_sliver_normals` |
| 34 | A re-committed file with the same name kept its old content on the PC (stale commit) and a test ran the old script. | 1 rerun | new file name per transfer, md5 checked on the PC before running |
| 35 | A wait loop longer than 60 s inside the UI Blender call timed out the bridge and blocked the next call. | 2 lost calls | keep in-Blender waits under 45 s |
| 36 | The gem was protected during thinning by a sphere guessed at z 0.86; the real socket is centred at z 0.826. The lower half of the socket and its ring were pushed in (ring up to −11.7 mm, gem face up to −6.4 mm): the pearl looked flat, half sunk and wavy. Claude first blamed the AI model after checking only the centre line. | user found it in the viewport; geometry cannot be fixed without re-running s1–s4 | measure every protected part on the mesh before an edit (circle fit) and check a before/after difference map; dragon v2: pearl drawn in the textures (`gem_dome`) |
| 37 | The factory Cube (2 m, around blade and guard) and 6 coincident trial copies were still in the work file: the AO bake came out black and blotchy, which made the first own textures dull. Normal maps were not affected. | 1 extra 4K bake | `remove_junk` before every bake |
| 38 | Decimation of the dragon LODs left 7 folded UV triangles per LOD (s6 FAIL). Moving only the UV points (Laplacian untangle) made it worse: 7 -> 9 and 7 -> 10. | 1 failed fix | `uv_unfold_collapse`: collapse the shortest edge of each folded triangle with UV interpolation (7 -> 0 in 1 round, -14 tris, 0 non-manifold, < 1 mm off LOD0), exp_20261021_222402_4ba9 |
| 39 | `Image.save_render` re-applied the scene's AgX view and wrote the scene's PNG format into the gallery .jpg files (darker, and not JPEG at all). | wrong gallery files | convert with Standard view and an explicit JPEG format; check the file magic, not the extension |
| 40 | The exported .blend (bpy.data.libraries.write) had no scene: opening it showed nothing; the README still described the first sword's EmissiveMask. | a buyer would see an empty file | s9 rebuilds a scene file and checks LOD0 visible + textures packed; README is built from the files present |
| 41 | A test that ran `libraries.write` + a blocking `subprocess.run` inside the UI Blender froze it for minutes. | lost session, Blender restarted | run tests and renders in a separate headless Blender started with Popen; the UI Blender only launches and reads |
| 42 | Fitting inferno_line to a real sword stretched the blade +27 % by rebuilding it (23 057 -> 14 673 vertices) and rebuilt the guard: details lost, design distorted, no gate noticed. | design lost; v4/v5 unusable | design lock: `extend_grip` / `thin_profile` / `thin_zone` refuse while `settings.design_lock` is on; size only via `uniform_fit`; s1 `design_unchanged` = `design_check` vs the surface saved at intake |

| 43 | A 4K bake could start before any 1K check, or after the UV was redone (each 4K bake costs a long wait); s2_variants always ran five candidates even when one method was known to suit. | hours of waiting | s4_bake refuses above 1K until a 1K check without FAIL, newer than s3_uv, is approved (`settings.allow_direct_highres_bake` skips); `settings.s2_plan` runs only the chosen candidates |
| 44 | s0_spec failed exaggerated fantasy designs (e.g. inferno_line) on real-world length ranges, blocking the pipeline for a deliberate design choice. | blocked stages | user decision 2026-10-27: `weapon_profiles.json` fantasy `geometry_info_only` → length/thickness ranges are INFO; units/scale, grip fits the hands and size vs the character stay gates |
## Rules kept from the studio rulebook

- Evidence before claims. Look at every render before reporting it.
- No PowerShell, no paid services, no MCP config changes and no downloads without explicit approval.
- Keep originals. Make small, reversible steps.
- Never re-run a non-idempotent call after a timeout. Check its log or status file first.

| 45 | 2026-10-28 | Uniform collapse smears thin raised bands on small curved parts (grip spiral, pommel inset) at any game budget; vertex-group weighting is too nonlinear. Fix: decimate each region separately in edit mode (selected faces, verts selected too) with its own triangle budget; QuadriFlow refuses this mesh (non-manifold verts on thin parts) and Instant Meshes gives stair-stepping and 2x faces. Per-project budget via settings.cfg_override. | s2_lowpoly |
| 46 | 2026-10-29 | QuadriFlow 'mesh needs to be manifold and consistent' was NOT about manifoldness: Blender's pre-check also rejects any edge shorter than 1e-4 units on all axes (1009 such edges on a 1.5M dagger, min 0.006 mm). Scaling x100 passes. Even then QuadriFlow loses thin parts (high->low p99 13-102 mm on 3 swords): never use it for game LOD0. | tools |
| 47 | 2026-10-29 | Benchmark on 3 swords x 3 budgets, same source: Blender Decimate collapse beats meshoptimizer 0.22 simplify 2-3x on deviation and on normals (meshopt is 20x faster, keeps a vertex subset; normal attributes make geometry worse). Instant Meshes quad-dominant at ~31k tris is ~7x worse than Decimate at 32k and opens holes; pure quads worse. Keep Decimate for s2. | s2_lowpoly |
| 48 | 2026-10-29 | X-symmetric decimation was always on: no-op on non-symmetric meshes, harmful on partly symmetric ones (inferno max dev 0.38 -> 0.83 mm). Now auto (mirror test). The global s2 deviation limit (0.0018 L) let a starved gem (31.9 deg) through: s2 now gates per-region normal error. | s2_lowpoly |
| 49 | 2026-10-29 | Regional decimation is a trade, not a free win: at 49k it keeps grip/pommel relief better on all 3 test swords (p95 -5..-17 %) for +5..+25 % global deviation; at 18k it starves the gem. Allowed only >= 45k; default stays uniform. Edit-mode decimate needs faces AND verts AND edges selected, or it decimates the whole mesh. | s2_lowpoly |
| 50 | 2026-10-29 | Judge a game low poly WITH its normal map: at 18k the grip bands that looked smeared in Solid came back with a 1K preview bake. Solid-only review drove the LOD0 to 49k (3-4x the market). | s2/s4 |
| 51 | 2026-10-29 | Absolute image differences hide in the render floor (AO noise, specular): measure the EXCESS over a dense reference with the same preview bake, in 16-bit renders. | look gate |
| 52 | 2026-10-29 | Preview bake pitfalls found the hard way: a view-layer material override does not reach objects without material slots; an unused generated image is regenerated blank (pack it); hard edges at preview seams draw dark lines (all smooth); a decimated copy inherits the high's UVMap and the bake uses the RENDER uv; bpy layer references dangle after uv_layers.new(). | look gate |
| 53 | 2026-10-29 | Never block the UI Blender with subprocess.run for a long job (LESSON 41 repeated: a 60 s timeout lost a reply). Popen + poll only. | process |
| 54 | 2026-10-31 | xatlas places fewer seams on smooth surfaces (-27 %) but its charts are irregular: its packer gave 39 % coverage with overlaps, and our FFT packer could not fit them even at 60 % (85 min). Keep forge_unwrap. Plans that name a tool as 'primary' before a benchmark were wrong 3 times out of 3 here (QuadriFlow, meshoptimizer, xatlas). | s3_uv |
| 55 | 2026-10-31 | A fixed bake ray as a share of the length is wrong for a low that sits 0.2 mm from the high: it reaches through thin overlaps (pommel cap over its sphere) and paints a dark streak. Set the ray from the measured low/high distance; the look gate caught it, the size checks did not. | s4_bake |
| 56 | 2026-10-31 | Gates that check file size and resolution passed an all-black gallery. Every image gate needs one check on the content (here: product brightness vs its albedo), and a stage must not depend on lights someone added by hand in an older project. | s8_media |
| 57 | 2026-10-31 | Re-running an old unit test calls record_experiment and re-registers the md5 of every changed file, so new untested code can look "tested" without its own evidence. Run the new evidence first, record it, and treat a silent "untested_files: []" after an old test as meaningless. | process |
| 58 | 2026-10-31 | Do not explain a strange number before testing the explanation: the 9.98 kg was blamed on the open mesh; after welding it was still 9.98 kg (a thick fantasy model). | s0_spec |
| 59 | 2026-10-31 | Tris->quads after decimation (Katsu "hybrid" step) on green_sword 22k: at 40 deg only 2,665 quads (24 % of the triangles joined; seams/sharp edges block the rest), vertices unchanged, but the look got WORSE: 0.0073 -> 0.0130 (40 deg) / 0.0159 (60 deg), FAIL. The normal map is baked on one diagonal per quad; when the quad is split again 10-20 % of the triangles get the other diagonal and the shading no longer matches. Keep the exported/baked mesh triangulated. Evidence: bench/quads/quads_result.json. | s2/s4 |

## 60. Most UV islands come from the packer, not the chart growth (2026-11-03 16:30)
green_sword: 53 charts -> 225 islands. The packer's hull-solidity split (uv_pack solidity=0.85) cuts charts into
pieces to pack tighter. Test copies (zz_uv_A/B, same charts, full s3 + 1K bake + look, nothing changed in code):
| solidity | islands | seam length | coverage | texel p50 px/cm | look worst (pommel) | s3 time |
| 0.85 (now) | 225 | 11.08 m | 0.62 | 70.1 | 0.0073 | 2150 s |
| 0.70 | 140 | 8.96 m | 0.60 | 69.0 | 0.0074 | 1350 s |
| 0.55 | 93 | 7.80 m | 0.55 | 66.1 | 0.0080 | 1022 s |
lmax 9->14 changed nothing. Wider chart cones (75/90 deg, merge 0.03) cut a little more (sweep only: 101-122 islands at 0.70)
but raise chart stretch p90 1.033 -> 1.06; not tested through bake. Price of fewer islands = coverage = texel density.
User chose 0.70 as the default (2026-11-03 16:40); verified live: default gives 140 islands.

## 61. Check the import orientation with two widths, not one (2026-11-03 17:00)
Raad (Tripo) came in pommel-down and edge-on. The x-only width profile with a 35 % threshold merged the blade into
the guard (66 % of the length), so "blade points down" passed on wrong data and s0_spec failed on a 9 cm grip.
The front renders showed only the blade's edge. Rule: blade side = the longer side of the widest 2D band; flat side to
the camera when the median Y width > 1.15 x X width (previous projects 0.14-0.54, Raad 1.40).
Still open: guard_center/tip cameras are fixed shares of the length, so a large crescent guard gives an extreme close-up
and a curved tip can be cut at the frame edge.

## 62. A test only validates what it names (2026-11-03 17:00)
record_experiment now hashes every top-level function. An experiment must name the functions changed since the last
accepted one, and one of its runs must be newer than the edit. Verified: a call without names was refused and listed
exactly the 4 changed functions.

## 63. Check that a camera sees what its name says (2026-11-03 17:14)
"tip" never contained the tip on 4 of 5 swords, and "guard_left/right" cut large or drooping wings. Measured on the real
vertices (share inside the frame), not on anatomy proxies: a proxy said the dagger tip was in frame while the render
showed it cut. Once the tip was really inspected, the green copy's 1K preview tip read 0.0116 (REVIEW) instead of 0.0042;
the gate was not stricter before, it was blind there.
