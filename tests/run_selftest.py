"""Smoke test: builds the procedural self-test sword and runs it through s0 -> s2 with the orchestrator, in a
temporary projects folder (your own projects and ledger are not touched). One crash is injected into s2 and must be
retried automatically.

    "<Blender folder>/5.2/python/bin/python.exe" tests/run_selftest.py [--generic] [--blender <blender executable>] [--keep]

Exit code 0 when every step is done and the injected crash was retried. Takes a few minutes.
"""
import json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__)); FORGE = os.path.dirname(HERE); args = sys.argv[1:]


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default


try: local = json.load(open(os.path.join(FORGE, "paths.local.json"), encoding="utf-8"))
except Exception: local = {}
blender = opt("--blender") or local.get("blender") or os.environ.get("BLENDER") or "blender"
root = tempfile.mkdtemp(prefix="sword_forge_selftest_"); projects = os.path.join(root, "projects")

qname = "selftest_generic_queue.json" if "--generic" in args else "selftest_queue.json"   # --generic: a non-weapon asset
Q = json.load(open(os.path.join(HERE, qname), encoding="utf-8")); Q["blender"] = blender
for pj in Q["projects"]:
    pj["work_blend"] = os.path.join(projects, pj["project"], "work", pj["project"] + ".blend")
qpath = os.path.join(root, "queue.json")
with open(qpath, "w", encoding="utf-8") as f: json.dump(Q, f, indent=1)

env = dict(os.environ, FORGE_PROJECTS=projects, FORGE_AGENT=os.environ.get("FORGE_AGENT", "selftest"))
t0 = time.time()
rc = subprocess.call([sys.executable, os.path.join(FORGE, "forge_orch.py"), "run", qpath], env=env)

pdir = os.path.join(projects, Q["projects"][0]["project"])
J = json.load(open(os.path.join(pdir, "orch_journal.json"), encoding="utf-8"))
S = json.load(open(os.path.join(pdir, "state.json"), encoding="utf-8"))
steps = {k: v.get("state") for k, v in J["steps"].items()}
retried = any(e.get("event") == "error" and e.get("transient") for e in J.get("events", []))
want = [s["id"] for s in Q["projects"][0]["steps"]]
ok = rc == 0 and all(steps.get(s) == "done" for s in want) and retried
print(json.dumps({"ok": ok, "rc": rc, "minutes": round((time.time() - t0) / 60, 1), "steps": steps,
                  "injected_crash_retried": retried,
                  "stages": {k: v.get("status") for k, v in S.get("stages", {}).items()}, "folder": root}, indent=1))
if ok and "--keep" not in args: shutil.rmtree(root, ignore_errors=True)
sys.exit(0 if ok else 1)
