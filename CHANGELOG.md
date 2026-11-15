# Changelog

## 1.5.0 (2026-11-03) — voxel clean-up + QEM low poly by default (exp_20261103_234813_266b)
- `voxel_cleanup(project)`: AI high polys are rebuilt through a MeshLib signed-distance voxel grid (0.00071 × length, 0.7 mm on a 1 m sword), floating parts removed, Taubin smoothing (15). Runs automatically at the first `s1_highpoly` of a NEW project (`config high_cleanup.method = "voxel"`; per project opt-out: setting `no_high_cleanup`). The textured original is kept hidden as `settings.texture_source`; the design baseline is re-written. User decision: result over fidelity (silver_fang benchmark of 32 methods, <scratch>\forge_ui21\cgpt).
- Low poly default `lowpoly.method = "qem"`: PyMeshLab quadric decimation (quality 0.2, no topology lock, no planar quadric) + repair only where needed (`_qem_copy`, `_qem_fix`), in `s2_lowpoly` and `s2_auto`.
- `start_bake(..., color_high_names=)`: BaseColor / Roughness / Metallic / Emissive baked from the texture source, Normal / AO from the high; `s4_bake` passes `settings.texture_source`, `s4_bake_check` renders it as the textured high.
- `forge.py`: `forge\pylibs` (pymeshlab, meshlib, scipy) appended to `sys.path`.
- silver_fang s2: look 0.0118 → 0.0083, silhouette 0.984 → 0.9935, low open edges 39 → 0, folds 45 → 4.


## 1.4.3 — 2026-10-31 (claude)  — control panel 2.0 (run the pipeline without an AI)
- `forge_addon.py` 2.0 (installed + enabled; 3D View > N > Forge): project list; every stage with its status icon,
  a Run button (enabled only when the previous gate is PASS/approved), Approve for REVIEW (same record as
  Project.approve + ledger line "panel"); "Run from selected until a REVIEW"; options (weapon type incl. the curved
  profiles, style, target use, bake 1K/4K, title); details of the selected stage: FAIL/REVIEW checks with their
  messages, the report page, the folder and up to 8 image thumbnails; "New project" = folder + s0_import of the AI file;
  "Open project file". Stages run through forge_orch.py (one headless Blender per step: lock, .blend backup before
  each step, retries, journal), so this Blender never freezes; it refuses to start when the open project file has
  unsaved changes. UI text is English (Blender does not shape Arabic).
- s7_export: `tex_dir` is optional (default settings.final_tex_dir), so queues need no path. exp_20261031_131941_b377.
- Tested on zz_green_check (s6 PASS via the panel; s4 1K two steps -> REVIEW stop; approve), zz_panel_new (new project
  -> s0 REVIEW), a draw test of every stage of 3 projects (no error), thumbnails load.

## 1.4.2 — 2026-10-31 (claude)  — fixes found by running green_sword end to end
Evidence: exp_20261031_115204_94af (zz_green_check, zz_dagger_check, zz_import_check; forge/test_142_fixes.py 18/18; the
8 older tests pass). Backup: forge/_backup/pre_1.4.2_20261031_113130.
- s4 bake: cage/ray defaults = 0.0015 L / max(0.005 L, 3 x s2 Hausdorff) (`_bake_ray_defaults`; settings
  `bake_cage_rel` / `bake_ray_rel` override). The old 0.0032 L / 0.0095 L reached an inner surface at the green
  sword's pommel: look excess 0.0138 -> 0.0073; dagger guard_center 0.0096 -> 0.0064, other views equal. LESSON 55.
- s8 media: `_ensure_studio` adds 3 area lights + grey world when the render scene has no light (a new project had
  none: the whole gallery rendered black and still passed). New checks: `scene_lights`, `brightness_<shot>` (product
  luminance vs BaseColor >= 0.6, REVIEW only). Frames the bounding-box centre; extra close-up `08_wire_guard`
  (the full-length wire shot is unreadable at 22k). LESSON 56.
