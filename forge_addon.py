bl_info = {"name": "Sword Forge", "author": "Blender AI Studio", "version": (2, 1, 0), "blender": (5, 2, 0),
           "location": "3D View > Sidebar (N) > Sword Forge", "description": "Control panel for the Sword Forge pipeline (no AI needed)",
           "category": "Pipeline"}
"""Sword Forge control panel 2.0 (2026-10-31).
Control only: the production logic stays in forge/*.py. Every stage runs in a separate headless Blender through the
orchestrator (forge_orch.py: lock, backup of the .blend before each step, retries, journal), so this Blender never
freezes and a crash only stops that step. The panel reads state.json / reports/<stage>/decision.json to show the
status, the failed or to-review checks with their messages, and the images to look at; Approve writes the same
record as Project.approve().
2.1 (2026-11-03): main card with progress and one "what to do now" button; Review, Stages, New project and Options are fold-out sub-panels (same buttons and settings as 2.0).
Install: Edit > Preferences > Add-ons > Install from Disk > forge_addon.py, then press N in the 3D view, tab "Sword Forge" (the tab "Forge" belongs to ForgeMaterial Studio).
UI text is English: Blender's interface does not shape Arabic letters."""
import bpy, os, sys, json, time, subprocess

def _forge_dir():
    """code folder: env FORGE_DIR > ~/.sword_forge_dir (written by setup_forge.py) > the folder of this file."""
    cands = [os.environ.get("FORGE_DIR")]
    ptr = os.path.join(os.path.expanduser("~"), ".sword_forge_dir")
    if os.path.exists(ptr): cands.append(open(ptr, encoding="utf-8").read().strip())
    cands.append(os.path.dirname(os.path.abspath(__file__)))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "forge_core.py")): return c
    return cands[-1]


def _local_paths(forge):
    try: p = json.load(open(os.path.join(forge, "paths.local.json"), encoding="utf-8"))
    except Exception: p = {}
    env = os.environ.get("FORGE_PROJECTS")
    root = os.path.expanduser(env or p.get("projects_root") or os.path.join("~", "SwordForge", "projects"))
    led = None if env else p.get("ledger")
    return root, os.path.expanduser(led or os.path.join(os.path.dirname(root), "forge_ledger.jsonl"))


FORGE_DIR = _forge_dir()
PROJECTS, LEDGER = _local_paths(FORGE_DIR)
STAGES = ["s0_intake", "s0_spec", "s1_highpoly", "s2_lowpoly", "s3_uv", "s4_bake", "s5_look", "s6_lods",
          "s7_export", "s8_media", "s9_package", "s10_publish"]
NICE = {"s0_intake": "0 Import", "s0_spec": "0b Spec", "s1_highpoly": "1 High poly", "s2_lowpoly": "2 Low poly",
        "s3_uv": "3 UV (~35 min)", "s4_bake": "4 Bake", "s5_look": "5 Look", "s6_lods": "6 LODs",
        "s7_export": "7 Export", "s8_media": "8 Gallery (~10 min)", "s9_package": "9 Package", "s10_publish": "10 Publish"}
NEEDS = {"s0_spec": "s0_intake", "s1_highpoly": "s0_spec", "s2_lowpoly": "s1_highpoly", "s3_uv": "s2_lowpoly",
         "s4_bake": "s3_uv", "s5_look": "s4_bake", "s6_lods": "s4_bake", "s7_export": "s6_lods", "s8_media": "s7_export",
         "s9_package": "s8_media", "s10_publish": "s9_package"}
TIMEOUT = {"s3_uv": 240, "s8_media": 120, "s2_lowpoly": 120, "s4_bake": 90}
_JOBS = {}            # project -> Popen of the orchestrator started from this Blender
_PREV = None          # image thumbnails


