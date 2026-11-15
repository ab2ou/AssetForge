# Sword Forge

**From an AI-generated sword to a game-ready product, with a quality gate after every step.**

Sword Forge is a Blender pipeline that takes a raw high-poly sword from an AI 3D generator and produces a
game asset ready for a marketplace such as Fab: a cleaned high poly, a low poly with LODs and collision, UVs, baked 4K/2K PBR
textures, FBX/GLB/OBJ/Blend exports, a render gallery and packaged zips.

Every stage ends with a **gate**: measured checks that are `PASS`, `FAIL` or `REVIEW`. A stage refuses to run on top of
a stage that failed or that a person has not approved. Code changes are accepted only with measured
evidence from a live run (`record_experiment`). See [CONTRIBUTING.md](CONTRIBUTING.md).

> Status: works end to end on swords (arming sword, longsword, greatsword, sabre, katana…). Part detection, inspection cameras,
> weapon specs and gallery shots assume a long bladed weapon; other assets are on the [roadmap](ROADMAP.md).
> Tested on Windows with Blender 5.2.2.

## Stages

| # | stage | what it does |
|---|---|---|
| 0 | `s0_import` / `s0_adopt` | import, orient (tip down, long axis Z), real scale, detect guard / grip / pommel |
| 0b | `s0_spec` | is it a usable weapon of its type? length, blade, grip, mass, balance, size next to a character |
| 1 | `s1_highpoly` | voxel rebuild of the AI surface (closed, no self-intersections, AI noise removed) and checks |
| 2 | `s2_lowpoly` | quadric (QEM) low poly inside a triangle budget; deviation, folds, shading and silhouette gates |
| 3 | `s3_uv` | class-based charts, LSCM, FFT packing with true padding; overlap, distortion, texel density audit |
| 4 | `s4_bake` | 1K test bake, comparison sheet, then 4K: BaseColor, Normal (GL + DX), Roughness, Metallic, AO, ORM, Emissive |
| 5 | `s5_look` | optional look painting / preview |
| 6 | `s6_lods` | LOD1 / LOD2 with shared UVs, UCX collision hulls |
| 7 | `s7_export` | FBX / GLB / OBJ / Blend, pivot at the grip, every file re-imported and validated |
| 8 | `s8_media` | studio gallery (hero, front, back, details, wireframe) + brightness checks |
| 9 | `s9_package` | one zip per format with 4K + 2K textures; listing data from measured numbers |
| 10 | `s10_publish` | checklist only; never runs without an explicit human decision |

Details, thresholds and the reasons behind them: [PIPELINE.md](PIPELINE.md), [LESSONS.md](LESSONS.md).

## Install

1. Install [Blender 5.2.2](https://www.blender.org/download/). Other versions are refused unless
   `allow_untested_blender` is set in `config.json`.
2. Clone this repository anywhere, then run the setup **with Blender's own Python** (so the libraries match its Python version):
   ```
   "<Blender folder>/5.2/python/bin/python.exe" setup_forge.py --projects D:/Forge/projects
   ```
   It remembers the code folder (`~/.sword_forge_dir`), writes `paths.local.json` (see `paths.example.json`) and
   installs [PyMeshLab](https://github.com/cnr-isti-vclab/PyMeshLab) into `./pylibs`.
3. Optional control panel: *Edit > Preferences > Add-ons > Install from Disk >* `forge_addon.py`, then press `N` in the
   3D view, tab **Sword Forge**.
4. Check the install:
   ```
   "<Blender folder>/5.2/python/bin/python.exe" tests/run_selftest.py
   ```
   It builds a procedural sword in a temporary folder, runs it from import to low poly with the orchestrator,
   injects one crash that must be retried, and prints a summary (exit code 0 = OK).

## Use

**Control panel** (no code): New project → import the AI file → press the "what to do now" button; review the images
of each REVIEW gate and approve.

**Inside Blender** (Scripting tab or an MCP tool):
```python
exec(open(r"<forge folder>/forge.py", encoding="utf-8").read())
s0_import("my_sword", r"D:/ai/my_sword.glb")
s0_spec("my_sword", weapon_type="longsword", style="fantasy")
status("my_sword")
```

**Headless** (one stage per Blender process; exit code 0 = PASS/REVIEW, 2 = FAIL, 3 = error, 4 = refused):
```
blender -b <projects>/my_sword/work/my_sword.blend -P <forge folder>/forge_cli.py -- s2_lowpoly "{\"project\":\"my_sword\"}" --save
```

**Queue** (runs and resumes many stages with backups, retries and a journal):
`python forge_orch.py run queue.json` or `run_forge.bat queue.json`.

Every run is appended to the ledger (`forge_ledger.jsonl` next to the projects folder); every gate writes
`reports/<stage>/report.json`, a Markdown summary and its images.

## Configuration

- `paths.local.json`: machine paths (projects folder, ledger, blender executable, optional `pylibs`). Not tracked by git.
  The environment variable `FORGE_PROJECTS` overrides the projects folder (the self-test uses it).
- `config.json` (optional): overrides of the defaults in `forge_core.py` (budgets, thresholds, families,
  `high_cleanup`, `lowpoly`). Changing it counts as a code change (evidence first).
- `weapon_profiles.json`: weapon dimension ranges with their sources. Unsourced ranges can only raise REVIEW.

## Repository layout

```
forge.py            loader (finds the folder, loads every module into one namespace)
forge_core.py       projects, state, gates, ledger, evidence manifest, defaults
forge_stages.py     the stages s0..s10 and high-poly edits
forge_mesh.py / forge_uv.py / forge_render.py / forge_look.py / forge_specs.py / forge_metrics.py
lib/                baker, exporter, packager, media kit, listing writer
forge_cli.py        headless runner      forge_orch.py   queue orchestrator      forge_addon.py  control panel
manifest.json       md5 of the files validated by an accepted experiment
experiments.jsonl   every recorded experiment (before / after numbers, evidence)
tests/              self-test         experiments/legacy_tests/   historical validation scripts
```

## License

Sword Forge is free software under the [GNU General Public License v3.0 or later](LICENSE).
Third-party software it uses (Blender, PyMeshLab, NumPy, optional MeshLib) is listed in
[THIRD_PARTY.md](THIRD_PARTY.md). The optional MeshLib engine is free for non-commercial use only. It is not installed
by default and the pipeline does not need it.

Copyright (C) 2026 ab2ou

---

### بالعربية

Sword Forge نظام داخل بلندر يحوّل سيفاً مولّداً بالذكاء الاصطناعي إلى منتج جاهز للألعاب والبيع: تنظيف الهاي بولي،
لو بولي مع LODs، UV، خرائط 4K، تصدير، معرض صور، وحزم مضغوطة. بعد كل مرحلة بوابة فحص (PASS / REVIEW / FAIL)،
ولا تبدأ مرحلة فوق مرحلة فاشلة أو غير معتمدة. التثبيت: شغّل `setup_forge.py` ببايثون بلندر، ثم `tests/run_selftest.py` للتأكد.
