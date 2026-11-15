# Sword Forge — from an AI-generated sword to a Fab product

Read this whole file before touching Blender. It is written for any assistant (Claude, ChatGPT, Gemini, Codex…) and for a human.

## The one rule

**A stage never runs on top of a stage that did not pass.**

Every stage ends with a *gate*: a list of checks, each `PASS`, `FAIL` or `REVIEW`.
- `FAIL`: fix it and re-run the same stage. Never continue.
- `REVIEW`: a person (or a vision model) must look at the images in the report and approve:
  `Project("<name>").approve("<stage>", who="user", note="...")`.
- Re-running a stage marks every later stage `STALE`. They must be re-run.

This rule exists because on the Inferno Dragon Sword we baked, textured and exported a low-poly that was crumpled at stage 2, and only found out at stage 8.

## Asset kinds (1.6.0)

- **weapon** (default for long, thin models): anatomy (tip, blade, guard, grip, pommel), weapon specs in `s0_spec`,
  sword cameras, part-based UV regions and gallery shots.
- **generic** (any other model: props, vehicles, furniture, creatures...): `s0_import(project, path, kind="generic")`
  or `kind="auto"` (the guess is a REVIEW at s0). Kept upright as imported, pivot at the centre of the base; cameras from
  the bounding box (front, back, sides, top, three-quarter, close-ups); `s0_spec(project, size_m=...)` checks the real
  size (largest side) and renders the model beside a character; one UV region (`body`); voxel size from the surface
  area; gallery from the generic cameras. Every gate after s0 is the same as for swords.
- Tested: swords (several real AI swords), a procedural model (`tests/run_selftest.py --generic`) and one real AI car
  (s0 -> s9). Generic assets have no part detection and no automatic colour painting yet.

## How to run it

**Inside Blender (MCP `execute_blender_code`, or the Scripting tab):**
```python
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
status("my_sword")
```

**Headless (any AI that can start programs; no MCP needed):**
```
blender -b <projects>\my_sword\work\my_sword.blend -P <forge>\forge_cli.py -- s2_lowpoly "{\"project\":\"my_sword\"}" --save
```
It prints `FORGE_RESULT {...}`. Exit code 0 = PASS/REVIEW, 2 = FAIL, 3 = error.

**Long work under MCP.** Calls time out after about 60 s. Bakes, decimation of huge meshes and Cycles renders run in a Blender timer: `run_job(...)` / `start_bake(...)` / `reshoot(...)`. Poll the status or log file; do not call the same job twice.