def _read(p, default=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return default


def _atomic(p, data):
    tmp = p + ".tmp"; json.dump(data, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str); os.replace(tmp, p)


def _projects(self, ctx):
    out = []
    if os.path.isdir(PROJECTS):
        for d in sorted(os.listdir(PROJECTS)):
            if os.path.exists(os.path.join(PROJECTS, d, "state.json")): out.append((d, d, ""))
    return out or [("", "(no project)", "")]


def _scene_groups(ctx):
    """mesh objects in the currently open .blend, grouped by topmost ancestor (one entry = one weapon/import).
    Lets 'Create + import' use a weapon that is already open instead of only a file on disk (several weapons
    are often open together, e.g. to compare before deciding which becomes a project)."""
    groups = {}
    for o in bpy.data.objects:
        if o.type != "MESH": continue
        r = o
        while r.parent is not None: r = r.parent
        groups.setdefault(r.name, []).append(o.name)
    return groups


def _scene_candidates(self, ctx):
    g = _scene_groups(ctx)
    if not g: return [("", "(no mesh objects open)", "")]
    items = []
    for root, names in sorted(g.items()):
        tris = 0
        for n in names:
            ob = bpy.data.objects.get(n)
            if ob and ob.type == "MESH": tris += len(ob.data.polygons)
        items.append((root, f"{root}  ({len(names)} obj, {tris:,} faces)", ""))
    return items


def _weapon_types(self, ctx):
    p = _read(os.path.join(FORGE_DIR, "weapon_profiles.json"), {}) or {}
    return [(k, k, "") for k in sorted(p.get("types", {}))] or [("arming_sword", "arming_sword", "")]


def _status(S, st):
    v = S.get("stages", {}).get(st, {}); s = v.get("status", "TODO")
    return s, bool(v.get("approved"))


def _ok(S, st):
    s, ap = _status(S, st); return s == "PASS" or (s == "REVIEW" and ap)


def _work(project):
    return os.path.join(PROJECTS, project, "work", project + ".blend")


def _running(project):
    p = _JOBS.get(project)
    if p is not None and p.poll() is None: return True
    lk = _read(os.path.join(PROJECTS, project, ".orch.lock"), None)      # an orchestrator started elsewhere
    if lk and time.time() - lk.get("t", 0) < 6 * 3600:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(lk['pid'])}", "/FO", "CSV", "/NH"], capture_output=True).stdout
            return f'"{int(lk["pid"])}"'.encode() in out
        except Exception: return False
    return False


def _steps_for(stage, f, S):
    """orchestrator steps for one stage (the last step of a gate is verified against its report)."""
    pj = f.project; k = {"project": pj}
    if stage == "s0_intake":
        return [{"fn": "s0_import", "kw": dict(k, path=bpy.path.abspath(f.source), title=f.title or None), "verify_stage": "s0_intake"}]
    if stage == "s0_spec":
        return [{"fn": "s0_spec", "kw": dict(k, weapon_type=f.weapon_type, style=f.style), "verify_stage": "s0_spec"}]
    if stage == "s2_lowpoly":
        return [{"fn": "set_target_use", "kw": dict(k, use=f.target_use)}, {"fn": "s2_auto", "kw": k, "verify_stage": "s2_lowpoly"}]
    if stage == "s4_bake":
        return [{"fn": "s4_bake", "kw": dict(k, size=int(f.bake_size))}, {"fn": "s4_bake_check", "kw": k, "verify_stage": "s4_bake"}]
    if stage == "s8_media":
        return [{"fn": "s8_media", "kw": k}, {"fn": "s8_media_check", "kw": k, "verify_stage": "s8_media"}]
    if stage == "s9_package":
        return [{"fn": "s9_package", "kw": dict(k, title=f.title or S.get("settings", {}).get("title")), "verify_stage": "s9_package"}]
    return [{"fn": stage, "kw": k, "verify_stage": stage}]


