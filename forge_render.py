"""forge_render - fast inspection renders (EEVEE, seconds per view) and side-by-side comparison sheets.
Cycles is only for marketing shots (stage 8). Diagnosis must be fast so it is done every time."""
import bpy, os, math
import numpy as np
from mathutils import Vector


def _engine():
    items = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    for e in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        if e in items: return e
    return "BLENDER_WORKBENCH"


# 1.6.0: a generic asset (anatomy kind "generic") has its own cameras. Each stands in for one sword camera, so the
# stage code that picks cameras by sword name (_vin) works for both kinds.
GENERIC_VIEW_OF = {"full_front": "front", "full_back": "back", "tip": "detail_low", "blade_mid": "three_quarter",
                   "junction": "detail_mid", "guard_center": "detail_center", "guard_left": "left", "guard_right": "right",
                   "guard_back": "three_quarter_back", "grip": "detail_high", "pommel": "top"}
_SWORD_VIEW_OF = {v: k for k, v in GENERIC_VIEW_OF.items()}


def _vin(name, names):
    """is the camera `name` one of `names` (sword camera names)? A generic camera counts as the sword camera it replaces."""
    return name in names or _SWORD_VIEW_OF.get(name) in names


def generic_views(an):
    """cameras for any asset, from its bounding box: front, back, left, right, top, two three-quarter views and four
    close-ups (low / middle / centre / high). 50 mm lens on a 36 mm sensor, 16:9."""
    c = tuple(an["bbox_center"]); sx, sy, sz = an["size"]
    def fit(w, h, depth): return 1.2 * max(w / 2 / 0.36, h / 2 / 0.2025) + depth / 2
    diag = (sx * sx + sy * sy + sz * sz) ** 0.5; dq = fit(diag, diag, 0.0); z0 = c[2] - sz / 2
    def zc(f): return (c[0], c[1], z0 + f * sz)
    dc = max(fit(0.55 * sx, 0.42 * sz, sy), 0.03)
    return [("front", c, (0, -1, 0), fit(sx, sz, sy)), ("back", c, (0, 1, 0), fit(sx, sz, sy)),
            ("detail_low", zc(0.2), (0.3, -1, 0.15), dc), ("three_quarter", c, (0.65, -0.75, 0.35), dq),
            ("detail_mid", zc(0.5), (-0.5, -1, 0.2), dc), ("detail_center", zc(0.5), (0.12, -1, 0.05), dc),
            ("left", c, (-1, 0, 0), fit(sy, sz, sx)), ("right", c, (1, 0, 0), fit(sy, sz, sx)),
            ("three_quarter_back", c, (-0.65, 0.75, 0.35), dq),
            ("detail_high", zc(0.8), (0.3, -1, 0.25), dc), ("top", c, (0, -0.12, 1), fit(sx, sy, sz))]


