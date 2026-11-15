"""forge_core - project folders, state, gates (PASS/FAIL/REVIEW), checkpoints, background jobs.

Every stage function:
  1. calls P.require(<previous stage>)        -> refuses to run on top of a failed/unreviewed stage
  2. does its work
  3. builds a Gate, adds checks, saves report  -> P.finish(stage, gate)
Nothing here needs scipy/PIL: only bpy + numpy (Blender's own Python).
"""
import os, json, time, shutil, traceback

FORGE_DIR = globals().get("FORGE_DIR") or os.path.dirname(os.path.abspath(__file__))     # set by forge.py


def load_paths():
    """machine paths, kept out of the method (and out of the evidence manifest): paths.local.json next to the code,
    see paths.example.json. Default: ~/SwordForge/projects with the ledger beside it."""
    try: p = json.load(open(os.path.join(FORGE_DIR, "paths.local.json"), encoding="utf-8"))
    except Exception: p = {}
    env = os.environ.get("FORGE_PROJECTS")                      # e.g. the self-test runs in a temporary folder
    root = os.path.expanduser(env or p.get("projects_root") or os.path.join("~", "SwordForge", "projects"))
    led = None if env else p.get("ledger")
    return {"projects_root": root, "blender": p.get("blender") or "blender",
            "ledger": os.path.expanduser(led or os.path.join(os.path.dirname(root), "forge_ledger.jsonl"))}


PATHS = load_paths()

STAGES = ["s0_intake", "s1_highpoly", "s2_lowpoly", "s3_uv", "s4_bake", "s5_look", "s6_lods",
          "s7_export", "s8_media", "s9_package", "s10_publish"]

DEFAULTS = {
    "projects_root": PATHS["projects_root"],
    "keep_checkpoints_per_stage": 2,
    "category": "hero_sword",
    "test_projects": ["forge_selftest"],                       # untested code may only run on these (evidence first)
    "allow_untested_code": False,
    "weapon": {"type": None, "style": "fantasy", "character_height_m": 1.80},
    # triangle budgets (LOD0 start, LOD0 max, LOD1 ratio, LOD2 ratio)
    "budgets": {"hero_sword": [18000, 32000, 0.5, 0.25], "standard_sword": [9000, 16000, 0.5, 0.25],
                "mobile_sword": [3000, 6000, 0.5, 0.25]},
    "texture_size": 4096,
    "uv_padding_px": 16,
    "uv_coverage": [0.65, 0.60],            # PASS >= [0], REVIEW >= [1], else FAIL
    # 1.5.0 (user decision 2026-11-03, silver_fang benchmark of 32 methods): AI high polys are rebuilt through a voxel
    # signed-distance grid (Blender OpenVDB voxel remesh since 1.5.2; MeshLib optional) + Taubin smoothing at s1; the low poly is a PyMeshLab quadric (QEM) decimation
    "high_cleanup": {"method": "voxel", "engine": "blender", "voxel_rel": 0.00071, "taubin_steps": 15, "min_part_pct": 1.5},
    "lowpoly": {"method": "qem", "qem_quality": 0.2,
                "dev_p99_rel": 0.0015,      # deviation p99 as a fraction of the asset length (1.26 m -> 1.9 mm)
                "folds_max_rel": 0.002,     # concave folds (>150 deg) as a fraction of edges
                "min_angle_deg": 1.0},
    # sword families override the defaults above (any key of lowpoly / uv_coverage / budgets entry)
    "family": "ornate",
    "families": {
        "straight_simple": {"lowpoly": {"dev_p99_rel": 0.0010, "folds_max_rel": 0.001}, "uv_coverage": [0.70, 0.65]},
        "curved":          {"lowpoly": {"dev_p99_rel": 0.0013, "folds_max_rel": 0.0015}, "uv_coverage": [0.67, 0.62]},
        "ornate":          {"lowpoly": {"dev_p99_rel": 0.0018, "folds_max_rel": 0.003}, "uv_coverage": [0.62, 0.55]},
    },
}


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict): _merge(a[k], v)
        else: a[k] = v
    return a


def load_config(family=None):
    cfg = json.loads(json.dumps(DEFAULTS))
    p = os.path.join(FORGE_DIR, "config.json")
    if os.path.exists(p):
        user = json.load(open(p, encoding="utf-8"))
        _merge(cfg, user)
    fam = family or cfg.get("family")
    if fam in cfg.get("families", {}): _merge(cfg, cfg["families"][fam]); cfg["family"] = fam
    return cfg