def _launch(ctx, stages, op, steps_override=None):
    f = ctx.scene.forge; pj = f.project
    if not pj: op.report({"ERROR"}, "choose or create a project first"); return False
    if _running(pj): op.report({"WARNING"}, "a job is already running for " + pj); return False
    work = _work(pj)
    try:                                   # 1.4.3b: the orchestrator backs up the .blend, not the stage states
        sp = os.path.join(PROJECTS, pj, "state.json")
        if os.path.exists(sp):
            import shutil; shutil.copy2(sp, sp + ".before_panel_" + time.strftime("%Y%m%d_%H%M%S"))
    except Exception: pass
    if bpy.data.filepath and os.path.normcase(bpy.data.filepath) == os.path.normcase(work) and bpy.data.is_dirty:
        op.report({"ERROR"}, "this Blender has unsaved changes in the project file: save or revert first (the job writes it)")
        return False
    root = os.path.join(PROJECTS, pj); os.makedirs(root, exist_ok=True); S = _read(os.path.join(root, "state.json"), {}) or {}
    J = _read(os.path.join(root, "orch_journal.json"), {"project": pj, "steps": {}, "events": []}) or {}
    steps = []
    for st in stages:
        sub = (steps_override or {}).get(st) if steps_override else None
        for i, s in enumerate(sub if sub is not None else _steps_for(st, f, S)):
            s["id"] = f"panel_{st}_{i}"; s["timeout_min"] = TIMEOUT.get(st, 60); s["continue_on_review"] = False
            steps.append(s)
            if not f.resume: J.get("steps", {}).pop(s["id"], None)          # a fresh run of this stage (not a resume)
    _atomic(os.path.join(root, "orch_journal.json"), J)
    q = {"blender": bpy.app.binary_path, "projects": [{"project": pj, "work_blend": work, "steps": steps}]}
    qp = os.path.join(root, "panel_queue.json"); _atomic(qp, q)
    log = os.path.join(root, "panel_orch.log")
    flags = (0x00000008 | 0x00000200) if os.name == "nt" else 0          # DETACHED_PROCESS | NEW_PROCESS_GROUP
    py = sys.executable
    _JOBS[pj] = subprocess.Popen([py, os.path.join(FORGE_DIR, "forge_orch.py"), "run", qp], stdout=open(log, "a", encoding="utf-8"),
                                 stderr=subprocess.STDOUT, creationflags=flags, close_fds=True, cwd=FORGE_DIR,
                                 env=dict(os.environ, FORGE_AGENT="panel"))
    _start_timer(); op.report({"INFO"}, f"started: {', '.join(stages)} (log: {log})"); return True


def _redraw():
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == "VIEW_3D": a.tag_redraw()
    except Exception: pass
    alive = any(p.poll() is None for p in _JOBS.values())
    return 3.0 if alive else None


def _start_timer():
    if not bpy.app.timers.is_registered(_redraw): bpy.app.timers.register(_redraw, first_interval=2.0)


def _thumb(path):
    global _PREV
    import bpy.utils.previews
    if _PREV is None: _PREV = bpy.utils.previews.new()
    try: key = f"{path}|{os.path.getmtime(path):.0f}"
    except Exception: return 0
    if key not in _PREV: _PREV.load(key, path, "IMAGE")
    return _PREV[key].icon_id


class FORGE_Props(bpy.types.PropertyGroup):
    project: bpy.props.EnumProperty(name="Project", items=_projects)
    new_name: bpy.props.StringProperty(name="New project", description="folder name, lower_case_with_underscores")
    source: bpy.props.StringProperty(name="AI file", subtype="FILE_PATH", description="GLB / GLTF / FBX / OBJ from the generator")
    import_source: bpy.props.EnumProperty(name="Source", items=[("FILE", "From a file", ""), ("SCENE", "Already open in this Blender", "")], default="FILE")
    scene_root: bpy.props.EnumProperty(name="Weapon", items=_scene_candidates)
    title: bpy.props.StringProperty(name="Title", description="product title (README, package)")
    weapon_type: bpy.props.EnumProperty(name="Type", items=_weapon_types)
    style: bpy.props.EnumProperty(name="Style", items=[("fantasy", "fantasy", ""), ("realistic", "realistic", "")])
    target_use: bpy.props.EnumProperty(name="Use", items=[("fab_pc", "fab_pc (16-30k)", ""), ("showcase", "showcase (30-50k)", ""),
                                                          ("mobile", "mobile (3-8k)", "")])
    bake_size: bpy.props.EnumProperty(name="Bake", items=[("1024", "1K (check first)", ""), ("4096", "4K (after 1K approved)", "")])
    selected: bpy.props.StringProperty(default="s0_intake")
    note: bpy.props.StringProperty(name="Note", default="looked at every image")
    resume: bpy.props.BoolProperty(name="Resume (keep finished steps)", default=False)
    show_images: bpy.props.BoolProperty(name="Show images", default=True)


