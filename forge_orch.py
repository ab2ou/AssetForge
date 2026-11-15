"""AssetForge orchestrator - runs OUTSIDE Blender (any Python 3, e.g. Blender's own python.exe).

Each step runs in a fresh headless Blender (`blender -b work.blend -P forge_cli.py -- fn json --save`):
no viewport, no UI freeze, no 60 s limit, a crash only kills that step.

  python forge_orch.py run   <queue.json>          # run / resume everything in the queue
  python forge_orch.py status <project>
  python forge_orch.py reset  <project> <step_id>  # make a failed/done step run again

Queue file:
  {"blender": "<path to blender.exe> (optional: paths.local.json \"blender\", env BLENDER or blender on PATH)",
   "projects": [{"project": "inferno_dragon_sword", "work_blend": "D:\\\\...\\\\work\\\\inferno_dragon_sword.blend",
                 "steps": [{"id": "variants", "fn": "s2_variants", "kw": {"project": "inferno_dragon_sword"},
                            "timeout_min": 180, "continue_on_review": true}]}]}

Guarantees: one orchestrator per project (lock file), atomic journal writes, fingerprints of inputs
(function, arguments, forge code, config), a backup of the .blend before each step, a disk-space check,
limited retries of transient errors, verification of the stage report, a log file per attempt, and resume:
steps already done with the same fingerprint are skipped.
"""
import os, sys, json, time, hashlib, shutil, subprocess

FORGE = os.path.dirname(os.path.abspath(__file__))
try: _LOCAL = json.load(open(os.path.join(FORGE, "paths.local.json"), encoding="utf-8"))   # see paths.example.json
except Exception: _LOCAL = {}
PROJECTS = os.path.expanduser(os.environ.get("FORGE_PROJECTS") or _LOCAL.get("projects_root")
                              or os.path.join("~", "AssetForge", "projects"))
BLENDER = _LOCAL.get("blender") or os.environ.get("BLENDER") or "blender"
MIN_FREE_GB = {}
for _d, _need in ((FORGE, 3.0), (PROJECTS, 15.0)):        # free space on the code drive and on the projects drive
    _k = os.path.splitdrive(os.path.abspath(_d))[0] + os.sep; MIN_FREE_GB[_k] = max(MIN_FREE_GB.get(_k, 0), _need)
TRANSIENT = ("TRANSIENT", "MemoryError", "EXCEPTION_ACCESS_VIOLATION", "Timeout", "out of memory", "No space left")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def atomic_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


LEDGER = os.path.expanduser((None if os.environ.get("FORGE_PROJECTS") else _LOCAL.get("ledger"))
                            or os.path.join(os.path.dirname(PROJECTS), "forge_ledger.jsonl"))


def ledger(event, **kw):
    try:
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(t=now(), event=event, agent=os.environ.get("FORGE_AGENT", "orchestrator"), **kw), default=str) + "\n")
    except Exception:
        pass


def code_hash():
    """pipeline version (FORGE_VERSION in forge.py) + config.json. Bump FORGE_VERSION when a change must
    invalidate finished steps; small fixes do not force a full re-run."""
    h = hashlib.sha1()
    for line in open(os.path.join(FORGE, "forge.py"), encoding="utf-8"):
        if line.startswith("FORGE_VERSION"): h.update(line.encode())
    cp = os.path.join(FORGE, "config.json")
    if os.path.exists(cp): h.update(open(cp, "rb").read())
    return h.hexdigest()[:12]


def fingerprint(step, chash):
    return hashlib.sha1(json.dumps([step["fn"], step.get("kw", {}), chash], sort_keys=True).encode()).hexdigest()[:16]


def disk_ok():
    bad = {}
    for d, need in MIN_FREE_GB.items():
        try:
            free = shutil.disk_usage(d).free / 1e9
            if free < need: bad[d] = round(free, 1)
        except Exception:
            pass
    return bad