def inspection_views(an):
    """camera list from the anatomy (z axis = sword length, tip low). Each: name, target, direction, dist."""
    if an.get("kind") == "generic": return generic_views(an)
    L = an["length"]; cx, cy = an.get("axis_xy", (0.0, 0.0)); gz = (an["guard_z0"] + an["guard_z1"]) / 2
    gw = an.get("guard_half_width", 0.12)
    cl = an.get("centerline")              # 1.4.2: curved blades -> aim at the blade centreline (absent: grip axis)
    bx, by = (an["bbox_center"][:2] if an.get("bbox_center") else (cx, cy))
    def at(z):
        if not cl: return (cx, cy, z)
        zs = [p[0] for p in cl]; return (float(np.interp(z, zs, [p[1] for p in cl])), float(np.interp(z, zs, [p[2] for p in cl])), z)
    # 1.4.6 (lesson 63): the tip view must contain the tip (it used to frame 4-10 % of L above it), and the guard side
    # views must contain the wing ends of large guards (distance grows with the guard, never shrinks below 0.16 L)
    tz = an["tip_z"] + 0.03 * L; c_ = at(tz)
    tip_t = (tuple((a + b) / 2 for a, b in zip(an["tip_point"][:2], c_[:2])) + (tz,)) if an.get("tip_point") else c_
    gd = max(0.16 * L, 1.4 * gw); wbs = an.get("wing_boxes")
    def wing_v(k, base, d):                 # frame the whole wing box when it is known (absent: as before)
        if not wbs: return (base, d, gd)
        b_ = wbs[k]; need = 1.2 * max(b_["h"][0] / 0.36, b_["h"][1] / 0.2025) + 0.05 * L   # 50 mm lens, 16:9
        return (tuple(b_["c"]), d, max(gd, need))
    V = [("full_front", (bx, by, L / 2), (0, -1, 0), 1.5 * L, 90),
         ("full_back", (bx, by, L / 2), (0, 1, 0), 1.5 * L, -90),
         ("tip", tip_t, (0.35, -1, 0.15), 0.18 * L),
         ("blade_mid", at((an["tip_z"] + an["guard_z0"]) / 2), (0.3, -1, 0.1), 0.28 * L),
         ("junction", at(an["guard_z0"]), (0.4, -1, 0.15), 0.16 * L),
         ("guard_center", (cx, cy, gz), (0.12, -1, 0.05), 0.14 * L),
         ("guard_left",) + wing_v(0, (cx - 0.6 * gw, cy, gz), (-0.25, -1, 0.1)),
         ("guard_right",) + wing_v(1, (cx + 0.6 * gw, cy, gz), (0.25, -1, 0.1)),
         ("guard_back", (cx, cy, gz), (-0.12, 1, 0.05), 0.16 * L),
         ("grip", (cx, cy, (an["grip_z0"] + an["grip_z1"]) / 2), (0.3, -1, 0.1), 0.2 * L),
         ("pommel", (cx, cy, an["pommel_z1"] - 0.03 * L), (0.35, -1, 0.2), 0.14 * L)]
    return V


def forge_aim(cam, target, direction, dist, roll=0.0):
    from mathutils import Matrix
    d = Vector(direction).normalized(); t = Vector(target)
    cam.location = t + d * dist
    q = (-d).to_track_quat("-Z", "Y")
    cam.rotation_euler = (q.to_matrix().to_4x4() @ Matrix.Rotation(math.radians(roll), 4, "Z")).to_euler()