class FORGE_OT_new(bpy.types.Operator):
    bl_idname = "forge.new_project"; bl_label = "Create + import"
    bl_description = "new project folder, then import (a file, or a weapon already open in this Blender)"

    def execute(self, ctx):
        f = ctx.scene.forge; n = f.new_name.strip().lower().replace(" ", "_")
        if not n or not n.replace("_", "").isalnum(): self.report({"ERROR"}, "name: letters, digits and _ only"); return {"CANCELLED"}
        if os.path.exists(os.path.join(PROJECTS, n, "state.json")): self.report({"ERROR"}, "project exists: " + n); return {"CANCELLED"}
        steps_override = None
        if f.import_source == "SCENE":
            groups = _scene_groups(ctx)
            if not groups: self.report({"ERROR"}, "no mesh objects open in this Blender"); return {"CANCELLED"}
            root = f.scene_root if f.scene_root in groups else (next(iter(groups)) if len(groups) == 1 else None)
            if not root: self.report({"ERROR"}, "more than one weapon is open: pick which one"); return {"CANCELLED"}
            names = groups[root]
            work = os.path.join(PROJECTS, n, "work", n + ".blend"); os.makedirs(os.path.dirname(work), exist_ok=True)
            dup = []
            for name in names:                                    # world-transform baked, unparented copies -> a clean standalone file
                o = bpy.data.objects.get(name)
                if o is None or o.type != "MESH": continue
                d = o.copy(); d.data = o.data.copy(); mw = o.matrix_world.copy(); d.parent = None; d.matrix_world = mw
                ctx.scene.collection.objects.link(d); dup.append(d)
            if not dup: self.report({"ERROR"}, "no mesh objects in that group"); return {"CANCELLED"}
            ctx.view_layer.update(); new_names = [d.name for d in dup]
            try:
                bpy.data.libraries.write(work, set(dup), fake_user=True)
            finally:
                for d in dup:
                    me = d.data; bpy.data.objects.remove(d, do_unlink=True)
                    if me.users == 0: bpy.data.meshes.remove(me)
            steps_override = {"s0_intake": [{"fn": "s0_adopt", "kw": {"project": n, "high_names": new_names, "title": f.title or None},
                                             "verify_stage": "s0_intake"}]}
        else:
            src = bpy.path.abspath(f.source)
            if not os.path.isfile(src): self.report({"ERROR"}, "choose the AI file first"); return {"CANCELLED"}
        for d in ("source", "work", "reports", "checkpoints", "renders", "export", "package"): os.makedirs(os.path.join(PROJECTS, n, d), exist_ok=True)
        _atomic(os.path.join(PROJECTS, n, "state.json"), {"name": n, "created": time.strftime("%Y-%m-%d %H:%M"), "stages": {}, "anatomy": {}, "settings": {}})
        f.project = n
        _launch(ctx, ["s0_intake"], self, steps_override=steps_override); return {"FINISHED"}


class FORGE_OT_select(bpy.types.Operator):
    bl_idname = "forge.select"; bl_label = "Details"; bl_description = "show checks and images of this stage"
    stage: bpy.props.StringProperty()

    def execute(self, ctx):
        ctx.scene.forge.selected = self.stage; return {"FINISHED"}