def pid_alive(pid):
    """True if a process with this id runs (Windows: tasklist; never os.kill, which terminates on Windows)."""
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], capture_output=True).stdout
            return f'"{int(pid)}"'.encode() in out
        os.kill(int(pid), 0); return True
    except Exception:
        return False


class Lock:
    def __init__(self, path): self.path = path

    def __enter__(self):
        if os.path.exists(self.path):
            info = read_json(self.path, {})
            if time.time() - info.get("t", 0) < 6 * 3600 and pid_alive(info.get("pid", -1)):
                raise SystemExit(f"locked by another orchestrator: {info}")
            print(f"stale lock (orchestrator {info.get('pid')} is not running) - taken over")
        atomic_json(self.path, {"pid": os.getpid(), "t": time.time(), "since": now()}); return self

    def __exit__(self, *a):
        try: os.remove(self.path)
        except Exception: pass


def run_step(blender, work, step, logdir, attempt):
    os.makedirs(logdir, exist_ok=True)
    log = os.path.join(logdir, f"{step['id']}_{time.strftime('%Y%m%d_%H%M%S')}_a{attempt}.log")
    args = [blender, "-b"] + ([work] if os.path.exists(work) else ["--factory-startup"]) + ["--python", os.path.join(FORGE, "forge_cli.py"), "--", step["fn"],
            json.dumps(step.get("kw", {}))] + (["--save"] if step.get("save", True) else [])
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as lf:
        try:
            p = subprocess.run(args, stdout=lf, stderr=subprocess.STDOUT, timeout=step.get("timeout_min", 120) * 60,
                               env=dict(os.environ, FORGE_WORK=work, **step.get("env", {})))
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = -9; lf.write("\nTimeout: step exceeded its time limit\n")
    text = open(log, encoding="utf-8", errors="replace").read()
    res = None
    for line in text.splitlines()[::-1]:
        if line.startswith("FORGE_RESULT "):
            try: res = json.loads(line[13:])
            except Exception: res = {"error": "unparsable result"}
            break
    return rc, res, log, round(time.time() - t0, 1), text


def verify(project, step, started):
    """the stage must have written a fresh report + decision (gate steps only)."""
    st = step.get("verify_stage")
    if not st: return True, "no stage report expected"
    d = os.path.join(PROJECTS, project, "reports", st)
    for f in ("report.json", "decision.json"):
        p = os.path.join(d, f)
        if not os.path.exists(p) or os.path.getmtime(p) < started - 1:
            return False, f"missing or stale {p}"
    return True, "report ok"


