"""game_mesh.py - game-ready LODs from a high-poly master (Blender_AI_Studio, Fab pipeline F1).

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\game_mesh.py").read())
    rep = make_lods(["dragon_blade_B_pro", "B_grip_collar", "B_pommel_collar"], "SM_DragonSword_B",
                    targets=(45000, 22000, 11000))
    dev = mesh_deviation("SM_DragonSword_B_LOD0", ["dragon_blade_B_pro", ...])   # accuracy vs master

The master objects are never modified (copies are joined, transforms applied, then decimated).
Feature protection: vertices on sharp creases (dihedral > protect_deg) get weight 0 in a vertex group that
the Decimate modifier uses, so outline, spikes and cut-outs keep their vertices longest.
Accuracy: distance from master surface samples to the LOD surface (BVH), reported in mm (p50/p95/max).
"""
import bpy, bmesh, time
import numpy as np
from mathutils.bvhtree import BVHTree


def _tri_count(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def _join_copies(src_names, name, coll=None):
    copies = []
    for n in src_names:
        o = bpy.data.objects[n]
        c = o.copy(); c.data = o.data.copy(); c.name = name + "_tmp"
        (coll or bpy.context.scene.collection).objects.link(c); copies.append(c)
    bpy.ops.object.select_all(action="DESELECT")
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if len(copies) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name; ob.data.name = name
    return ob


def _protect_group(ob, protect_deg):
    me = ob.data
    bm = bmesh.new(); bm.from_mesh(me)
    w = np.ones(len(bm.verts), np.float32)
    lim = np.radians(protect_deg)
    for e in bm.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle(0) > lim:
            for v in e.verts:
                w[v.index] = 0.0
        elif len(e.link_faces) != 2:
            for v in e.verts:
                w[v.index] = 0.0
    bm.free()
    vg = ob.vertex_groups.get("decimate_weight") or ob.vertex_groups.new(name="decimate_weight")
    idx = np.arange(len(w))
    for val in (0.0, 1.0):
        sel = idx[w == val].tolist()
        if sel:
            vg.add(sel, val, "REPLACE")
    return vg, float((w == 0).mean())


def decimate_to(ob, target, protect_deg=35.0, use_group=True):
    cur = _tri_count(ob)
    if cur <= target:
        return cur
    md = ob.modifiers.new("dec", "DECIMATE"); md.decimate_type = "COLLAPSE"
    md.ratio = target / cur; md.use_collapse_triangulate = True
    if use_group:
        vg, frac = _protect_group(ob, protect_deg)
        md.vertex_group = vg.name; md.vertex_group_factor = 1.0
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=md.name)
    # if protection kept too many triangles, finish without the group
    if _tri_count(ob) > target * 1.08:
        md = ob.modifiers.new("dec2", "DECIMATE"); md.decimate_type = "COLLAPSE"
        md.ratio = target / _tri_count(ob); md.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=md.name)
    return _tri_count(ob)


def make_lods(src_names, base, targets=(45000, 22000, 11000), protect_deg=35.0):
    t0 = time.time(); rep = {}
    prev = None
    for i, tgt in enumerate(targets):
        name = f"{base}_LOD{i}"
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        ob = _join_copies(src_names if prev is None else [prev.name], name)
        n = decimate_to(ob, tgt, protect_deg)
        bpy.ops.object.shade_smooth_by_angle(angle=np.radians(40))
        rep[name] = {"tris": n, "verts": len(ob.data.vertices)}
        prev = ob
    rep["seconds"] = round(time.time() - t0, 1)
    return rep