class FORGE_OT_run(bpy.types.Operator):
    bl_idname = "forge.run_stage"; bl_label = "Run"; bl_description = "run this stage in a background Blender"
    stage: bpy.props.StringProperty()
    chain: bpy.props.BoolProperty(default=False, description="also run the following stages until a REVIEW or FAIL")

    def _later_done(self, S):
        """stages after this one that already have a result (a re-run makes them STALE: they must be redone)."""
        if self.stage not in STAGES: return []
        i = STAGES.index(self.stage) + 1
        return [st for st in STAGES[i:] if st != "s0_spec" and S.get("stages", {}).get(st, {}).get("status") not in (None, "TODO", "STALE")]

    def invoke(self, ctx, ev):
        S = _read(os.path.join(PROJECTS, ctx.scene.forge.project, "state.json"), {}) or {}
        done = S.get("stages", {}).get(self.stage, {}).get("status") not in (None, "TODO", "STALE")
        self._later = self._later_done(S) if self.stage != "s0_spec" else []
        if done or self._later:              # 1.4.3b: one click re-ran s2 on a finished project and made 7 stages STALE
            return ctx.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(ctx)

    def draw(self, ctx):
        L = self.layout; L.alert = True
        L.label(text=f"{self.stage} already has a result: run it again?", icon="ERROR")
        if getattr(self, "_later", None):
            L.label(text=f"{len(self._later)} later stages become STALE and must be redone:")
            L.label(text="   " + ", ".join(self._later)[:70])
            if "s3_uv" in self._later: L.label(text="   (UV ~35 min, gallery ~10 min)")
        L.label(text="The .blend and state.json are backed up first.")

    def execute(self, ctx):
        f = ctx.scene.forge; S = _read(os.path.join(PROJECTS, f.project, "state.json"), {}) or {}
        need = NEEDS.get(self.stage)
        if need and not _ok(S, need):
            self.report({"ERROR"}, f"{self.stage} needs {need} PASS or approved first"); return {"CANCELLED"}
        stages = [self.stage]
        if self.chain:
            i = STAGES.index(self.stage); stages = [s for s in STAGES[i:] if s != "s0_intake"]
        f.selected = self.stage
        return {"FINISHED"} if _launch(ctx, stages, self) else {"CANCELLED"}


class FORGE_OT_approve(bpy.types.Operator):
    bl_idname = "forge.approve"; bl_label = "Approve REVIEW"; bl_description = "you looked at the images and accept this stage"
    stage: bpy.props.StringProperty()

    def invoke(self, ctx, ev):
        return ctx.window_manager.invoke_confirm(self, ev)

    def execute(self, ctx):
        f = ctx.scene.forge; p = os.path.join(PROJECTS, f.project, "state.json"); S = _read(p, {})
        st = S.setdefault("stages", {}).setdefault(self.stage, {})
        if st.get("status") != "REVIEW": self.report({"ERROR"}, "only a REVIEW stage can be approved"); return {"CANCELLED"}
        st["approved"] = {"by": "user (panel)", "note": f.note, "time": time.strftime("%Y-%m-%d %H:%M")}
        _atomic(p, S)
        try:
            open(LEDGER, "a", encoding="utf-8").write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "event": "approve", "agent": "panel",
                                                                  "project": f.project, "stage": self.stage, "by": "user (panel)", "note": f.note}) + "\n")
        except Exception: pass
        self.report({"INFO"}, f"{self.stage} approved"); return {"FINISHED"}


class FORGE_OT_open(bpy.types.Operator):
    bl_idname = "forge.open_path"; bl_label = "Open"; bl_description = "open in Windows (report page, image or folder)"
    path: bpy.props.StringProperty()

    def execute(self, ctx):
        if os.path.exists(self.path): os.startfile(self.path)
        else: self.report({"WARNING"}, "not found: " + self.path)
        return {"FINISHED"}


