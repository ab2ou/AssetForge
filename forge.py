"""AssetForge loader (shared core for the add-on, the CLI and MCP calls).

    FORGE_DIR = r"<path to this folder>"     # optional once setup_forge.py has run (or env FORGE_DIR is set)
    exec(open(FORGE_DIR + "/forge.py", encoding="utf-8").read())
    status("my_sword")

Read PIPELINE.md first. Every stage refuses to run when the previous gate is not PASS (or approved REVIEW).
"""
import os, json, sys


def _find_forge_dir():
    """the code folder: FORGE_DIR set before exec > env FORGE_DIR > folder of the running script > the path stored in
    ~/.assetforge_dir by setup_forge.py."""
    cands = [globals().get("FORGE_DIR"), os.environ.get("FORGE_DIR")]
    if globals().get("__file__"): cands.append(os.path.dirname(os.path.abspath(globals()["__file__"])))
    ptr = os.path.join(os.path.expanduser("~"), ".assetforge_dir")
    if os.path.exists(ptr): cands.append(open(ptr, encoding="utf-8").read().strip())
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "forge_core.py")): return os.path.abspath(c)
    raise RuntimeError("AssetForge folder not found: set FORGE_DIR before exec(...), set the environment variable "
                       "FORGE_DIR, or run setup_forge.py once")


FORGE_DIR = _find_forge_dir()
try: _LOCAL = json.load(open(os.path.join(FORGE_DIR, "paths.local.json"), encoding="utf-8"))
except Exception: _LOCAL = {}
FORGE_PYLIBS = _LOCAL.get("pylibs") or os.path.join(FORGE_DIR, "pylibs")    # pymeshlab (+ optional meshlib)
if os.path.isdir(FORGE_PYLIBS) and FORGE_PYLIBS not in sys.path: sys.path.append(FORGE_PYLIBS)
_FILES = ("forge_core.py", "forge_mesh.py", "forge_render.py", "forge_metrics.py",
           "lib/baker_v2.py", "lib/uv_layout.py", "lib/game_mesh.py", "lib/fab_export_v2.py", "lib/fab_pivot.py",
           "lib/media_kit.py", "lib/fab_package_v4.py", "lib/listing_writer_v5.py", "lib/seam_normals.py",
           "forge_uv.py", "forge_specs.py", "forge_look.py", "forge_stages.py")
_seen = {}; FORGE_NAME_CLASHES = []                   # LESSON 14: one shared namespace -> a later file silently
for _f in _FILES:                                     # replaced forge_render._aim with media_kit._aim (broken renders)
    _src = open(os.path.join(FORGE_DIR, _f), encoding="utf-8").read()
    for _line in _src.splitlines():
        if _line.startswith("def "):
            _n = _line[4:].split("(")[0]
            if _n in _seen: FORGE_NAME_CLASHES.append(f"{_n}: {_seen[_n]} vs {_f}")
            _seen[_n] = _f
    exec(_src)
if FORGE_NAME_CLASHES:
    print("FORGE WARNING: function name clashes:", FORGE_NAME_CLASHES)
# FORGE_VERSION = pipeline version: bump only when finished steps must be redone (it is part of the step fingerprints)
FORGE_VERSION = "1.1"
FORGE_RELEASE = "1.2"                  # code release (CHANGELOG)


def check_environment():
    """production Blender version is pinned in config.json ("blender_version"); a different version only runs
    when "allow_untested_blender" is true (test it in a separate copy first)."""
    import bpy, importlib
    cfg = load_config(); want = cfg.get("blender_version", "5.2.2"); have = bpy.app.version_string.split()[0]
    deps = {}
    for m in ("numpy", "bmesh", "mathutils"):
        try: importlib.import_module(m); deps[m] = "ok"
        except Exception as e: deps[m] = f"missing: {e}"
    ok = have.startswith(want) or cfg.get("allow_untested_blender", False)
    free = {}
    import shutil
    for d in {os.path.splitdrive(x)[0] + os.sep for x in (FORGE_DIR, cfg.get("projects_root", FORGE_DIR))}:
        try: free[d] = round(shutil.disk_usage(d).free / 1e9, 1)
        except Exception: pass
    unt = untested_files(["forge.py"] + list(_FILES) + ["forge_cli.py", "forge_orch.py", "config.json", "weapon_profiles.json"])
    return {"blender": have, "pinned": want, "version_ok": ok and not FORGE_NAME_CLASHES, "deps": deps, "free_gb": free,
            "forge": FORGE_VERSION, "release": FORGE_RELEASE, "name_clashes": FORGE_NAME_CLASHES, "untested_files": unt, "code_tested": not unt}


FORGE_ENV = check_environment()
if FORGE_ENV["untested_files"]:
    print("FORGE NOTE: untested files (allowed on test projects only until record_experiment validates them):", FORGE_ENV["untested_files"])
if not FORGE_ENV["version_ok"]:
    print(f"FORGE WARNING: Blender {FORGE_ENV['blender']} is not the pinned production version {FORGE_ENV['pinned']}")