LEDGER = PATHS["ledger"]                                       # append-only history of every run, all projects
LESSONS_JSONL = os.path.join(FORGE_DIR, "lessons.jsonl")       # lessons recorded by any agent (machine readable)


def agent_name():
    return os.environ.get("FORGE_AGENT", "unknown-agent")


def ledger(event, **kw):
    """one JSON line per event; never raises (the ledger must not break production)."""
    try:
        rec = dict(t=time.strftime("%Y-%m-%d %H:%M:%S"), event=event, agent=agent_name(), **kw)
        with open(LEDGER, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def record_lesson(kind, title, what, cause="", fix="", gate="", project="", stage="", evidence=(), agent=None):
    """kind: "error" | "success" | "idea". Any agent (or person) calls this when something went wrong or worked well.
    It is appended to forge/lessons.jsonl and LESSONS_LOG.md is regenerated. Promote important ones to LESSONS.md
    (with the gate that now prevents them) in the next development round."""
    if kind in ("error", "success"):
        miss = [e for e in evidence if not os.path.exists(e)]
        if not evidence or miss:
            raise EvidenceError(f"a {kind} lesson needs existing evidence files (missing: {miss or 'none given'}); "
                                "an untested opinion is recorded as kind='idea'")
    rec = {"t": time.strftime("%Y-%m-%d %H:%M"), "kind": kind, "title": title, "what": what, "cause": cause, "fix": fix,
           "gate": gate, "project": project, "stage": stage, "evidence": list(evidence), "agent": agent or agent_name(),
           "tested": kind != "idea"}
    with open(LESSONS_JSONL, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rows = [json.loads(l) for l in open(LESSONS_JSONL, encoding="utf-8") if l.strip()]
    L = ["# Lessons log (auto-generated from lessons.jsonl - do not edit by hand)", "",
         "| date | kind | project/stage | title | cause | fix | gate | agent |", "|---|---|---|---|---|---|---|---|"]
    for r in rows[::-1]:
        L.append(f"| {r['t']} | {r['kind']} | {r['project']}/{r['stage']} | {r['title']} | {r['cause']} | {r['fix']} | {r['gate']} | {r['agent']} |")
    open(os.path.join(FORGE_DIR, "LESSONS_LOG.md"), "w", encoding="utf-8").write("\n".join(L))
    ledger("lesson", kind=kind, title=title, project=project, stage=stage)
    return rec


# ======================================================================= evidence first (CONTRIBUTING rule 0)
# A change to the code or to the reference data counts only when a live run proves it. record_experiment() refuses
# a record without measured before/after values and existing evidence files; accepted experiments register the md5 of
# the changed files in manifest.json. Files whose md5 is not registered are "untested": forge_cli refuses to run them
# on a real project (only on test projects such as forge_selftest) until an experiment validates them.
EXPERIMENTS_JSONL = os.path.join(FORGE_DIR, "experiments.jsonl")
MANIFEST = os.path.join(FORGE_DIR, "manifest.json")


class EvidenceError(RuntimeError):
    pass


def func_hashes(path):
    """md5 of each top-level function/class of a .py file, plus '<module>' for everything outside them (1.4.5)."""
    import ast, hashlib
    src = open(path, encoding="utf-8").read(); tree = ast.parse(src); out = {}; rest = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = hashlib.md5((ast.get_source_segment(src, node) or "").encode("utf-8")).hexdigest()
        else: rest.append(ast.dump(node))
    out["<module>"] = hashlib.md5("\n".join(rest).encode("utf-8")).hexdigest()
    return out


def seed_function_baselines():
    """store function hashes for manifest files whose current md5 is the tested one (or whose backup is)."""
    man = load_manifest(); done = {}
    for f, e in man["files"].items():
        if e.get("funcs") or not f.endswith(".py"): continue
        p = os.path.join(FORGE_DIR, f)
        cands = [p] + sorted([os.path.join(os.path.dirname(p), b) for b in os.listdir(os.path.dirname(p))
                              if b.startswith(os.path.basename(p) + ".before_")], reverse=True) if os.path.exists(p) else []
        for c in cands:
            if file_md5(c) == e["md5"]: e["funcs"] = func_hashes(c); done[f] = os.path.basename(c); break
    tmp = MANIFEST + ".tmp"; json.dump(man, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, MANIFEST)
    return done


def file_md5(path):
    """1.5.3: line endings do not count (git may check files out with CRLF or LF)."""
    import hashlib
    return hashlib.md5(open(path, "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def load_manifest():
    return json.load(open(MANIFEST, encoding="utf-8")) if os.path.exists(MANIFEST) else {"files": {}}


def untested_files(rel_paths):
    """files whose current md5 was never validated by an accepted experiment."""
    man = load_manifest()["files"]; out = []
    for r in rel_paths:
        p = os.path.join(FORGE_DIR, r)
        if not os.path.exists(p): continue
        if man.get(r.replace("\\", "/"), {}).get("md5") != file_md5(p): out.append(r)
    return out


def record_experiment(title, change, hypothesis, files, runs, before, after, evidence, result, notes="", agent=None,
                      functions=None):
    """The only way a code/data change becomes "tested".
    files    : changed files relative to the forge folder (e.g. ["forge_uv.py"]) - their current md5 is registered
    runs     : [{"project": ..., "step" or "stage": ..., "report": <existing path>}]  the live runs that test it
    before / after : measured values (same keys) from those runs, e.g. {"min_gap_px": 10.5} -> {"min_gap_px": 17.2}
    evidence : existing files (reports, images, logs) a reviewer can open
    result   : "better" | "same" | "mixed" (accepted, md5 registered) or "worse" | "failed" (recorded, not accepted)
    General knowledge, articles or "best practice" without a run here are not evidence: record them as
    record_lesson("idea", ...) instead; they never change the code."""
    probs = []
    if result not in ("better", "same", "mixed", "worse", "failed"): probs.append(f"result {result!r}")
    if not isinstance(before, dict) or not isinstance(after, dict) or not before or not after:
        probs.append("before/after must be non-empty dicts of measured values")
    elif not (set(before) & set(after)): probs.append("before and after share no measured key")
    if not runs: probs.append("no live run listed")
    for r in runs or []:
        rp = r.get("report")
        if not rp or not os.path.exists(rp): probs.append(f"run report missing: {rp}")
    miss = [e for e in evidence or [] if not os.path.exists(e)]
    if not evidence: probs.append("no evidence files")
    if miss: probs.append(f"evidence files missing: {miss}")
    for f in files or []:
        if not os.path.exists(os.path.join(FORGE_DIR, f)): probs.append(f"changed file not found: {f}")
    # 1.4.5 (lesson 57): an old test re-run must not validate code it never touched. Every top-level function/class
    # changed since the file's last accepted experiment has to be named in functions=, and at least one run report or
    # evidence file must be newer than the change.
    changed_map = {}; man0 = load_manifest()["files"]
    for f in files or []:
        fpath = os.path.join(FORGE_DIR, f)
        if not f.endswith(".py") or not os.path.exists(fpath): continue
        prev = (man0.get(f.replace("\\", "/")) or {}).get("funcs")
        cur = func_hashes(fpath)
        if prev is None:
            changed_map[f] = "no function baseline yet"; continue
        ch = sorted(k for k in cur if prev.get(k) != cur[k]); changed_map[f] = ch
        miss_f = [k for k in ch if k not in (functions or [])]
        if miss_f: probs.append(f"{f}: changed but not named in functions= (an unrelated test cannot validate them): {miss_f}")
        newest = max([os.path.getmtime(r["report"]) for r in runs or [] if r.get("report") and os.path.exists(r["report"])] +
                     [os.path.getmtime(e) for e in evidence or [] if os.path.exists(e)] + [0])
        if ch and newest < os.path.getmtime(fpath) - 1:
            probs.append(f"{f}: every run/evidence file is older than the last edit of the file (re-run after the change)")
    if probs:
        raise EvidenceError("experiment refused (evidence first): " + "; ".join(probs))
    import uuid; eid = time.strftime("exp_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    rec = {"id": eid, "t": time.strftime("%Y-%m-%d %H:%M"), "agent": agent or agent_name(), "title": title, "change": change,
           "hypothesis": hypothesis, "files": {f: file_md5(os.path.join(FORGE_DIR, f)) for f in files or []},
           "functions": list(functions or []), "functions_changed": changed_map,
           "runs": runs, "before": before, "after": after, "evidence": list(evidence), "result": result, "notes": notes}
    with open(EXPERIMENTS_JSONL, "a", encoding="utf-8") as fh: fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    accepted = result in ("better", "same", "mixed")
    if accepted and files:
        man = load_manifest()
        for f, h in rec["files"].items():
            e_ = {"md5": h, "experiment": eid, "t": rec["t"]}
            if f.endswith(".py"): e_["funcs"] = func_hashes(os.path.join(FORGE_DIR, f))
            man["files"][f.replace("\\", "/")] = e_
        tmp = MANIFEST + ".tmp"; json.dump(man, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, MANIFEST)
    rows = [json.loads(l) for l in open(EXPERIMENTS_JSONL, encoding="utf-8") if l.strip()]
    L = ["# Experiments (auto-generated from experiments.jsonl - evidence for every code/data change)", "",
         "| id | date | agent | title | result | before | after | files |", "|---|---|---|---|---|---|---|---|"]
    for r in rows[::-1]:
        L.append(f"| {r['id']} | {r['t']} | {r['agent']} | {r['title']} | {r['result']} | {json.dumps(r['before'])} | {json.dumps(r['after'])} | {', '.join(r['files'])} |")
    open(os.path.join(FORGE_DIR, "EXPERIMENTS.md"), "w", encoding="utf-8").write("\n".join(L))
    ledger("experiment", id=eid, title=title, result=result, files=list(rec["files"]), accepted=accepted)
    return {"id": eid, "accepted": accepted}


def register_baseline(files, evidence, note, agent=None):
    """one-time start of the manifest: register the files that earlier live runs already validated (only while the
    manifest is empty; every later change goes through record_experiment)."""
    man = load_manifest()
    if man["files"]: raise EvidenceError("the manifest already exists: use record_experiment for changes")
    miss = [e for e in evidence if not os.path.exists(e)]
    if not evidence or miss: raise EvidenceError(f"baseline needs existing evidence files (missing: {miss or 'none given'})")
    eid = "baseline_" + time.strftime("%Y%m%d_%H%M%S")
    for f in files:
        man["files"][f] = {"md5": file_md5(os.path.join(FORGE_DIR, f)), "experiment": eid, "t": time.strftime("%Y-%m-%d %H:%M")}
    man["baseline"] = {"id": eid, "note": note, "evidence": list(evidence), "agent": agent or agent_name()}
    tmp = MANIFEST + ".tmp"; json.dump(man, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, MANIFEST)
    ledger("baseline", id=eid, files=list(files))
    return {"id": eid, "files": len(files)}


class GateError(RuntimeError):
    pass


class Gate:
    """collects checks; status = FAIL if any FAIL, else REVIEW if any REVIEW, else PASS."""

    def __init__(self, stage):
        self.stage = stage; self.checks = []; self.images = []; self.notes = []; self.data = {}
        self.diagnostics = []; self.comparison = []

    def check(self, cid, value, ok, review=False, msg="", expected=None):
        st = "PASS" if ok else ("REVIEW" if review else "FAIL")
        self.checks.append({"id": cid, "value": value, "expected": expected, "status": st, "msg": msg})
        return st

    def need_review(self, cid, msg):
        """things only a human (or a vision model) can judge: always REVIEW until approved."""
        self.checks.append({"id": cid, "value": None, "status": "REVIEW", "msg": msg})

    def image(self, path, caption="", kind="images"):
        getattr(self, kind).append({"path": path, "caption": caption})

    @property
    def status(self):
        s = [c["status"] for c in self.checks]
        return "FAIL" if "FAIL" in s else ("REVIEW" if "REVIEW" in s else "PASS")


class Project:
    def __init__(self, name, cfg=None):
        self.name = name
        root0 = load_config()["projects_root"]; sp = os.path.join(root0, name, "state.json")
        st0 = json.load(open(sp, encoding="utf-8")).get("settings", {}) if os.path.exists(sp) else {}
        fam = st0.get("family")
        self.cfg = cfg or load_config(fam)
        # per-project override (user decision, e.g. a higher LOD0 budget for one hero asset); merged last, this project only
        if not cfg and isinstance(st0.get("cfg_override"), dict): _merge(self.cfg, json.loads(json.dumps(st0["cfg_override"])))
        self.root = os.path.join(self.cfg["projects_root"], name)
        for d in ["source", "work", "reports", "checkpoints", "renders", "export", "package"]:
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self.state_path = os.path.join(self.root, "state.json")
        self.state = json.load(open(self.state_path, encoding="utf-8")) if os.path.exists(self.state_path) else \
            {"name": name, "created": time.strftime("%Y-%m-%d %H:%M"), "stages": {}, "anatomy": {}, "settings": {}}

    # ---------- paths
    def p(self, *a):
        return os.path.join(self.root, *a)

    def gate_dir(self, stage, sub=""):
        d = os.path.join(self.root, "reports", stage, sub); os.makedirs(d, exist_ok=True); return d

    def save(self):
        tmp = self.state_path + ".tmp"
        json.dump(self.state, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    # ---------- stage control
    def status(self, stage):
        return self.state["stages"].get(stage, {}).get("status", "TODO")

    def require(self, stage):
        st = self.status(stage)
        if st == "PASS" or (st == "REVIEW" and self.state["stages"][stage].get("approved")):
            return True
        raise GateError(f"{stage} is {st}: fix it (or approve its REVIEW items) before running the next stage")

    def approve(self, stage, who="user", note=""):
        """a human/vision review accepted the REVIEW items of a stage."""
        s = self.state["stages"].setdefault(stage, {})
        s["approved"] = {"by": who, "note": note, "time": time.strftime("%Y-%m-%d %H:%M")}
        self.save(); ledger("approve", project=self.name, stage=stage, by=who, note=note); return s

    def invalidate_after(self, stage):
        """re-running a stage makes every later stage stale."""
        if stage not in STAGES: return                       # side gates (s0_spec) do not make later stages stale
        i = STAGES.index(stage)
        for st in STAGES[i + 1:]:
            if st in self.state["stages"]:
                self.state["stages"][st]["status"] = "STALE"

    def finish(self, stage, gate, extra=None):
        rep = {"stage": stage, "status": gate.status, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "family": self.cfg.get("family"), "checks": gate.checks, "images": gate.images,
               "diagnostics": gate.diagnostics, "comparison": gate.comparison, "notes": gate.notes, "data": gate.data}
        try:
            import bpy
            rep["blender"] = bpy.app.version_string; rep["blend_file"] = bpy.data.filepath
        except Exception:
            pass
        if extra: rep.update(extra)
        gd = self.gate_dir(stage); self.gate_dir(stage, "diagnostics"); self.gate_dir(stage, "comparison")
        path = os.path.join(gd, "report.json")
        json.dump(rep, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
        json.dump(rep, open(self.p("reports", f"{stage}.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
        fails = [c for c in gate.checks if c["status"] == "FAIL"]; revs = [c for c in gate.checks if c["status"] == "REVIEW"]
        decision = {"stage": stage, "decision": gate.status, "time": rep["time"],
                    "reason": ("FAIL: " + ", ".join(f"{c['id']}={c['value']} (expected {c.get('expected') or c['msg']})" for c in fails)) if fails else
                              ("REVIEW needed: " + ", ".join(c["id"] for c in revs)) if revs else "all checks passed",
                    "failed": [c["id"] for c in fails], "to_review": [c["id"] for c in revs],
                    "look_at": [i["path"] for i in gate.comparison + gate.diagnostics],
                    "how_to_approve": f'Project("{self.name}").approve("{stage}", who="...", note="...")' if revs and not fails else None}
        json.dump(decision, open(os.path.join(gd, "decision.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        try:
            self._write_html(gd, rep, decision)
        except Exception as e:
            rep["notes"].append(f"html failed: {e!r}")
        self._write_md(stage, rep)
        self.invalidate_after(stage)
        self.state["stages"][stage] = {"status": gate.status, "time": rep["time"], "report": path}
        self.save()
        ledger("stage", project=self.name, stage=stage, status=gate.status, family=self.cfg.get("family"),
               failed=decision["failed"], review=decision["to_review"],
               values={c["id"]: c["value"] for c in gate.checks if not isinstance(c["value"], (dict, list))})
        return rep

    def _write_html(self, gd, rep, decision):
        import html
        col = {"PASS": "#1b7f3a", "FAIL": "#b3261e", "REVIEW": "#a15c00"}
        rows = "".join(f"<tr><td>{html.escape(str(c['id']))}</td><td style='color:{col.get(c['status'], '#333')};font-weight:600'>{c['status']}</td>"
                       f"<td>{html.escape(str(c['value']))}</td><td>{html.escape(str(c.get('expected') or ''))}</td><td>{html.escape(str(c['msg']))}</td></tr>"
                       for c in rep["checks"])
        def imgs(lst):
            out = ""
            for i in lst:
                rel = os.path.relpath(i["path"], gd).replace("\\", "/")
                out += f"<figure><a href='{rel}'><img src='{rel}' loading='lazy'></a><figcaption>{html.escape(i['caption'])} - {html.escape(os.path.basename(i['path']))}</figcaption></figure>"
            return out
        doc = f"""<!doctype html><html><head><meta charset='utf-8'><title>{rep['stage']} - {rep['status']}</title>
<style>body{{font-family:system-ui,sans-serif;margin:16px;background:#f6f6f4;color:#222}}table{{border-collapse:collapse;background:#fff}}
td,th{{border:1px solid #ddd;padding:4px 8px;font-size:13px}}figure{{display:inline-block;margin:6px;max-width:48%}}img{{max-width:100%;border:1px solid #ccc}}
.badge{{padding:4px 10px;border-radius:6px;color:#fff;background:{col.get(rep['status'], '#333')}}}</style></head><body>
<h1>{rep['stage']} <span class='badge'>{rep['status']}</span></h1>
<p><b>Decision:</b> {html.escape(decision['reason'])}</p>
<p>{rep['time']} - family: {rep.get('family')} - {html.escape(str(rep.get('blend_file', '')))}</p>
{('<p><b>To approve after looking at every image:</b> <code>' + html.escape(decision['how_to_approve']) + '</code></p>') if decision.get('how_to_approve') else ''}
<table><tr><th>check</th><th>status</th><th>value</th><th>expected</th><th>note</th></tr>{rows}</table>
<h2>Comparison</h2>{imgs(rep['comparison'])}<h2>Diagnostics</h2>{imgs(rep['diagnostics'])}<h2>Other</h2>{imgs(rep['images'])}
</body></html>"""
        open(os.path.join(gd, "index.html"), "w", encoding="utf-8").write(doc)

    def _write_md(self, stage, rep):
        L = [f"# {stage} - {rep['status']}", "", f"time: {rep['time']}  family: {rep.get('family')}", "",
             "| check | status | value | expected | note |", "|---|---|---|---|---|"]
        for c in rep["checks"]:
            L.append(f"| {c['id']} | {c['status']} | {c['value']} | {c.get('expected') or ''} | {c['msg']} |")
        if rep["notes"]: L += ["", "## notes"] + [f"- {n}" for n in rep["notes"]]
        for k in ("comparison", "diagnostics", "images"):
            if rep.get(k): L += ["", f"## {k}"] + [f"- {i['caption']}: `{i['path']}`" for i in rep[k]]
        open(self.p("reports", f"{stage}.md"), "w", encoding="utf-8").write("\n".join(L))

    # ---------- checkpoints (keep the last N per stage; older ones go to checkpoints/archive)
    def checkpoint(self, stage):
        import bpy
        d = self.p("checkpoints"); n = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(d, f"{stage}_{n}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        mine = sorted(f for f in os.listdir(d) if f.startswith(stage + "_") and f.endswith(".blend"))
        keep = self.cfg["keep_checkpoints_per_stage"]
        if len(mine) > keep:
            arch = os.path.join(d, "archive"); os.makedirs(arch, exist_ok=True)
            for f in mine[:-keep]:
                shutil.move(os.path.join(d, f), os.path.join(arch, f))
        return path


# ---------- background jobs (MCP calls time out after ~60 s; long work runs in a Blender timer)
def run_job(project, name, fn, *args, **kw):
    """runs fn(*args) in a bpy timer; status file reports/<name>.status.json = queued|running|done|error.
    In background (headless) Blender it simply runs synchronously."""
    import bpy
    path = project.p("reports", f"{name}.status.json")

    def W(**k):
        json.dump(dict(k, time=time.strftime("%H:%M:%S")), open(path, "w"), default=str)

    def job():
        W(state="running")
        try:
            r = fn(*args, **kw); W(state="done", result=r)
        except Exception:
            W(state="error", traceback=traceback.format_exc())
        return None
    if bpy.app.background:
        job(); return json.load(open(path))
    W(state="queued"); bpy.app.timers.register(job, first_interval=0.3)
    return {"state": "queued", "status_file": path}


def job_status(project, name):
    path = project.p("reports", f"{name}.status.json")
    return json.load(open(path)) if os.path.exists(path) else {"state": "missing"}