class FORGE_OT_load_work(bpy.types.Operator):
    bl_idname = "forge.open_work"; bl_label = "Open project file"; bl_description = "open the project's .blend (to look at the result)"

    def invoke(self, ctx, ev):
        return ctx.window_manager.invoke_confirm(self, ev)

    def execute(self, ctx):
        pj = ctx.scene.forge.project; w = _work(pj)
        if not os.path.exists(w): self.report({"ERROR"}, "no work file yet"); return {"CANCELLED"}
        bpy.ops.wm.open_mainfile(filepath=w); return {"FINISHED"}


_WORD = {"PASS": "done", "FAIL": "failed", "REVIEW": "to review", "STALE": "outdated", "TODO": ""}
_ICON = {"PASS": "CHECKMARK", "FAIL": "CANCEL", "REVIEW": "ERROR", "STALE": "TIME", "TODO": "DOT"}


def _ui_state(ctx):
    # 2.1: what every Sword Forge panel reads: props, project folder, state.json, is a job running
    f = ctx.scene.forge
    root = os.path.join(PROJECTS, f.project) if f.project else ""
    S = (_read(os.path.join(root, "state.json"), {}) or {}) if root else {}
    return f, root, S, (bool(f.project) and _running(f.project))


def _next_stage(S):
    # 2.1: first stage (pipeline order) that is not finished; None when every stage is done
    for st in STAGES:
        if not _ok(S, st): return st
    return None


def _big(layout, scale=1.5):
    r = layout.row(); r.scale_y = scale; return r


class FORGE_PT_panel(bpy.types.Panel):
    # 2.1: main card = project, progress and ONE "what to do now" button; the rest lives in the sub-panels below
    bl_label = "Sword Forge"; bl_space_type = "VIEW_3D"; bl_region_type = "UI"; bl_category = "Sword Forge"

    def draw(self, ctx):
        L = self.layout; f, root, S, run = _ui_state(ctx)
        r = L.row(align=True); r.scale_y = 1.2; r.prop(f, "project", text="", icon="FILE_BLEND")
        if not f.project:
            b = L.box(); b.label(text="No project yet", icon="INFO"); b.label(text="Open 'New project' below to start")
            return
        done = sum(1 for st in STAGES if _ok(S, st)); n = len(STAGES)
        try:
            L.progress(factor=done / n, type="BAR", text=f"{done} / {n} stages done")
        except Exception:
            L.label(text=f"{done} / {n} stages done", icon="SEQUENCE")
        card = L.box()
        if run: self.draw_running(card, root)
        else: self.draw_next(card, f, S, root)
        r = L.row(align=True)
        r.operator("forge.open_work", text="Open project file", icon="FILE_BLEND")
        r.operator("forge.open_path", text="", icon="FILE_FOLDER").path = root

    def draw_running(self, card, root):
        card.alert = True
        J = _read(os.path.join(root, "orch_journal.json"), {}) or {}
        cur = [k for k, v in J.get("steps", {}).items() if v.get("state") == "running"]
        card.label(text="Running: " + (", ".join(c.replace("panel_", "") for c in cur) or "starting..."), icon="SORTTIME")
        card.label(text="Runs in the background: you can keep working")
        _big(card, 1.3).operator("forge.open_path", text="Open log", icon="TEXT").path = os.path.join(root, "panel_orch.log")

    def draw_next(self, card, f, S, root):
        st = _next_stage(S)
        if st is None:
            card.label(text="All stages done", icon="CHECKMARK"); return
        s, ap = _status(S, st); nice = NICE.get(st, st)
        if s == "REVIEW":
            card.label(text=nice + " waits for your review", icon="ERROR")
            if f.selected != st: card.operator("forge.select", text="Show its images", icon="HIDE_OFF").stage = st
            else: card.label(text="Look at the images below, then approve", icon="HIDE_OFF")
            _big(card).operator("forge.approve", text="Approve " + nice, icon="CHECKBOX_HLT").stage = st
        elif s == "FAIL":
            card.alert = True; card.label(text=nice + " failed", icon="CANCEL")
            _big(card, 1.3).operator("forge.select", text="Show what failed", icon="VIEWZOOM").stage = st
        elif st == "s0_intake":
            card.label(text="Import has not finished", icon="INFO")
            card.operator("forge.open_path", text="Open log", icon="TEXT").path = os.path.join(root, "panel_orch.log")
        elif st == "s10_publish":
            card.label(text="Ready to publish", icon="CHECKMARK")
            card.label(text="Publish only runs from its own button in Stages")
        else:
            card.label(text=("Outdated: " if s == "STALE" else "Next: ") + nice, icon="FORWARD")
            op = _big(card).operator("forge.run_stage", text="Run " + nice, icon="PLAY"); op.stage = st; op.chain = True
            card.label(text="Stops at the next review and waits for you")