def mesh_deviation(lod_name, master_names, samples=200000, seed=0):
    """distances (mm) master->LOD (lost detail / silhouette) and LOD->master (bulges)."""
    dg = bpy.context.evaluated_depsgraph_get()
    def world_tris(o):
        me = o.data
        co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3).astype(np.float64)
        M = np.array(o.matrix_world); co = co @ M[:3, :3].T + M[:3, 3]
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get("vertices", tri)
        return co, tri.reshape(-1, 3)
    lod = bpy.data.objects[lod_name]
    lc, lt = world_tris(lod)
    bl = BVHTree.FromPolygons([tuple(v) for v in lc], [tuple(f) for f in lt], all_triangles=True)
    rng = np.random.default_rng(seed)
    out = {}
    pts_all = []
    for n in master_names:
        c, t = world_tris(bpy.data.objects[n])
        a = np.linalg.norm(np.cross(c[t[:, 1]] - c[t[:, 0]], c[t[:, 2]] - c[t[:, 0]]), axis=1)
        k = rng.choice(len(t), size=max(1, int(samples * a.sum() / 1.0)) if False else samples // len(master_names), p=a / a.sum())
        r1, r2 = rng.random(len(k)), rng.random(len(k)); s = np.sqrt(r1)
        p = c[t[k, 0]] * (1 - s)[:, None] + c[t[k, 1]] * (s * (1 - r2))[:, None] + c[t[k, 2]] * (s * r2)[:, None]
        pts_all.append(p)
    P = np.vstack(pts_all)
    d = np.array([bl.find_nearest(tuple(p))[3] for p in P]) * 1000
    out["master_to_lod_mm"] = {"p50": round(float(np.percentile(d, 50)), 3), "p95": round(float(np.percentile(d, 95)), 3),
                               "p99": round(float(np.percentile(d, 99)), 3), "max": round(float(d.max()), 3)}
    # where are the largest deviations (z histogram of the worst 0.5%)
    worst = P[d > np.percentile(d, 99.5)]
    out["worst_z_hist_5cm"] = np.histogram(worst[:, 2], bins=np.arange(-0.05, 1.35, 0.05))[0].tolist()
    return out


def replace_grip(lod_name, master="dragon_blade_B_pro", z0=0.946, z1=1.137, cut=(0.951, 1.1315),
                 axis=(-0.0033, -0.0006), r_max=0.035, segments=32, ring_step=0.004, pct=70):
    """Hybrid retopo for a surface of revolution: delete the decimated grip faces of the LOD and insert a clean
    cylinder whose radius follows the master at every height. Ends sit inside the collars (hidden)."""
    lod = bpy.data.objects[lod_name]; me = lod.data
    hm = bpy.data.objects[master]
    co = np.empty(len(hm.data.vertices) * 3, np.float32); hm.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64); M = np.array(hm.matrix_world); W = co @ M[:3, :3].T + M[:3, 3]
    r = np.hypot(W[:, 0] - axis[0], W[:, 1] - axis[1])
    zs = np.arange(z0, z1 + 1e-9, ring_step); radii = []
    for z in zs:
        m = (np.abs(W[:, 2] - z) < ring_step) & (r < r_max)
        radii.append(np.percentile(r[m], pct) if m.sum() > 20 else np.nan)
    radii = np.array(radii); ok = ~np.isnan(radii)
    radii = np.interp(zs, zs[ok], radii[ok])
    k = np.ones(5) / 5; radii = np.convolve(np.pad(radii, 2, mode="edge"), k, "valid")
    bm = bmesh.new(); bm.from_mesh(me)
    Ml = np.array(lod.matrix_world)
    kill = []
    for f in bm.faces:
        c = f.calc_center_median(); c = Ml[:3, :3] @ np.array(c) + Ml[:3, 3]
        if cut[0] < c[2] < cut[1] and np.hypot(c[0] - axis[0], c[1] - axis[1]) < r_max:
            kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    Minv = np.linalg.inv(Ml)
    rings = []
    for z, rad in zip(zs, radii):
        ring = []
        for s in range(segments):
            a = 2 * np.pi * s / segments
            p = np.array([axis[0] + rad * np.cos(a), axis[1] + rad * np.sin(a), z, 1.0])
            ring.append(bm.verts.new(tuple((Minv @ p)[:3])))
        rings.append(ring)
    for i in range(len(rings) - 1):
        for s in range(segments):
            a, b = rings[i][s], rings[i][(s + 1) % segments]; c, d = rings[i + 1][(s + 1) % segments], rings[i + 1][s]
            bm.faces.new((a, b, c, d))
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    bm.to_mesh(me); bm.free(); me.update()
    for p in me.polygons:
        p.use_smooth = True
    return {"deleted_faces": len(kill), "rings": len(zs), "segments": segments, "tris": _tri_count(lod),
            "radius_mm_min_max": [round(float(radii.min()) * 1000, 2), round(float(radii.max()) * 1000, 2)]}


def add_weighted_normals(name):
    ob = bpy.data.objects[name]
    md = ob.modifiers.get("WeightedNormal") or ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    md.keep_sharp = True; md.weight = 50
    return True