- s7/s9: one file name per map in Textures/2K (export renames the baker's *_2K.png); s9 no longer FAILs on
  duplicates and the zips lose ~15 % dead weight.
- s9 README: the Emissive line comes from the map (`_map_has_signal`): "no glowing parts" instead of the
  hard-coded "lava and gem". `package(..., emissive=)`.
- s0_import: `weld=True` merges coincident seam vertices before intake (19,018 open edges -> 0 on the GLB), so
  s0_spec measures a closed mesh. (The green sword's 9.98 kg did not change: it is its real volume.)
- Cameras: anatomy gains `centerline`, `tip_point`, `bbox_center` (`refresh_anatomy_geometry(project)` for old
  projects). The tip / blade_mid / junction views follow a curved blade; old projects without the keys keep the old
  targets. `_look_reference` is re-made when the camera set changes.
- s5: a lit comparison sheet (high vs final LOD0 material) so the REVIEW has something to look at.
- weapon_profiles: `sabre`, `scimitar` (aliases shamshir, talwar), `katana` (sourced blade/mass where found, the
  rest null = REVIEW only).
Not fixed (needs research or a decision): painted-in lighting in AI albedo (no detector yet), s3 runtime (36 min
at 22k), quad display topology (tested after 1.4.2: rejected, LESSON 59), the record_experiment loophole (LESSON 57).

## 1.4.1 — 2026-10-31 (claude)  — ideas taken from the outside "AI weapon pipeline" plan, each tested
- s2 report: `hausdorff_mm` (worst distance, both directions) and `chamfer_mean_mm` (mean distance) next to the
  percentiles (`deviation` returns the mean). Report only. Evidence: `forge/test_surface_metrics.py` (10 mm offset
  reads 9.999 / 9.991 mm).
- Re-import validation after export: already in s7 (`reimport_validate`: FBX/GLB/OBJ re-imported, length, pivot,
  UV layers, materials, textures). No change.
- xatlas 0.0.11 for UVs: REJECTED. Its own packer reached 39 % coverage with overlaps (8 FAIL); xatlas charts with
  the Sword Forge packer failed at every coverage level down to 60 % (85 min). Only gain: 27 % less seam length on
  smooth surfaces. Code removed; xatlas stays installed in tools/pylibs. LESSON 54.
- Material ID masks: belong to s5 (colouring), not done yet.

## 1.4.0 — 2026-10-29 (claude)  — "not distorted" = looks like the high WITH its normal map (user request: full system update)
- s0: `set_target_use(project, "fab_pc" | "showcase" | "mobile")` writes the LOD0 budget and the s2 candidates
  (fab_pc 16-30k, candidates 16/22/30k; showcase 30-50k; mobile 3-8k) instead of raising limits by hand.
- s2: `s2_auto(project)` builds the candidates, judges each by geometry (deviation, per-region normals) AND by look:
  `look_preview_bake` (1K tangent normal on a smart-UV layer, all smooth, small cage) + `look_compare` (high grey vs
  low grey+normal, 9 inspection cameras, same light, 16-bit renders): silhouette IoU >= 0.988 and luminance
  difference p95 above a dense 120k reference <= 0.010 (`_look_reference`, cached per project). Keeps the smallest
  passing candidate and gates it with `s2_lowpoly`, which now always runs the look checks too.
- s4: `s4_bake_check` runs the same look check on the real baked normal map and real UV.
- s3/s4: `_keep_awake()` stops Windows from sleeping while the stage runs (s3 was lost on 2026-10-28).
- `_decimate_copy` drops the high's UV layers, custom normals and sharp flags (garbage after decimation; the inherited
  UVMap broke the preview bake; s3 already removed it from finished LODs).
- Calibration: 3 swords x 8 candidates (bench/results/*_look_cal2.json). Old system s2 (18k symmetric, deviation-only
  gate) passed on all 3 swords and passed meshoptimizer/8k candidates; the new gate rejects them. Evidence:
  `forge/test_look_gate.py` 17/17 + integration on zz_regional_check (s2_auto) and zz_s4_check (s4). LESSONS 50-53.
- Known limit: the 1K preview is conservative (a real 4K bake of the 18k Inferno LOD0 passes the s4 look check).

## 1.3.8 — 2026-10-29 (claude)  — s2 method "regional" (user request)
- `s2_lowpoly(method="regional")` or setting `lowpoly.method = "regional"`: each region (gem, guard, grip, pommel,
  blade) gets its own triangle budget (`lowpoly.regional_shares`, default 7.5/29/19/18/26.5 %), decimated in edit
  mode on its own faces, 2 passes to hit the target. Refused below `lowpoly.regional_min_tris` (45000).
  Default stays "uniform". Note: the default hero max is 32k, so regional needs a project cfg_override.
- Evidence (3 swords, 49k, same source): grip p95 -12..-17 %, pommel p95 -5..-14 %, global deviation p99
  +5..+25 % (<= 0.16 mm). Integration run on a temporary copy (zz_regional_check). LESSON 49.

## 1.3.7 — 2026-10-29 (claude)  — s2 from the tool benchmark (QuadriFlow, Instant Meshes, meshoptimizer, Decimate)
- `_decide_symmetry` (setting `lowpoly.symmetry`: auto | on | off, default auto): X-symmetric decimation only when
  the mesh is mirror-symmetric about x=0 (mirror p99 <= 0.0005 L). Before: always on; on the 3 benchmark swords it was
  a no-op on 2 and worse on 1 (max deviation 0.38 -> 0.83 mm). Used by `_decimate_copy` and `_collapse`.
- s2 checks `region_normal_p95_deg` (REVIEW > 13, FAIL > 20 deg, per blade/guard/gem/grip/pommel) and
  `inconsistent_winding` (`edge_faces` now counts edges whose two faces wind the same way).
  Before: a gem starved to 31.9 deg passed s2 on the global p99 (1.18 mm < 2.13 mm).
- Evidence: `forge/test_s2_improvements.py` 13/13; benchmark data `<studio>\bench\results`. LESSONS 46-48.

## 1.3.6 — 2026-10-28 (claude)  — per-project cfg override (user decision)
- `Project.__init__`: `state.settings.cfg_override` (dict) is merged into that project's cfg last; other projects,
  categories and defaults are unchanged; an explicit `cfg=` argument skips it.
- First use: crimson_lava_dagger LOD0 max budget 32k -> 50k (regional decimation, 48,958 tris, chosen by the user).
- Evidence: `forge/test_project_override.py` 6/6. LESSON 45.

## 1.3.5 — 2026-10-27 (claude)  — fantasy: real-world geometry ranges are INFO only (user decision)
- `spec_checks`: when the style has `geometry_info_only` (fantasy, in `weapon_profiles.json`), a length/thickness
  range outside the real range becomes an INFO PASS instead of FAIL/REVIEW. Unchanged: realistic style, mass and
  balance (REVIEW band), `scale_plausible` (units), `grip_fits_hands`, `usable_by_character`.
- MASTER_RULEBOOK sec. 12: the 2026-10-18 rule is marked superseded for Sword Forge `s0_spec`.
- Evidence: `forge/test_fantasy_geometry.py`, old code (backup) vs new on the same cases, 7/7; fantasy geometry
  FAILs 2 -> 0. LESSON 44.

## 1.3.4 — 2026-10-27 (claude)  — 4K bake only after an approved 1K check; s2 plan from settings
- `s4_bake(size>1024)` refuses until a 1K `s4_bake_check` without FAIL, newer than s3_uv, is approved by the user.
  Re-baking 4K after a 4K check stays allowed. `settings.allow_direct_highres_bake = True` skips the rule.
  `s4_bake_check` at 1K stores `settings.bake_1k_check` (time, ok).
- `s2_variants(project, plan=None)`: the plan in the call, else `settings.s2_plan` (e.g. `[["A", 18000]]`), else the
  five default candidates (`S2_DEFAULT_PLAN`, unchanged).
- Evidence: `forge/test_bake_and_plan.py` on forge_selftest, 12/12 (guard logic and plan resolution; no bake was
  started; the live store of `bake_1k_check` runs on the next real 1K bake). LESSON 43.

## 1.3.3 — 2026-10-27 (claude)  — design lock: the design's shape never changes
- New: `uniform_fit(project, target_overall_m=... | factor=...)` changes the SIZE only (one factor on all axes about
  the tip). This is the way to match a real sword's length.
- New: `design_check(project)` compares the high poly with the surface saved at intake (`design_baseline`), after
  removing one uniform size factor. FAIL above `settings.design_tolerance` (default 0.0005 of the length).
  `s0_adopt` / `s0_import` save the baseline automatically; s1 has a new check `design_unchanged`.
- `extend_grip`, `thin_profile`, `thin_zone` refuse while `settings.design_lock` is on (default). Only the user may
  turn it off: `set_settings(project, design_lock=False)`.
- Evidence: `forge/test_design_lock.py` on forge_selftest, 8/8 (uniform 1.15 -> PASS 0 mm; thin_zone 0.7 with the
  front silhouette unchanged -> FAIL 1.297 mm; restore -> PASS). LESSON 42.

## 1.3.2 — 2026-10-22 (claude)  — s8 JPG colours, s9 package fixes
- `s8_media_check` converts with `_jpeg_from_png`. `Image.save_render` applies the scene view transform (AgX) and the
  scene file format: the old gallery "JPGs" were darker PNG files (mean abs diff 0.0255 -> 0.0041, magic 89504e47 ->
  ffd8). New gate check: gallery total < 25 MB (Fab).
- `s9_package`:
  - makes Textures/2K from 4K.
  - Rebuilds the .blend as a normal scene file. The libraries.write file opened on an empty scene. In the new file LOD0 is visible, LOD1/LOD2 and UCX are in hidden collections, and the textures are packed. The library-only file is kept in export/_backup_blend.
  - New gate checks for these.
- `lib/fab_package_v4`: README lists the real texture files and the measured height. The EmissiveMask line appears only when that map exists. The GLB line names the embedded maps.
- Experiments: exp_20261022_001944_efb3, exp_20261022_002158_e0e3.
- Dragon v2: s8 approved (user), s9 REVIEW (4 zips: Blend 118.5, FBX 80.5, GLB 39.5, OBJ 78.7 MB).

## 1.3.1 — 2026-10-21 (claude)  — s6 UV folds from decimation
- `forge_mesh.uv_flipped_tris` / `uv_unfold_collapse`; `s6_lods` repairs each LOD after `seam_sharp`. Dragon v2: LOD1
  7 -> 0, LOD2 7 -> 0 flipped UV triangles; s6 PASS, s7 PASS (FBX/GLB/OBJ re-imported, textures = look_iter10_4096).
  The UV-only relaxation tried first (`uv_untangle`) made it worse and was removed. exp_20261021_222402_4ba9.

## 1.3 — 2026-10-21 (claude)  — s5 own textures
- `forge_look.py` (numpy): texel maps from the UV layout (world position, normal, part per texel), 3D value noise on
  texel positions (no seams), curvature from the baked normal map (island borders ignored), layers: black steel with
  worn edges and darker cavities, leather grip, lava channel along the blade ridge (robust polynomial fit), heated guard
  horns, gem. Tangent frames in Blender's convention (checked on the dragon: decoded bake matches the high poly 0.973 vs
  0.939). `gem_dome`: a flat gem face shaded as a round pearl by sphere normals (textures only).
- `forge_stages`: `look_paint(project, size)` writes BaseColor / ORM / Emissive (+ Normal when gem_dome is set),
  `look_preview`, `remove_junk` (factory objects and trial copies that spoil AO bakes), `add_gem` / `remove_gem` and
  `settings.keep_whole` (objects copied whole into the low poly; not used on the dragon v2: the user chose not to
  re-run the stages). exp_20261021_193743_0067.

## 1.2.1 — 2026-10-21 (claude)  — fix the dark dots (folded micro-faces)
- `forge_mesh.fold_edges` / `fold_relax` + `forge_stages.fix_folds` (new high-poly edit, positions saved first):
  edges folded more than 90° are found from face normals; their vertices (then +1, +2 rings if needed) are relaxed
  towards the neighbour mean, each by at most 0.3 mm; every other vertex stays exactly in place.
- Live test (Blender 5.2.2, forge_selftest, exp_20261021_171006_c48a): copy of the dragon v2 high 95 → 0 folded
  edges, 140 of 750 002 vertices moved, max 0.3 mm; synthetic grid with 8 pushed vertices 32 → 0, back to 0.0002 mm;
  restore exact.
- `forge_stages.fix_sliver_normals` + `restore_normals` (new edit; corner normals saved first; geometry and topology
  unchanged): the dot fix_folds left was a cap triangle (0.0002 mm², corner ~180°) standing at 89.5°. Blender weights
  vertex normals by corner angle, so it tilted the normal by ~45°. At vertices of slivers (corner > 160° or < 5°) that
  are not on a crease (20°), have ≥ 3 normal faces and are tilted ≥ 10°, the shading normal becomes the area-weighted
  one. Dragon: 244 vertices. Looser rules (12 234 / 10 218 vertices) darkened the stepped blade edges and were
  rejected (exp_20261021_175346_72f7). Lower fold thresholds (85–70°) made 55–474 new folds: rejected.
- Dragon v2 1K after both edits (s1→s4 rerun after fix_folds, bake only after the normals edit): the 4 dark dots in the
  trial views are gone; SSIM metal+normal 0.9149 → 0.9138 (no change); UV coverage 0.68 → 0.65 (new decimation).

## 1.2 — 2026-10-21 (claude)  — evidence first + weapon fit (s0_spec)
- **Evidence-first rule enforced in code** (user request): `record_experiment(...)` refuses a change without measured
  before/after values, an existing run report and existing evidence files; accepted experiments register file md5s in
  `manifest.json`. `check_environment` lists untested files; `forge_cli` refuses untested code on real projects
  (only `config.test_projects` may run it). `record_lesson("error"|"success")` needs evidence; ideas are flagged
  untested. `register_baseline` starts the manifest once. CONTRIBUTING rule 0, AGENT_PROMPT updated.
- **s0_spec — is it a usable weapon of its type?** (user request) `forge_specs.py` + `weapon_profiles.json`: length,
  blade / grip / pommel, guard width, thickness, volume (surface-crossing integration, exact on a box, 0.1 % on a
  sphere), mass estimate, centre of mass, point of balance; sourced ranges per type (arming sword, longsword,
  greatsword, dagger, spear, axes, round shield); fantasy widens length and mass; grip vs hand breadth; length vs a
  character. Unsourced ranges can only REVIEW. Renders the weapon beside a grey character proxy and hand blocks on the
  grip. s1 now requires s0_spec (`settings.legacy_no_spec` for old projects).
- **s0_candidates** (user request: "I put 3 versions, choose the best"): `candidate_measure` / `candidates_compare`,
  `_import_normalised` shared with `s0_import` (glTF parents removed with the world transform kept), `export_test_glb`.
  Health is measured after welding seam splits. Grid cell relative to length. Orchestrator takes over stale locks.
- **Geometry edits on the high poly** (user decisions for version 02): `extend_grip`, `thin_zone`, `thin_profile`
  (one smooth thickness profile, self-checked per slab), `restore_positions` (every edit saves the vertex positions
  first), `render_check` (same cameras before/after, with a side view).
- **Fantasy physics** = REVIEW band (restores the agreed studio rule in `scripts/mass_balance.py`); balance ranges
  sourced from mass_balance.py. New work files are cleaned of the factory Cube/Camera/Light.
- `MODEL_ROUTING.md`: split each order into tasks per model / effort (user rule).
- Tests: TEST_RESULTS.md; experiments exp_20261021_085849_64c8, exp_20261021_093912_5150, exp_20261021_113746_3297,
  exp_20261021_114102_036b, exp_20261021_115901_d6dc, exp_20261021_121218_0723 (EXPERIMENTS.md).

## 1.1.3 — 2026-10-21 (claude)  — s3 UV recipe ported into Sword Forge
- `forge_uv.py` (numpy only): class-restricted normal-cone charts → LSCM (conjugate gradient, no scipy) → split/repair
  until no flips or overlaps → merge small charts → FFT packing (no PIL/scipy) with a **Euclidean** padding disk.
  Long pieces are cut across or placed first; unsplittable slivers are scaled and listed; blade, sharp edges and gem
  are never shrunk to fit (coverage drops instead). Coverage tried from 0.70 down; never forced.
- `uv_audit`: overlaps at 4K, exact island gap and border, coverage under both definitions (area sum = the old "74 %";
  pixel raster), Jacobian distortion, texel density, per-region checks (blade, guard, gem, grip, pommel, edges).
- s3 gate: every audit check + hard edges inside islands + flat faces + **UVs read back from Blender = packed layout**
  + islands = pieces + shrunk pieces; diagnostics: UV islands/texel/regions PNGs, checker renders, edge renders;
  the previous UVs are saved (`uv_backup`, `uv_restore`) and audited for comparison.
- `trial_bake(keep_uv=True)` bakes the s3 layout as is; `normal_map_stats`; `trial_rescore` re-measures old and new
  trials with the same code and writes difference heat images.
- Found: the old "16 px" padding measured 10.5 px (diamond dilation) — lesson 20.

## 1.1.2 — 2026-10-21 (claude)
- Baker: shared-material reroute fix (lesson 17); BaseColor via emission (lesson 18).
- s1 gate `materials_connected` plus `repair_disconnected_materials`.
- `unwrap_object` (s3 recipe reusable). Trials: `trial_bake` / `trial_compare` (same UV, 1K bake, lit and metal+normal renders, SSIM/MAE). `set_settings`. Variant D (protected zones).
- Inspection scene re-creates its lights and camera (lesson 19). `material_override` for uniform diagnostic renders. SSIM clamped.
- Code frozen for the dragon A/D trial run. md5: forge_stages f50a66a7, forge_render 04a51461, forge_metrics 95f0b0b2, lib/baker_v2 9a3c3d1c, forge_core 9bbaffca, forge_orch d7ca81b6, forge 34803e69.

## 1.1.1 — 2026-10-21 (claude)
- Fix: name clash `_aim` (forge_render vs lib/media_kit). Renamed to `forge_aim`. The loader now detects clashes (lesson 14).
- Dragon sword variants measured (TEST_RESULTS.md): method A selected for s2.

## 1.1 — 2026-10-21 (claude)
- Orchestrator outside Blender (`forge_orch.py`): every step runs in headless Blender, with a queue, an atomic journal, input fingerprints, retries of transient errors, a disk check, a .blend backup before each step, report verification and resume.
  Why: diagnostic renders froze the UI Blender twice (lessons 5 and 13).
- Synchronous bake and media renders in background mode (`lib/baker_v2.py`, `lib/media_kit.py`).
- Inspection renders in a separate `FORGE_inspect` scene, so the user's scene is never touched. Workbench is used for geometry checks.
- Four gate outputs: `report.json`, `decision.json`, `comparison/` and `diagnostics/`, plus an `index.html` review page.
- `forge_metrics.py`: ray-cast silhouette IoU, depth and normal comparison, plus image MAE/SSIM.
- s2 variants A/B/C with budgets (`s2_variants`, `s2_select`). The pick is provisional until calibrated.
- Families (straight_simple / curved / ornate) in config. Blender version pinned to 5.2.2.
- Add-on control panel (`forge_addon.py`).
- Production ledger and `record_lesson`, plus `CONTRIBUTING.md`, so any agent can log errors and successes and improve the system.
- Self-test sword (`selftest_make`) and `forge_selftest_queue.json` with an injected failure.

## 1.0 — 2026-10-20 (claude)
- First version: stages s0–s10, gates, PIPELINE.md, LESSONS.md.

## 1.4.4 (2026-11-03 16:30)
- forge_addon.py: unregister() no longer fails when Blender quits (a local `import bpy.utils.previews` made `bpy`
  unbound when no previews were loaded). Verified: headless enable -> disable prints no traceback.
- forge_uv.py: uv_pack default solidity 0.85 -> 0.70 (user decision 2026-11-03 16:40, lesson 60, exp_20261103_163930_30b1):
  green_sword 225 -> 140 islands, seams 11.1 -> 9.0 m, s3 36 -> 22 min, look 0.0073 -> 0.0074, coverage 0.62 -> 0.60.
  Existing projects keep their UVs until s3_uv is run again.

## 1.4.5 (2026-11-03 17:00)
- Import orientation (exp_20261103_165925_4030): models that arrive pommel-down or edge-on are turned (rigid rotation,
  shape unchanged) so the tip is at Z=0 and the blade's flat side faces the front camera. detect_anatomy uses the
  widest 2D band for the blade side and falls back to a 2D guard band when the x band covers >30 % of the length.
  The rotation is written to settings.import_orientation and shown in the s0_intake notes.
  Raad: s0_spec FAIL -> REVIEW (grip 0.088 -> 0.147 m, guard band 0.66 -> 0.12 m, balance -0.22 -> +0.12 m).
  Existing projects: old vs new detect_anatomy identical on all four.
- record_experiment(functions=...) (exp_20261103_165926_2089): every top-level function changed since the file's last
  accepted experiment must be named, and one run/evidence file must be newer than the edit (closes lesson 57).
  Function baselines were seeded from the tested versions of all manifest files.

## 1.4.6 (2026-11-03 17:14)
- Inspection cameras (exp_20261103_171408_d000): the tip view now contains the tip (it framed 4-10 % of L above it:
  0 % of the tip region was in frame on 4 of 5 swords), and the guard side views frame the whole wing box
  (anatomy.wing_boxes, new in _anatomy_geometry). Old anatomies without wing_boxes keep the old side views until
  refresh_anatomy_geometry. Look-reference caches are keyed by the cameras, so they rebuild by themselves.

## 1.4.7 (2026-11-03 17:31)
- New Project box (exp_20261103_173035_17c5): a "Source" choice -- From a file (as before), or Already open in this
  Blender. When more than one weapon is open (grouped by topmost ancestor object), a dropdown lets you pick which
  one; with exactly one it is used automatically; with none the button is disabled with a message. The chosen
  weapon's objects are duplicated with their world transform baked in, written alone to the project's work.blend,
  and the pipeline starts from s0_adopt (same gate as s0_import) -- the open Blender's own objects are left exactly
  as they were.

## 2.1 (control panel, 2026-11-03)
- Sword Forge panel redesigned: main card with project, progress bar (x / 12 stages done) and one big 'what to do now' button (Approve / Run next / Show what failed / Open log).
- Review, Stages, New project and Options are fold-out sub-panels (New project and Options closed by default). Same buttons and settings as 2.0.
- Tested: old vs new draw over 65 project states, 0 errors, no control lost (exp_20261103_184926_48d9). Backup: forge_addon.py.before_ui21_20261103_184725.

## 1.4.8 (2026-11-03)
- Fix: a weapon taken from the open scene ('Already open in this Blender') was written to work.blend in no collection, so s2 failed: 'cannot be selected because it is not in View Layer'. s0_adopt now links such objects to the scene collection (_link_orphans; link only, shape unchanged). exp_20261103_190306_7fe8.
- silver_fang: work.blend fixed by hand the same way (backup silver_fang.blend.before_link_20261103_185938).

## 1.4.9 (2026-11-03)
- s2: tiny non-manifold edges (3+ triangles on an edge shorter than 0.001 L: decimation fins) are merged on the low-poly (merge_tiny_nonmanifold_edges, forge_mesh.py). Deviation unchanged; manifold lows untouched. exp_20261103_192336_d312.

## 1.5.1 (2026-11-04) — auto-correct weapon type at s0_spec (exp_20261104_134702_37af)
- s0_spec no longer FAILs just because the declared weapon type doesn't fit the geometry's size. If scale_plausible would fail for the declared type and the proportion-based guess_type() is a different, confident guess, the project's settings.weapon.type is auto-corrected and saved, and the gate re-checks against the corrected type.
- Tested on project `test` (geometry_0, overall 1.898 m, declared arming_sword): auto-corrected to greatsword, scale_plausible went FAIL (2.157) -> PASS (1.168), stage status FAIL -> REVIEW.

## 1.5.2 (2026-11-15) — open voxel engine by default (exp_20261115_143505_ef3b)
- voxel_cleanup now rebuilds the high poly with Blender's built-in OpenVDB voxel remesh (`_blender_voxel`). MeshLib stays available as `high_cleanup.engine = "meshlib"` but is no longer needed (its free licence excludes commercial use).
- silver_fang, same QEM 50k low poly: folds 4 -> 0, dev p99 0.13 -> 0.12 mm, pommel normal p95 16.3 -> 15.9 deg, look excess 0.0083 -> 0.0061, silhouette IoU 0.9935 -> 0.9939, Hausdorff 0.296 -> 0.25 mm. Rejected: Blender 0.5 mm (2M tris, 4 self-intersections), PyMeshLab uniform resampling (676 non-manifold edges).

## 1.5.3 (2026-11-15) — repository release preparation
- No machine paths in the code: `forge.py` finds its folder (FORGE_DIR before exec, env FORGE_DIR, the running script's folder, or `~/.sword_forge_dir`); machine paths live in the untracked `paths.local.json` (`paths.example.json`); env `FORGE_PROJECTS` overrides the projects folder. CLI, orchestrator, add-on and `run_forge.bat` follow the same rules.
- `setup_forge.py` (paths + PyMeshLab into `pylibs/`), `tests/run_selftest.py` (procedural sword s0→s2 with an injected crash, in a temporary folder), README, GPL-3.0 LICENSE, THIRD_PARTY.md, .gitignore.
- s0_spec: an automatically corrected or undeclared weapon type is REVIEW, never a silent PASS (1.5.1 made it PASS; a small weapon imported too large would have been relabelled without a warning).
- Historical validation scripts moved to `experiments/legacy_tests/`; local paths in history files replaced by placeholders.
- Manifest md5 ignores line endings (`file_md5`), so a git checkout with CRLF or LF stays "tested"; text files stored with LF. Experiments exp_20261115_145611_acd6 and exp_20261115_145902_14ad.

## 1.6.0 (2026-11-15) — any model, not only weapons (exp_20261115_202550_5e9c)
- New asset kind `generic` next to `weapon`: `s0_import(project, path, kind="auto" | "weapon" | "generic")`, `s0_adopt(..., kind=)`.
  `auto` guesses from the proportions (longest side >= 2.5 x the next one = weapon) and shows the guess as REVIEW. In the panel: type "any other model".
- Generic assets: kept upright as imported (base on Z = 0, pivot at the centre of the base); cameras from the bounding box
  (front, back, sides, top, three-quarter, four close-ups); `s0_spec(project, size_m=...)` checks the real size and renders
  the asset beside a character (weapon measurements skipped); one UV region `body`; gallery shots from the generic cameras.
- Voxel clean-up: for generic assets the voxel comes from the surface area (about 1.2 M triangles); open meshes get their
  holes capped first when the rebuild would lose surface; new s1 check `cleanup_kept_shape` (REVIEW above 0.5 % lost, FAIL above 5 %).
- Tested s0 → s9 on a procedural non-weapon (`selftest_make_generic`, `tests/run_selftest.py --generic`). Swords: identical numbers on silver_fang.
- Known limits: not yet run on a real AI-generated non-weapon; no part detection for generic assets (one region); look painting and listing text are still written for swords.