class FORGE_PT_review(bpy.types.Panel):
    bl_label = "Review"; bl_space_type = "VIEW_3D"; bl_region_type = "UI"; bl_category = "Sword Forge"
    bl_parent_id = "FORGE_PT_panel"

    @classmethod
    def poll(cls, ctx): return bool(ctx.scene.forge.project)

    def draw_header(self, ctx): self.layout.label(text="", icon="HIDE_OFF")

    def draw(self, ctx):
        L = self.layout; f, root, S, run = _ui_state(ctx); st = f.selected
        if not st: L.label(text="Click a stage in 'Stages'", icon="INFO"); return
        s, ap = _status(S, st); appr = s == "REVIEW" and ap
        h = L.box().row()
        h.label(text=NICE.get(st, st), icon="CHECKBOX_HLT" if appr else _ICON.get(s, "DOT"))
        h.label(text="approved" if appr else (_WORD.get(s, s) or "not run"))
        d = _read(os.path.join(root, "reports", st, "decision.json"), None)
        R = _read(os.path.join(root, "reports", st, "report.json"), None)
        if not R: L.label(text="not run yet"); return
        L.label(text=f"{R.get('status')}  {R.get('time', '')}", icon="TIME")
        bad = [c for c in R.get("checks", []) if c.get("status") in ("FAIL", "REVIEW")]
        if bad:
            cb = L.box(); cb.label(text=f"Checks to look at ({len(bad)})", icon="VIEWZOOM")
            for c in bad:
                col = cb.column(align=True); col.alert = c["status"] == "FAIL"
                v = c.get("value"); vs = json.dumps(v, default=str)[:60] if v is not None else ""
                col.label(text=f"{c['status']}  {c['id']} {vs}", icon="CANCEL" if c["status"] == "FAIL" else "ERROR")
                if c.get("msg"):
                    m = str(c["msg"])
                    for k in range(0, min(len(m), 240), 60): col.label(text="     " + m[k:k + 60])
        if d and d.get("how_to_approve") and not ap: L.label(text="Look at the images, then press Approve", icon="HIDE_OFF")
        r = L.row(align=True)
        r.operator("forge.open_path", text="Report page", icon="URL").path = os.path.join(root, "reports", st, "index.html")
        r.operator("forge.open_path", text="Folder", icon="FILE_FOLDER").path = os.path.join(root, "reports", st)
        r.prop(f, "show_images", text="", icon="IMAGE_DATA")
        if f.show_images:
            imgs = [i["path"] for i in (R.get("comparison", []) + R.get("images", []) + R.get("diagnostics", [])) if isinstance(i, dict) and i.get("path")]
            imgs = [p for p in imgs if os.path.exists(p)][:8]
            if not imgs: L.label(text="no images in this report")
            g = L.grid_flow(columns=2, even_columns=True)
            for p in imgs:
                c = g.column(); ic = _thumb(p)
                if ic: c.template_icon(icon_value=ic, scale=7)
                c.operator("forge.open_path", text=os.path.basename(p)[:28], icon="IMAGE_DATA").path = p
        L.prop(f, "note")
        if s == "REVIEW" and not ap:
            r = _big(L, 1.4); r.enabled = not run
            r.operator("forge.approve", text="Approve " + NICE.get(st, st), icon="CHECKBOX_HLT").stage = st