def run_queue(qpath):
    Q = read_json(qpath); blender = Q.get("blender", BLENDER); chash = code_hash()
    for pj in Q["projects"]:
        project = pj["project"]; root = os.path.join(PROJECTS, project); os.makedirs(root, exist_ok=True)
        jpath = os.path.join(root, "orch_journal.json"); J = read_json(jpath, {"project": project, "steps": {}, "events": []})
        work = pj["work_blend"]
        with Lock(os.path.join(root, ".orch.lock")):
            for step in pj["steps"]:
                sid = step["id"]; fp = fingerprint(step, chash); rec = J["steps"].get(sid, {})
                if rec.get("state") == "done" and rec.get("fingerprint") == fp:
                    print(f"[{project}] {sid}: done already (same fingerprint) - skipped"); continue
                if rec.get("state") == "stopped" and rec.get("fingerprint") == fp and not step.get("rerun"):
                    S = read_json(os.path.join(root, "state.json"), {}); vs = step.get("verify_stage")
                    if vs and S.get("stages", {}).get(vs, {}).get("approved") and rec.get("decision") == "REVIEW":
                        rec["state"] = "done"; rec["approved"] = S["stages"][vs]["approved"]; atomic_json(jpath, J)
                        print(f"[{project}] {sid}: REVIEW approved by {rec['approved'].get('by')} - continuing"); continue
                    print(f"[{project}] {sid}: stopped at {rec.get('decision')} - needs review/reset"); break
                bad = disk_ok()
                if bad:
                    J["events"].append({"t": now(), "event": "paused_disk", "free": bad}); atomic_json(jpath, J)
                    print(f"PAUSED: low disk {bad}"); return 5
                if os.path.exists(work):                                     # backup before a step can change it
                    shutil.copy2(work, work + ".before_" + sid)
                max_try = step.get("retries", 2) + 1
                for attempt in range(1, max_try + 1):
                    started = time.time()
                    rec = {"state": "running", "fingerprint": fp, "fn": step["fn"], "attempt": attempt, "started": now()}
                    J["steps"][sid] = rec; atomic_json(jpath, J)
                    print(f"[{project}] {sid}: attempt {attempt} ...", flush=True)
                    rc, res, log, secs, text = run_step(blender, work, step, os.path.join(root, "logs"), attempt)
                    rec.update(rc=rc, log=log, seconds=secs, ended=now())
                    err = (res or {}).get("error") if res else "no FORGE_RESULT (crash?)"
                    if err:
                        transient = rc in (-9, None) or res is None or any(k in str(err) + text[-4000:] for k in TRANSIENT)
                        rec.update(state="error", error=str(err)[-1500:], transient=transient)
                        J["events"].append({"t": now(), "step": sid, "event": "error", "attempt": attempt, "transient": transient})
                        ledger("step_error", project=project, step=sid, fn=step["fn"], attempt=attempt, transient=transient, error=str(err)[-400:], log=log)
                        atomic_json(jpath, J)
                        if transient and attempt < max_try:
                            if os.path.exists(work + ".before_" + sid):           # restore the input of the step
                                shutil.copy2(work + ".before_" + sid, work)
                            time.sleep(min(30, 5 * attempt)); continue
                        print(f"[{project}] {sid}: ERROR -> stop (see {log})"); return 3
                    ok, why = verify(project, step, started)
                    result = res.get("result") if isinstance(res, dict) else None
                    decision = (result.get("status") if isinstance(result, dict) else None) if step.get("verify_stage") else "ok"
                    rec.update(verify=why, decision=decision)
                    if not ok:
                        rec["state"] = "error"; atomic_json(jpath, J); print(f"[{project}] {sid}: verify failed {why}"); return 3
                    if decision == "FAIL" or (decision == "REVIEW" and not step.get("continue_on_review")):
                        rec["state"] = "stopped"; atomic_json(jpath, J)
                        ledger("step_stopped", project=project, step=sid, decision=decision)
                        print(f"[{project}] {sid}: {decision} -> stop for review (reports/{step.get('verify_stage', '')})"); return 0
                    rec["state"] = "done"; atomic_json(jpath, J); print(f"[{project}] {sid}: {decision} in {secs}s")
                    ledger("step_done", project=project, step=sid, fn=step["fn"], decision=decision, seconds=secs, attempts=attempt)
                    break
    return 0


def status(project):
    J = read_json(os.path.join(PROJECTS, project, "orch_journal.json"), {})
    S = read_json(os.path.join(PROJECTS, project, "state.json"), {})
    return {"orchestrator": {k: {kk: v.get(kk) for kk in ("state", "decision", "attempt", "seconds", "ended")} for k, v in J.get("steps", {}).items()},
            "stages": {k: v.get("status") for k, v in S.get("stages", {}).items()}}


def reset(project, sid):
    p = os.path.join(PROJECTS, project, "orch_journal.json"); J = read_json(p, {})
    J.get("steps", {}).pop(sid, None); atomic_json(p, J); return True


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "run": sys.exit(run_queue(sys.argv[2]))
    elif cmd == "status": print(json.dumps(status(sys.argv[2]), indent=2))
    elif cmd == "reset": print(reset(sys.argv[2], sys.argv[3]))
    else: print(__doc__)