def _inspect_scene():
    """a separate scene that only LINKS the objects to inspect: the main scene is never touched.
    Camera, lights and world are re-created whenever missing (they did not always survive save/reload)."""
    sc = bpy.data.scenes.get("FORGE_inspect") or bpy.data.scenes.new("FORGE_inspect")
    if sc.world is None or sc.world.name != "FORGE_world":
        w = bpy.data.worlds.get("FORGE_world") or bpy.data.worlds.new("FORGE_world")
        w.color = (0.18, 0.18, 0.2); w.use_nodes = True
        bg = w.node_tree.nodes.get("Background")
        if bg: bg.inputs[0].default_value = (0.18, 0.18, 0.2, 1); bg.inputs[1].default_value = 0.6
        sc.world = w
    have = {o.name for o in sc.collection.objects}
    for n, loc, e in (("FORGE_key", (1.5, -2.0, 2.0), 600), ("FORGE_fill", (-2.0, -1.0, 1.0), 250), ("FORGE_rim", (0, 2.5, 2.0), 400)):
        if n in have: continue
        o = bpy.data.objects.get(n)
        if o is None or o.type != "LIGHT":
            l = bpy.data.lights.new(n, "AREA"); l.energy = e; l.size = 1.5
            o = bpy.data.objects.new(n, l); o.location = loc
            o.rotation_euler = (Vector((0, 0, 0.6)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.collection.objects.link(o)
    if sc.camera is None or sc.camera.name not in sc.collection.objects:
        cam = bpy.data.objects.get("FORGE_inspect_cam")
        if cam is None:
            cam = bpy.data.objects.new("FORGE_inspect_cam", bpy.data.cameras.new("FORGE_inspect_cam"))
        if cam.name not in sc.collection.objects: sc.collection.objects.link(cam)
        sc.camera = cam
    cam = sc.camera; cam.data.type = "PERSP"; cam.data.lens = 50; cam.data.sensor_width = 36; cam.data.sensor_fit = "AUTO"
    cam.data.clip_start = 0.001; cam.data.clip_end = 100
    try: sc.view_settings.view_transform = "AgX"
    except Exception: sc.view_settings.view_transform = "Standard"
    for o in sc.collection.objects:                      # lights/camera must be enabled for the render
        if o.type in ("LIGHT", "CAMERA"): o.hide_render = False; o.hide_viewport = False
    return sc


def render_views(show, views, out_dir, prefix, res=(960, 540), samples=16, engine="EEVEE", mode="solid", override_mat=None):
    """render each view of the `show` objects in the FORGE_inspect scene; returns file paths. Synchronous.
    engine="WORKBENCH": geometry/shading checks (no shader compilation). mode: solid | attribute | silhouette | wire."""
    sc = _inspect_scene(); r = sc.render; os.makedirs(out_dir, exist_ok=True)
    for o in list(sc.collection.objects):
        if o.type not in ("LIGHT", "CAMERA"): sc.collection.objects.unlink(o)
    objs = [bpy.data.objects[n] for n in show]
    vis = {o.name: (o.hide_render, o.hide_viewport) for o in objs}
    for o in objs:
        sc.collection.objects.link(o); o.hide_render = False; o.hide_viewport = False
    for o in sc.objects:
        if o.type == "LIGHT": o.hide_render = engine == "WORKBENCH"
    cam = sc.camera; sh = sc.display.shading; swapped = []
    w = sc.world; w.color = (0.18, 0.18, 0.2)
    if engine == "WORKBENCH":
        r.engine = "BLENDER_WORKBENCH"; sh.light = "STUDIO"; sh.color_type = "SINGLE"
        sh.single_color = (0.62, 0.62, 0.64); sh.show_specular_highlight = True
        if mode == "attribute": sh.color_type = "VERTEX"
        if mode == "silhouette":                         # black shape on white: compares outlines only
            sh.light = "FLAT"; sh.single_color = (0, 0, 0); sh.show_specular_highlight = False; w.color = (1, 1, 1)
    else:
        r.engine = _engine()
        try: sc.eevee.taa_render_samples = samples
        except Exception: pass
        if mode == "wire":
            wm = _wire_mat()
            for o in objs:
                swapped.append((o, [s_.material for s_ in o.material_slots]))
                for s_ in o.material_slots: s_.material = wm
    r.resolution_x, r.resolution_y = res; r.resolution_percentage = 100; r.image_settings.file_format = "PNG"
    vl = sc.view_layers[0]; vl.material_override = override_mat            # same material on everything (geometry/normal checks)
    out = []
    try:
        for v in views:
            name, tgt, d, dist = v[:4]
            forge_aim(cam, tgt, d, dist, v[4] if len(v) > 4 else 0.0)
            r.filepath = os.path.join(out_dir, f"{prefix}_{name}.png")
            bpy.ops.render.render(write_still=True, scene=sc.name); out.append(r.filepath)
    finally:
        vl.material_override = None
        for o, mats in swapped:
            for s_, m in zip(o.material_slots, mats): s_.material = m
        for o in objs:
            sc.collection.objects.unlink(o); o.hide_render, o.hide_viewport = vis[o.name]
    return out


def _load(path):
    im = bpy.data.images.load(path, check_existing=False)
    w, h = im.size; a = np.empty(w * h * 4, np.float32); im.pixels.foreach_get(a)
    bpy.data.images.remove(im)
    return a.reshape(h, w, 4)


def compare_sheet(left, right, out_path, gap=6, step=2):
    """rows of [left | right] images (e.g. high | low) -> one PNG. Rows are in the given order."""
    rows = []
    for a, b in zip(left, right):
        A = _load(a)[::step, ::step]; B = _load(b)[::step, ::step]; h = min(A.shape[0], B.shape[0])
        sep = np.ones((h, gap, 4), np.float32)
        rows.append(np.concatenate([A[:h], sep, B[:h]], 1))
    w = max(r.shape[1] for r in rows)
    pad = [np.pad(r, ((0, gap), (0, w - r.shape[1]), (0, 0)), constant_values=1.0) for r in rows]
    S = np.concatenate(pad[::-1], 0)          # Blender images start at the bottom row
    im = bpy.data.images.new("FORGE_sheet", S.shape[1], S.shape[0], alpha=True)
    im.pixels.foreach_set(S.ravel()); im.filepath_raw = out_path; im.file_format = "PNG"; im.save()
    bpy.data.images.remove(im)
    return out_path