class FORGE_PT_stages(bpy.types.Panel):
    bl_label = "Stages"; bl_space_type = "VIEW_3D"; bl_region_type = "UI"; bl_category = "Sword Forge"
    bl_parent_id = "FORGE_PT_panel"

    @classmethod
    def poll(cls, ctx): return bool(ctx.scene.forge.project)

    def draw_header(self, ctx): self.layout.label(text="", icon="SEQUENCE")

    def draw(self, ctx):
        L = self.layout; f, root, S, run = _ui_state(ctx)
        col = L.column(align=True)
        for st in STAGES:
            s, ap = _status(S, st); appr = s == "REVIEW" and ap
            row = col.row(align=True)
            word = "approved" if appr else _WORD.get(s, s)
            row.operator("forge.select", text=NICE[st] + ("   " + word if word else ""),
                         icon="CHECKBOX_HLT" if appr else _ICON.get(s, "DOT"), depress=st == f.selected).stage = st
            ready = not NEEDS.get(st) or _ok(S, NEEDS[st])
            sub = row.row(align=True); sub.enabled = ready and not run and st != "s0_intake"
            sub.operator("forge.run_stage", text="", icon="PLAY").stage = st
            r2 = row.row(align=True)
            if s == "REVIEW" and not ap:
                r2.enabled = not run; r2.operator("forge.approve", text="", icon="CHECKBOX_HLT").stage = st
            else:
                r2.label(text="", icon="BLANK1")
        L.separator()
        r = L.row(); r.enabled = not run and bool(f.selected) and f.selected != "s0_intake"
        op = r.operator("forge.run_stage", text="Run from selected until a review", icon="FF"); op.stage = f.selected; op.chain = True
        L.prop(f, "resume")


class FORGE_PT_new(bpy.types.Panel):
    bl_label = "New project"; bl_space_type = "VIEW_3D"; bl_region_type = "UI"; bl_category = "Sword Forge"
    bl_parent_id = "FORGE_PT_panel"; bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, ctx): self.layout.label(text="", icon="ADD")

    def draw(self, ctx):
        L = self.layout; f = ctx.scene.forge
        L.prop(f, "new_name", text="Name")
        L.row(align=True).prop(f, "import_source", expand=True)
        if f.import_source == "FILE":
            L.prop(f, "source")
        else:
            g = _scene_groups(ctx)
            if not g:
                L.label(text="no mesh objects open in this Blender", icon="ERROR")
            elif len(g) == 1:
                L.label(text="will use: " + next(iter(g)), icon="MESH_DATA")
            else:
                L.prop(f, "scene_root")
        _big(L, 1.4).operator("forge.new_project", icon="IMPORT")


class FORGE_PT_options(bpy.types.Panel):
    bl_label = "Options"; bl_space_type = "VIEW_3D"; bl_region_type = "UI"; bl_category = "Sword Forge"
    bl_parent_id = "FORGE_PT_panel"; bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, ctx): self.layout.label(text="", icon="PREFERENCES")

    def draw(self, ctx):
        L = self.layout; L.use_property_split = True; L.use_property_decorate = False; f = ctx.scene.forge
        for p in ("weapon_type", "style", "target_use", "bake_size", "title"): L.prop(f, p)


_classes = (FORGE_Props, FORGE_OT_new, FORGE_OT_select, FORGE_OT_run, FORGE_OT_approve, FORGE_OT_open, FORGE_OT_load_work,
            FORGE_PT_panel, FORGE_PT_review, FORGE_PT_stages, FORGE_PT_new, FORGE_PT_options)


def register():
    for c in _classes: bpy.utils.register_class(c)
    bpy.types.Scene.forge = bpy.props.PointerProperty(type=FORGE_Props)


def unregister():
    global _PREV
    if _PREV is not None:
        from bpy.utils import previews as _pv            # (a local 'import bpy...' made bpy unbound below)
        _pv.remove(_PREV); _PREV = None
    del bpy.types.Scene.forge
    for c in reversed(_classes): bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
