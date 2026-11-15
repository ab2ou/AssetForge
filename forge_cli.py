"""headless runner (used by the orchestrator, or by any AI/script that can start programs):

  blender -b <work.blend> -P <forge folder>/forge_cli.py -- <function> "<json kwargs>" [--save]

prints one line "FORGE_RESULT {...}". Exit codes: 0 PASS/REVIEW/ok, 2 gate FAIL, 3 error, 4 environment refused.
Test hook: env FORGE_INJECT="<function>:<n>" makes the first n calls of <function> crash (counter file next to the .blend).
"""
import sys, os, json, traceback
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
FORGE_DIR = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(FORGE_DIR, "forge.py"), encoding="utf-8").read())
import bpy
code = 0
try:
    if not FORGE_ENV["version_ok"]:
        print("FORGE_RESULT " + json.dumps({"error": "blender version not pinned", "env": FORGE_ENV})); sys.exit(4)
    fn_name = argv[0]; kw = json.loads(argv[1]) if len(argv) > 1 and not argv[1].startswith("--") else {}
    _cfg = load_config()
    if FORGE_ENV["untested_files"] and kw.get("project") and kw["project"] not in _cfg.get("test_projects", []) \
            and not _cfg.get("allow_untested_code"):
        print("FORGE_RESULT " + json.dumps({"error": "untested code on a real project (evidence first): run it on a test "
              "project, then record_experiment(...) with the measured before/after", "untested": FORGE_ENV["untested_files"]})); sys.exit(4)
    inj = os.environ.get("FORGE_INJECT", "")
    if inj.startswith(fn_name + ":"):
        cnt_file = bpy.data.filepath + ".inject_count"
        n = int(open(cnt_file).read()) if os.path.exists(cnt_file) else 0
        if n < int(inj.split(":")[1]):
            open(cnt_file, "w").write(str(n + 1))
            raise RuntimeError(f"TRANSIENT injected failure {n + 1} for {fn_name}")
    if not bpy.data.filepath:                       # new work file (factory startup): drop the default Cube/Camera/Light
        for _n in ("Cube", "Camera", "Light"):
            _o = bpy.data.objects.get(_n)
            if _o is not None: bpy.data.objects.remove(_o, do_unlink=True)
    res = globals()[fn_name](**kw)
    if isinstance(res, dict) and res.get("status") == "FAIL": code = 2
    if "--save" in argv:
        if bpy.data.filepath: bpy.ops.wm.save_mainfile()
        elif os.environ.get("FORGE_WORK"):
            os.makedirs(os.path.dirname(os.environ["FORGE_WORK"]), exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=os.environ["FORGE_WORK"])
    print("FORGE_RESULT " + json.dumps({"ok": True, "result": res}, default=str)[:200000])
except SystemExit:
    raise
except Exception:
    print("FORGE_RESULT " + json.dumps({"error": traceback.format_exc()})); code = 3
sys.stdout.flush()
sys.exit(code)