**Where things live.**
- Code: `<forge>\`
- Projects: `<projects>\<name>\`, with these folders:
  - `source/` — the untouched AI file (kept forever)
  - `work/` — the `.blend` file and bakes
  - `reports/` — `<stage>.json` and `<stage>.md` for every gate
  - `renders/`
  - `export/`
  - `package/`
  - `checkpoints/` — the last 2 per stage; older ones go to `archive/`
  - `state.json`

## Stages

| # | function | what it does | gate (FAIL unless noted) |
|---|---|---|---|
| 0a | `candidate_measure(project, path, tag)` per AI file, then `candidates_compare(project, tags)` | When the generator gave several versions: each is imported into its own .blend (source never modified) and measured the same way (mesh health after welding seam splits, mirror symmetry, surface noise, textures, weapon spec) with the same cameras. | No automatic winner: table + picture grid; the person chooses. |
| 0b | `s0_spec(project, weapon_type, style)` | **Is it a usable weapon of its type?** Length, blade, grip, guard, thickness, volume, mass estimate, balance, grip vs hands, size vs a character (renders with a grey character proxy and hand blocks). | Sourced ranges FAIL; unsourced ranges only REVIEW. s1 refuses to run until s0_spec passes or is approved. |
| 0 | `s0_import(project, path)` or `s0_adopt(project, high_names)` | Imports GLB/FBX/OBJ, keeps the original, puts the long axis on Z with the tip at Z=0, applies transforms, and detects the anatomy (guard, grip, pommel, pivot). | Blade points down. Real size. **REVIEW**: anatomy numbers against the front render. |
| 0c | high-poly edits (each saves vertex positions first; `restore_positions(project, path)` undoes it) | `weld_highpoly` (coincident seam vertices), `extend_grip`, `thin_profile` / `thin_zone`, **`fix_folds`** (folded micro-faces that bake as dark dots: relax ≤ 0.3 mm, only around folds), **`fix_sliver_normals`** (degenerate slivers that tilt the shading normal: area-weighted normal at those vertices only; `restore_normals`), `render_check(project, tag)` before/after. | Each writes `reports/s0_edits/<edit>.json`. Re-run s1 and later stages after a geometry edit; a normals-only edit needs only the bake (s4) again. |
| 1 | `s1_highpoly(project)` | Checks the AI mesh. Clean-up is done by hand or by script and then re-checked. | No non-manifold edges. **REVIEW**: close-ups for noise, beaded or dotted ridges, asymmetry, melted details. AI meshes usually need a voxel remesh, smoothing and mirroring. |
| 2 | `s2_lowpoly(project)` | X-symmetric decimation, then **fold repair** (diagonal flips). Raises the budget ×1.3 until the geometry gate passes, up to the category maximum. | Concave folds > 150° ≤ 0.2 % of edges. Deviation p99 ≤ 0.15 % of length (low→high) and 0.3 % (high→low). Few slivers. **REVIEW**: compare sheet of high vs flat-shaded low. |
| 3 | `s3_uv(project)` | Forge UV recipe (`forge_uv.py`): charts per class (blade faces / sides / grip) → LSCM → repair → FFT packing with a true Euclidean padding, never forcing coverage; then **smooth shading with hard edges only on seams**, weighted normals. Old UVs saved first. | 0 flips, 0 zero-area, 0 overlap px at 4K, exact gap ≥ 16 px (REVIEW ≥ 12), border ≥ 8 px, coverage (area sum) by family, distortion, texel spread, per-region density and cleanliness (blade, guard, gem, grip, pommel, edges), **UVs read back from Blender = packed layout**, **0 hard edges inside islands**, 0 flat faces. **REVIEW**: seam placement with checker renders. |
| 4 | `s4_bake(project, 1024)`, then `s4_bake_check(project)` | **Test bake at 1K first**, then the comparison sheet (lit, textured, high vs low, 10 close-ups). Only after approval: `s4_bake(project, 4096)` and check again. | All maps written. **REVIEW**: no seam lines, creases, dark wedges or lost details. |
| 5 | `look_paint(project, size)` (own textures, forge_look) then `look_preview`; or `s5_look(project, script)` for a project hook | Black steel, worn edges, leather, lava, gem from texel positions and the baked AO / normal maps. Run `remove_junk` before the bake. | **REVIEW**: preview renders; effects only where intended. |
| 6 | `s6_lods(project)` | LOD1/LOD2 at 50 % / 25 %, same UVs, seam-sharp normals, UCX collision split at guard and grip. | LODs exist. No UV flips. Collision hulls present. |
| 7 | `s7_export(project, tex_dir)` | **Deselects every object first**, exports FBX/GLB/OBJ/Blend with the pivot at the grip, then re-imports every file into a scratch scene. | Re-import validate passes (height, pivot, UVs, textures, no extra objects). GLB < 80 MB (a huge file means the high poly slipped in). |
| 8 | `s8_media(project)`, then `s8_media_check(project)` | Cycles gallery and wireframe. Converts to JPG. | ≥ 1920×1080, < 3 MB each. **REVIEW**: images show the real product. |
| 9 | `s9_package(project)` | One zip per format, plus an English README. | Zips present. **REVIEW**: listing text matches the files. |
| 10 | `s10_publish(project)` | Rights and Fab checklist. | **REVIEW** each item: AI-content disclosure, the generator's commercial terms, no franchise copying, own textures only, formats tested, gallery rules, README, price and licence. |

## Evidence first

Changing the code, the thresholds or the reference data needs a live test: run it on `forge_selftest`, then
`record_experiment(...)` with measured before/after and evidence files (CONTRIBUTING rule 0). Until then the changed
files are *untested* and `forge_cli` refuses them on real projects.

## Budgets and thresholds

Defaults are in `forge_core.DEFAULTS`. Override them in `forge/config.json`.

| category | LOD0 start | LOD0 max | LOD1 | LOD2 |
|---|---|---|---|---|
| hero_sword (ornate, close-ups) | 18 000 | 32 000 | 50 % | 25 % |
| standard_sword | 9 000 | 16 000 | 50 % | 25 % |
| mobile_sword | 3 000 | 6 000 | 50 % | 25 % |

Textures: 4K with a 2K copy. Padding 16 px at 4K. UV coverage 0.65–0.78 is normal. Higher coverage cuts more seams and is not better.

## Fast diagnosis

- Inspection renders use EEVEE: about 10 views in seconds.
- Cycles is only for marketing (stage 8).
- To find which map causes an artefact, render the same close-up three ways: without the normal map, with the normal map only, and as flat-shaded geometry.

## Reports

- `reports/<stage>.md` is the human summary.
- `reports/<stage>.json` is for machines: checks, data, image paths, Blender version, `.blend` path.
- A claim of success is only valid if the report says so. Evidence before claims.


## 1.4.2 notes (2026-10-31)
- `s0_import` welds coincident seam vertices by default (`weld=False` to skip).
- Curved blades: run `refresh_anatomy_geometry(project)` once on a project made before 1.4.2 so the inspection
  cameras follow the blade (new projects get it in s0). The look reference is rebuilt automatically.
- s4 cage/ray come from the s2 Hausdorff distance (`_bake_ray_defaults`); override with settings `bake_cage_rel`, `bake_ray_rel`.
- s8 adds its own studio lights when the scene has none and checks the product brightness.


## Control panel (no AI needed)
3D View > press N > tab **Sword Forge**. Choose the project; press ▶ on a stage (or "Run from selected until a REVIEW");
when it stops at REVIEW, select the stage, look at the images (thumbnails / Report page), write a note, press the
approve button, then run the next stage. New weapon: "New project" box (name + AI file) > Create + import.
Long stages (UV ~35 min, gallery ~10 min) run in the background; the panel shows "Running" and the log.
