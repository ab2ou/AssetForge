"""forge_stages - the pipeline. Each stage: require(previous) -> work -> gate -> report -> checkpoint.
Object naming inside a project (prefix = state.settings.asset, e.g. "SM_DragonSword"):
  high-poly source objects ...... state.settings.high  (list of names)
  low-poly ...................... <asset>_LOD0 / _LOD1 / _LOD2, collision UCX_<asset>_LOD0_NN
"""
import bpy, os, json, math, time, shutil
import numpy as np


def _proj(name):
    return Project(name)


def _asset(P):
    return P.state["settings"].get("asset", "SM_" + "".join(w.capitalize() for w in P.name.split("_")))


def _highs(P):
    return P.state["settings"]["high"]


def _L(P):
    return P.state["anatomy"]["length"]


# ======================================================================= s0 intake
def detect_anatomy(names):
    """sword anatomy along +Z (tip low). Uses the width profile: the guard is the widest band."""
    pts = []
    for n in names:
        co, tv, _, _, _ = tri_arrays(n); pts.append(co)
    V = np.concatenate(pts)
    z0, z1 = V[:, 2].min(), V[:, 2].max(); L = z1 - z0
    nb = 200; zb = np.linspace(z0, z1, nb + 1); w = np.zeros(nb)
    idx = np.clip(((V[:, 2] - z0) / L * nb).astype(int), 0, nb - 1)
    for b in range(nb):
        m = idx == b
        if m.any(): w[b] = V[m, 0].max() - V[m, 0].min()
    g = int(np.argmax(w)); thr = 0.35 * w[g]
    a = g
    while a > 0 and w[a - 1] > thr: a -= 1
    b = g
    while b < nb - 1 and w[b + 1] > thr: b += 1
    guard_z0, guard_z1 = zb[a], zb[b + 1]
    # 1.4.5 (lesson 61): width in both axes. The widest 2D band is the guard; the blade is its longer side.
    wy = np.zeros(nb)
    for k_ in range(nb):
        m = idx == k_
        if m.any(): wy[k_] = V[m, 1].max() - V[m, 1].min()
    w2 = np.maximum(w, wy); g2 = int(np.argmax(w2))
    side_below, side_above = zb[g2] - z0, z1 - zb[g2 + 1]
    guard_method = "x_width_0.35"; half_w = float(w[g] / 2)
    if guard_z1 - guard_z0 > 0.3 * L:        # the x band ran into a wide blade or grip: no real guard is that long
        thr2 = 0.5 * w2[g2]; a = g2
        while a > 0 and w2[a - 1] > thr2: a -= 1
        b = g2
        while b < nb - 1 and w2[b + 1] > thr2: b += 1
        guard_method = f"2d_width_0.5 (x band was {(guard_z1 - guard_z0) / L:.0%} of the length)"
        guard_z0, guard_z1 = zb[a], zb[b + 1]; half_w = float(w2[g2] / 2)
    top = z1; grip_len = top - guard_z1
    grip_z0 = guard_z1; grip_z1 = guard_z1 + 0.78 * grip_len
    # pommel = first band in the upper part of the hilt that is clearly wider than the grip
    hb = [k for k in range(b + 1, nb) if w[k] > 0]
    if len(hb) > 6:
        lower = hb[:max(3, int(0.5 * len(hb)))]; gw_ = float(np.median(w[lower]))
        for k in hb[int(0.4 * len(hb)):]:
            if w[k] > 1.35 * gw_:
                grip_z1 = zb[k]; break
    gm = (V[:, 2] > grip_z0 + 0.1 * grip_len) & (V[:, 2] < grip_z1)
    axis = V[gm][:, :2].mean(0) if gm.any() else np.zeros(2)
    an = {"length": float(L), "tip_z": float(z0), "guard_z0": float(guard_z0), "guard_z1": float(guard_z1),
          "grip_z0": float(grip_z0), "grip_z1": float(grip_z1), "pommel_z1": float(top),
          "guard_half_width": half_w, "axis_xy": [float(axis[0]), float(axis[1])],
          "pivot": [float(axis[0]), float(axis[1]), float((grip_z0 + grip_z1) / 2)],
          "blade_side_longer": bool(side_below > side_above), "guard_method": guard_method,
          "blade_side_m": [round(float(side_below), 4), round(float(side_above), 4)]}
    an.update(_anatomy_geometry(V, an))
    return an


def _anatomy_geometry(V, an, nb=24):
    """1.4.2: blade centreline (mean x,y per height band, tip..guard) and the bounding-box centre. Cameras aim at
    the centreline, so a CURVED blade (sabre, scimitar) is framed where it really is; a straight blade gives the
    same targets as the grip axis (green_sword 2026-10-31: the tip camera missed the curved tip)."""
    z0, zg = an["tip_z"], an["guard_z0"]; cl = []
    for k in range(nb):
        a = z0 + (zg - z0) * k / nb; b = z0 + (zg - z0) * (k + 1) / nb; m = (V[:, 2] >= a) & (V[:, 2] < b)
        if m.any(): cl.append([float((a + b) / 2), float(V[m, 0].mean()), float(V[m, 1].mean())])
    lo, hi = V.min(0), V.max(0); tp = V[np.argmin(V[:, 2])]
    # 1.4.6: box of each guard wing (outer 40 % of the guard half-width, guard band + 10 % of L below for drooping wings)
    cx_ = an.get("axis_xy", (0.0, 0.0))[0]; gw_ = an.get("guard_half_width", 0.0); Lz = an["length"]
    G_ = V[(V[:, 2] >= an["guard_z0"] - 0.1 * Lz) & (V[:, 2] <= an["guard_z1"])]; wb = []
    for side in (G_[G_[:, 0] < cx_ - 0.6 * gw_], G_[G_[:, 0] > cx_ + 0.6 * gw_]):
        if len(side) < 3: wb = None; break
        lo_, hi_ = side.min(0), side.max(0)
        wb.append({"c": [float(c) for c in (lo_ + hi_) / 2], "h": [float((hi_[0] - lo_[0]) / 2), float((hi_[2] - lo_[2]) / 2)]})
    return {"centerline": cl, "tip_point": [float(tp[0]), float(tp[1]), float(tp[2])], "wing_boxes": wb,
            "bbox_center": [float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2), float((lo[2] + hi[2]) / 2)]}


def guess_kind(names):
    """1.6.0: "weapon" for a long thin model (longest side >= 2.5 x the next one: swords, daggers, spears), else
    "generic". Only a first guess: s0_intake shows it as REVIEW, and kind= on s0_import / s0_adopt decides."""
    V = np.concatenate([tri_arrays(n)[0] for n in names]); S = np.sort(V.max(0) - V.min(0))
    return "weapon" if S[2] >= 2.5 * max(float(S[1]), 1e-9) else "generic"


def detect_anatomy_generic(names):
    """1.6.0: 'anatomy' of any asset = its bounding box. length = the largest dimension (the scale every relative
    tolerance uses), height = the Z extent, pivot = centre of the base. The guard / grip keys are height bands
    (thirds) kept only so that code written for swords (collision split, zone masks) runs: they are not parts."""
    V = np.concatenate([tri_arrays(n)[0] for n in names]); lo, hi = V.min(0), V.max(0); S = hi - lo
    H = float(S[2]); z0 = float(lo[2]); cx, cy = float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2)
    return {"kind": "generic", "length": float(S.max()), "height": H, "size": [float(x) for x in S],
            "bbox_center": [cx, cy, float((lo[2] + hi[2]) / 2)], "tip_z": z0, "guard_z0": z0 + H / 3, "guard_z1": z0 + 2 * H / 3,
            "grip_z0": z0 + 2 * H / 3, "grip_z1": z0 + 0.9 * H, "pommel_z1": float(hi[2]), "guard_half_width": float(S[0] / 2),
            "axis_xy": [cx, cy], "pivot": [cx, cy, z0], "blade_side_longer": True, "tip_point": [cx, cy, z0],
            "centerline": None, "wing_boxes": None, "guard_method": "generic: height thirds (compatibility bands, not parts)"}


def _detect(P, names):
    """anatomy by the project's asset kind (settings.kind: "weapon" = default, or "generic")."""
    return detect_anatomy_generic(names) if P.state["settings"].get("kind") == "generic" else detect_anatomy(names)


def refresh_anatomy_geometry(project):
    """add centerline/bbox_center to an existing project's anatomy (no other anatomy value changes)."""
    P = _proj(project); V = np.concatenate([tri_arrays(n)[0] for n in _highs(P)])
    P.state["anatomy"].update(_anatomy_geometry(V, P.state["anatomy"])); P.save()
    return {k: P.state["anatomy"][k] for k in ("bbox_center",)} | {"centerline_points": len(P.state["anatomy"]["centerline"])}


def _link_orphans(names):
    """1.4.8: a weapon taken from an open scene arrives through bpy.data.libraries.write, which writes the objects but
    no collection: they load in no collection, outside the view layer, and the first select_set (s2 preview bake:
    'cannot be selected because it is not in View Layer') fails. Link such objects to the scene collection; this only
    adds a collection link, the mesh and its transform are not touched."""
    out = []
    for n in names:
        o = bpy.data.objects.get(n)
        if o is not None and not o.users_collection:
            bpy.context.scene.collection.objects.link(o); out.append(n)
    if out: bpy.context.view_layer.update()
    return out


def s0_adopt(project, high_names, asset=None, anatomy=None, title=None, kind=None):
    """register an existing high-poly (already in the open .blend) as the project's source."""
    P = _proj(project); G = Gate("s0_intake")
    _lk = _link_orphans(high_names)
    if _lk: G.notes.append(f"linked to the scene (they were in no collection, shape unchanged): {_lk}")
    P.state["settings"]["high"] = list(high_names)
    if asset: P.state["settings"]["asset"] = asset
    if title: P.state["settings"]["title"] = title
    st_ = P.state["settings"]                               # 1.6.0: asset kind (weapon / generic)
    if kind and kind != "auto": st_["kind"] = kind; st_["kind_auto"] = False
    elif not st_.get("kind"): st_["kind"] = guess_kind(high_names); st_["kind_auto"] = True
    generic = st_["kind"] == "generic"
    an = anatomy or _detect(P, high_names); P.state["anatomy"] = an
    _b = P.state["settings"].get("design_baseline")
    if not _b or not os.path.exists(_b) or P.state["settings"].get("design_baseline_names") != list(high_names):
        G.data["design_baseline"] = _write_baseline(P, list(high_names))   # the design as it came in (design_check)
    P.save()
    G.check("asset_kind", st_["kind"], not st_.get("kind_auto"), review=True,
            msg="chosen from the proportions (long and thin = weapon, else generic): confirm it, or import again with kind=...")
    if generic:
        G.check("size_m", [round(x, 4) for x in an["size"]], 0.005 < an["length"] < 100.0, msg="width x depth x height in metres")
        G.need_review("orientation", "front render: is the model upright (Z up) and facing the front camera? Pivot = centre of the base")
    else:
        G.check("blade_points_down", an["blade_side_longer"], an["blade_side_longer"], msg="blade must be the longer side, tip at min Z")
        G.check("length_m", round(an["length"], 4), 0.3 < an["length"] < 3.0, msg="real-world size in metres")
        G.need_review("anatomy", "check guard/grip/pommel heights and the pivot in state.json against the front render")
    try:
        views = [v for v in inspection_views(an) if _vin(v[0], ("full_front", "full_back", "guard_center", "tip"))]
        G.images += [{"path": p, "caption": "high-poly"} for p in render_views(set(high_names), views, P.p("renders", "s0"), "high")]
    except Exception as e:
        G.notes.append(f"render failed: {e!r}")
    G.data["anatomy"] = an
    orient = P.state["settings"].get("import_orientation")
    if orient:
        G.data["import_orientation"] = orient
        if orient.get("flipped") or orient.get("face_turned_90"):
            G.notes.append(f"import turned the model (rigid rotation, shape unchanged): {orient}")
    return P.finish("s0_intake", G)


def _import_normalised(src, collection="FORGE_high", kind="auto"):
    """import GLB/GLTF/FBX/OBJ, apply transforms, long axis -> Z, blade (the longer side) down, tip at Z=0, centred.
    Returns the new mesh object names."""
    before = set(bpy.data.objects); ext = os.path.splitext(src)[1].lower()
    if ext in (".glb", ".gltf"): bpy.ops.import_scene.gltf(filepath=src)
    elif ext == ".fbx": bpy.ops.import_scene.fbx(filepath=src)
    elif ext == ".obj": bpy.ops.wm.obj_import(filepath=src)
    else: raise ValueError("unsupported format " + ext)
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    coll = bpy.data.collections.get(collection) or bpy.data.collections.new(collection)
    if coll.name not in bpy.context.scene.collection.children: bpy.context.scene.collection.children.link(coll)
    for o in new:
        for c in list(o.users_collection): c.objects.unlink(o)
        coll.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in new:                                               # glTF parents meshes to empties: keep the world transform
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw; o.select_set(True)
    bpy.context.view_layer.objects.active = new[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    import mathutils
    if kind == "auto": kind = guess_kind([o.name for o in new])
    if kind == "generic":                 # 1.6.0: keep the file's orientation (Z up), centre it, base on Z = 0
        V = np.concatenate([tri_arrays(o.name)[0] for o in new]); c = (V.max(0) + V.min(0)) / 2
        T = mathutils.Matrix.Translation((-c[0], -c[1], -V[:, 2].min()))
        for o in new: o.data.transform(T); o.data.update()
        return [o.name for o in new], {"kind": "generic", "orientation": "kept as imported (Z up), centred, base at Z=0"}
    V = np.concatenate([tri_arrays(o.name)[0] for o in new]); ext3 = V.max(0) - V.min(0); ax = int(np.argmax(ext3))
    R = mathutils.Matrix.Identity(4)
    if ax == 0: R = mathutils.Matrix.Rotation(math.radians(90), 4, "Y")
    elif ax == 1: R = mathutils.Matrix.Rotation(math.radians(-90), 4, "X")
    for o in new: o.data.transform(R)
    # 1.4.5 (lesson 61): the blade's flat side must face the front camera (-Y), i.e. its width runs along X
    V = np.concatenate([tri_arrays(o.name)[0] for o in new]); zz = V[:, 2]; nb_ = 200
    ib = np.clip(((zz - zz.min()) / max(float(np.ptp(zz)), 1e-9) * nb_).astype(int), 0, nb_ - 1); wx_, wy_ = [], []
    for b_ in range(nb_):
        m_ = ib == b_
        if m_.sum() > 2: wx_.append(float(np.ptp(V[m_, 0]))); wy_.append(float(np.ptp(V[m_, 1])))
    face_turned = bool(np.median(wy_) > 1.15 * np.median(wx_))
    if face_turned:
        Rz = mathutils.Matrix.Rotation(math.radians(90), 4, "Z")
        for o in new: o.data.transform(Rz)
    an = detect_anatomy([o.name for o in new])
    if not an["blade_side_longer"]:
        F = mathutils.Matrix.Rotation(math.pi, 4, "X")
        for o in new: o.data.transform(F)
    V = np.concatenate([tri_arrays(o.name)[0] for o in new]); c = (V.max(0) + V.min(0)) / 2
    T = mathutils.Matrix.Translation((-c[0], -c[1], -V[:, 2].min()))
    for o in new: o.data.transform(T); o.data.update()
    return [o.name for o in new], {"kind": "weapon", "long_axis_was": "xyz"[ax], "flipped": not an["blade_side_longer"],
                                   "face_turned_90": face_turned, "width_y_over_x": round(float(np.median(wy_) / max(np.median(wx_), 1e-9)), 3)}


# ======================================================================= 1.5.0 voxel clean-up + QEM low poly
def _incons_faces(tv):
    """faces on manifold edges whose two faces traverse the edge the same way (non-orientable / flipped spots)."""
    e = np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]]); f = np.tile(np.arange(len(tv)), 3)
    k = np.sort(e, 1); key = k[:, 0] * (int(k.max()) + 1) + k[:, 1]; order = np.argsort(key, kind="stable"); key = key[order]
    u, st, cnt = np.unique(key, return_index=True, return_counts=True); s_ = st[cnt == 2]; i0 = order[s_]; i1 = order[s_ + 1]
    fwd = e[:, 0] < e[:, 1]; bad = fwd[i0] == fwd[i1]
    return np.unique(np.concatenate([f[i0][bad], f[i1][bad]]))


def _blender_voxel(co, tv, voxel):
    """1.5.2: closed surface through Blender's built-in voxel remesh (OpenVDB, GPL like Blender). Takes / returns
    world-space triangle arrays. silver_fang 2026-11-15: same quality as MeshLib at 0.7 mm, s2 gates equal or better."""
    me0 = bpy.data.meshes.new("FORGE_vx_tmp"); ob = bpy.data.objects.new("FORGE_vx_tmp", me0); mname = me0.name
    bpy.context.scene.collection.objects.link(ob)
    try:
        replace_mesh(ob.name, co, tv)
        mod = ob.modifiers.new("vx", "REMESH"); mod.mode = "VOXEL"; mod.voxel_size = float(voxel); mod.adaptivity = 0.0
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(bpy.context.evaluated_depsgraph_get()))
        me.calc_loop_triangles()
        v = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", v); v = v.reshape(-1, 3)
        t = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", t)
        M = np.array(ob.matrix_world); v = v @ M[:3, :3].T + M[:3, 3]
        bpy.data.meshes.remove(me)
        return v, t.reshape(-1, 3)
    finally:
        bpy.data.objects.remove(ob)                  # Blender 5 may free the orphan mesh with it: look it up by name
        if bpy.data.meshes.get(mname): bpy.data.meshes.remove(bpy.data.meshes[mname])


def _close_holes(co, tv):
    """1.6.0: cap the open boundaries of a mesh (PyMeshLab) so a voxel rebuild knows inside from outside."""
    import pymeshlab
    ms = pymeshlab.MeshSet(); ms.add_mesh(pymeshlab.Mesh(vertex_matrix=np.asarray(co, np.float64), face_matrix=np.asarray(tv, np.int32)))
    for _ in range(3):
        try: ms.meshing_repair_non_manifold_edges(); ms.meshing_repair_non_manifold_vertices()
        except Exception: pass
        try: ms.meshing_close_holes(maxholesize=1000000, newfaceselected=False)
        except Exception: pass
    m = ms.current_mesh(); return m.vertex_matrix().astype(np.float64), m.face_matrix().astype(np.int64)


def _lost_surface(co, tv, c2, t2, tol, n=20000):
    """share of the original surface (area-weighted samples) farther than tol from the rebuilt surface."""
    from mathutils.bvhtree import BVHTree
    d = nearest_dist(BVHTree.FromPolygons(np.asarray(c2).tolist(), np.asarray(t2).tolist()), sample_surface(np.asarray(co, float), np.asarray(tv), n)[0])
    return float((np.asarray(d) > tol).mean())


def voxel_cleanup(project, voxel_rel=None, taubin_steps=None, min_part_pct=None):
    """1.5.0 default high-poly clean-up (user decision 2026-11-03): rebuild the AI surface through a signed-distance
    voxel grid (1.5.2: Blender's own OpenVDB voxel remesh by default; MeshLib only if config engine="meshlib", it needs
    a commercial licence for commercial work), voxel = voxel_rel x length (0.7 mm on a 1 m sword), drop floating bits,
    Taubin-smooth.
    Removes AI noise, serrated edges, open seams and self-intersections; the design changes slightly (silver_fang:
    mean 0.04 mm, max 1.7 mm at sharp tips) and the user accepted that. The textured original is kept hidden as
    settings.texture_source: s4 bakes colour / roughness / metallic / emission from it, normals and AO from the new
    high. The design baseline is re-written (the cleaned surface is the new design)."""
    import bmesh, pymeshlab
    P = _proj(project); c = P.cfg.get("high_cleanup", {}); L = _L(P)
    vr = voxel_rel or c.get("voxel_rel", 0.00071); ts_ = taubin_steps if taubin_steps is not None else c.get("taubin_steps", 15)
    mp = min_part_pct if min_part_pct is not None else c.get("min_part_pct", 1.5)
    names = list(_highs(P)); asset = _asset(P); src = []
    for i, n in enumerate(names):                               # keep the textured original for the colour bake
        ob = bpy.data.objects[n]; cp = ob.copy(); cp.data = ob.data.copy()
        cp.name = f"{asset}_texture_source" + (f"_{i}" if i else ""); cp.data.name = cp.name
        for col in ob.users_collection: col.objects.link(cp)
        cp.hide_set(True); cp.hide_render = True; src.append(cp.name)
    co, tv = _joined_world(names); eng = c.get("engine", "blender"); vox = float(vr * L)
    if P.state["settings"].get("kind") == "generic" and not voxel_rel:
        # 1.6.0: a sword is thin, so voxel = 0.00071 x length gives ~1 M triangles. A bulky asset of the same length
        # has far more surface: size the voxel from the area (triangles ~ 2.7 x area / voxel^2), never finer than above
        a_ = np.asarray(co)[np.asarray(tv)]; area = float(np.linalg.norm(np.cross(a_[:, 1] - a_[:, 0], a_[:, 2] - a_[:, 0]), axis=1).sum() / 2)
        vox = max(vox, math.sqrt(2.7 * area / float(c.get("max_tris", 1.2e6))))     # measured: tris ~ 2.7 x area / voxel^2
    if eng == "meshlib":                     # optional; free for non-commercial use only
        from meshlib import mrmeshpy as mm, mrmeshnumpy as mn
        m = mn.meshFromFacesVerts(np.ascontiguousarray(tv, np.int32), np.ascontiguousarray(co, np.float32))
        prm = mm.OffsetParameters(); prm.voxelSize = vox
        try: prm.signDetectionMode = mm.SignDetectionMode.HoleWindingRule
        except Exception: pass
        m2 = mm.offsetMesh(mm.MeshPart(m), 0.0, prm)
        c2 = mn.getNumpyVerts(m2).astype(np.float64); t2 = mn.getNumpyFaces(m2.topology).astype(np.int64)
    else:
        c2, t2 = _blender_voxel(co, tv, vox)
    # 1.6.0: an open mesh (holes, separate shells) can lose whole parts in a voxel rebuild: measure it, and retry once
    # with the holes capped. s1 gates on the remaining loss.
    lost = _lost_surface(co, tv, c2, t2, 4 * vox); closed = False
    if lost > 0.005 and eng != "meshlib":
        cc, tc = _close_holes(co, tv); c2b, t2b = _blender_voxel(cc, tc, vox); lost_b = _lost_surface(co, tv, c2b, t2b, 4 * vox)
        if lost_b < lost: c2, t2, lost, closed = c2b, t2b, lost_b, True
    ms = pymeshlab.MeshSet(); ms.add_mesh(pymeshlab.Mesh(vertex_matrix=c2, face_matrix=t2.astype(np.int32)))
    n0 = ms.current_mesh().face_number()
    ms.meshing_remove_connected_component_by_diameter(mincomponentdiag=pymeshlab.PercentageValue(mp))
    if ts_: ms.apply_coord_taubin_smoothing(lambda_=0.5, mu=-0.53, stepsmoothnum=int(ts_))
    ms.meshing_remove_unreferenced_vertices(); out = ms.current_mesh()
    c3 = out.vertex_matrix().astype(np.float64); t3 = out.face_matrix().astype(np.int64)
    keep = names[0]; replace_mesh(keep, c3, t3); ob = bpy.data.objects[keep]
    for p_ in ob.data.polygons: p_.use_smooth = True
    for n in names[1:]:                                          # one closed surface now: the other parts are inside it
        o_ = bpy.data.objects[n]; o_.hide_set(True); o_.hide_render = True
    s_ = P.state["settings"]; s_["high"] = [keep]; s_["texture_source"] = src; s_.pop("look_ref", None)
    info = {"method": ("MeshLib" if eng == "meshlib" else "Blender OpenVDB") + " voxel + small parts removed + Taubin",
            "engine": eng, "voxel_mm": round(vox * 1000, 3), "taubin_steps": ts_,
            "small_parts_faces_removed": int(n0 - len(t3)),
            "lost_surface_pct": round(100 * _lost_surface(co, tv, c3, t3, 4 * vox), 2), "holes_capped_first": closed, "tris": int(len(t3)), "replaced": names, "texture_source": src,
            "time": time.strftime("%Y-%m-%d %H:%M")}
    s_["high_cleanup"] = info; P.save()
    info["design_baseline"] = _write_baseline(P, [keep]); P.save()
    json.dump(info, open(os.path.join(P.gate_dir("s0_edits"), "voxel_cleanup.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit="voxel_cleanup", **{k: v for k, v in info.items() if k in ("voxel_mm", "taubin_steps", "tris")})
    return info


def _qem_fix(name, bvh, L, th):
    """repairs a QEM result only where needed (the sequence that took silver_fang to winding/non-manifold PASS)."""
    import bmesh, pymeshlab, mathutils
    co, tv, *_ = tri_arrays(name); et = edge_faces(tv); rep = {"nonmanifold_in": et["n_nonmanifold"], "winding_in": et.get("n_inconsistent_winding", 0)}
    if not rep["nonmanifold_in"] and not rep["winding_in"]: return rep
    ms = pymeshlab.MeshSet(); ms.add_mesh(pymeshlab.Mesh(vertex_matrix=co, face_matrix=tv.astype(np.int32)))
    for _k in range(4): ms.meshing_repair_non_manifold_edges(method=0); ms.meshing_repair_non_manifold_vertices()
    try: ms.meshing_close_holes(maxholesize=30, newfaceselected=False)
    except Exception: pass
    ms.meshing_remove_unreferenced_vertices(); mo = ms.current_mesh(); replace_mesh(name, mo.vertex_matrix().astype(np.float64), mo.face_matrix().astype(np.int64))
    co, tv, *_ = tri_arrays(name)
    a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]; n = np.cross(b - a, c - a); cen = (a + b + c) / 3; flip = np.zeros(len(tv), bool)
    for i in range(len(tv)):
        loc, nh, _, _ = bvh.find_nearest(mathutils.Vector(cen[i]))
        if loc is not None and float(np.dot(n[i], np.array(nh))) < 0: flip[i] = True
    tv[flip] = tv[flip][:, ::-1]; bad = _incons_faces(tv); keep = np.ones(len(tv), bool); keep[bad] = False
    ms = pymeshlab.MeshSet(); ms.add_mesh(pymeshlab.Mesh(vertex_matrix=co, face_matrix=tv[keep].astype(np.int32)))
    for _k in range(3): ms.meshing_repair_non_manifold_edges(method=0); ms.meshing_repair_non_manifold_vertices()
    try: ms.meshing_close_holes(maxholesize=60, newfaceselected=False)
    except Exception: pass
    ms.meshing_remove_unreferenced_vertices(); mo = ms.current_mesh(); replace_mesh(name, mo.vertex_matrix().astype(np.float64), mo.face_matrix().astype(np.int64))
    c_, t_, *_ = tri_arrays(name); t2, fl = fold_repair(c_, t_, bvh, z_skip=None); t2, dp = drop_duplicate_faces(t2)
    c2, t2, fi, _ = merge_tiny_nonmanifold_edges(c_, t2, th.get("fin_merge_max_rel", 0.001) * L)
    if fl or dp or fi: replace_mesh(name, c2, t2)
    me = bpy.data.objects[name].data
    for _k in range(2):
        bm = bmesh.new(); bm.from_mesh(me); be = [e for e in bm.edges if e.is_boundary]
        if be: r = bmesh.ops.holes_fill(bm, edges=be, sides=0); bmesh.ops.triangulate(bm, faces=r["faces"])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(me); bm.free(); me.update()
    rep.update(flipped=int(flip.sum()), dropped=int(len(bad)))
    return rep


def _qem_copy(P, target, name):
    """joined high (same as _decimate_copy, keep_whole parts included) -> PyMeshLab quadric decimation (QEM, quality
    0.2, no topology lock, no planar quadric: the silver_fang winner) -> repair only if needed."""
    import pymeshlab
    th = P.cfg.get("lowpoly", {}); L = _L(P)
    ob = _decimate_copy(P, 10 ** 12, name)                      # ratio 1.0: join + transform only
    co, tv, *_ = tri_arrays(name)
    ms = pymeshlab.MeshSet(); ms.add_mesh(pymeshlab.Mesh(vertex_matrix=co, face_matrix=tv.astype(np.int32)))
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(target), qualitythr=th.get("qem_quality", 0.2), preserveboundary=True,
        boundaryweight=2.0, preservenormal=True, preservetopology=False, optimalplacement=True, planarquadric=False, autoclean=True)
    mo = ms.current_mesh(); replace_mesh(name, mo.vertex_matrix().astype(np.float64), mo.face_matrix().astype(np.int64))
    bvh = bvh_of(_highs(P))[0]; rep = _qem_fix(name, bvh, L, th)
    ob = bpy.data.objects[name]; ob["forge_qem"] = json.dumps(rep)
    return ob


def s0_import(project, path, title=None, forward="-Y", up="Z", weld=True, kind="auto"):
    """import an AI-generated model (GLB/GLTF/FBX/OBJ), keep the original file, normalise to +Z with the tip low,
    apply transforms; then same checks as s0_adopt."""
    P = _proj(project); src = P.p("source", os.path.basename(path))
    if os.path.abspath(path) != os.path.abspath(src): shutil.copy2(path, src)
    names, orient = _import_normalised(src, kind=kind)      # kind: "auto" | "weapon" | "generic" (any other model)
    P.state["settings"]["import_orientation"] = orient
    P.state["settings"]["kind"] = orient.get("kind", "weapon"); P.state["settings"]["kind_auto"] = kind == "auto"; P.save()
    if weld:          # 1.4.2: importers split vertices on UV seams -> open mesh -> wrong volume/mass in s0_spec
        P.state["settings"]["high"] = list(names); P.save(); weld_highpoly(project, names=names)
    return s0_adopt(project, names, title=title)


def export_test_glb(project, path, scale=1.0, rot_x_deg=0.0):
    """test helper: export the project's high poly as a GLB with a scale / rotation applied to the file only
    (simulates AI files in other units or orientations). The scene is left unchanged."""
    import mathutils
    P = _proj(project); objs = [bpy.data.objects[n] for n in _highs(P)]
    M = mathutils.Matrix.Rotation(math.radians(rot_x_deg), 4, "X") @ mathutils.Matrix.Scale(scale, 4)
    keep = [o.matrix_world.copy() for o in objs]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs: o.matrix_world = M @ o.matrix_world; o.select_set(True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True)
    finally:
        for o, m_ in zip(objs, keep): o.matrix_world = m_; o.select_set(False)
    return {"path": path, "bytes": os.path.getsize(path)}


# ======================================================================= s0 edits: proven geometry edits on the high poly
def _thin_axis(co, tv, an):
    cr = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]]); A3 = np.linalg.norm(cr, axis=1) / 2
    N = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-20); z = co[tv].mean(1)[:, 2]
    bl = z < an["guard_z0"]
    return int(np.argmax([(np.abs(N[bl, i]) * A3[bl]).sum() for i in (0, 1)]))


def _edit_snapshot(names, an, dens):
    cos, tvs, off = [], [], 0
    for n in names:
        co, tv, _, _, _ = tri_arrays(n)
        tol = max(float(np.ptp(co, 0).max()) * 1e-6, 1e-9)
        _, first, inv = np.unique(np.round(co / tol).astype(np.int64), axis=0, return_index=True, return_inverse=True)
        cos.append(co[first]); tvs.append(inv.ravel()[tv] + off); off += len(first)
    co = np.vstack(cos); tv = np.vstack(tvs); m, prof = measure_weapon(co, tv, an, dens)
    zc = prof["z"]; zones = {}
    for k, (a, b) in {"blade": (an["tip_z"], an["guard_z0"]), "guard": (an["guard_z0"], an["guard_z1"]),
                      "grip": (an["grip_z0"], an["grip_z1"]), "pommel": (an["grip_z1"], 1e9)}.items():
        sel = (zc >= a) & (zc < b); zones[k] = {"volume_L": round(float(prof["volume"][sel].sum()) * 1e3, 4), "kg": round(float(prof["mass"][sel].sum()), 3)}
    ext = np.ptp(co, 0)
    return {"measure": m, "zones": zones, "extent_xz_m": [round(float(ext[0]), 4), round(float(ext[2]), 4)], "extent_y_m": round(float(ext[1]), 4)}


def _save_positions(P, names, tag):
    d = P.gate_dir("s0_edits"); path = os.path.join(d, f"positions_before_{tag}_{time.strftime('%Y%m%d_%H%M%S')}.npz")
    arrs = {}
    for n in names:
        me = bpy.data.objects[n].data; a = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", a); arrs[n] = a
    np.savez(path, **arrs); return path


def restore_positions(project, path):
    """undo an edit: put back the vertex positions saved before it (same topology)."""
    D = np.load(path)
    for n in D.files:
        me = bpy.data.objects[n].data
        if len(me.vertices) * 3 != len(D[n]): raise RuntimeError(f"{n}: topology changed, cannot restore")
        me.vertices.foreach_set("co", D[n]); me.update()
    return {"restored": D.files}


# ======================================================================= design lock: the design's shape never changes
# LESSON 42 (inferno_line v4/v5): fitting a model to a real sword by stretching, thinning or rebuilding parts changed the
# design. The size is changed only by uniform_fit (one factor on all axes). Shape edits (extend_grip, thin_profile,
# thin_zone) are refused while settings.design_lock is on (default); only the user may turn it off.
# design_check compares the high poly with the surface saved at intake, so ANY tool or ad-hoc script that changes the
# shape is caught (s1 gate), whatever it was.
def _design_locked(P):
    return bool(P.state["settings"].get("design_lock", True))


def _design_guard(P, edit):
    if _design_locked(P):
        raise RuntimeError(f"{edit}: refused - design_lock is on (the shape of the design must not change). "
                           f"Change the size only with uniform_fit('{P.name}', target_overall_m=...). Shape edits need the "
                           f"user's explicit decision: set_settings('{P.name}', design_lock=False)")


def _joined_world(names):
    cos, tvs, off = [], [], 0
    for n in names:
        co, tv, _, _, _ = tri_arrays(n); cos.append(co); tvs.append(tv + off); off += len(co)
    return np.vstack(cos), np.vstack(tvs)


def _write_baseline(P, names):
    co, tv = _joined_world(names)
    path = os.path.join(P.gate_dir("s0_edits"), f"design_baseline_{time.strftime('%Y%m%d_%H%M%S')}.npz")
    np.savez(path, co=co, tv=tv)
    P.state["settings"]["design_baseline"] = path; P.state["settings"]["design_baseline_names"] = list(names)
    return path


def design_baseline(project, names=None):
    """save the design's surface (world-space triangles of the high poly) as the reference for design_check.
    s0_adopt / s0_import do this automatically; call it again only when the USER accepts a new design."""
    P = _proj(project); names = names or _highs(P); path = _write_baseline(P, names); P.save()
    return {"design_baseline": path}


def _surface_dist(src, co, tv):
    from mathutils.bvhtree import BVHTree
    t = BVHTree.FromPolygons([tuple(map(float, v)) for v in co], [tuple(map(int, f)) for f in tv], epsilon=0.0)
    d = np.empty(len(src))
    for i, p in enumerate(src):
        hit = t.find_nearest(tuple(map(float, p))); d[i] = hit[3] if hit[0] is not None else np.inf
    return d


def design_check(project, names=None, tol_rel=None, samples=60000):
    """did the design's SHAPE change since the intake baseline? One uniform size factor (overall length ratio) is
    removed first, so uniform_fit passes; a stretch, thinning, rebuilt or remeshed part that lost detail does not.
    Surface distance both ways as a share of the length; FAIL above tol_rel (settings.design_tolerance, default
    0.0005 = 0.6 mm on a 1.2 m sword; fix_folds moves at most 0.3 mm)."""
    P = _proj(project); names = names or _highs(P); s = P.state["settings"]; path = s.get("design_baseline")
    if not path or not os.path.exists(path):
        return {"status": "NO_BASELINE", "hint": f"design_baseline('{project}') once the user accepts the current design"}
    D = np.load(path); cb, tb = D["co"], D["tv"]; cc, tc = _joined_world(names)
    tol = float(tol_rel if tol_rel is not None else s.get("design_tolerance", 0.0005))
    def frame(co):
        lo, hi = co.min(0), co.max(0); return np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]]), hi[2] - lo[2]
    ob, Lb = frame(cb); oc, Lc = frame(cc); k = Lc / Lb; cb2 = (cb - ob) * k + oc
    rng = np.random.default_rng(0)
    def sub(a): return a if len(a) <= samples else a[rng.choice(len(a), samples, replace=False)]
    pb, pc = sub(cb2), sub(cc)
    d1 = _surface_dist(pb, cc, tc) / Lc; d2 = _surface_dist(pc, cb2, tb) / Lc
    d = np.concatenate([d1, d2]); pts = np.vstack([pb, pc]); w = int(np.argmax(d))
    rep = {"status": "PASS" if float(d.max()) <= tol else "FAIL", "uniform_factor": round(float(k), 6),
           "max_rel": round(float(d.max()), 7), "p99_rel": round(float(np.percentile(d, 99)), 7), "tol_rel": tol,
           "max_mm": round(float(d.max() * Lc * 1000), 3), "worst_at_z_m": round(float(pts[w, 2]), 4),
           "share_over_tol": round(float((d > tol).mean()), 5), "baseline": path}
    return rep


def uniform_fit(project, target_overall_m=None, factor=None, names=None):
    """change the SIZE only: one factor on all three axes about the tip, so the shape and every detail are kept
    (the way to match a real sword's length). Positions are saved first (restore_positions); design_check must PASS."""
    P = _proj(project); names = names or _highs(P); co, _ = _joined_world(names)
    lo, hi = co.min(0), co.max(0)
    Lnow = float((hi - lo).max()) if P.state["settings"].get("kind") == "generic" else float(hi[2] - lo[2])
    f = float(factor) if factor else (float(target_overall_m) / Lnow if target_overall_m else 0.0)
    if f <= 0: raise ValueError("give target_overall_m (metres) or factor")
    saved = _save_positions(P, names, "uniform_fit"); piv = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    for n in names:
        ob = bpy.data.objects[n]; me = ob.data; Mw = np.array(ob.matrix_world); Mi = np.linalg.inv(Mw)
        L = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", L); L = L.reshape(-1, 3)
        W = L @ Mw[:3, :3].T + Mw[:3, 3]; W = piv + (W - piv) * f
        L = (W - Mw[:3, 3]) @ Mi[:3, :3].T; me.vertices.foreach_set("co", L.ravel()); me.update()
    P.state["anatomy"] = _detect(P, names); P.save()
    dc = design_check(project, names)
    rep = {"edit": "uniform_fit", "factor": round(f, 6), "length_before_m": round(Lnow, 4), "length_after_m": round(Lnow * f, 4),
           "design_check": dc, "saved_positions": saved}
    json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), "uniform_fit.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit="uniform_fit", factor=rep["factor"], design=dc.get("status"))
    return rep


def extend_grip(project, target_m=None, add_m=None, keep_ends_m=0.012, names=None, anatomy=None):
    """lengthen the grip by stretching only its middle (the collars / ends keep their shape); everything above moves
    up. Vertex positions are saved first (restore_positions). Reports before/after measurements."""
    _design_guard(_proj(project), "extend_grip")
    P = _proj(project); names = names or _highs(P); an = anatomy or detect_anatomy(names)
    prof = load_profiles(); before = _edit_snapshot(names, an, prof["densities"])
    g0, g1 = an["grip_z0"], an["grip_z1"]; cur = g1 - g0
    add = add_m if add_m is not None else max(0.0, (target_m or cur) - cur)
    a, b = g0 + keep_ends_m, g1 - keep_ends_m
    if add <= 0 or b - a <= 0.01: return {"skipped": True, "grip_m": round(cur, 4)}
    saved = _save_positions(P, names, "extend_grip"); f = (b - a + add) / (b - a)
    for n in names:
        ob = bpy.data.objects[n]; me = ob.data; Mw = np.array(ob.matrix_world); Mi = np.linalg.inv(Mw)
        L = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", L); L = L.reshape(-1, 3)
        W = L @ Mw[:3, :3].T + Mw[:3, 3]; z = W[:, 2]
        W[:, 2] = np.where(z > b, z + add, np.where(z > a, a + (z - a) * f, z))
        L = (W - Mw[:3, 3]) @ Mi[:3, :3].T; me.vertices.foreach_set("co", L.ravel()); me.update()
    an2 = detect_anatomy(names); after = _edit_snapshot(names, an2, prof["densities"])
    rep = {"edit": "extend_grip", "add_m": round(add, 4), "stretch_factor": round(f, 3), "stretched_z": [round(a, 4), round(b, 4)],
           "before": before, "after": after, "anatomy_after": an2, "saved_positions": saved}
    json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), "extend_grip.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit="extend_grip", add_m=rep["add_m"], grip_after=after["measure"].get("grip_m"))
    return {k: rep[k] for k in ("edit", "add_m", "stretch_factor")} | {"grip_before": before["measure"].get("grip_m"), "grip_after": after["measure"].get("grip_m")}


def weld_highpoly(project, tol_rel=1e-6, names=None, clear_custom_normals=True):
    """merge vertices that sit at exactly the same place (importers split them along UV / normal seams). The
    tolerance is tiny (1e-6 of the weapon length, ~1 micrometre on a 1.2 m sword): only coincident vertices merge,
    never real details. UVs stay per corner, so the texture layout is kept. Positions are saved first."""
    import bmesh
    P = _proj(project); names = names or _highs(P); an = P.state.get("anatomy") or _detect(P, names)
    tol = max(an["length"] * tol_rel, 1e-9); saved = _save_positions(P, names, "weld"); out = {}
    for n in names:
        ob = bpy.data.objects[n]; me = ob.data
        co, tv, _, _, _ = tri_arrays(n); et0 = edge_faces(tv)
        loops0 = len(me.loops); v0 = len(me.vertices)
        bm = bmesh.new(); bm.from_mesh(me)
        r = bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=tol); bm.to_mesh(me); bm.free(); me.update()
        if clear_custom_normals and me.has_custom_normals:
            bpy.context.view_layer.objects.active = ob
            try: bpy.ops.mesh.customdata_custom_splitnormals_clear()
            except Exception: pass
        for p in me.polygons: p.use_smooth = True
        co, tv, _, _, _ = tri_arrays(n); et1 = edge_faces(tv)
        out[n] = {"vertices": [v0, len(me.vertices)], "loops": [loops0, len(me.loops)], "open_edges": [et0["n_boundary"], et1["n_boundary"]],
                  "nonmanifold_edges": [et0["n_nonmanifold"], et1["n_nonmanifold"]], "uv_layers": [l.name for l in me.uv_layers]}
    rep = {"edit": "weld", "tolerance_m": tol, "objects": out, "saved_positions": saved}
    json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), "weld.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit="weld", tol=tol, objects={k: v["open_edges"] for k, v in out.items()})
    return rep


def fix_folds(project, angle_deg=90.0, rings=(0, 1, 2), iters=30, max_move_m=0.0003, names=None):
    """repair tiny folded triangles of the high poly (AI artefacts that render as dark dots): only the vertices of
    edges folded more than angle_deg (plus up to 2 rings) are relaxed, each by at most max_move_m; every other vertex
    stays exactly in place (forge_mesh.fold_relax). Positions are saved first (restore_positions)."""
    P = _proj(project); names = names or _highs(P); rep = {"edit": "fix_folds", "objects": {}}
    saved = _save_positions(P, names, "fix_folds")
    for n in names:
        ob = bpy.data.objects[n]; me = ob.data; Mw = np.array(ob.matrix_world); Mi = np.linalg.inv(Mw)
        co0, tv, _, _, _ = tri_arrays(n)
        co, r = fold_relax(co0, tv, angle_deg=angle_deg, rings=rings, iters=iters, max_move=max_move_m)
        if r["vertices_moved"]:
            L = (co - Mw[:3, 3]) @ Mi[:3, :3].T; me.vertices.foreach_set("co", L.ravel()); me.update()
        rep["objects"][n] = r
    rep["saved_positions"] = saved
    json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), "fix_folds.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit="fix_folds", objects={k: [v["folded_edges_before"], v["folded_edges_after"], v["max_move_mm"]] for k, v in rep["objects"].items()})
    return rep


def fix_sliver_normals(project, max_angle=160.0, min_angle=5.0, crease_deg=20.0, min_good_faces=3, min_dev_deg=10.0, names=None):
    """dark dots from degenerate triangles: Blender weights vertex normals by corner angle, so a sliver (a corner
    > max_angle, or one < min_angle) with a random normal gets a big weight and tilts the vertex normal (measured up
    to 45 deg on the dragon). Only at the vertices of such slivers the shading normal is replaced by the
    area-weighted normal (a sliver has ~0 area, so ~0 weight). Geometry and topology are unchanged; every other
    corner keeps its current normal, and so do vertices on a crease (normal faces around them differ by more than
    crease_deg), vertices with fewer than min_good_faces normal faces, and vertices whose normal is tilted less than
    min_dev_deg (measured on the dragon: the stepped blade edges got darker with looser rules). Undo: restore_normals(project, path)."""
    P = _proj(project); names = names or _highs(P); rep = {"edit": "fix_sliver_normals", "objects": {}}
    d = P.gate_dir("s0_edits"); path = os.path.join(d, f"normals_before_slivers_{time.strftime('%Y%m%d_%H%M%S')}.npz"); saved = {}
    for n in names:
        me = bpy.data.objects[n].data; V = len(me.vertices); NL = len(me.loops)
        co = np.empty(V * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        me.calc_loop_triangles(); T = len(me.loop_triangles)
        tv = np.empty(T * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv); tv = tv.reshape(-1, 3)
        cn = np.empty(NL * 3); me.corner_normals.foreach_get("vector", cn); cn = cn.reshape(-1, 3)
        saved[n] = cn.ravel().copy(); saved[n + "__had_custom"] = np.array([me.has_custom_normals])
        A = co[tv]; cr = np.cross(A[:, 1] - A[:, 0], A[:, 2] - A[:, 0])
        def ang(k):
            a = A[:, (k + 1) % 3] - A[:, k]; b = A[:, (k + 2) % 3] - A[:, k]
            return np.degrees(np.arccos(np.clip((a * b).sum(1) / np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-30), -1, 1)))
        an = np.stack([ang(k) for k in range(3)], 1)
        sl = (an.max(1) > max_angle) | (an.min(1) < min_angle); vs = np.zeros(V, bool); vs[tv[sl].ravel()] = True
        nw = np.zeros((V, 3))
        for k in range(3):
            for q in range(3): nw[:, q] += np.bincount(tv[:, k], cr[:, q], V)
        nw /= np.maximum(np.linalg.norm(nw, axis=1), 1e-30)[:, None]
        fn = cr / np.maximum(np.linalg.norm(cr, axis=1), 1e-30)[:, None]; good = ~sl
        mind = np.ones(V)                                   # creases (real sharp edges between normal faces) keep their shading
        for k in range(3): np.minimum.at(mind, tv[good, k], (fn[good] * nw[tv[good, k]]).sum(1))
        crease = mind < math.cos(math.radians(crease_deg)); vs &= ~crease
        ng = np.zeros(V)
        for k in range(3): ng += np.bincount(tv[good, k], minlength=V)
        vs &= ng >= min_good_faces                          # enough normal faces around to define the surface
        lv = np.empty(NL, np.int64); me.loops.foreach_get("vertex_index", lv)
        cdev = np.zeros(V); np.maximum.at(cdev, lv, np.degrees(np.arccos(np.clip((cn * nw[lv]).sum(1), -1, 1))))
        vs &= cdev >= min_dev_deg                           # only where the current shading normal is really tilted
        sel = vs[lv]; new = cn.copy(); new[sel] = nw[lv[sel]]
        dev = np.degrees(np.arccos(np.clip((new[sel] * cn[sel]).sum(1), -1, 1))) if sel.any() else np.zeros(1)
        me.normals_split_custom_set(new.tolist()); me.update()
        cn2 = np.empty(NL * 3); me.corner_normals.foreach_get("vector", cn2); cn2 = cn2.reshape(-1, 3)
        untouched = float(np.abs(cn2[~sel] - cn[~sel]).max()) if (~sel).any() else 0.0
        rep["objects"][n] = {"sliver_triangles": int(sl.sum()), "crease_vertices_skipped": int((crease & np.isin(np.arange(V), tv[sl].ravel())).sum()), "vertices_changed": int(vs.sum()), "corners_changed": int(sel.sum()),
                             "normal_change_deg_p50": round(float(np.percentile(dev, 50)), 3), "normal_change_deg_p99": round(float(np.percentile(dev, 99)), 3),
                             "normal_change_deg_max": round(float(dev.max()), 3), "untouched_corners_max_diff": round(untouched, 6),
                             "had_custom_normals": bool(saved[n + "__had_custom"][0])}
    np.savez(path, **saved); rep["saved_normals"] = path
    json.dump(rep, open(os.path.join(d, "fix_sliver_normals.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit="fix_sliver_normals", objects={k: [v["vertices_changed"], v["normal_change_deg_max"]] for k, v in rep["objects"].items()})
    return rep


def restore_normals(project, path):
    """undo fix_sliver_normals: put back the corner normals saved before it (or clear custom normals if there were none)."""
    D = np.load(path); out = []
    for k in D.files:
        if k.endswith("__had_custom"): continue
        me = bpy.data.objects[k].data
        if bool(D[k + "__had_custom"][0]): me.normals_split_custom_set(D[k].reshape(-1, 3).tolist())
        else:
            bpy.context.view_layer.objects.active = bpy.data.objects[k]
            try: bpy.ops.mesh.customdata_custom_splitnormals_clear()
            except Exception: me.normals_split_custom_set(D[k].reshape(-1, 3).tolist())
        me.update(); out.append(k)
    return {"restored": out}


def add_gem(project, center, radii, name=None, segments=32, rings=16, protect_r=None):
    """replace a broken AI gem by a clean ellipsoid (a separate high-poly object, kept whole in the low poly through
    settings.keep_whole). center (x, y, z) m, radii (rx, ry, rz) m: ry = how far it stands out on each face. The part
    of the ellipsoid inside the guard stays hidden. Undo: remove_gem(project, name)."""
    import bmesh
    P = _proj(project); st = P.state["settings"]; name = name or _asset(P) + "_gem_high"
    old = bpy.data.objects.get(name)
    if old: me_ = old.data; bpy.data.objects.remove(old); bpy.data.meshes.remove(me_)
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=1.0)
    for v in bm.verts: v.co.x *= radii[0]; v.co.y *= radii[1]; v.co.z *= radii[2]
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me); ob.location = center
    src = bpy.data.objects[_highs(P)[0]]
    for c_ in src.users_collection: c_.objects.link(ob)
    if src.material_slots and src.material_slots[0].material: me.materials.append(src.material_slots[0].material)
    bpy.context.view_layer.update()
    ob.data.transform(ob.matrix_world); ob.matrix_world = __import__("mathutils").Matrix.Identity(4)
    st["high"] = [n for n in st["high"] if n != name] + [name]
    st["keep_whole"] = sorted(set(st.get("keep_whole", [])) | {name})
    r = protect_r or max(radii) * 1.1
    st["protect_zones"] = [[center[0], center[1], center[2], r]]
    P.save()
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    rep = {"edit": "add_gem", "object": name, "center_m": list(center), "radii_m": list(radii), "tris": tris,
           "protect_zones": st["protect_zones"], "high": st["high"], "keep_whole": st["keep_whole"]}
    json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), "add_gem.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit="add_gem", object=name, radii=list(radii), center=list(center))
    return rep


def remove_gem(project, name=None):
    P = _proj(project); st = P.state["settings"]; name = name or _asset(P) + "_gem_high"
    ob = bpy.data.objects.get(name)
    if ob: me_ = ob.data; bpy.data.objects.remove(ob); bpy.data.meshes.remove(me_)
    st["high"] = [n for n in st["high"] if n != name]; st["keep_whole"] = [n for n in st.get("keep_whole", []) if n != name]; P.save()
    return {"removed": name, "high": st["high"]}


def remove_junk(project, dry_run=False):
    """delete objects that are not part of the asset but take part in bakes and renders: the factory Cube / Camera /
    Light and leftover trial copies (<asset>_trial_*; their reports stay). Found on the dragon v2: a 2 m Cube around
    the blade and guard plus 6 coincident trial copies made the AO bake black and blotchy."""
    P = _proj(project); base = _asset(P); keep = set(_highs(P)) | {f"{base}_LOD{i}" for i in range(3)}
    junk = []
    for o in list(bpy.data.objects):
        if o.name in keep or o.name.startswith("FORGE_") or o.name.startswith("UCX_"): continue
        if o.name in ("Cube", "Camera", "Light") or o.name.startswith(f"{base}_trial_"): junk.append((o.name, o.type))
    if not dry_run:
        for n, _ in junk: bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)   # orphan data is not saved
    rep = {"edit": "remove_junk", "removed": junk, "dry_run": dry_run}
    if not dry_run:
        json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), "remove_junk.json"), "w"), indent=2)
        ledger("edit", project=P.name, edit="remove_junk", removed=[n for n, _ in junk])
    return rep


def render_check(project, tag, views=("full_front", "side", "guard_center", "grip", "pommel"), engine="WORKBENCH"):
    """the same cameras before and after an edit: renders the high poly into reports/s0_edits/<tag>/.
    'side' looks along the thin axis's normal (shows thickness)."""
    P = _proj(project); an = _detect(P, _highs(P)); out = P.gate_dir("s0_edits", tag); L = an["length"]
    cx, cy = an["axis_xy"]; V = {v[0]: v for v in inspection_views(an)}
    V["side"] = ("side", (cx, cy, L / 2), (1, 0, 0), 1.5 * L, 90)
    paths = render_views(set(_highs(P)), [V[v] for v in views if v in V], out, "high", engine=engine)
    return {"renders": paths}


def _profile_factor(z, points):
    """thickness factor along z from control points [[z, f], ...]: constant outside, smoothstep between points (C1)."""
    pts = sorted(points); zs = np.array([p[0] for p in pts], float); fs = np.array([p[1] for p in pts], float)
    out = np.full(len(z), fs[0]); out[z >= zs[-1]] = fs[-1]
    for i in range(len(zs) - 1):
        m = (z >= zs[i]) & (z < zs[i + 1]); t = (z[m] - zs[i]) / max(zs[i + 1] - zs[i], 1e-9)
        out[m] = fs[i] + (fs[i + 1] - fs[i]) * t * t * (3 - 2 * t)
    return out


def thin_profile(project, points, protect=None, names=None, anatomy=None, tag="thin_profile"):
    """thinner along the thin axis with ONE smooth factor profile over the whole length (no step between zones):
    points = [[z, factor], ...]. protect spheres stay unchanged. The report compares the measured per-slab volume
    ratio with the requested profile (a dip or bump shows up as an error)."""
    _design_guard(_proj(project), tag)
    P = _proj(project); names = names or _highs(P); an = anatomy or detect_anatomy(names)
    prof = load_profiles(); before = _edit_snapshot(names, an, prof["densities"])
    cos = [tri_arrays(n)[:2] for n in names]; co_all = np.vstack([c for c, _ in cos])
    tv_all = np.vstack([t + sum(len(c) for c, _ in cos[:i]) for i, (_, t) in enumerate(cos)])
    ax = _thin_axis(co_all, tv_all, an); c_ax = an["axis_xy"][ax]
    _, vb, _ = volume_profile(co_all, tv_all, 2, cell=0.005)
    saved = _save_positions(P, names, tag)
    def smooth(t): t = np.clip(t, 0, 1); return t * t * (3 - 2 * t)
    for n in names:
        ob = bpy.data.objects[n]; me = ob.data; Mw = np.array(ob.matrix_world); Mi = np.linalg.inv(Mw)
        L = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", L); L = L.reshape(-1, 3)
        W = L @ Mw[:3, :3].T + Mw[:3, 3]; f = _profile_factor(W[:, 2], points)
        for x, y, zz, r in (protect or []):
            d = np.linalg.norm(W - np.array([x, y, zz]), axis=1); k = smooth((d - r) / max(0.5 * r, 1e-9)); f = 1 - k * (1 - f)
        W[:, ax] = c_ax + (W[:, ax] - c_ax) * f
        L = (W - Mw[:3, 3]) @ Mi[:3, :3].T; me.vertices.foreach_set("co", L.ravel()); me.update()
    cos2 = [tri_arrays(n)[:2] for n in names]; co2 = np.vstack([c for c, _ in cos2])
    e, va, _ = volume_profile(co2, tv_all, 2, cell=0.005); zc = (e[:-1] + e[1:]) / 2
    n_ = min(len(va), len(vb)); ok = vb[:n_] > 0.02 * vb.max()
    want = _profile_factor(zc[:n_], points); got = np.where(ok, va[:n_] / np.maximum(vb[:n_], 1e-12), np.nan)
    far = np.ones(n_, bool)
    for x, y, zz, r in (protect or []): far &= np.abs(zc[:n_] - zz) > 1.6 * r
    err = np.abs(got - want)[ok & far]
    an2 = detect_anatomy(names); after = _edit_snapshot(names, an2, prof["densities"])
    rep = {"edit": tag, "points": points, "axis": "xy"[ax], "protect": protect, "before": before, "after": after,
           "slab_ratio_error": {"p50": round(float(np.nanmedian(err)), 4), "p95": round(float(np.nanpercentile(err, 95)), 4), "max": round(float(np.nanmax(err)), 4)},
           "anatomy_after": an2, "saved_positions": saved}
    json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), f"{tag}.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit=tag, kg_before=before["measure"].get("mass_kg"), kg_after=after["measure"].get("mass_kg"))
    return {"edit": tag, "kg_before": before["measure"].get("mass_kg"), "kg_after": after["measure"].get("mass_kg"),
            "slab_ratio_error": rep["slab_ratio_error"], "front_extent_before": before["extent_xz_m"], "front_extent_after": after["extent_xz_m"]}


def thin_zone(project, z0, z1, factor, blend_m=0.02, protect=None, names=None, anatomy=None, tag="thin"):
    """make a z-band thinner along the weapon's thin axis (front silhouette unchanged), smoothly blended over blend_m;
    protect = [[x, y, z, r], ...] spheres kept unchanged (e.g. the gem stays round). Positions saved first."""
    _design_guard(_proj(project), tag)
    P = _proj(project); names = names or _highs(P); an = anatomy or detect_anatomy(names)
    prof = load_profiles(); before = _edit_snapshot(names, an, prof["densities"])
    cos = [tri_arrays(n)[:2] for n in names]; co_all = np.vstack([c for c, _ in cos])
    tv_all = np.vstack([t + sum(len(c) for c, _ in cos[:i]) for i, (_, t) in enumerate(cos)])
    ax = _thin_axis(co_all, tv_all, an); c_ax = an["axis_xy"][ax]
    saved = _save_positions(P, names, tag)
    def smooth(t): t = np.clip(t, 0, 1); return t * t * (3 - 2 * t)
    for n in names:
        ob = bpy.data.objects[n]; me = ob.data; Mw = np.array(ob.matrix_world); Mi = np.linalg.inv(Mw)
        L = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", L); L = L.reshape(-1, 3)
        W = L @ Mw[:3, :3].T + Mw[:3, 3]; z = W[:, 2]
        w = np.minimum(smooth((z - (z0 - blend_m)) / max(blend_m, 1e-9)), smooth(((z1 + blend_m) - z) / max(blend_m, 1e-9)))
        for x, y, zz, r in (protect or []):
            d = np.linalg.norm(W - np.array([x, y, zz]), axis=1); w = w * smooth((d - r) / max(0.5 * r, 1e-9))
        s = 1.0 - w * (1.0 - factor)
        W[:, ax] = c_ax + (W[:, ax] - c_ax) * s
        L = (W - Mw[:3, 3]) @ Mi[:3, :3].T; me.vertices.foreach_set("co", L.ravel()); me.update()
    an2 = detect_anatomy(names); after = _edit_snapshot(names, an2, prof["densities"])
    rep = {"edit": tag, "z": [z0, z1], "factor": factor, "blend_m": blend_m, "axis": "xy"[ax], "protect": protect,
           "before": before, "after": after, "anatomy_after": an2, "saved_positions": saved}
    json.dump(rep, open(os.path.join(P.gate_dir("s0_edits"), f"{tag}.json"), "w"), indent=2, default=str)
    ledger("edit", project=P.name, edit=tag, factor=factor, kg_before=before["measure"].get("mass_kg"), kg_after=after["measure"].get("mass_kg"))
    return {"edit": tag, "axis": "xy"[ax], "kg_before": before["measure"].get("mass_kg"), "kg_after": after["measure"].get("mass_kg"),
            "front_extent_before": before["extent_xz_m"], "front_extent_after": after["extent_xz_m"]}


# ======================================================================= s0_candidates: several AI versions of one weapon
def candidate_measure(project, path, tag, weapon_type=None, style=None, character_height=None):
    """one AI version, in its own .blend (the orchestrator gives each candidate its own work file): import + normalise
    (the source file is never modified), then mesh health, symmetry, surface noise, textures, s0_spec measurements and
    checks, and the same renders for every candidate. Writes reports/s0_candidates/<tag>/candidate.json."""
    import time as _t
    P = _proj(project); t0 = _t.time(); out = P.gate_dir("s0_candidates", tag)
    w = dict(P.cfg.get("weapon", {})); w.update(P.state["settings"].get("weapon", {}))
    wt = weapon_type or w.get("type"); st = style or w.get("style", "fantasy")
    ch = {"height_m": character_height or w.get("character_height_m", 1.8)}
    names, how = _import_normalised(path, "FORGE_candidate")
    cos, tvs, off = [], [], 0; health = {"objects": len(names), "tris": 0, "nonmanifold_edges": 0, "open_edges": 0,
                                          "degenerate_tris": 0, "duplicate_vertices": 0}
    for n in names:
        co, tv, _, _, _ = tri_arrays(n)
        # glTF/FBX importers split vertices along UV and normal seams: weld coincident positions before judging
        # holes, volume or noise (otherwise every seam counts as an open edge)
        tol = max(float(np.ptp(co, 0).max()) * 1e-6, 1e-9)
        _, first, inv = np.unique(np.round(co / tol).astype(np.int64), axis=0, return_index=True, return_inverse=True)
        co_w = co[first]; tv_w = inv.ravel()[tv]
        health["duplicate_vertices"] += int(len(co) - len(co_w))
        et = edge_faces(tv_w); _, A3 = tri_normals(co_w, tv_w)
        health["tris"] += len(tv); health["nonmanifold_edges"] += et["n_nonmanifold"]; health["open_edges"] += et["n_boundary"]
        health["degenerate_tris"] += int((A3 < 1e-12).sum())
        cos.append(co_w); tvs.append(tv_w + off); off += len(co_w)
    co = np.vstack(cos); tv = np.vstack(tvs)
    health["note"] = "open / non-manifold edges counted after welding coincident vertices (seam splits are not holes)"
    an = detect_anatomy(names); prof = load_profiles()
    ang, conc, et = dihedral(co, tv)
    health["dihedral_deg"] = {"p50": round(float(np.percentile(ang, 50)), 2), "p90": round(float(np.percentile(ang, 90)), 2),
                              "p99": round(float(np.percentile(ang, 99)), 2)}
    health["edges_over_60deg_share"] = round(float((ang > 60).mean()), 5)
    bvh, _, _ = bvh_of(names); pts, _ = sample_surface(co, tv, 20000, seed=1)
    mir = pts.copy(); mir[:, 0] = 2 * an["axis_xy"][0] - mir[:, 0]
    d = nearest_dist(bvh, mir) * 1000
    health["mirror_x_mm"] = {"p50": round(float(np.percentile(d, 50)), 2), "p95": round(float(np.percentile(d, 95)), 2)}
    imgs = set()
    for n in names:
        for s_ in bpy.data.objects[n].material_slots:
            if s_.material and s_.material.use_nodes:
                for x in s_.material.node_tree.nodes:
                    if x.type == "TEX_IMAGE" and x.image: imgs.add((x.image.name, tuple(x.image.size)))
    health["textures"] = sorted([f"{a} {b[0]}x{b[1]}" for a, b in imgs])
    m, _ = measure_weapon(co, tv, an, prof["densities"])
    guess = guess_type(m)
    C = spec_checks(m, wt or guess[0], st, prof, ch) if (wt or guess[0]) != "unknown" else []
    views = [v for v in inspection_views(an) if _vin(v[0], ("full_front", "full_back", "tip", "blade_mid", "junction", "guard_center", "guard_left", "grip", "pommel"))]
    geo = render_views(set(names), views, out, "geo", engine="WORKBENCH")
    lit = render_views(set(names), [v for v in views if _vin(v[0], ("full_front", "guard_center", "pommel"))], out, "lit")
    rep = {"tag": tag, "source": path, "import": how, "objects": names, "anatomy": an, "health": health,
           "measure": m, "weapon_type": wt or guess[0], "type_guess": guess, "style": st,
           "checks": [list(c) for c in C], "fails": sum(1 for c in C if c[2] == "FAIL"), "reviews": sum(1 for c in C if c[2] == "REVIEW"),
           "renders": {"geometry": geo, "lit": lit}, "seconds": round(_t.time() - t0, 1)}
    json.dump(rep, open(os.path.join(out, "candidate.json"), "w"), indent=2, default=str)
    ledger("candidate", project=P.name, tag=tag, source=os.path.basename(path), tris=health["tris"], fails=rep["fails"],
           reviews=rep["reviews"], mass_kg=m.get("mass_kg"), overall_m=m.get("overall_m"))
    return {k: rep[k] for k in ("tag", "fails", "reviews", "seconds")}


def candidates_compare(project, tags, views=("full_front", "guard_center", "guard_left", "junction", "blade_mid", "pommel")):
    """one table and one picture grid (rows = views, columns = candidates, same cameras). No automatic winner: the
    numbers and pictures are the evidence for the person (or the AI) who chooses."""
    P = _proj(project); d = P.gate_dir("s0_candidates"); R = {}
    for t in tags: R[t] = json.load(open(os.path.join(P.gate_dir("s0_candidates", t), "candidate.json")))
    keys = [("tris", lambda r: r["health"]["tris"]), ("objects", lambda r: r["health"]["objects"]),
            ("open edges", lambda r: r["health"]["open_edges"]), ("non-manifold edges", lambda r: r["health"]["nonmanifold_edges"]),
            ("degenerate tris", lambda r: r["health"]["degenerate_tris"]), ("seam-split verts (welded)", lambda r: r["health"]["duplicate_vertices"]),
            ("mirror deviation p50 / p95 mm", lambda r: f"{r['health']['mirror_x_mm']['p50']} / {r['health']['mirror_x_mm']['p95']}"),
            ("dihedral p50 / p90 deg (noise)", lambda r: f"{r['health']['dihedral_deg']['p50']} / {r['health']['dihedral_deg']['p90']}"),
            ("textures", lambda r: "; ".join(r["health"]["textures"]) or "none")]
    mk = ["overall_m", "blade_m", "grip_m", "guard_width_m", "pommel_m", "thickness_m", "blade_section_mm2_median", "mass_kg", "pob_from_guard_m", "watertight"]
    L_ = ["| | " + " | ".join(tags) + " |", "|---|" + "---|" * len(tags)]
    for k, f in keys: L_.append(f"| {k} | " + " | ".join(str(f(R[t])) for t in tags) + " |")
    for k in mk: L_.append(f"| {k} | " + " | ".join(str(R[t]["measure"].get(k)) for t in tags) + " |")
    for c in [c[0] for c in R[tags[0]]["checks"]]:
        L_.append(f"| check {c} | " + " | ".join(next((f"{x[2]} ({x[1]})" for x in R[t]["checks"] if x[0] == c), "-") for t in tags) + " |")
    L_.append("| FAIL / REVIEW | " + " | ".join(f"{R[t]['fails']} / {R[t]['reviews']}" for t in tags) + " |")
    open(os.path.join(d, "candidates.md"), "w", encoding="utf-8").write("\n".join(L_))
    rows = []
    for v in views:
        ims = [_load(os.path.join(P.gate_dir("s0_candidates", t), f"geo_{v}.png"))[::2, ::2] for t in tags]
        h = min(i.shape[0] for i in ims); sep = np.ones((h, 6, 4), np.float32)
        r_ = ims[0][:h]
        for i in ims[1:]: r_ = np.concatenate([r_, sep, i[:h]], 1)
        rows.append(r_)
    wmax = max(r_.shape[1] for r_ in rows)
    S = np.concatenate([np.pad(r_, ((0, 6), (0, wmax - r_.shape[1]), (0, 0)), constant_values=1.0) for r_ in rows][::-1], 0)
    sheet = os.path.join(d, "candidates_geometry.png")
    im = bpy.data.images.new("FORGE_cand", S.shape[1], S.shape[0], alpha=True); im.pixels.foreach_set(S.ravel())
    im.filepath_raw = sheet; im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)
    json.dump({"tags": tags, "table": os.path.join(d, "candidates.md"), "sheet": sheet}, open(os.path.join(d, "candidates.json"), "w"), indent=2)
    ledger("candidates_compare", project=P.name, tags=list(tags))
    return {"table": os.path.join(d, "candidates.md"), "sheet": sheet}


def disconnected_materials(names):
    """materials of the given objects whose active output has no Surface link (a bake bug left these behind)."""
    bad = []
    for n in names:
        for s_ in bpy.data.objects[n].material_slots:
            m = s_.material
            if not m or not m.use_nodes: continue
            out = next((x for x in m.node_tree.nodes if x.type == "OUTPUT_MATERIAL" and x.is_active_output), None)
            if out is None or not out.inputs["Surface"].is_linked: bad.append(m.name)
    return sorted(set(bad))


def repair_disconnected_materials(project):
    """reconnect Principled BSDF -> Material Output where the link was lost; remove stray BAKE_tmp nodes."""
    P = _proj(project); fixed = []
    for mname in disconnected_materials(_highs(P)):
        m = bpy.data.materials[mname]; nt = m.node_tree
        for x in [x for x in nt.nodes if x.name.startswith("BAKE_tmp")]: nt.nodes.remove(x)
        out = next((x for x in nt.nodes if x.type == "OUTPUT_MATERIAL" and x.is_active_output), None)
        bs = next((x for x in nt.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if out and bs: nt.links.new(bs.outputs[0], out.inputs["Surface"]); fixed.append(mname)
    ledger("repair", project=P.name, what="material outputs", fixed=fixed)
    return {"fixed": fixed, "still_bad": disconnected_materials(_highs(P))}


# ======================================================================= s1 high-poly checks
def s1_highpoly(project, noise_review=True):
    """checks the AI mesh; cleanup itself is a REVIEW-driven step (remesh/smooth/symmetrise as needed)."""
    P = _proj(project); P.require("s0_intake"); G = Gate("s1_highpoly")
    if not P.state["settings"].get("legacy_no_spec"): P.require("s0_spec")     # a usable weapon of its type first
    hc = P.cfg.get("high_cleanup", {})                  # 1.5.0: voxel clean-up is the default for NEW projects (first s1)
    if hc.get("method") == "voxel" and "s1_highpoly" not in P.state["stages"] and not P.state["settings"].get("high_cleanup") \
            and not P.state["settings"].get("no_high_cleanup"):
        G.data["voxel_cleanup"] = voxel_cleanup(project); P = _proj(project)
    vc_ = P.state["settings"].get("high_cleanup") or {}
    if isinstance(vc_, dict) and vc_.get("lost_surface_pct") is not None:      # 1.6.0: did the voxel rebuild drop parts?
        lp_ = vc_["lost_surface_pct"]
        G.check("cleanup_kept_shape", lp_, lp_ <= 0.5, review=lp_ <= 5.0,
                msg="% of the original surface more than 4 voxels from the rebuilt one (hidden inner faces count): "
                    "above 5 % a part is missing - open mesh? close it, or set settings no_high_cleanup")
    tot_tris = 0; nm = 0; bd = 0; loose = 0
    for n in _highs(P):
        co, tv, _, _, _ = tri_arrays(n); et = edge_faces(tv)
        tot_tris += len(tv); nm += et["n_nonmanifold"]; bd += et["n_boundary"]
        ob = bpy.data.objects[n]
        if any(abs(s - 1) > 1e-6 for s in ob.scale) or any(abs(r) > 1e-6 for r in ob.rotation_euler): G.notes.append(f"{n}: unapplied transform")
    G.check("nonmanifold_edges", nm, nm == 0, review=nm < 50, msg="edges shared by >2 faces")
    G.check("open_edges", bd, bd == 0, review=True, msg="holes are fine only if hidden (inside the guard)")
    G.check("high_tris", tot_tris, tot_tris > 50000, review=True, msg="too few tris -> nothing to bake")
    bad = disconnected_materials(_highs(P))
    G.check("materials_connected", bad, not bad, msg="a material with no Surface link bakes black (repair_disconnected_materials)")
    dc = design_check(project); G.data["design_check"] = dc
    G.check("design_unchanged", dc.get("max_mm", dc["status"]), dc["status"] == "PASS", review=dc["status"] == "NO_BASELINE",
            msg="the shape must equal the intake design (only one uniform size factor allowed); else restore_positions")
    if noise_review:
        G.need_review("surface", "close-ups: no noise, no dotted/beaded ridges, symmetric, no melted details (AI artefacts)")
    views = [v for v in inspection_views(P.state["anatomy"]) if not _vin(v[0], ("full_back",))]
    G.images += [{"path": p, "caption": "high (workbench)"} for p in render_views(set(_highs(P)), views, P.p("renders", "s1"), "high", engine="WORKBENCH")]
    return P.finish("s1_highpoly", G)


# ======================================================================= s2 low-poly
_SYM_CACHE = {}


def _mesh_tris(me):
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
    tv = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv)
    return co.reshape(-1, 3), tv.reshape(-1, 3)


def _decide_symmetry(me, mode="auto", tol_rel=0.0005):
    """X-symmetric decimation only when the mesh really is mirror-symmetric about x=0 (2026-10-29 benchmark: on
    non-symmetric swords it changed nothing on 2 models and made the third worse, max deviation 0.38 -> 0.83 mm)."""
    if mode in (True, "on"): return True, {"mode": "on"}
    if mode in (False, "off"): return False, {"mode": "off"}
    co, tv = _mesh_tris(me); L = float((co.max(0) - co.min(0)).max())
    key = (len(co), len(tv), round(float(co.sum()), 5))
    if key not in _SYM_CACHE:
        m = mirror_symmetry(co, tv); _SYM_CACHE[key] = (bool(m["p99"] <= tol_rel * L),
            {"mode": "auto", "mirror_p99_mm": round(m["p99"] * 1000, 3), "limit_mm": round(tol_rel * L * 1000, 3)})
    sym, info = _SYM_CACHE[key]; return sym, dict(info, symmetric=sym)


def _decimate_copy(P, target, name):
    """merge the high-poly objects, decimate them to `target` triangles (X-symmetric). Objects listed in
    settings.keep_whole (e.g. a clean gem made by add_gem) are not decimated: they are appended unchanged."""
    keep = set(P.state["settings"].get("keep_whole", []))
    highs = [bpy.data.objects[n] for n in _highs(P) if n not in keep]
    kept = [bpy.data.objects[n] for n in _highs(P) if n in keep]
    old = bpy.data.objects.get(name)
    if old: me = old.data; bpy.data.objects.remove(old); bpy.data.meshes.remove(me)
    dg = bpy.context.evaluated_depsgraph_get(); meshes = []
    import bmesh
    bm = bmesh.new()
    for h in highs:
        tmp = h.evaluated_get(dg).to_mesh(); tmp.transform(h.matrix_world); bm.from_mesh(tmp); h.evaluated_get(dg).to_mesh_clear()
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    # the high's UV layers and custom normals are garbage after decimation (and the inherited UVMap broke the
    # preview bake, 2026-10-29): s3 makes UV_game from scratch
    for u in list(me.uv_layers): me.uv_layers.remove(u)
    if me.has_custom_normals: me.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(me.loops))
    for an_ in ("sharp_edge", "sharp_face"):
        if me.attributes.get(an_) is not None: me.attributes.remove(me.attributes[an_])
    keep_tris = sum(len(p.vertices) - 2 for k in kept for p in k.data.polygons)
    target = max(target - keep_tris, 100)
    ob = bpy.data.objects.new(name, me)
    coll = bpy.data.collections.get("FORGE_low") or bpy.data.collections.new("FORGE_low")
    if coll.name not in bpy.context.scene.collection.children: bpy.context.scene.collection.children.link(coll)
    coll.objects.link(ob)
    tri0 = sum(len(p.vertices) - 2 for p in me.polygons)
    mod = ob.modifiers.new("dec", "DECIMATE"); mod.decimate_type = "COLLAPSE"; mod.ratio = min(1.0, target / max(tri0, 1))
    sym, sinfo = _decide_symmetry(me, P.cfg.get("lowpoly", {}).get("symmetry", "auto")); ob["forge_symmetry"] = json.dumps(sinfo)
    mod.use_symmetry = sym; mod.symmetry_axis = "X"; mod.use_collapse_triangulate = True
    bpy.ops.object.select_all(action="DESELECT"); ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)
    if kept:
        bm = bmesh.new(); bm.from_mesh(ob.data)
        for k in kept:
            tmp = k.evaluated_get(dg).to_mesh(); tmp.transform(k.matrix_world); bm.from_mesh(tmp); k.evaluated_get(dg).to_mesh_clear()
        bm.to_mesh(ob.data); bm.free(); ob.data.update()
    return ob


REGIONAL_SHARES = {"gem": 0.075, "guard": 0.29, "grip": 0.19, "pommel": 0.18, "blade": 0.265}


def regional_decimate(ob, target, anatomy, zones=(), shares=None, symmetry="auto", passes=2):
    """decimate each anatomical region with its own triangle budget (edit mode, selected faces only; region borders stay
    connected). Small curved parts (grip bands, pommel insets) get more triangles than a uniform collapse gives them.
    2026-10-29 benchmark (3 swords, 49k): grip/pommel normal error p95 -10..-17 %, global deviation p99 +2..+25 %.
    At 18k it starves the gem: only for budgets >= lowpoly.regional_min_tris."""
    shares = dict(shares or REGIONAL_SHARES); an = anatomy
    names = [k for k in ("gem", "guard", "grip", "pommel", "blade") if k in shares and (k != "gem" or zones)]
    tot_share = sum(shares[k] for k in names); budget = {k: target * shares[k] / tot_share for k in names}
    src = ob.data.copy(); sym = _decide_symmetry(ob.data, symmetry)[0]; scale = 1.0; hist = []
    bpy.ops.object.select_all(action="DESELECT"); ob.select_set(True); bpy.context.view_layer.objects.active = ob
    for it in range(passes):
        if it: old = ob.data; ob.data = src.copy(); bpy.data.meshes.remove(old)
        for k in names:
            me = ob.data; npo = len(me.polygons); M = np.array(ob.matrix_world)
            cen = np.empty(npo * 3); me.polygons.foreach_get("center", cen); cen = cen.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
            z = cen[:, 2]; gem = np.zeros(npo, bool)
            for x, y, zz, r in (zones or ()): gem |= np.linalg.norm(cen - np.array([x, y, zz]), axis=1) < r
            lab = np.where(z < an["guard_z0"], 4, np.where(z < an["guard_z1"], 1, np.where(z < an["grip_z1"], 2, 3)))
            lab[gem] = 0; sel = lab == ["gem", "guard", "grip", "pommel", "blade"].index(k)
            lt = np.empty(npo, np.int64); me.polygons.foreach_get("loop_total", lt); cnt = int((lt[sel] - 2).sum())
            if cnt == 0: continue
            lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
            vsel = np.zeros(len(me.vertices), bool); vsel[lv[np.repeat(sel, lt)]] = True
            ev = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
            me.polygons.foreach_set("select", sel); me.vertices.foreach_set("select", vsel); me.edges.foreach_set("select", vsel[ev[:, 0]] & vsel[ev[:, 1]])
            bpy.ops.object.mode_set(mode="EDIT"); bpy.context.tool_settings.mesh_select_mode = (False, False, True)
            bpy.ops.mesh.decimate(ratio=min(1.0, budget[k] * scale / cnt), use_symmetry=sym, symmetry_axis="X")
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT"); bpy.ops.mesh.quads_convert_to_tris(); bpy.ops.object.mode_set(mode="OBJECT")
        n = len(ob.data.polygons); hist.append({"pass": it, "tris": n, "scale": round(scale, 4)})
        if abs(n - target) / target < 0.01: break
        scale *= target / n
    bpy.data.meshes.remove(src)
    return {"symmetry": sym, "budget": {k: int(v) for k, v in budget.items()}, "passes": hist}


def _regional_copy(P, target, name):
    """joined high copy (same as _decimate_copy, keep_whole objects appended unchanged) -> regional_decimate."""
    keep = set(P.state["settings"].get("keep_whole", []))
    kept_tris = sum(len(p.vertices) - 2 for n in _highs(P) if n in keep for p in bpy.data.objects[n].data.polygons)
    ob = _decimate_copy(P, 10 ** 12, name)          # ratio 1.0: join + transform only, no decimation
    info = regional_decimate(ob, max(target - kept_tris, 100), P.state["anatomy"], P.state["settings"].get("protect_zones") or (),
                             P.cfg.get("lowpoly", {}).get("regional_shares"), P.cfg.get("lowpoly", {}).get("symmetry", "auto"))
    ob["forge_regional"] = json.dumps(info); return ob


def _region_normal_p95(P, name, bvh):
    """area-weighted p95 of the angle between each low-poly face normal and the nearest high-poly normal, per region
    (blade, guard, gem, grip, pommel). Catches small curved parts starved of triangles, which the global deviation
    limit lets through (2026-10-29: a gem at 45 deg / 7 mm max passed s2 with p99 1.2 mm)."""
    import mathutils
    co, tv, *_ = tri_arrays(name); a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
    n = np.cross(b - a, c - a); ar = np.linalg.norm(n, axis=1); n = n / np.maximum(ar[:, None], 1e-20); cen = (a + b + c) / 3
    ang = np.empty(len(tv))
    for i, p in enumerate(cen):
        loc, nh, _, _ = bvh.find_nearest(mathutils.Vector(p))
        ang[i] = 90.0 if loc is None else math.degrees(math.acos(min(1.0, abs(float(np.dot(n[i], np.array(nh)))))))
    an = P.state.get("anatomy", {})
    if not all(k in an for k in ("guard_z0", "guard_z1", "grip_z0", "grip_z1")): return {}
    R = uv_regions(co, tv, an, zones=P.state["settings"].get("protect_zones") or ()); out = {}
    for k, m in R.items():
        if k == "edges" or not m.any(): continue
        s_ = np.argsort(ang[m]); w = ar[m][s_]; cw = np.cumsum(w) / w.sum()
        out[k] = round(float(ang[m][s_][min(int(np.searchsorted(cw, 0.95)), int(m.sum()) - 1)]), 2)
    return out


# ======================================================================= look gate (2026-10-29)
# A game low poly is "not distorted" when, WITH its baked normal map, it looks like the high poly from the same cameras
# and light, and its silhouette matches. Geometry keeps silhouette and big forms; the normal map carries fine relief.
USE_PROFILES = {   # LOD0 triangle budgets by intended use (s0). candidates: what s2_auto builds and compares
    "fab_pc":   {"budget": [16000, 30000], "candidates": [16000, 22000, 30000], "texture": 4096},
    "showcase": {"budget": [30000, 50000], "candidates": [30000, 40000, 50000], "texture": 4096},
    "mobile":   {"budget": [3000, 8000], "candidates": [3000, 5000, 8000], "texture": 2048}}
LOOK_VIEWS = ("full_front", "tip", "blade_mid", "junction", "guard_center", "guard_left", "guard_right", "grip", "pommel")
LOOK_GREY = (0.55, 0.55, 0.57, 1.0)


def set_target_use(project, use):
    """s0: choose the intended use; writes the LOD0 budget and the s2 candidates for this project (cfg_override)."""
    if use not in USE_PROFILES: raise ValueError(f"target use must be one of {list(USE_PROFILES)}")
    P = _proj(project); u = USE_PROFILES[use]; cat = P.cfg["category"]; lod = list(P.cfg["budgets"][cat][2:4])
    ov = P.state["settings"].setdefault("cfg_override", {})
    ov.setdefault("budgets", {})[cat] = [u["budget"][0], u["budget"][1]] + lod
    ov.setdefault("lowpoly", {})["candidates"] = list(u["candidates"]); P.state["settings"]["target_use"] = use; P.save()
    return {"use": use, "budget": ov["budgets"][cat], "candidates": u["candidates"]}


def _look_grey_mat(name, normal_img=None, uv_name=None):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n in list(nt.nodes):
        if n.type not in ("OUTPUT_MATERIAL", "BSDF_PRINCIPLED"): nt.nodes.remove(n)
    bs = [n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"][0]
    bs.inputs["Base Color"].default_value = LOOK_GREY; bs.inputs["Roughness"].default_value = 0.42; bs.inputs["Metallic"].default_value = 0.0
    if normal_img is not None:
        tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = normal_img; normal_img.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap"); nm.uv_map = uv_name or ""
        nt.links.new(tx.outputs["Color"], nm.inputs["Color"]); nt.links.new(nm.outputs["Normal"], bs.inputs["Normal"])
    return m


def look_preview_bake(low_name, high_names, L, size=1024, uv_name="UV_preview", cage_rel=0.0015, ray_rel=0.005):
    """quick tangent normal bake for judging a candidate before s3: smart-UV (own layer), ALL faces smooth (hard
    edges at preview seams made dark lines, 2026-10-29), small cage, normals from geometry (high normal maps unlinked)."""
    low = bpy.data.objects[low_name]; highs = [bpy.data.objects[n] for n in high_names]; sc = bpy.context.scene
    if bpy.context.object and bpy.context.object.mode != "OBJECT": bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()            # a just-created collection (FORGE_low) is not in the view layer yet
    low.hide_set(False); bpy.ops.object.select_all(action="DESELECT"); low.select_set(True); bpy.context.view_layer.objects.active = low
    if bpy.context.view_layer.objects.active != low:
        raise RuntimeError(f"look_preview_bake: could not make {low_name} active (edit-mode unwrap would hit another object)")
    pa = low.data.uv_layers.active; prev_active = pa.name if pa else None        # names: layer references dangle after .new()
    prev_render = next((u.name for u in low.data.uv_layers if u.active_render), None)
    uv = low.data.uv_layers.get(uv_name) or low.data.uv_layers.new(name=uv_name); uv = low.data.uv_layers[uv_name]
    low.data.uv_layers.active = uv; uv.active_render = True      # the bake uses the RENDER uv: a decimated copy carries the high's UVMap
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004); bpy.ops.object.mode_set(mode="OBJECT")
    uvc = np.empty(len(low.data.loops) * 2, np.float32); low.data.uv_layers[uv_name].data.foreach_get("uv", uvc)
    if float(uvc.max() - uvc.min()) < 0.5: raise RuntimeError(f"look_preview_bake: UV unwrap of {low_name} is empty")
    for p_ in low.data.polygons: p_.use_smooth = True
    for an_ in ("sharp_edge", "sharp_face"):  # decimated copies inherit the high's sharp edges -> hard patches in the preview
        if low.data.attributes.get(an_) is not None: low.data.attributes.remove(low.data.attributes[an_])
    if low.data.has_custom_normals:          # ... and its custom normals as garbage
        with bpy.context.temp_override(object=low, active_object=low, selected_objects=[low], selected_editable_objects=[low]):
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
    img = bpy.data.images.get(low_name + "_PREVIEW_N")
    if img: bpy.data.images.remove(img)
    img = bpy.data.images.new(low_name + "_PREVIEW_N", size, size); img.colorspace_settings.name = "Non-Color"
    saved = [s_.material for s_ in low.material_slots]
    m = bpy.data.materials.new("FORGE_preview_bake"); m.use_nodes = True; tx = m.node_tree.nodes.new("ShaderNodeTexImage"); tx.image = img
    m.node_tree.nodes.active = tx; low.data.materials.clear(); low.data.materials.append(m)
    prev = (sc.render.engine, sc.cycles.samples, sc.cycles.device); sc.render.engine = "CYCLES"; sc.cycles.samples = 1; sc.cycles.device = "CPU"
    bk = sc.render.bake; bk.use_selected_to_active = True; bk.cage_extrusion = cage_rel * L; bk.max_ray_distance = ray_rel * L; bk.margin = 16
    try: bk.margin_type = "ADJACENT_FACES"
    except Exception: pass
    cut = _unlink_normal_maps(highs)
    for o in highs + [low]: o.hide_render = False; o.hide_set(False)
    for o in highs: o.select_set(True)
    low.select_set(True); bpy.context.view_layer.objects.active = low
    low.data.update(); bpy.context.view_layer.update()      # the bake reads the evaluated mesh: refresh it after the edits above
    t = time.time()
    try: bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")
    finally:
        _relink(cut); sc.render.engine, sc.cycles.samples, sc.cycles.device = prev
    img.use_fake_user = True; img.pack()        # keep the baked pixels: an unused generated image is regenerated blank
    low.data.materials.clear()
    for mm in saved: low.data.materials.append(mm)
    bpy.data.materials.remove(m); uvs = low.data.uv_layers
    uvs.active = uvs[prev_active] if (prev_active and prev_active in uvs) else uvs[uv_name]
    if prev_render and prev_render != uv_name and prev_render in uvs: uvs[prev_render].active_render = True
    return {"image": img.name, "uv": uv_name, "size": size, "seconds": round(time.time() - t, 1)}


def look_compare(anatomy, high_names, low_name, out_dir, tag, normal_img, uv_name, views=LOOK_VIEWS, res=(800, 450)):
    """render high (grey) and low (grey + normal map) from the inspection cameras with the same light; per view:
    silhouette IoU and the luminance difference inside the shared mask (mean, p95)."""
    os.makedirs(out_dir, exist_ok=True); low = bpy.data.objects[low_name]
    V = [v for v in inspection_views(anatomy) if _vin(v[0], views)]
    sc = _inspect_scene(); prev = (sc.render.film_transparent, sc.view_settings.exposure, sc.render.image_settings.color_depth)
    sc.render.film_transparent = True; sc.view_settings.exposure = -1.3; sc.render.image_settings.color_depth = "16"   # 8-bit steps hid the differences
    grey = _look_grey_mat("FORGE_look_grey"); lowm = _look_grey_mat("FORGE_look_low_" + low_name, bpy.data.images[normal_img], uv_name)
    saved = [s_.material for s_ in low.material_slots]; low.data.materials.clear(); low.data.materials.append(lowm)
    # the high gets the same grey by swapping its slot materials (a view-layer override does not reach objects
    # without material slots: the high rendered with Blender's default surface, 0.79 vs 0.54 brightness)
    hsaved = []
    for n in high_names:
        o = bpy.data.objects[n]; hsaved.append((o, [s_.material for s_ in o.material_slots], len(o.material_slots)))
        if not o.material_slots: o.data.materials.append(grey)
        for s_ in o.material_slots: s_.material = grey
    try:
        hp = render_views(set(high_names), V, out_dir, "high", res=res, samples=16)
        lp = render_views({low_name}, V, out_dir, tag, res=res, samples=16)
    finally:
        low.data.materials.clear()
        for mm in saved: low.data.materials.append(mm)
        for o, mats, n0 in hsaved:
            if n0 == 0: o.data.materials.clear()
            else:
                for s_, mm in zip(o.material_slots, mats): s_.material = mm
        sc.render.film_transparent, sc.view_settings.exposure, sc.render.image_settings.color_depth = prev
    out = {}; w = np.array([0.2126, 0.7152, 0.0722])
    for v, a, b in zip(V, hp, lp):
        A = _load(a); Bm = _load(b); ma = A[..., 3] > 0.5; mb = Bm[..., 3] > 0.5; both = ma & mb
        d = np.abs(A[..., :3] @ w - Bm[..., :3] @ w)[both]
        out[v[0]] = {"iou": round(float(both.sum() / max((ma | mb).sum(), 1)), 4),
                     "dL_mean": round(float(d.mean()) if d.size else 1.0, 4), "dL_p95": round(float(np.percentile(d, 95)) if d.size else 1.0, 4)}
    worst_d = max(out.items(), key=lambda kv: kv[1]["dL_p95"]); worst_i = min(out.items(), key=lambda kv: kv[1]["iou"])
    sheet = compare_sheet(hp, lp, os.path.join(out_dir, f"sheet_high_vs_{tag}.png"))
    return {"views": out, "worst_dL_p95": [worst_d[0], worst_d[1]["dL_p95"]], "min_iou": [worst_i[0], worst_i[1]["iou"]], "sheet": sheet}


def _look_for(P, name, tag, size=1024):
    """preview bake + look_compare for one low poly of a project; removes the preview UV afterwards."""
    L = _L(P); b = look_preview_bake(name, _highs(P), L, size=size)
    r = look_compare(P.state["anatomy"], _highs(P), name, P.gate_dir("s2_lowpoly", "look"), tag, b["image"], b["uv"])
    me = bpy.data.objects[name].data; uvp = me.uv_layers.get(b["uv"])
    if uvp is not None: me.uv_layers.remove(uvp)          # preview UV never reaches s3/export
    r["bake"] = b; return r


def _look_reference(P):
    """a dense reference low poly (lowpoly.look_ref_tris, default 120k) with the same preview bake: its difference to
    the high is the render floor (AO noise, specular), so candidates are judged by the EXCESS over it. Cached per
    project (key = high triangle count)."""
    th = P.cfg["lowpoly"]; key = str(sum(len(p.vertices) - 2 for n in _highs(P) for p in bpy.data.objects[n].data.polygons))
    cams = json.dumps([[v[0]] + [round(x, 5) for x in v[1]] for v in inspection_views(P.state["anatomy"])])
    c = P.state["settings"].get("look_ref")
    if c and c.get("key") == key and c.get("version") == 7 and c.get("cams", cams) == cams: return c["views"]
    name = _asset(P) + "_look_ref"; ob = _decimate_copy(P, th.get("look_ref_tris", 120000), name)
    r = _look_for(P, name, "reference"); me = ob.data; bpy.data.objects.remove(ob); bpy.data.meshes.remove(me)
    P.state["settings"]["look_ref"] = {"key": key, "version": 7, "cams": cams, "views": r["views"]}; P.save()
    return r["views"]


def _look_excess(look, ref):
    ex = {v: round(look["views"][v]["dL_p95"] - ref.get(v, {}).get("dL_p95", 0.0), 4) for v in look["views"]}
    w = max(ex.items(), key=lambda kv: kv[1]); return w, ex


def _look_status(look, th, ref=None):
    emax, imin = th.get("look_excess_p95_max", 0.010), th.get("look_iou_min", 0.988)   # calibrated 2026-10-29 on 3 swords x 8 candidates
    worst, ex = _look_excess(look, ref or {}); ok_e = worst[1] <= emax; ok_i = look["min_iou"][1] >= imin
    return ok_e and ok_i, {"excess_p95_max": emax, "iou_min": imin, "worst_excess": [worst[0], worst[1]], "excess": ex}


def s2_auto(project, candidates=None, method=None):
    """build LOD0 candidates (budgets from the target use), judge each WITH a preview normal bake (look gate) and by
    geometry (deviation, per-region normals); keep the smallest candidate that passes and gate it with s2_lowpoly."""
    P = _proj(project); P.require("s1_highpoly"); th = P.cfg["lowpoly"]; asset = _asset(P)
    cands = sorted(candidates or th.get("candidates") or USE_PROFILES["fab_pc"]["candidates"])
    bvh, _, _ = bvh_of(_highs(P)); rep = []; chosen = None; ref = _look_reference(P)
    for t in cands:
        name = f"{asset}_cand_auto_{t // 1000}k"
        meth = method or th.get("method", "uniform")
        ob = _regional_copy(P, t, name) if (meth == "regional" and t >= th.get("regional_min_tris", 45000)) else \
            (_qem_copy(P, t, name) if meth == "qem" else _decimate_copy(P, t, name))
        dev, _ = deviation(name, _highs(P), n=20000); rn = _region_normal_p95(P, name, bvh); lk = _look_for(P, name, f"cand_{t // 1000}k")
        ok_look, lim = _look_status(lk, th, ref); ok_geo = (not rn) or max(rn.values()) <= th.get("region_normal_p95_fail", 20.0)
        r = {"budget": t, "tris": len(ob.data.polygons), "dev_p99_mm": round(dev["low_to_high"]["p99"] * 1000, 3), "region_p95": rn,
             "look": {"worst_excess": lim["worst_excess"], "min_iou": lk["min_iou"], "sheet": lk["sheet"]}, "pass": bool(ok_look and ok_geo)}
        rep.append(r); ob.hide_set(True); ob.hide_render = True
        if r["pass"] and chosen is None: chosen = name
    json.dump(rep, open(os.path.join(P.gate_dir("s2_lowpoly"), "auto_candidates.json"), "w"), indent=2, default=str)
    if chosen is None: chosen = f"{asset}_cand_auto_{cands[-1] // 1000}k"     # none passed: gate the largest, the gate will say why
    old = bpy.data.objects.get(asset + "_LOD0")
    if old: old.name = asset + "_LOD0_prev"; old.hide_set(True); old.hide_render = True
    bpy.data.objects[chosen].hide_set(False); bpy.data.objects[chosen].hide_render = False
    res = s2_lowpoly(project, existing=chosen); res["auto_candidates"] = rep; res["auto_chosen"] = chosen
    return res


def s2_lowpoly(project, target=None, max_iter=4, step=1.3, existing=None, method=None):
    """decimate -> fold repair -> gates; raises the budget until the geometry gate passes.
    existing=<object>: gate an existing low-poly instead of making one.
    method: "uniform" (default, lowpoly.method) or "regional" (per-region budgets, only for target >= lowpoly.regional_min_tris)."""
    P = _proj(project); P.require("s1_highpoly"); cfg = P.cfg; G = Gate("s2_lowpoly")
    method = method or cfg.get("lowpoly", {}).get("method", "uniform"); rmin = cfg.get("lowpoly", {}).get("regional_min_tris", 45000)
    b0, bmax = cfg["budgets"][cfg["category"]][:2]; target = target or b0
    name = _asset(P) + "_LOD0"; L = _L(P); th = cfg["lowpoly"]
    bvh, _, _ = bvh_of(_highs(P)); hist = []
    for it in range(max_iter):
        if existing:
            if existing != name: bpy.data.objects[existing].name = name
            ob = bpy.data.objects[name]
        elif method == "regional":
            if target < rmin: raise ValueError(f"regional decimation needs >= {rmin} tris (got {target}): below that it starves small parts")
            ob = _regional_copy(P, target, name)
        elif method == "qem":
            ob = _qem_copy(P, target, name)
        else:
            ob = _decimate_copy(P, target, name)
        co, tv, _, _, _ = tri_arrays(name)
        tv2, flips = fold_repair(co, tv, bvh, z_skip=None)
        tv2, dups = drop_duplicate_faces(tv2)
        co2, tv2, fins, _ = merge_tiny_nonmanifold_edges(co, tv2, th.get("fin_merge_max_rel", 0.001) * L)   # 1.4.9
        if flips or dups or fins: replace_mesh(name, co2, tv2)
        co, tv, _, _, _ = tri_arrays(name)
        ang, conc, et = dihedral(co, tv)
        folds = int(((ang > 150) & conc).sum()); fold_rel = folds / max(et["n_edges"], 1)
        mina = min_angles(co, tv); slivers = int((mina < th["min_angle_deg"]).sum())
        dev, per_tri = deviation(name, _highs(P), n=30000)
        ok_dev = dev["low_to_high"]["p99"] <= th["dev_p99_rel"] * L and dev["high_to_low"]["p99"] <= 2 * th["dev_p99_rel"] * L
        ok_fold = fold_rel <= th["folds_max_rel"]
        hist.append({"tris": len(tv), "folds": folds, "flips": flips, "duplicate_faces_removed": dups, "tiny_nonmanifold_merged": fins, "dev": dev, "slivers": slivers})
        if (ok_dev and ok_fold) or existing or target >= bmax: break
        target = min(int(target * step), bmax)
    G.data["iterations"] = hist
    # standard surface metrics (sampled, both directions): Hausdorff = worst distance, Chamfer = mean distance
    G.data["hausdorff_mm"] = round(max(dev["low_to_high"]["max"], dev["high_to_low"]["max"]) * 1000, 3)
    G.data["chamfer_mean_mm"] = round((dev["low_to_high"]["mean"] + dev["high_to_low"]["mean"]) / 2 * 1000, 4)
    G.check("tris", len(tv), len(tv) <= bmax, msg=f"budget max {bmax}")
    G.check("concave_folds", folds, ok_fold, review=fold_rel < 3 * th["folds_max_rel"], msg="fold > 150 deg = crumpled shading")
    G.check("dev_low_to_high_p99_mm", round(dev["low_to_high"]["p99"] * 1000, 2), dev["low_to_high"]["p99"] <= th["dev_p99_rel"] * L,
            review=True, msg=f"limit {th['dev_p99_rel'] * L * 1000:.2f} mm")
    G.check("dev_high_to_low_p99_mm", round(dev["high_to_low"]["p99"] * 1000, 2), dev["high_to_low"]["p99"] <= 2 * th["dev_p99_rel"] * L,
            review=True, msg="lost silhouette/detail")
    G.check("slivers", slivers, slivers < 0.02 * len(tv), review=True, msg=f"min angle < {th['min_angle_deg']} deg")
    G.check("nonmanifold", et["n_nonmanifold"], et["n_nonmanifold"] == 0)
    G.check("inconsistent_winding", et.get("n_inconsistent_winding", 0), et.get("n_inconsistent_winding", 0) == 0,
            msg="the two faces of an edge must wind opposite ways (flipped patch)")
    rne = _region_normal_p95(P, name, bvh)
    if rne:
        wk, wv = max(rne.items(), key=lambda kv: kv[1]); lr, lf = th.get("region_normal_p95_review", 13.0), th.get("region_normal_p95_fail", 20.0)
        G.check("region_normal_p95_deg", rne, wv <= lr, review=wv <= lf,
                msg=f"worst {wk} {wv:.1f} deg (review > {lr}, fail > {lf}): small curved parts starved of triangles")
    if th.get("look_gate", True):
        ref = _look_reference(P); lk = _look_for(P, name, "lod0"); ok_l, lim = _look_status(lk, th, ref); G.data["look"] = dict(lk, excess=lim["excess"])
        G.check("look_excess_p95", lim["worst_excess"], lim["worst_excess"][1] <= lim["excess_p95_max"], review=lim["worst_excess"][1] <= 2 * lim["excess_p95_max"],
                msg=f"with a preview normal bake (1K): worst view luminance difference to the high ABOVE a dense reference (limit {lim['excess_p95_max']})")
        G.check("look_silhouette_iou", lk["min_iou"], lk["min_iou"][1] >= lim["iou_min"], review=lk["min_iou"][1] >= lim["iou_min"] - 0.01,
                msg=f"silhouette overlap high vs low, worst view (limit {lim['iou_min']})")
        G.image(lk["sheet"], "look gate: left high, right low WITH preview normal map", "comparison")
    if bpy.data.objects[name].get("forge_symmetry"): G.data["symmetry"] = json.loads(bpy.data.objects[name]["forge_symmetry"])
    G.data["method"] = "existing" if existing else method
    if bpy.data.objects[name].get("forge_regional"): G.data["regional"] = json.loads(bpy.data.objects[name]["forge_regional"])
    # ---- comparison: same camera/light, high vs low (flat), silhouettes, wireframe
    ob = bpy.data.objects[name]
    for p in ob.data.polygons: p.use_smooth = False
    views = [v for v in inspection_views(P.state["anatomy"]) if not _vin(v[0], ("full_back",))]
    cd = P.gate_dir("s2_lowpoly", "comparison"); dd = P.gate_dir("s2_lowpoly", "diagnostics")
    hi = render_views(set(_highs(P)), views, cd, "high", engine="WORKBENCH")
    lo = render_views({name}, views, cd, "low_flat", engine="WORKBENCH")
    G.image(compare_sheet(hi, lo, os.path.join(cd, "sheet_high_vs_lowflat.png")), "left high, right low (flat): shape and big forms", "comparison")
    sv = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], ("full_front", "full_back", "guard_center"))]
    hs = render_views(set(_highs(P)), sv, cd, "sil_high", engine="WORKBENCH", mode="silhouette")
    ls = render_views({name}, sv, cd, "sil_low", engine="WORKBENCH", mode="silhouette")
    G.image(compare_sheet(hs, ls, os.path.join(cd, "sheet_silhouette.png")), "silhouettes: edges, tips, notches must match", "comparison")
    wv = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], ("full_front", "guard_center", "junction"))]
    for p_ in render_views({name}, wv, cd, "wire_low", mode="wire"): G.image(p_, "low wireframe", "comparison")
    # ---- diagnostics: defects painted on the model
    dv = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], ("full_front", "full_back", "guard_center", "guard_left", "junction", "pommel"))]
    F = et["F"]; bad = np.zeros(len(tv), int)
    bad[F[(ang > 150) & conc].ravel()] = 2; bad[(mina < th["min_angle_deg"]) & (bad == 0)] = 1
    rgb = np.tile([0.6, 0.6, 0.62], (len(tv), 1)); rgb[bad == 2] = (1, 0, 0); rgb[bad == 1] = (1, 0.9, 0)
    paint_tris(name, rgb)
    for p_ in render_views({name}, dv, dd, "issues", engine="WORKBENCH", mode="attribute"):
        G.image(p_, "red = folds > 150 deg, yellow = slivers", "diagnostics")
    lim = th["dev_p99_rel"] * L
    paint_tris(name, heat(per_tri, lim))
    for p_ in render_views({name}, dv, dd, "deviation", engine="WORKBENCH", mode="attribute"):
        G.image(p_, f"deviation low->high: blue 0 .. red >= {lim * 1000:.1f} mm", "diagnostics")
    G.need_review("silhouette_and_shape", "comparison sheets: silhouette, notches, V-shapes, edge sharpness and big forms must match the high poly; numbers passing is not enough")
    P.checkpoint("s2_lowpoly")
    return P.finish("s2_lowpoly", G)


# ======================================================================= s0_spec: is it a usable weapon of its type?
def _spec_proxies(an, height, hands, hand_breadth):
    """temporary grey stand-ins: a simple 'character' of the given height beside the weapon, and hand blocks
    (hand breadth each) stacked on the grip from the guard. Removed after the renders."""
    made = []
    def box(name, size, loc):
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc); o = bpy.context.active_object; o.name = name
        o.scale = size; made.append(o.name); return o
    def cyl(name, r, d, loc):
        bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=d, location=loc, vertices=24); o = bpy.context.active_object
        o.name = name; made.append(o.name); return o
    H = height; x = an["axis_xy"][0] - 0.45 * H * 0.5 - 0.25; y = an["axis_xy"][1]
    cyl("FORGE_char_leg_l", 0.06 * H / 1.8, 0.47 * H, (x - 0.05 * H, y, 0.235 * H))
    cyl("FORGE_char_leg_r", 0.06 * H / 1.8, 0.47 * H, (x + 0.05 * H, y, 0.235 * H))
    box("FORGE_char_torso", (0.2 * H, 0.11 * H, 0.33 * H), (x, y, 0.47 * H + 0.165 * H))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.065 * H, location=(x, y, 0.87 * H)); o = bpy.context.active_object
    o.name = "FORGE_char_head"; made.append(o.name)
    cyl("FORGE_char_arm_l", 0.035 * H, 0.36 * H, (x - 0.13 * H, y, 0.62 * H))
    cyl("FORGE_char_arm_r", 0.035 * H, 0.36 * H, (x + 0.13 * H, y, 0.62 * H))
    hands_objs = []
    for k in range(hands):
        z0 = an["grip_z0"] + k * hand_breadth
        o = box(f"FORGE_hand_{k}", (0.09, 0.05, hand_breadth * 0.98), (an["axis_xy"][0], an["axis_xy"][1] - 0.035, z0 + hand_breadth / 2))
        hands_objs.append(o.name)
    return made, hands_objs


def _s0_spec_generic(P, size_m=None, character_height=None):
    """1.6.0 spec gate of a generic asset: real size and a render beside a character. Weapon measurements (blade,
    grip, mass, balance, hands) do not apply and are skipped."""
    G = Gate("s0_spec"); st = P.state["settings"]; prof = load_profiles(); an = P.state["anatomy"]
    if size_m: st["size_m"] = float(size_m)
    H = float(character_height or st.get("character_height_m") or prof["character"]["height_m"]); st["character_height_m"] = H; P.save()
    co, tv = _joined_world(list(_highs(P))); co = np.asarray(co, float); tv = np.asarray(tv)
    lo, hi = co.min(0), co.max(0); S = hi - lo; big = float(S.max()); et = edge_faces(tv)
    n_open = int(et["n_boundary"] + et["n_nonmanifold"])
    a, b, c_ = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]; vol = abs(float(np.einsum("ij,ij->i", a, np.cross(b, c_)).sum() / 6))
    G.check("asset_kind", "generic", True, msg="not a long weapon: blade / grip / mass / balance checks are skipped")
    G.check("size_m", [round(float(x), 4) for x in S], 0.005 < big < 100.0, msg="width x depth x height in metres")
    want = st.get("size_m")
    if want:
        r = big / want
        G.check("size_declared", round(r, 3), 0.9 <= r <= 1.1,
                msg=f"largest side {big:.3f} m / declared {want} m must be 0.9-1.1 (else uniform_fit('{P.name}', target_overall_m={want}))")
    else:
        G.check("size_declared", None, False, review=True,
                msg=f"largest side is {big:.3f} m: is that the real size? Declare it with s0_spec('{P.name}', size_m=...) to make this a measured check")
    G.check("volume_reliable", n_open, n_open == 0, review=True, msg="open / non-manifold edges (the voxel clean-up of s1 closes them)")
    G.data.update(kind="generic", measurements={"extent_m": [round(float(x), 4) for x in S], "largest_m": round(big, 4),
                                                 "open_edges": n_open, "volume_m3": vol, "character_height_m": H})
    cd = P.gate_dir("s0_spec", "comparison")
    an2 = dict(an); an2["axis_xy"] = [float(lo[0]) + 0.025 * H + 0.15, an["axis_xy"][1]]     # character left of the asset
    made, _h = _spec_proxies(an2, H, 0, prof["character"]["hand_breadth_m"])
    try:
        x0 = float(lo[0]) - 0.45 * H - 0.1; W = float(hi[0]) - x0; hh = max(H, float(hi[2])); zb = min(0.0, float(lo[2]))
        v1 = [("with_character", ((x0 + float(hi[0])) / 2, an["axis_xy"][1], (zb + hh) / 2), (0, -1, 0),
               1.2 * max(W / 2 / 0.36, (hh - zb) / 2 / 0.2025) + float(S[1]) / 2 + 0.3, 0)]
        for p_ in render_views(set(_highs(P)) | set(made), v1, cd, "scale", engine="WORKBENCH"):
            G.image(p_, f"asset beside a {H} m character (grey proxy)", "comparison")
    finally:
        for n in made:
            o = bpy.data.objects.get(n)
            if o: me = o.data; bpy.data.objects.remove(o); bpy.data.meshes.remove(me)
    G.notes.append("size: change it ONLY with uniform_fit(project, target_overall_m=<largest side in metres>)")
    G.need_review("size_and_orientation", "look at the image beside the character: right size, upright, front towards the camera?")
    return P.finish("s0_spec", G)


def s0_spec(project, weapon_type=None, style=None, character_height=None, hands=None, size_m=None):
    """Is the AI model a usable weapon of its type? Measures length, blade/grip, width, thickness, volume, estimated
    mass and point of balance, compares them with weapon_profiles.json (sourced ranges; fantasy widens them) and
    with a character (grip fits the hands, length vs the character). Renders the weapon beside a character of the
    chosen height and hand blocks on the grip. Side gate: it does not make later stages stale; s1 requires it."""
    P = _proj(project); P.require("s0_intake"); G = Gate("s0_spec")
    if P.state["settings"].get("kind") == "generic" or weapon_type == "generic":         # 1.6.0: any other model
        return _s0_spec_generic(P, size_m=size_m, character_height=character_height)
    w = dict(P.cfg.get("weapon", {})); w.update(P.state["settings"].get("weapon", {}))
    if weapon_type: w["type"] = weapon_type; w.pop("type_auto_from", None)
    if style: w["style"] = style
    if character_height: w["character_height_m"] = character_height
    if hands: w["hands"] = hands
    P.state["settings"]["weapon"] = w; P.save()
    prof = load_profiles()
    cos, tvs, off = [], [], 0
    for n in _highs(P):
        co, tv, _, _, _ = tri_arrays(n); cos.append(co); tvs.append(tv + off); off += len(co)
    co = np.vstack(cos); tv = np.vstack(tvs); an = P.state["anatomy"]
    m, prof_z = measure_weapon(co, tv, an, prof["densities"])
    guess = guess_type(m); wt = w.get("type"); auto_from = None
    if wt:
        prof_t = prof["types"].get(wt)
        implausible = False
        if prof_t:
            key = "diameter" if "diameter" in prof_t else "overall"
            mid = sum(prof_t[key][:2]) / 2
            r = (m["overall_m"] / mid) if mid else 1
            implausible = not (0.5 <= r <= 2.0)
        if implausible and guess[0] not in (wt, "unknown") and guess[2] >= 0.5:
            auto_from = wt; wt = guess[0]; w["type"] = wt; w["type_auto_from"] = auto_from
            P.state["settings"]["weapon"] = w; P.save()
    else:
        wt = guess[0]
    # 1.5.3: an automatic type is never a silent PASS - a small weapon imported too large also reads as a bigger type
    if auto_from or (w.get("type_auto_from") and wt == w.get("type")):
        G.check("weapon_type_declared", wt, False, review=True,
                msg=f"auto-corrected from '{auto_from or w['type_auto_from']}' to '{wt}' ({guess[1]}): the declared type "
                    f"did not fit the size. Confirm the type AND the scale (wrong import units look like a bigger weapon)")
    elif w.get("type"):
        G.check("weapon_type_declared", wt, True, msg=f"declared; guess from proportions: {guess[0]} ({guess[1]})")
    else:
        G.check("weapon_type_declared", wt, False, review=True,
                msg=f"not declared; auto-set from proportions: {guess[0]} ({guess[1]}). Declare it: "
                    f"set_settings('{project}', weapon={{'type': '...', 'style': 'fantasy'}})")
    st = w.get("style", "fantasy"); ch = {"height_m": w.get("character_height_m", prof["character"]["height_m"])}
    C = spec_checks(m, wt, st, prof, ch, w.get("hands"))
    for cid, val, s_, rule, src in C:
        G.check(cid, val, s_ == "PASS", review=s_ == "REVIEW", msg=rule, expected=f"source: {src}")
    G.data.update(measurements=m, weapon=w, guess=guess, profile=prof["types"].get(wt),
                  mass_profile={"z": prof_z["z"][::10].round(3).tolist(), "kg": prof_z["mass"][::10].round(4).tolist()})
    dd = P.gate_dir("s0_spec", "diagnostics"); cd = P.gate_dir("s0_spec", "comparison")
    hp = prof["types"].get(wt, {}).get("hands", 1) if not w.get("hands") else w["hands"]
    made, hands_objs = _spec_proxies(an, ch["height_m"], hp, prof["character"]["hand_breadth_m"])
    try:
        H = ch["height_m"]; cx = an["axis_xy"][0] - 0.3 * H
        v1 = [("with_character", (cx, an["axis_xy"][1], 0.5 * max(H, m["overall_m"])), (0, -1, 0), 2.6 * max(H, m["overall_m"]), 0)]
        for p_ in render_views(set(_highs(P)) | set(made), v1, cd, "scale", engine="WORKBENCH"):
            G.image(p_, f"weapon beside a {H} m character (grey proxy)", "comparison")
        gz = (an["grip_z0"] + an["grip_z1"]) / 2; gl = an["grip_z1"] - an["grip_z0"]
        v2 = [("grip_hands", (an["axis_xy"][0], an["axis_xy"][1], gz), (0.35, -1, 0.1), 3.4 * max(gl, hp * prof["character"]["hand_breadth_m"]) + 0.3, 0)]
        for p_ in render_views(set(_highs(P)) | set(hands_objs), v2, cd, "grip", engine="WORKBENCH"):
            G.image(p_, f"{hp} hand block(s) of {prof['character']['hand_breadth_m'] * 100:.1f} cm on the grip from the guard", "comparison")
    finally:
        for n in made + hands_objs:
            o = bpy.data.objects.get(n)
            if o: me = o.data; bpy.data.objects.remove(o); bpy.data.meshes.remove(me)
    G.notes.append("size: change it ONLY with uniform_fit(project, target_overall_m=...) - one factor on all axes; "
                   "shape edits are locked (settings.design_lock) so the design is never distorted")
    G.need_review("proportions_fit_the_design", "look at the character and grip images: does the weapon read as the declared type and size?")
    return P.finish("s0_spec", G)


# ======================================================================= s3 normals + UV
def uv_backup(name, path):
    """save every UV layer of `name` (per loop) to an .npz so a layout can be compared or restored later."""
    me = bpy.data.objects[name].data; d = {}
    for L in me.uv_layers:
        a = np.empty(len(me.loops) * 2); L.data.foreach_get("uv", a); d["uv__" + L.name] = a.reshape(-1, 2)
    sharp = np.zeros(len(me.edges), bool); seam = np.zeros(len(me.edges), bool)
    for e in me.edges: sharp[e.index] = e.use_edge_sharp; seam[e.index] = e.use_seam
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path, loops=len(me.loops), sharp=sharp, seam=seam, **d)
    return {"path": path, "layers": [k[4:] for k in d]}


def uv_restore(name, path, layer=None):
    """put back a UV layer saved by uv_backup (same mesh topology only)."""
    me = bpy.data.objects[name].data; D = np.load(path)
    if int(D["loops"]) != len(me.loops): raise RuntimeError("topology changed: cannot restore this UV backup")
    keys = [k for k in D.files if k.startswith("uv__")]
    for k in keys if layer is None else ["uv__" + layer]:
        L = me.uv_layers.get(k[4:]) or me.uv_layers.new(name=k[4:]); L.data.foreach_set("uv", D[k].ravel())
    if len(D["sharp"]) == len(me.edges):
        for e in me.edges: e.use_edge_sharp = bool(D["sharp"][e.index]); e.use_seam = bool(D["seam"][e.index])
    me.update(); return {"restored": [k[4:] for k in keys]}


def _ensure_tris(name):
    """per-triangle UVs need one triangle per polygon (game export triangulates anyway; the shape is unchanged)."""
    ob = bpy.data.objects[name]; me = ob.data
    n = sum(1 for p in me.polygons if len(p.vertices) != 3)
    if n:
        import bmesh
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) != 3], quad_method="BEAUTY", ngon_method="BEAUTY")
        bm.to_mesh(me); bm.free(); me.update()
    return n


def uv_classes(co, tv, anatomy=None):
    """chart classes: blade-flat front / back / sides, and the grip+pommel zone (charts never cross a class).
    Generic assets (1.6.0): classes by the dominant facing axis only."""
    if anatomy and anatomy.get("kind") == "generic": anatomy = None
    cr = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]]); A3 = np.linalg.norm(cr, axis=1) / 2
    N = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-20); z = co[tv].mean(1)[:, 2]
    blade = z < anatomy["guard_z0"] if anatomy else np.ones(len(tv), bool)
    ax = int(np.argmax([(np.abs(N[blade, i]) * A3[blade]).sum() for i in (0, 1)]))     # the axis the blade faces look along
    cls = np.where(N[:, ax] > 0.5, 0, np.where(N[:, ax] < -0.5, 1, 2))
    if anatomy: cls[z >= anatomy["grip_z0"]] = 3
    return cls, "xy"[ax]


def uv_regions(co, tv, anatomy, zones=(), sharp_deg=45.0):
    """critical regions for the UV gate: blade, guard, gem (settings.protect_zones), grip, pommel, edges (tris next to
    feature edges sharper than sharp_deg)."""
    c = co[tv].mean(1); z = c[:, 2]; an = anatomy
    if an.get("kind") == "generic":       # 1.6.0: no named parts: one region (+ gem zones and feature edges below)
        R = {"body": np.ones(len(tv), bool)}
    else:
        R = {"blade": z < an["guard_z0"], "guard": (z >= an["guard_z0"]) & (z < an["guard_z1"]),
             "grip": (z >= an["grip_z0"]) & (z < an["grip_z1"]), "pommel": z >= an["grip_z1"]}
    if zones:
        g = np.zeros(len(tv), bool)
        for x, y, zz, r in zones: g |= np.linalg.norm(c - np.array([x, y, zz]), axis=1) < r
        R["gem"] = g
    ang, conc, et = dihedral(co, tv); e = np.zeros(len(tv), bool)
    F = et["F"][ang > sharp_deg]; e[F[:, 0]] = True; e[F[:, 1]] = True; R["edges"] = e
    return R


def forge_unwrap(name, tex=4096, pad_px=16, hard_deg=45.0, uv_name="UV_game", anatomy=None, G=2048, protect_zones=None,
                 coverage_try=None, log=print):
    """the Sword Forge UV recipe (port of the container tools that reached 74 %): class-restricted normal-cone charts
    -> LSCM -> split/repair until no flips or overlaps -> merge small charts -> FFT packing with a Euclidean padding.
    Then smooth shading with hard edges only on seams (> hard_deg) and weighted normals."""
    t0 = time.time(); ob = bpy.data.objects[name]; me = ob.data
    if bpy.context.object and bpy.context.object.mode != "OBJECT": bpy.ops.object.mode_set(mode="OBJECT")
    ntri = _ensure_tris(name)
    co, tv, tl, _, _ = tri_arrays(name)
    cls, ax = uv_classes(co, tv, anatomy)
    UV, ch, rc = uv_charts(co, tv, cls, log=log)
    margin = int(round(pad_px / 2 * G / tex))
    protect = None
    if anatomy:                                                     # blade, sharp edges and gem are never shrunk to fit
        R = uv_regions(co, tv, anatomy, protect_zones or [])
        protect = R.get("blade", np.zeros(len(tv), bool)) | R["edges"] | R.get("gem", np.zeros(len(tv), bool))
    kw_ = {"coverage_try": tuple(coverage_try)} if coverage_try else {}
    out, rp = uv_pack(UV, tv, G=G, margin=margin, protect=protect, log=log, **kw_)
    tri_scale = rp.pop("_tri_scale")
    for L in list(me.uv_layers): me.uv_layers.remove(L)
    L = me.uv_layers.new(name=uv_name); me.uv_layers.active = L; L.active_render = True
    arr = np.zeros((len(me.loops), 2)); arr[tl.ravel()] = out.reshape(-1, 2); L.data.foreach_set("uv", arr.ravel())
    me.update()
    _, tv2, tl2, uv_back, _ = tri_arrays(name, uv_name)              # what Blender really holds = what was packed?
    applied = {"max_abs_diff": float(np.abs(uv_back - out).max()) if uv_back is not None and uv_back.shape == out.shape else None,
               "same_triangles": bool(np.array_equal(tv2, tv) and np.array_equal(tl2, tl)),
               "islands_in_blender": int(len(np.unique(uv_islands_np(tv2, uv_back)))), "pieces_packed": rp["pieces"]}
    r_sn = seam_sharp(name, uv_name, max_deg=hard_deg)
    if not any(md.type == "WEIGHTED_NORMAL" for md in ob.modifiers):
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL"); wn.keep_sharp = True; wn.weight = 50
    shr = {}
    if anatomy:
        for k in ("body", "blade", "edges", "gem", "guard", "grip", "pommel"):
            if k in R and R[k].any():
                m_ = R[k] & (tri_scale < 0.999)
                shr[k] = {"tris_shrunk": int(m_.sum()), "min_factor": round(float(tri_scale[R[k]].min()), 3)}
    return {"method": "forge", "triangulated_polys": ntri, "class_axis": ax, "charts": rc, "pack": rp, "seam_sharp": r_sn,
            "applied": applied, "shrunk_by_region": shr, "seconds": round(time.time() - t0, 1)}


def unwrap_object(name, angle_limit=66.0, hard_deg=45.0, tex=4096, pad_px=16, uv_name="UV_game", method="forge", anatomy=None,
                  protect_zones=None, coverage_try=None):
    """the s3 unwrap recipe for any object (used by s3_uv and by trials, so both are identical).
    method="forge": forge_unwrap (default since 1.2). method="smart": the 1.1 smart-project recipe (kept for comparison)."""
    if method == "forge":
        return forge_unwrap(name, tex=tex, pad_px=pad_px, hard_deg=hard_deg, uv_name=uv_name, anatomy=anatomy,
                            protect_zones=protect_zones, coverage_try=coverage_try)
    ob = bpy.data.objects[name]; me = ob.data
    for L in list(me.uv_layers): me.uv_layers.remove(L)
    me.uv_layers.new(name=uv_name)
    bpy.ops.object.select_all(action="DESELECT"); ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle_limit), island_margin=0.0, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.seams_from_islands()
    bpy.ops.uv.unwrap(method="CONFORMAL", margin=0.0)
    m = pad_px / tex
    bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=True, rotate_method="ANY", scale=True,
                            merge_overlap=False, margin_method="FRACTION", margin=m, pin=False, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")
    r_sn = seam_sharp(name, uv_name, max_deg=hard_deg)
    if not any(md.type == "WEIGHTED_NORMAL" for md in ob.modifiers):
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL"); wn.keep_sharp = True; wn.weight = 50
    return r_sn


def uv_audit_object(P, name, uv_name="UV_game", tex=None):
    """uv_audit on a Blender object with the project's regions and thresholds."""
    tex = tex or P.cfg["texture_size"]
    co, tv, tl, uvt, _ = tri_arrays(name, uv_name)
    if uvt is None: return {"error": f"{name} has no {uv_name}"}, [], None, None, None
    regs = uv_regions(co, tv, P.state["anatomy"], P.state["settings"].get("protect_zones", []))
    th = dict(P.cfg.get("uv_thresholds", {})); th.setdefault("cov", tuple(P.cfg["uv_coverage"]))
    rep, C = uv_audit(co, tv, uvt, tex, regs, pad_px=P.cfg["uv_padding_px"], cfg={"uv_thresholds": th})
    return rep, C, (co, tv, uvt), regs, tl


def _checker_mat(name="FORGE_uv_checker", uv_name="UV_game", squares=64):
    """UV checker for distortion/seam review: `squares` squares across the 0..1 texture (64 -> 64 px squares at 4K)."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = uv_name
    ck = nt.nodes.new("ShaderNodeTexChecker"); ck.inputs["Scale"].default_value = squares
    ck.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1); ck.inputs["Color2"].default_value = (0.08, 0.08, 0.1, 1)
    nt.links.new(uvn.outputs[0], ck.inputs["Vector"]); nt.links.new(ck.outputs["Color"], bs.inputs["Base Color"])
    bs.inputs["Roughness"].default_value = 0.6; nt.links.new(bs.outputs[0], out.inputs[0])
    return m


def _keep_awake():
    """Windows: keep the computer from sleeping while a long stage runs in this process (s3 was lost on 2026-10-28
    when the computer slept). Cleared automatically when the Blender process exits."""
    try:
        import ctypes; ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001); return True
    except Exception:
        return False


def s3_uv(project, method="forge", angle_limit=66.0, hard_deg=45.0, tex=None, pad_px=None, uv_name="UV_game",
          compare_with=()):
    """UV + normals. Gate (every check PASS/FAIL/REVIEW, thresholds from config/family):
    inside 0..1, flips, zero-area, overlap px at 4K, exact min island gap and border, coverage (area-sum definition,
    raster value reported too), distortion (Jacobian anisotropy), texel spread, per-region density and cleanliness
    (blade, guard, gem, grip, pommel, edges), ZERO hard edges inside islands, 0 flat faces; REVIEW of seam placement
    with checker renders. The previous UVs are saved first (uv_backup) and audited the same way for comparison."""
    P = _proj(project); P.require("s2_lowpoly"); cfg = P.cfg; G = Gate("s3_uv"); G.data["keep_awake"] = _keep_awake()
    tex = tex or cfg["texture_size"]; pad_px = pad_px or cfg["uv_padding_px"]
    name = _asset(P) + "_LOD0"; ob = bpy.data.objects[name]
    dd = P.gate_dir("s3_uv", "diagnostics"); cd = P.gate_dir("s3_uv", "comparison"); rd = P.gate_dir("s3_uv")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bk = uv_backup(name, os.path.join(rd, f"uv_before_{stamp}.npz"))
    before = None
    if ob.data.uv_layers.get(uv_name) is not None:
        before = uv_audit_object(P, name, uv_name, tex)[0]
    cmp = {}
    for o in compare_with:
        if bpy.data.objects.get(o) is not None:
            r_, C_, *_ = uv_audit_object(P, o, uv_name, tex); cmp[o] = {"report": r_, "checks": C_}
    # speed: the same mesh packed before -> start one level above the coverage that worked (skips known failures)
    levels = [0.70, 0.68, 0.65, 0.62, 0.60, 0.55, 0.50]; co_, tv_, _, _, _ = tri_arrays(name)
    mkey = f"{len(tv_)}_{round(float(np.abs(co_).sum()), 4)}"; last = P.state["settings"].get("uv_last", {})
    ctry = None
    if last.get("key") == mkey and last.get("coverage"):
        ctry = [c for c in levels if c <= last["coverage"] + 0.021] or None
    rec = unwrap_object(name, angle_limit, hard_deg, tex, pad_px, uv_name, method=method, anatomy=P.state["anatomy"],
                        protect_zones=P.state["settings"].get("protect_zones", []), coverage_try=ctry)
    if isinstance(rec, dict) and rec.get("method") == "forge":
        P.state["settings"]["uv_last"] = {"key": mkey, "coverage": rec["pack"]["target_coverage"]}; P.save()
        rec["coverage_levels_tried_from"] = ctry[0] if ctry else levels[0]
    rep, C, (co, tv, uvt), regs, _ = uv_audit_object(P, name, uv_name, tex)
    her = hard_edge_report(name, uv_name)
    for cid, val, st, rule in C:
        G.check(cid, val, st == "PASS", review=st == "REVIEW", msg=rule)
    G.check("hard_edges_inside_islands", her["hard_edges_inside_islands"], her["hard_edges_inside_islands"] == 0,
            msg="hard edge without a UV seam = visible line/crease after baking (lesson 2)")
    G.check("flat_shaded_faces", her["flat_shaded_faces"], her["flat_shaded_faces"] == 0)
    if isinstance(rec, dict) and rec.get("method") == "forge":
        ap = rec["applied"]
        G.check("uv_applied_matches_packed", ap["max_abs_diff"], ap["max_abs_diff"] is not None and ap["max_abs_diff"] < 1e-5 and ap["same_triangles"],
                msg="UVs read back from the Blender mesh equal the packed layout that was measured")
        G.check("uv_islands_match_pieces", f"{ap['islands_in_blender']}/{ap['pieces_packed']}", ap["islands_in_blender"] == ap["pieces_packed"],
                review=True, msg="no island lost or merged when the layout was written to the mesh")
        crit = {k: v for k, v in rec["shrunk_by_region"].items() if k in ("blade", "edges", "gem") and v["tris_shrunk"]}
        G.check("critical_regions_shrunk", crit or 0, not crit, review=True,
                msg="pieces of blade / sharp edges / gem scaled down to fit (lower texel density): look at the texel map")
        G.check("pieces_shrunk", len(rec["pack"]["shrunk"]), not rec["pack"]["shrunk"], review=True,
                msg="any piece scaled down is listed with its factor in uv_audit.json (recipe.pack.shrunk)")
    G.data.update(recipe=rec, uv=rep, edges=her, backup=bk, before=before, compare=cmp)
    json.dump({"recipe": rec, "audit": rep, "checks": C, "edges": her, "before": before, "compare": cmp},
              open(os.path.join(rd, "uv_audit.json"), "w"), indent=2, default=str)
    pics = uv_diag_pngs(co, tv, uvt, os.path.join(dd, "uv"), 2048, regs, pad_px, tex)
    G.image(pics["islands"], f"UV islands: red = overlap, magenta = islands closer than {pad_px}px at {tex}", "diagnostics")
    G.image(pics["texel"], "texel density: blue 0.5x, green 1x, red 1.5x the median", "diagnostics")
    G.image(pics["regions"], "regions: blade blue, guard orange, gem red, grip green, pommel violet, feature edges yellow", "diagnostics")
    for o in cmp:
        co2, tv2, _, uv2, _ = tri_arrays(o, uv_name)
        G.image(uv_diag_pngs(co2, tv2, uv2, os.path.join(cd, f"uv_{o}"), 2048, None, pad_px, tex)["islands"], f"previous layout: {o}", "comparison")
    views = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], ("full_front", "full_back", "junction", "blade_mid", "guard_center", "guard_left", "grip", "pommel"))]
    for p_ in render_views({name}, views, dd, "checker", override_mat=_checker_mat(uv_name=uv_name)):
        G.image(p_, "UV checker (64 px squares at 4K): squares should stay square and equal in size; seams show as breaks", "diagnostics")
    paint_tris(name, hard_edge_tris(name, uv_name))
    for p_ in render_views({name}, [v for v in views if _vin(v[0], ("full_front", "guard_center", "guard_left", "junction"))], dd, "edges", engine="WORKBENCH", mode="attribute"):
        G.image(p_, "red = hard edge inside an island (line after bake), orange = seam on a smooth surface", "diagnostics")
    G.need_review("seam_placement", f"seams on smooth visible surfaces: {rep['seam_length_on_smooth_m']} m; check the checker renders of gem, blade flats and guard")
    P.checkpoint("s3_uv")
    return P.finish("s3_uv", G)


def normal_map_stats(img_path, uvt, regions=None):
    """normal-map health inside the UV islands: share of strongly tilted texels (tilt > 60 deg), local roughness
    (p99 of the per-pixel change) and the same per region. Compare two bakes with the same layout or between layouts."""
    im = bpy.data.images.load(img_path, check_existing=False); w, h = im.size
    px = np.empty(w * h * 4, np.float32); im.pixels.foreach_get(px); bpy.data.images.remove(im)
    n = px.reshape(h, w, 4)[..., :3] * 2 - 1                                  # row 0 = bottom (Blender), same as UV v
    r, c, t = _tri_pixels(np.asarray(uvt) * np.array([w, h]), 0.0, -1.0)     # pixels one texel inside the islands
    ok = (r >= 0) & (r < h) & (c >= 0) & (c < w); r, c, t = r[ok], c[ok], t[ok]
    inside = np.zeros((h, w), bool); inside[r, c] = True
    gx = np.zeros((h, w)); gy = np.zeros((h, w))
    gx[:, :-1] = np.linalg.norm(n[:, 1:] - n[:, :-1], axis=2); gy[:-1] = np.linalg.norm(n[1:] - n[:-1], axis=2)
    both = inside.copy(); both[:, :-1] &= inside[:, 1:]; both[:-1] &= inside[1:]
    g = np.maximum(gx, gy)
    def st(mask):
        if mask.sum() == 0: return None
        nz = n[..., 2][mask]
        return {"texels": int(mask.sum()), "tilt_gt60_share": round(float((nz < 0.5).mean()), 5),
                "tilt_p99_deg": round(float(np.degrees(np.arccos(np.clip(np.percentile(nz, 1), -1, 1)))), 2),
                "change_p99": round(float(np.percentile(g[mask & both], 99)), 4) if (mask & both).any() else None}
    out = {"size": [w, h], "all": st(inside)}
    for k, m in (regions or {}).items():
        mm = np.zeros((h, w), bool); sel = np.asarray(m, bool)[t]; mm[r[sel], c[sel]] = True; out[k] = st(mm)
    return out


# ======================================================================= s4 bake (test 1K -> compare -> final 4K)
def _bake_highres_guard(P, size):
    """None when a bake above 1K may start, else the reason. Rule: a 1K bake was checked with no FAIL after the last
    UV change (s3_uv), and the user approved that 1K check (LESSON 43: 4K bakes are only for an approved 1K result).
    settings.allow_direct_highres_bake = True skips the rule (the user's decision)."""
    s = P.state["settings"]
    if size <= 1024 or s.get("allow_direct_highres_bake"): return None
    c = s.get("bake_1k_check") or {}
    if not c.get("ok"): return "no 1K bake check without FAIL yet: s4_bake(project, size=1024) -> s4_bake_check(project)"
    uv = P.state.get("stages", {}).get("s3_uv", {}).get("time", "")
    if c.get("time", "") < uv: return f"the UV changed after the last 1K check ({c.get('time')} < s3_uv {uv}): bake and check 1K again"
    if (s.get("last_bake") or {}).get("size", 0) <= 1024:
        st = P.state.get("stages", {}).get("s4_bake", {})
        if not (st.get("status") == "PASS" or (st.get("status") == "REVIEW" and st.get("approved"))):
            return "the 1K bake check is not approved yet: look at the comparison sheet, then the user approves s4_bake"
    return None


def _bake_ray_defaults(P):
    """1.4.2 (green_sword 2026-10-31): the old fixed cage 0.0032 L / ray 0.0095 L reached through a thin overlap
    at the pommel (look excess 0.0138, dark streak); the look-gate preview values 0.0015 L / 0.005 L were better in
    all 9 views. Ray = max(0.005 L, 3 x the measured s2 Hausdorff distance) so it always covers the low/high gap.
    settings.bake_cage_rel / bake_ray_rel override (the user's decision)."""
    L = _L(P); st = P.state["settings"]; hd = 0.0
    try: hd = json.load(open(P.state["stages"]["s2_lowpoly"]["report"], encoding="utf-8"))["data"].get("hausdorff_mm", 0) / 1000
    except Exception: pass
    cage = st.get("bake_cage_rel", 0.0015) * L
    ray = max(st.get("bake_ray_rel", 0.005) * L, 3 * hd)
    return cage, ray


def s4_bake(project, size=1024, out=None, cage=None, max_ray=None):
    """timer bake. Call with size=1024 first: s4_bake_check() renders the comparison sheet. Then size=4096."""
    P = _proj(project); P.require("s3_uv"); _keep_awake()
    why = _bake_highres_guard(P, size)
    if why: raise GateError(f"s4_bake size={size} refused: {why}")
    name = _asset(P) + "_LOD0"; L = _L(P)
    out = out or P.p("work", f"bake_{size}")
    pre = P.state["settings"].get("tex_prefix", "T_" + _asset(P)[3:])
    hook = P.state["settings"].get("before_bake")          # e.g. turn off a preview-only overlay on the high poly
    if hook: exec(hook, globals())
    dc, dr = _bake_ray_defaults(P)
    cage = cage or dc; max_ray = max_ray or dr
    tsrc = [n for n in (P.state["settings"].get("texture_source") or []) if n in bpy.data.objects]   # 1.5.0
    r = start_bake(name, _highs(P), out, prefix=pre, size=size, cage=cage, max_ray=max_ray, color_high_names=tsrc or None)
    P.state["settings"]["last_bake"] = {"size": size, "dir": out, "cage": cage, "max_ray": max_ray}; P.save()
    return {"started": r, "dir": out, "log": os.path.join(out, "bake_log.txt")}


def s4_bake_check(project):
    """after the bake log says done: material -> close-up comparison high vs low (lit, textured) -> gate."""
    P = _proj(project); G = Gate("s4_bake"); lb = P.state["settings"]["last_bake"]
    name = _asset(P) + "_LOD0"; pre = P.state["settings"].get("tex_prefix", "T_" + _asset(P)[3:])
    log = open(os.path.join(lb["dir"], "bake_log.txt")).read()
    G.check("bake_finished", "done" in log, "done" in log)
    hook = P.state["settings"].get("after_bake")
    if hook: exec(hook, globals())
    game_material([name], lb["dir"], pre, "M_" + _asset(P)[3:])
    for f in os.listdir(lb["dir"]):
        if f.endswith(".png") and f.startswith(pre):
            G.check("map_" + f[len(pre) + 1:-4], os.path.getsize(os.path.join(lb["dir"], f)), os.path.getsize(os.path.join(lb["dir"], f)) > 1000)
    views = [v for v in inspection_views(P.state["anatomy"]) if not _vin(v[0], ("full_back",))]
    cd = P.gate_dir("s4_bake", "comparison")
    tsrc = [n for n in (P.state["settings"].get("texture_source") or []) if n in bpy.data.objects]   # textured original
    hi = render_views(set(tsrc or _highs(P)), views, cd, f"high_{lb['size']}")
    lo = render_views({name}, views, cd, f"low_{lb['size']}")
    G.image(compare_sheet(hi, lo, os.path.join(cd, f"sheet_high_vs_low_{lb['size']}.png")), "left high, right low (baked, lit)", "comparison")
    npng = os.path.join(lb["dir"], f"{pre}_Normal.png")
    if os.path.exists(npng) and P.cfg["lowpoly"].get("look_gate", True):
        im_ = bpy.data.images.load(npng, check_existing=True); uvn = P.state["settings"].get("uv_name", "UV_game")
        lk = look_compare(P.state["anatomy"], _highs(P), name, P.gate_dir("s4_bake", "look"), f"baked_{lb['size']}", im_.name, uvn)
        ref = _look_reference(P); ok_l, lim = _look_status(lk, P.cfg["lowpoly"], ref); G.data["look"] = dict(lk, excess=lim["excess"])
        G.check("look_excess_p95", lim["worst_excess"], lim["worst_excess"][1] <= lim["excess_p95_max"], review=lim["worst_excess"][1] <= 2 * lim["excess_p95_max"],
                msg="final baked normal map (grey) vs high, above the dense preview reference: worst view")
        G.check("look_silhouette_iou", lk["min_iou"], lk["min_iou"][1] >= lim["iou_min"], review=lk["min_iou"][1] >= lim["iou_min"] - 0.01, msg="silhouette overlap, worst view")
        G.image(lk["sheet"], "look gate (baked normal, grey): left high, right low", "comparison")
    G.need_review("bake_visual", "no seam lines, no creases, no dark wedges, no missing details vs high (gem, guard, junction)")
    G.data["size"] = lb["size"]
    if lb["size"] <= 1024:
        P.state["settings"]["bake_1k_check"] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                "ok": not any(c["status"] == "FAIL" for c in G.checks), "dir": lb["dir"]}
        P.save()
    return P.finish("s4_bake", G)


# ======================================================================= s6 LODs + collision
def s6_lods(project, ratios=None):
    P = _proj(project); P.require("s4_bake"); G = Gate("s6_lods"); an = P.state["anatomy"]
    base = _asset(P); lod0 = base + "_LOD0"; t0 = sum(len(p.vertices) - 2 for p in bpy.data.objects[lod0].data.polygons)
    r = ratios or P.cfg["budgets"][P.cfg["category"]][2:4]
    rep = lods_from(lod0, base, targets=tuple(int(t0 * x) for x in r))
    for i in (1, 2):
        seam_sharp(f"{base}_LOD{i}")
        rep[f"{base}_LOD{i}"]["uv_unfold"] = uv_unfold_collapse(f"{base}_LOD{i}")    # decimation folds a few UV triangles
    parts = ((-1, an["guard_z0"]), (an["guard_z0"], an["guard_z1"]), (an["guard_z1"], 99))
    ucx = make_collision(lod0, parts=parts)
    G.data.update(lods=rep, ucx=ucx)
    for i in (1, 2):
        n = f"{base}_LOD{i}"; G.check(f"lod{i}_exists", n in bpy.data.objects, n in bpy.data.objects)
        uvr = uv_report(n); G.check(f"lod{i}_uv_flips", uvr["flipped_tris"], uvr["flipped_tris"] == 0)
    G.check("collision_hulls", len(ucx), len(ucx) >= 1)
    return P.finish("s6_lods", G)


# ======================================================================= s7 export + re-import
def s7_export(project, tex_dir=None, formats=("FBX", "GLB", "OBJ")):
    P = _proj(project); P.require("s6_lods"); G = Gate("s7_export"); an = P.state["anatomy"]
    tex_dir = tex_dir or P.state["settings"].get("final_tex_dir")     # 1.4.2: the panel/queue need no path (set by s5)
    if not tex_dir or not os.path.isdir(tex_dir): raise GateError("s7_export: no texture folder (run s5_look first or pass tex_dir)")
    base = _asset(P); pre = P.state["settings"].get("tex_prefix", "T_" + base[3:]); root = P.p("export", base)
    for o in bpy.data.objects:                                  # LESSON: hidden-but-selected objects get exported
        try: o.select_set(False)
        except Exception: pass
    piv = an["pivot"]
    rep = export_with_pivot(base, root, tex_dir, pre, pivot=tuple(piv))
    pf = (piv[2] - an["tip_z"]) / an["length"]
    if an.get("kind") == "generic":           # validate() measures along the longest side: where the base-centre pivot sits on it
        ax_ = int(np.argmax(an["size"])); pf = (piv[ax_] - (an["bbox_center"][ax_] - an["size"][ax_] / 2)) / an["size"][ax_]
    v = validate(root, base, expect_height_m=an["length"], pivot_frac=pf)
    G.data.update(export=rep, validate=v)
    G.check("reimport_validate", v.get("passed"), bool(v.get("passed")), msg="; ".join(v.get("problems", [])[:5]))
    for d in formats:
        dd = os.path.join(root, d); n = len(os.listdir(dd)) if os.path.isdir(dd) else 0
        G.check(f"files_{d}", n, n > 0)
    mb = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(os.path.join(root, "GLB")) for f in fs) / 1e6
    G.check("glb_size_mb", round(mb, 1), mb < 80, msg="a huge GLB means extra objects slipped in")
    return P.finish("s7_export", G)


# ======================================================================= s10 publish checklist
PUBLISH_CHECKLIST = [
    ("ai_disclosure", "Fab listing: AI-generated content disclosed (the base model came from an AI generator)"),
    ("source_license", "the AI generator's terms allow commercial resale of its outputs (paid plan if required)"),
    ("no_ip", "the design does not copy a known franchise / brand / character"),
    ("textures_own", "all textures are baked from our own model (no third-party images)"),
    ("formats_tested", "every format named in the listing was re-imported and checked (s7)"),
    ("gallery", "images JPG/PNG >= 1920x1080, < 3 MB each, show the real product (no paint-over)"),
    ("readme", "English README with formats, tris per LOD, texture list, units, pivot"),
    ("price_license", "price and license chosen; description matches what is delivered"),
]


def s10_publish(project):
    P = _proj(project); P.require("s9_package"); G = Gate("s10_publish")
    done = P.state["settings"].get("publish_checks", {})
    for k, msg in PUBLISH_CHECKLIST:
        if done.get(k): G.check(k, True, True, msg=msg)
        else: G.need_review(k, msg)
    return P.finish("s10_publish", G)


def status(project):
    P = _proj(project)
    return {s: P.status(s) for s in STAGES}


# ======================================================================= s5 look (project-specific effects)
def s5_look(project, script=None):
    """project hook for effects painted in texture space (lava, runes, glow...). The script must write the final
    maps into P.state.settings.final_tex_dir and list what it changed. Without a script the bake is the look."""
    P = _proj(project); P.require("s4_bake"); G = Gate("s5_look")
    script = script or P.state["settings"].get("look_script")
    if script:
        ns = dict(globals(), P=P, G=G); exec(open(script, encoding="utf-8").read(), ns)
    else:                                          # the look the user chose (look_paint dir), else the bake itself
        st = P.state["settings"]; st["final_tex_dir"] = st.get("look_chosen_dir") or st["last_bake"]["dir"]; P.save()
    st = P.state["settings"]; fd = st.get("final_tex_dir"); pre = st.get("tex_prefix", "T_" + _asset(P)[3:])
    G.check("final_tex_dir", fd, bool(fd) and os.path.isdir(fd))
    size = st["last_bake"]["size"]
    for k in ("BaseColor", "ORM", "Normal", "Normal_DX", "Emissive", "AO"):
        f = os.path.join(fd, f"{pre}_{k}.png"); ok = os.path.exists(f); sz = None
        if ok:
            im = bpy.data.images.load(f, check_existing=False); sz = list(im.size); bpy.data.images.remove(im)
        G.check(f"map_{k}", sz, ok and sz == [size, size], msg=f"{size} px")
    game_material([_asset(P) + "_LOD0"], fd, pre, "M_" + _asset(P)[3:])     # the work file shows the final look
    try:                     # 1.4.2: the REVIEW had no image; render the final material (lit) next to the high
        views = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], ("full_front", "guard_center", "grip", "pommel", "tip"))]
        cd = P.gate_dir("s5_look", "comparison")
        hi = render_views(set(_highs(P)), views, cd, "high"); lo = render_views({_asset(P) + "_LOD0"}, views, cd, "final")
        G.image(compare_sheet(hi, lo, os.path.join(cd, "sheet_high_vs_final.png")), "left high (generator material), right final LOD0 material", "comparison")
    except Exception as e:
        G.notes.append(f"s5 preview render failed: {e!r}")
    G.need_review("look", "effects only where intended; nothing glowing by accident; preview layers off before bakes")
    return P.finish("s5_look", G)


def _img_read(path, size, channels=3):
    """image -> (size, size, channels) float32 in Blender row order (row 0 = v 0), resized when needed."""
    im = bpy.data.images.load(path, check_existing=False)
    if im.colorspace_settings.name != "Non-Color": im.colorspace_settings.name = "Non-Color"
    if tuple(im.size) != (size, size): im.scale(size, size)
    a = np.empty(size * size * 4, np.float32); im.pixels.foreach_get(a); bpy.data.images.remove(im)
    return a.reshape(size, size, 4)[..., :channels]


def _img_write(path, arr):
    """(S,S,3) 0..1 already encoded (sRGB colour or linear data) -> 8-bit PNG, values stored as given."""
    S = arr.shape[0]; im = bpy.data.images.new(os.path.basename(path), S, S, alpha=False)
    im.colorspace_settings.name = "Non-Color"
    px = np.ones((S, S, 4), np.float32); px[..., :3] = np.clip(arr, 0, 1); im.pixels.foreach_set(px.ravel())
    im.filepath_raw = path; im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)


def look_paint(project, size=2048, tag=None, look=None):
    """s5: our own textures painted in texture space (forge_look): black steel, worn edges, leather grip, red gem and
    lava (blade channel, guard horns). Writes BaseColor / ORM / Emissive next to copies of the baked Normal maps."""
    P = _proj(project); P.require("s4_bake"); t0 = time.time(); an = P.state["anatomy"]; st = P.state["settings"]
    name = _asset(P) + "_LOD0"; pre = st.get("tex_prefix", "T_" + _asset(P)[3:]); bdir = st["last_bake"]["dir"]
    tag = tag or f"look_{size}"; out = P.p("work", tag); os.makedirs(out, exist_ok=True)
    ob = bpy.data.objects[name]; me = ob.data
    co, tv, tl, _, _ = tri_arrays(name)
    uv = np.empty(len(me.loops) * 2); me.uv_layers[st.get("uv_name", "UV_game")].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    cn = np.empty(len(me.loops) * 3); me.corner_normals.foreach_get("vector", cn); cn = cn.reshape(-1, 3) @ np.array(ob.matrix_world)[:3, :3].T
    tm = texel_maps(co, tv, tl, uv, cn, size); lab = parts(tm, an, [] if st.get("gem_dome") else st.get("protect_zones", []), st.get("gem_ellipsoids", []))
    ao = _img_read(os.path.join(bdir, f"{pre}_AO.png"), size, 1)[..., 0]
    nm = _img_read(os.path.join(bdir, f"{pre}_Normal.png"), size, 3)
    valid = np.zeros(size * size, bool); valid[tm["idx"]] = True; valid = valid.reshape(size, size)
    cur = curvature_from_normal(nm, valid); ridge = blade_ridge(co, tv, an)
    L = look or st.get("look") or {}
    aot = ao.ravel()[tm["idx"]].copy(); nt = nm.reshape(-1, 3)[tm["idx"]] * 2 - 1; gem_rr = None; gem_rep = None
    if st.get("gem_dome"):                         # the flat AI gem shaded as a round pearl (textures only)
        gm, gw, gn, grr = gem_dome(tm, st["gem_dome"]); Tt, Bb, Nn = tangent_frames(co, tv, tl, uv, tm)
        dt = np.stack([(gn * Tt).sum(1), (gn * Bb).sum(1), (gn * Nn).sum(1)], 1)
        nt = nt * (1 - gw[:, None]) + dt * gw[:, None]; nt /= np.maximum(np.linalg.norm(nt, axis=1, keepdims=True), 1e-9)
        aot = aot * (1 - 0.45 * gw * np.clip((grr - 0.7) / 0.3, 0, 1)); lab[gm] = 4; gem_rr = grr
        gem_rep = {"texels": int(gm.sum()), "spec": st["gem_dome"]}
    ai = None
    if L.get("style") == "ai_lava":                # the first dragon sword's method: AI bake + cracked lava in its red
        bc_ai = _img_read(os.path.join(bdir, f"{pre}_BaseColor.png"), size, 3).reshape(-1, 3)[tm["idx"]]
        em_ai = _img_read(os.path.join(bdir, f"{pre}_Emissive.png"), size, 3).reshape(-1, 3)[tm["idx"]]
        orm_ai = _img_read(os.path.join(bdir, f"{pre}_ORM.png"), size, 3).reshape(-1, 3)[tm["idx"]]
        gz = (st.get("gem_dome") or {}).get("center", [0, an["guard_z0"] + 0.165])[1]
        ai = ai_lava(tm, bc_ai, em_ai, silhouette_distance(co, tv), an, ridge, gz, L)
        lm = ai["lava_m"]
        R = {"rough": orm_ai[:, 1] * (1 - lm) + 0.75 * lm, "metal": orm_ai[:, 2] * (1 - lm), "lava": lm,
             "emit": np.zeros((len(lm), 3), np.float32)}
    elif L.get("style") == "molten":               # the user's reference look (cracked lava band, red rims)
        R = paint_molten(tm, lab, aot, silhouette_distance(co, tv), ridge, an, L, gem_rr)
    else:
        R = paint(tm, lab, aot, cur.ravel()[tm["idx"]], ridge, an, L, gem_rr)
    pad = max(4, size // 256)
    if gem_rep:
        nimg = to_image(tm, (nt * 0.5 + 0.5).astype(np.float32), pad_px=pad); nimg[~valid] = nm[~valid]
        _img_write(os.path.join(out, f"{pre}_Normal.png"), nimg)
        ndx = nimg.copy(); ndx[..., 1] = 1 - ndx[..., 1]; _img_write(os.path.join(out, f"{pre}_Normal_DX.png"), ndx)
    bcs = ai["base_srgb"] if ai else _srgb(R["base"]).astype(np.float32)
    _img_write(os.path.join(out, f"{pre}_BaseColor.png"), to_image(tm, bcs, pad_px=pad))
    orm = np.stack([aot, R["rough"], R["metal"]], 1).astype(np.float32)
    _img_write(os.path.join(out, f"{pre}_ORM.png"), to_image(tm, orm, pad_px=pad))
    ems = ai["emit_srgb"] if ai else _srgb(R["emit"]).astype(np.float32)
    _img_write(os.path.join(out, f"{pre}_Emissive.png"), to_image(tm, ems, pad_px=pad))
    for k in ("Normal", "Normal_DX", "AO"):
        src = os.path.join(bdir, f"{pre}_{k}.png")
        if gem_rep and k != "AO": continue
        if os.path.exists(src):
            if size == st["last_bake"]["size"]: shutil.copy2(src, os.path.join(out, f"{pre}_{k}.png"))
            else:
                im = bpy.data.images.load(src, check_existing=False); im.colorspace_settings.name = "Non-Color"; im.scale(size, size)
                im.filepath_raw = os.path.join(out, f"{pre}_{k}.png"); im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)
    names = ["blade", "guard", "grip", "pommel", "gem"]; cnt = np.bincount(lab, minlength=5)
    rep = {"dir": out, "size": size, "texels": int(len(tm["idx"])), "coverage": round(len(tm["idx"]) / size / size, 4),
           "parts_texels": {names[i]: int(cnt[i]) for i in range(5)}, "lava_share": round(float((R["lava"] > 0.1).mean()), 4),
           "emissive_share": round(float(((ai["emit_srgb"] if ai else R["emit"]).max(1) > 0.05).mean()), 4), "style": L.get("style", "basic"), "gem_dome": gem_rep, "seconds": round(time.time() - t0, 1), "look": L}
    json.dump(rep, open(os.path.join(out, "look_report.json"), "w"), indent=2, default=str)
    ledger("look_paint", project=P.name, size=size, dir=out, lava_share=rep["lava_share"])
    return rep


def look_preview(project, tex_dir, tag="look", views=("full_front", "junction", "blade_mid", "guard_center", "guard_left", "grip", "pommel"),
                 emission=2.0):
    """EEVEE renders of LOD0 with the maps in tex_dir (its own materials are put back afterwards)."""
    P = _proj(project); name = _asset(P) + "_LOD0"; pre = P.state["settings"].get("tex_prefix", "T_" + _asset(P)[3:])
    ob = bpy.data.objects[name]; keep = [s_.material for s_ in ob.material_slots]
    mname = game_material([name], tex_dir, pre, f"M_preview_{tag}")
    m = bpy.data.materials[mname]
    for n_ in m.node_tree.nodes:
        if n_.type == "BSDF_PRINCIPLED": n_.inputs["Emission Strength"].default_value = emission
    out = P.gate_dir("s5_look", f"preview_{tag}"); V = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], views)]
    try:
        files = render_views({name}, V, out, "look")
    finally:
        ob.data.materials.clear()
        for m_ in keep: ob.data.materials.append(m_)
    return {"images": files, "dir": out}


# ======================================================================= s8 media (Cycles, marketing)
def _ensure_studio(sc):
    """1.4.2 (green_sword 2026-10-31): reshoot() renders the MAIN scene with its own lights. A project imported into
    a new file has none (forge_cli removes the default Light) -> the whole gallery came out black. If the scene has
    no light that renders, add the same 3 area lights + grey world as the inspection scene. A scene that already
    has lights (a hand-made 'cine' rig) is left alone."""
    from mathutils import Vector
    lit = [o.name for o in sc.objects if o.type == "LIGHT" and not o.hide_render]
    if lit: return {"added": False, "lights": lit}
    w = bpy.data.worlds.get("STUDIO_world") or bpy.data.worlds.new("STUDIO_world"); w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg: bg.inputs[0].default_value = (0.18, 0.18, 0.2, 1); bg.inputs[1].default_value = 0.6
    sc.world = w; made = []
    for n, loc, e in (("STUDIO_key", (1.5, -2.0, 2.0), 600), ("STUDIO_fill", (-2.0, -1.0, 1.0), 250), ("STUDIO_rim", (0, 2.5, 2.0), 400)):
        o = bpy.data.objects.get(n)
        if o is None:
            l = bpy.data.lights.new(n, "AREA"); l.energy = e; l.size = 1.5; o = bpy.data.objects.new(n, l); o.location = loc
            o.rotation_euler = (Vector((0, 0, 0.6)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        if o.name not in sc.collection.objects: sc.collection.objects.link(o)
        o.hide_render = False; made.append(o.name)
    return {"added": True, "lights": made}


def _albedo_mean(P):
    """mean of the final BaseColor texels that are not padding (both values as stored in the 8-bit PNGs)."""
    st = P.state["settings"]; fd = st.get("final_tex_dir") or (st.get("last_bake") or {}).get("dir")
    pre = st.get("tex_prefix", "T_" + _asset(P)[3:]); f = os.path.join(fd or "", f"{pre}_BaseColor.png")
    if not os.path.exists(f): return None
    im = bpy.data.images.load(f, check_existing=False); im.scale(512, 512)
    a = np.empty(512 * 512 * 4, np.float32); im.pixels.foreach_get(a); bpy.data.images.remove(im)
    a = a.reshape(-1, 4)[:, :3]; m = a.max(1) > 0.02
    return float((a[m] @ np.array([0.2126, 0.7152, 0.0722])).mean()) if m.any() else None


def _product_brightness(png):
    """mean luminance of the product pixels (pixels that differ from the background sampled at the 4 corners)."""
    im = bpy.data.images.load(png, check_existing=False); im.scale(480, 270)
    a = np.empty(480 * 270 * 4, np.float32); im.pixels.foreach_get(a); bpy.data.images.remove(im)
    a = a.reshape(270, 480, 4)[..., :3]; bg = np.median(np.stack([a[2, 2], a[2, -3], a[-3, 2], a[-3, -3]]), 0)
    m = np.abs(a - bg).max(-1) > 0.06
    if m.mean() < 0.002: return 0.0, float(m.mean())
    lum = (a[m] @ np.array([0.2126, 0.7152, 0.0722]))
    return float(lum.mean()), float(m.mean())


def s8_media(project, shots=None):
    """marketing renders (Cycles) of LOD0 with the final material; then convert to JPG 1920x1080 < 3 MB."""
    P = _proj(project); P.require("s7_export"); an = P.state["anatomy"]
    out = P.p("renders", "media"); os.makedirs(out, exist_ok=True)
    V = {v[0]: v for v in inspection_views(an)}
    bc = an.get("bbox_center") or [0, 0, an["length"] / 2]
    c0 = (bc[0], bc[1], an["length"] / 2)            # 1.4.2: frame the bounding box (curved blades sat off-centre)
    if an.get("kind") == "generic" and not shots:              # 1.6.0: gallery from the generic cameras
        def g_(n, k=1.0): return dict(target=tuple(V[n][1]), direction=V[n][2], dist=k * V[n][3], lens=50, roll=0)
        back = dict(g_("front"), target=(-V["front"][1][0], -V["front"][1][1], V["front"][1][2]))
        shots = [("01_hero", g_("three_quarter", 0.72), 0), ("02_front", g_("front"), 0), ("03_back", back, 180),
                 ("04_side", g_("right"), 0), ("05_detail", g_("detail_center"), 0), ("06_detail_high", g_("detail_high"), 0),
                 ("07_wire", g_("three_quarter", 0.72), 0, "wire"), ("08_wire_detail", g_("detail_center"), 0, "wire")]
    shots = shots or [("01_hero", dict(target=c0, direction=(0.55, -0.8, 0.18), dist=1.2 * an["length"], lens=35, roll=-58), 0),
                      ("02_front", dict(target=c0, direction=(0, -1, 0), dist=1.6 * an["length"], lens=50, roll=90), 0),
                      ("03_back", dict(target=(-c0[0], -c0[1], c0[2]), direction=(0, -1, 0), dist=1.6 * an["length"], lens=50, roll=-90), 180),
                      ("04_guard", dict(target=V["guard_center"][1], direction=(0.15, -1, 0.08), dist=0.33 * an["length"], lens=50, roll=0), 0),
                      ("05_blade", dict(target=V["junction"][1], direction=(0.2, -1, 0.1), dist=0.44 * an["length"], lens=50, roll=90), 0),
                      ("06_grip", dict(target=V["grip"][1], direction=(0.25, -1, 0.12), dist=0.5 * an["length"], lens=50, roll=90), 0),
                      ("07_wire", dict(target=c0, direction=(0.55, -0.8, 0.18), dist=1.2 * an["length"], lens=35, roll=-58), 0, "wire"),
                      ("08_wire_guard", dict(target=V["guard_center"][1], direction=(0.15, -1, 0.08), dist=0.33 * an["length"], lens=50, roll=0), 0, "wire")]
    P.state["settings"]["media_studio"] = _ensure_studio(bpy.context.scene)
    reshoot(_asset(P) + "_LOD0", out, shots)
    P.state["settings"]["media_dir"] = out; P.save()
    return {"queued": len(shots), "dir": out, "log": os.path.join(out, "reshoot_log.txt"), "next": "s8_media_check"}


def _jpeg_from_png(src, dst, quality=92):
    """PNG -> JPEG with the same colours. Image.save_render applies the scene's view transform: with AgX the
    gallery JPGs came out darker (mean 0.084 -> 0.059 on the dragon hero) - so Standard is set while saving.
    The scene's file format is also set to JPEG (save_render writes the scene format, not im.file_format)."""
    sc = bpy.context.scene; vs = sc.view_settings; ims = sc.render.image_settings
    keep = (vs.view_transform, vs.look, vs.exposure, vs.gamma, ims.file_format, ims.quality, ims.color_mode)
    im = bpy.data.images.load(src, check_existing=False)
    try:
        vs.view_transform = "Standard"; vs.look = "None"; vs.exposure = 0.0; vs.gamma = 1.0
        ims.file_format = "JPEG"; ims.quality = quality; ims.color_mode = "RGB"
        im.save_render(dst, scene=sc)
        return list(im.size)
    finally:
        vs.view_transform, vs.look, vs.exposure, vs.gamma = keep[:4]
        ims.file_format, ims.quality, ims.color_mode = keep[4:]
        bpy.data.images.remove(im)


def s8_media_check(project):
    P = _proj(project); G = Gate("s8_media"); out = P.state["settings"]["media_dir"]
    pngs = sorted(f for f in os.listdir(out) if f.endswith(".png"))
    G.check("images", len(pngs), len(pngs) >= 5, msg="Fab gallery: several angles + wireframe")
    stu = P.state["settings"].get("media_studio") or {}
    G.check("scene_lights", stu.get("lights"), bool(stu.get("lights")), review=True, msg="lights in the render scene (none = black gallery)")
    alb = _albedo_mean(P)                  # 1.4.2: the size/format checks passed on an all-black gallery
    for f in pngs:
        if "wire" in f: continue
        lum, cov = _product_brightness(os.path.join(out, f)); ratio = lum / alb if alb else None
        G.check("brightness_" + f, {"lum": round(lum, 3), "vs_albedo": ratio and round(ratio, 2), "cover": round(cov, 3)},
                bool(ratio and ratio >= 0.6 and cov >= 0.01), review=True,
                msg="lit product as bright as >= 60 % of its BaseColor and >= 1 % of the frame; else lights/exposure are off")
    jdir = os.path.join(out, "jpg"); os.makedirs(jdir, exist_ok=True); tot = 0.0
    for f in pngs:
        jp = os.path.join(jdir, f[:-4] + ".jpg")
        for q in (92, 88, 84):                                   # Fab: < 3 MB per image
            size = _jpeg_from_png(os.path.join(out, f), jp, q)
            if os.path.getsize(jp) < 3.0e6: break
        G.check("res_" + f, size, size[0] >= 1920 and size[1] >= 1080)
        mb = os.path.getsize(jp) / 1e6; tot += mb; G.check("size_" + f, round(mb, 2), mb < 3.0)
        G.image(jp, f)
    G.check("gallery_total_mb", round(tot, 2), tot < 25.0, msg="Fab: 2D gallery images < 25 MB in total")
    G.need_review("gallery", "images show the real product, no defects visible, lava/effects as intended")
    return P.finish("s8_media", G)


# ======================================================================= s9 package + listing
_BLEND_SCENE_SCRIPT = r"""
import bpy, sys, json
src, dst, base = sys.argv[sys.argv.index("--") + 1:][:3]
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
for d in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights, bpy.data.collections):
    for x in list(d): d.remove(x)
with bpy.data.libraries.load(src, link=False) as (a, b): b.objects = list(a.objects)
sc = bpy.context.scene; sc.name = base
top = bpy.data.collections.new(base); lods = bpy.data.collections.new(base + "_LOD1_LOD2"); col = bpy.data.collections.new(base + "_Collision")
sc.collection.children.link(top); top.children.link(lods); top.children.link(col)
for o in b.objects:
    if o is None: continue
    o.use_fake_user = False
    if o.name.startswith("UCX_"): col.objects.link(o); o.display_type = "WIRE"; o.hide_render = True
    elif o.name.endswith("_LOD0"): top.objects.link(o)
    else: lods.objects.link(o)
lc = sc.view_layers[0].layer_collection.children[top.name]
lc.children[lods.name].hide_viewport = True; lc.children[col.name].hide_viewport = True
lods.hide_render = True
for im in bpy.data.images:
    if not im.packed_file: im.pack()
bpy.ops.wm.save_as_mainfile(filepath=dst, compress=True)
bpy.ops.wm.open_mainfile(filepath=dst)
sc = bpy.context.scene
rep = {"scene": sc.name, "objects": sorted(o.name for o in sc.objects),
       "visible": sorted(o.name for o in sc.objects if o.visible_get()),
       "images": {i.name: bool(i.packed_file) for i in bpy.data.images if i.source == "FILE"},   # not Render Result / Viewer Node
       "tris": {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in sc.objects if o.type == "MESH"}}
print("BLEND_SCENE " + json.dumps(rep))
"""


def _blend_scene_file(P, base):
    """s7 writes the .blend with bpy.data.libraries.write: it has no scene, so a buyer who opens it sees nothing.
    Rebuild it (in a separate Blender) as a normal file: LOD0 visible, LOD1/LOD2 and UCX in hidden collections,
    textures packed. The library-only file is kept outside the package folder."""
    import subprocess
    bdir = P.p("export", base, "Blend"); src = os.path.join(bdir, f"{base}.blend")
    bk = P.p("export", "_backup_blend"); os.makedirs(bk, exist_ok=True); lib = os.path.join(bk, f"{base}_library_only.blend")
    if not os.path.exists(lib): shutil.copy2(src, lib)
    scr = os.path.join(bk, "blend_scene.py"); open(scr, "w", encoding="utf-8").write(_BLEND_SCENE_SCRIPT)
    tmp = os.path.join(bk, f"{base}_scene.blend")
    r = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "-P", scr, "--", lib, tmp, base], capture_output=True, text=True, timeout=600)
    line = [l for l in r.stdout.splitlines() if l.startswith("BLEND_SCENE ")]
    if not line: raise RuntimeError("blend scene rebuild failed: " + (r.stdout + r.stderr)[-1500:])
    rep = json.loads(line[0][12:])
    for f in os.listdir(bdir): os.remove(os.path.join(bdir, f))          # only the rebuilt file goes into the package
    shutil.copy2(tmp, src); rep["mb"] = round(os.path.getsize(src) / 1e6, 1)
    return rep


def _textures_2k(root):
    """Textures/2K from Textures/4K (the README and the listing promise both sizes)."""
    d4, d2 = os.path.join(root, "Textures", "4K"), os.path.join(root, "Textures", "2K"); os.makedirs(d2, exist_ok=True); made = []
    for f in sorted(os.listdir(d4)):
        if not f.endswith(".png") or os.path.exists(os.path.join(d2, f)): continue
        im = bpy.data.images.load(os.path.join(d4, f), check_existing=False)
        if f.endswith(("_Normal.png", "_Normal_DX.png", "_ORM.png", "_AO.png")): im.colorspace_settings.name = "Non-Color"
        im.scale(im.size[0] // 2, im.size[1] // 2); im.filepath_raw = os.path.join(d2, f); im.file_format = "PNG"; im.save()
        bpy.data.images.remove(im); made.append(f)
    return made


def _map_has_signal(path, thr=0.02):
    """False when the map is missing or (near) black everywhere."""
    if not os.path.exists(path): return False
    im = bpy.data.images.load(path, check_existing=False); im.scale(256, 256)
    a = np.empty(256 * 256 * 4, np.float32); im.pixels.foreach_get(a); bpy.data.images.remove(im)
    return bool(a.reshape(-1, 4)[:, :3].max() > thr)


def s9_package(project, title=None, price=19.99):
    P = _proj(project); P.require("s8_media"); G = Gate("s9_package"); base = _asset(P)
    title = title or P.state["settings"].get("title", P.name.replace("_", " ").title())
    tris = tuple(sum(len(p.vertices) - 2 for p in bpy.data.objects[f"{base}_LOD{i}"].data.polygons) for i in range(3))
    root = P.p("export", base); pk = P.p("package")
    made2k = _textures_2k(root)
    blend = _blend_scene_file(P, base)
    G.check("blend_scene_lod0_visible", blend["visible"], f"{base}_LOD0" in blend["visible"])
    G.check("blend_textures_packed", blend["images"], bool(blend["images"]) and all(blend["images"].values()))
    n4 = sorted(os.listdir(os.path.join(root, "Textures", "4K"))); n2 = sorted(os.listdir(os.path.join(root, "Textures", "2K")))
    G.check("textures_2k", len(n2), n2 == n4, msg="every 4K map has a 2K copy")
    emi = _map_has_signal(os.path.join(root, "Textures", "4K", f"{P.state['settings'].get('tex_prefix', 'T_' + base[3:])}_Emissive.png"))
    G.data["emissive_used"] = emi
    rep = package(root, pk, base=title.replace(" ", ""), title=title, tris=tris, height_m=P.state["anatomy"].get("height", P.state["anatomy"]["length"]), emissive=emi)
    G.data.update(package=rep, blend=blend, textures_2k_made=made2k)
    zips = [f for f in os.listdir(pk) if f.endswith(".zip")]
    G.check("zips", len(zips), len(zips) >= 2)
    for z in zips:
        mb = os.path.getsize(os.path.join(pk, z)) / 1e6; G.check("zip_" + z, round(mb, 1), mb < 2000)
    G.need_review("listing_text", "title, description, tags, technical specs match the files (write listing.md)")
    return P.finish("s9_package", G)


# ======================================================================= s2 variants (method chosen by evidence)
def _joined_high_copy(P, name):
    import bmesh
    old = bpy.data.objects.get(name)
    if old: me = old.data; bpy.data.objects.remove(old); bpy.data.meshes.remove(me)
    dg = bpy.context.evaluated_depsgraph_get(); bm = bmesh.new()
    for n in _highs(P):
        h = bpy.data.objects[n]; tmp = h.evaluated_get(dg).to_mesh(); tmp.transform(h.matrix_world)
        bm.from_mesh(tmp); h.evaluated_get(dg).to_mesh_clear()
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    coll = bpy.data.collections.get("FORGE_candidates") or bpy.data.collections.new("FORGE_candidates")
    if coll.name not in bpy.context.scene.collection.children: bpy.context.scene.collection.children.link(coll)
    coll.objects.link(ob); ob.hide_render = True
    return ob


def _apply(ob, mod):
    bpy.ops.object.select_all(action="DESELECT"); ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _collapse(ob, target, group=None, factor=1.0, symmetry="auto"):
    tri0 = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    m = ob.modifiers.new("dec", "DECIMATE"); m.decimate_type = "COLLAPSE"; m.ratio = min(1.0, target / max(tri0, 1))
    m.use_symmetry = _decide_symmetry(ob.data, symmetry)[0]; m.symmetry_axis = "X"; m.use_collapse_triangulate = True
    if group: m.vertex_group = group; m.vertex_group_factor = factor
    _apply(ob, m)


def build_candidate(P, method, budget, tag):
    """A: symmetric collapse.  B: voxel remesh -> collapse.  C: importance-weighted collapse
    (blade/grip decimated harder, guard/gem/pommel kept denser).  D: A + protected zones (settings.protect_zones)."""
    an = P.state["anatomy"]; L = an["length"]; name = f"{_asset(P)}_cand_{tag}"
    ob = _joined_high_copy(P, name)
    if method == "B":
        r = ob.modifiers.new("vox", "REMESH"); r.mode = "VOXEL"; r.voxel_size = P.cfg.get("voxel_rel", 0.0007) * L
        r.use_smooth_shade = False; _apply(ob, r)
        _collapse(ob, budget)
    elif method == "C":
        vg = ob.vertex_groups.new(name="decimate_more")
        co = np.empty(len(ob.data.vertices) * 3); ob.data.vertices.foreach_get("co", co); z = co.reshape(-1, 3)[:, 2]
        w = np.where(z < an["guard_z0"], 1.0, np.where(z < an["guard_z1"], 0.15, np.where(z < an["grip_z1"], 0.7, 0.3)))
        for val in np.unique(w):
            idx = np.nonzero(w == val)[0].tolist(); vg.add(idx, float(val), "REPLACE")
        gname = vg.name
        _collapse(ob, budget, group=gname, factor=P.cfg.get("importance_factor", 2.0))
        g = ob.vertex_groups.get(gname)
        if g is not None: ob.vertex_groups.remove(g)
    elif method == "D":
        # A + protection of small precious parts (e.g. a gem): settings.protect_zones = [[x, y, z, radius], ...]
        zones = P.state["settings"].get("protect_zones", [])
        vg = ob.vertex_groups.new(name="decimate_more")
        co = np.empty(len(ob.data.vertices) * 3); ob.data.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        w = np.ones(len(co))
        for zx, zy, zz, zr in zones:
            dd = np.linalg.norm(co - np.array([zx, zy, zz]), axis=1)
            w = np.minimum(w, np.clip(dd / zr, 0.05, 1.0) ** 2)
        for val in np.unique(np.round(w, 2)):
            idx = np.nonzero(np.round(w, 2) == val)[0].tolist(); vg.add(idx, float(val), "REPLACE")
        gname = vg.name
        _collapse(ob, budget, group=gname, factor=P.cfg.get("protect_factor", 1.0))
        g = ob.vertex_groups.get(gname)
        if g is not None: ob.vertex_groups.remove(g)
    else:
        _collapse(ob, budget)
    return ob


def s2_variant(project, method="A", budget=18000, tag=None, high_bvh=None, high_views=None):
    """build + measure one low-poly candidate; nothing is renamed, the s2 gate is not touched."""
    import time as _t
    P = _proj(project); P.require("s1_highpoly"); t0 = _t.time()
    tag = tag or f"{method}_{budget // 1000}k"; th = P.cfg["lowpoly"]; L = _L(P)
    out = P.gate_dir("s2_variants", tag)
    hb = high_bvh or bvh_of(_highs(P))[0]
    ob = build_candidate(P, method, budget, tag); name = ob.name; t_build = _t.time() - t0
    co, tv, _, _, _ = tri_arrays(name)
    tv2, flips = fold_repair(co, tv, hb)
    if flips: replace_mesh(name, co, tv2)
    co, tv, _, _, _ = tri_arrays(name)
    ang, conc, et = dihedral(co, tv); folds = int(((ang > 150) & conc).sum())
    mina = min_angles(co, tv); slivers = int((mina < th["min_angle_deg"]).sum())
    dev, per_tri = deviation(name, _highs(P), n=30000)
    views = [v for v in inspection_views(P.state["anatomy"]) if not _vin(v[0], ("guard_back",))]
    geo = compare_geometry(hb, bvh_object(name), views)
    rep = {"tag": tag, "method": method, "budget": budget, "tris": int(len(tv)), "flips": flips, "folds": folds,
           "fold_rel": round(folds / max(et["n_edges"], 1), 5), "slivers": slivers,
           "nonmanifold": et["n_nonmanifold"], "open_edges": et["n_boundary"],
           "dev_mm": {k: {kk: round(vv * 1000, 3) for kk, vv in v.items()} for k, v in dev.items()},
           "geometry": geo, "geometry_summary": summarize_geometry(geo),
           "seconds": {"build": round(t_build, 1), "total": round(_t.time() - t0, 1)}}
    # critical checks (a high overall score can never hide these)
    crit = []
    if et["n_nonmanifold"] > 0.0005 * et["n_edges"]: crit.append("nonmanifold")
    if rep["fold_rel"] > 3 * th["folds_max_rel"]: crit.append("folds")
    if rep["geometry_summary"].get("silhouette_iou_min", 1) < 0.95: crit.append("silhouette")
    rep["critical_fail"] = crit
    for p in ob.data.polygons: p.use_smooth = False
    kv = [v for v in views if _vin(v[0], ("full_front", "guard_center", "guard_left", "junction", "tip", "pommel"))]
    rep["images"] = render_views({name}, kv, out, "flat", engine="WORKBENCH")
    paint_tris(name, heat(per_tri, th["dev_p99_rel"] * L))
    rep["images"] += render_views({name}, kv[:3], out, "deviation", engine="WORKBENCH", mode="attribute")
    if high_views is None:
        hd = P.gate_dir("s2_variants", "_high"); high_views = render_views(set(_highs(P)), kv, hd, "high", engine="WORKBENCH")
    rep["sheet"] = compare_sheet(high_views, rep["images"][:len(kv)], os.path.join(out, "sheet_high_vs_flat.png"))
    json.dump(rep, open(os.path.join(out, "variant.json"), "w"), indent=2, default=str)
    ob.hide_set(True)
    return rep


S2_DEFAULT_PLAN = (("A", 18000), ("B", 18000), ("C", 18000), ("A", 10000), ("A", 25000))


def _s2_plan(P, plan=None):
    """the plan passed in the call, else settings.s2_plan (e.g. [["A", 18000]] once one method is known to suit this
    kind of weapon: one candidate instead of five), else every default candidate."""
    p = plan or P.state["settings"].get("s2_plan") or S2_DEFAULT_PLAN
    return tuple((str(m), int(b)) for m, b in p)


def s2_variants(project, plan=None):
    """run several candidates and write a comparison table. Ranking is provisional until calibrated:
    1) drop candidates with a critical failure, 2) list the quality numbers, 3) among candidates whose quality is
    within a small margin of the best, prefer the fewest triangles."""
    P = _proj(project); P.require("s1_highpoly"); plan = _s2_plan(P, plan)
    hb = bvh_of(_highs(P))[0]
    kv = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], ("full_front", "guard_center", "guard_left", "junction", "tip", "pommel"))]
    hv = render_views(set(_highs(P)), kv, P.gate_dir("s2_variants", "_high"), "high", engine="WORKBENCH")
    rows = []
    for method, budget in plan:
        try:
            rows.append(s2_variant(project, method, budget, high_bvh=hb, high_views=hv))
        except Exception as e:
            import traceback
            rows.append({"tag": f"{method}_{budget // 1000}k", "error": traceback.format_exc()[-1500:]})
    ok = [r for r in rows if not r.get("error") and not r.get("critical_fail")]
    if ok:
        best_d = min(r["geometry_summary"].get("depth_p95_mm_worst", 9e9) for r in ok)
        best_n = min(r["geometry_summary"].get("normal_p95_deg_worst", 9e9) for r in ok)
        near = [r for r in ok if r["geometry_summary"].get("depth_p95_mm_worst", 9e9) <= 1.2 * best_d + 0.05
                and r["geometry_summary"].get("normal_p95_deg_worst", 9e9) <= 1.15 * best_n + 1.0]
        pick = min(near, key=lambda r: r["tris"]) if near else None
    else:
        pick = None
    summary = {"rows": rows, "provisional_pick": pick["tag"] if pick else None,
               "rule": "critical fails dropped; within 20% depth-p95 and 15% normal-p95 of the best -> fewest tris"}
    d = P.gate_dir("s2_variants")
    json.dump(summary, open(os.path.join(d, "variants.json"), "w"), indent=2, default=str)
    L_ = ["| tag | tris | folds | IoU min | depth p95 worst mm | normal p95 worst deg | dev p99 mm | critical | s |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("error"): L_.append(f"| {r['tag']} | ERROR | | | | | | | |"); continue
        g = r["geometry_summary"]
        L_.append(f"| {r['tag']} | {r['tris']} | {r['folds']} | {g.get('silhouette_iou_min')} | {g.get('depth_p95_mm_worst')} | "
                  f"{g.get('normal_p95_deg_worst')} | {r['dev_mm']['low_to_high']['p99']} | {','.join(r['critical_fail']) or '-'} | {r['seconds']['total']} |")
    L_ += ["", f"provisional pick: **{summary['provisional_pick']}** ({summary['rule']})"]
    open(os.path.join(d, "variants.md"), "w", encoding="utf-8").write("\n".join(L_))
    return summary


def s2_select(project, tag):
    """promote a candidate to <asset>_LOD0 (any existing LOD objects are kept, renamed *_pre_forge) and gate it."""
    P = _proj(project); base = _asset(P)
    for i in range(3):
        o = bpy.data.objects.get(f"{base}_LOD{i}")
        if o: o.name = f"{base}_pre_forge_LOD{i}"; o.hide_render = True
    ob = bpy.data.objects[f"{base}_cand_{tag}"]; ob.hide_set(False)
    P.state["settings"]["s2_pick"] = tag; P.save()
    return s2_lowpoly(project, existing=ob.name)


# ======================================================================= self-test sword (regression / resume tests)
def selftest_make(project="forge_selftest", subdiv=3):
    """builds a small procedural 'high-poly' sword (blade, guard, grip, pommel, gem) in an empty file,
    so the pipeline, the orchestrator and resume can be tested in minutes without a real asset."""
    import bmesh
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    parts = []

    def add(name, verts, faces, sub=subdiv):
        me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces); me.update()
        ob = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(ob)
        m = ob.modifiers.new("sub", "SUBSURF"); m.levels = sub; m.render_levels = sub
        bpy.context.view_layer.objects.active = ob; ob.select_set(True)
        bpy.ops.object.modifier_apply(modifier=m.name); ob.select_set(False); parts.append(name); return ob

    # blade: diamond section, tapered to a point at z=0
    w, t = 0.03, 0.006; z0, z1 = 0.0, 0.70
    V = [(0, 0, z0), (-w, 0, 0.12), (0, -t, 0.12), (w, 0, 0.12), (0, t, 0.12),
         (-w, 0, z1), (0, -t, z1), (w, 0, z1), (0, t, z1)]
    F = [(0, 2, 1), (0, 3, 2), (0, 4, 3), (0, 1, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8), (5, 6, 7, 8)]
    add("st_blade", V, F, sub=2)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.72)); g = bpy.context.active_object; g.name = "st_guard"
    g.scale = (0.22, 0.03, 0.035); bpy.ops.object.transform_apply(scale=True)
    m = g.modifiers.new("sub", "SUBSURF"); m.levels = subdiv; bpy.ops.object.modifier_apply(modifier=m.name); parts.append("st_guard")
    bpy.ops.mesh.primitive_cylinder_add(radius=0.016, depth=0.2, location=(0, 0, 0.84), vertices=48); c = bpy.context.active_object; c.name = "st_grip"
    m = c.modifiers.new("sub", "SUBSURF"); m.levels = 2; bpy.ops.object.modifier_apply(modifier=m.name); parts.append("st_grip")
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, location=(0, 0, 0.96), segments=64, ring_count=32); p = bpy.context.active_object; p.name = "st_pommel"; parts.append("st_pommel")
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.014, location=(0, -0.03, 0.72), segments=64, ring_count=32); ge = bpy.context.active_object; ge.name = "st_gem"; parts.append("st_gem")
    mat = bpy.data.materials.new("st_metal"); mat.use_nodes = True
    bs = mat.node_tree.nodes.get("Principled BSDF")
    if bs: bs.inputs["Metallic"].default_value = 1.0; bs.inputs["Roughness"].default_value = 0.3
    for n in parts:
        o = bpy.data.objects[n]; o.data.materials.append(mat)
        for poly in o.data.polygons: poly.use_smooth = True
    P = Project(project); P.state["settings"].update({"asset": "SM_SelfTest", "tex_prefix": "T_SelfTest", "family": "straight_simple",
                                                       "title": "Forge Self Test"}); P.save()
    return {"parts": parts, "tris": sum(sum(len(pp.vertices) - 2 for pp in bpy.data.objects[n].data.polygons) for n in parts)}


def selftest_make_generic(project="forge_selftest_generic", subdiv=4):
    """1.6.0: a procedural non-weapon 'high poly' (Blender's monkey head on a base, 0.6 m, two colours, open edges at
    the eyes like many AI meshes) so the generic path can be tested in minutes without a real asset."""
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_monkey_add(size=0.5, location=(0, 0, 0.36)); m = bpy.context.active_object; m.name = "st_head"
    md = m.modifiers.new("sub", "SUBSURF"); md.levels = subdiv; bpy.ops.object.modifier_apply(modifier=md.name)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=0.12, location=(0, 0, 0.06), vertices=64); b = bpy.context.active_object; b.name = "st_base"
    md = b.modifiers.new("bev", "BEVEL"); md.width = 0.012; md.segments = 3; bpy.ops.object.modifier_apply(modifier=md.name)
    md = b.modifiers.new("sub", "SUBSURF"); md.levels = 2; bpy.ops.object.modifier_apply(modifier=md.name)
    for ob, col, rough, metal in ((m, (0.55, 0.3, 0.12, 1), 0.55, 0.0), (b, (0.25, 0.27, 0.3, 1), 0.35, 1.0)):
        mat = bpy.data.materials.new(ob.name + "_mat"); mat.use_nodes = True; bs = mat.node_tree.nodes.get("Principled BSDF")
        if bs: bs.inputs["Base Color"].default_value = col; bs.inputs["Roughness"].default_value = rough; bs.inputs["Metallic"].default_value = metal
        ob.data.materials.append(mat)
        for p_ in ob.data.polygons: p_.use_smooth = True
    return {"made": ["st_head", "st_base"], "tris": int(sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in (m, b)))}


def approve_stage(project, stage, who="user", note=""):
    """CLI-callable approval (the self-test approves its own REVIEW items; real projects: the user)."""
    a = Project(project).approve(stage, who=who, note=note)
    return {"approved": stage, "by": who, "time": a["approved"]["time"]}


# ======================================================================= trials: same UV + 1K bake for several candidates
TRIAL_VIEWS = ("full_front", "junction", "blade_mid", "tip", "guard_center", "guard_left", "guard_right", "guard_back", "pommel")


def set_settings(project, **kv):
    """CLI-callable: store project settings (e.g. protect_zones=[[x, y, z, r]])."""
    P = Project(project); P.state["settings"].update(kv); P.save(); return {"settings": list(kv)}


def _diag_metal(name="FORGE_diag_metal", normal_img=None):
    """uniform diagnostic material: grey polished metal, optionally with a tangent normal map only."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bs.inputs["Base Color"].default_value = (0.55, 0.55, 0.57, 1); bs.inputs["Metallic"].default_value = 1.0
    bs.inputs["Roughness"].default_value = 0.22; nt.links.new(bs.outputs[0], out.inputs[0])
    if normal_img is not None:
        tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = normal_img; tx.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(tx.outputs[0], nm.inputs["Color"]); nt.links.new(nm.outputs[0], bs.inputs["Normal"])
    return m


def trial_bake(project, tag, obj=None, size=1024, keep_uv=False, method="forge", cage=None, max_ray=None):
    """copy a candidate, give it the s3 UV/shading recipe, bake at `size` with the s4 settings, and compare it with
    the high poly: lit (final materials) and normal-only (same grey metal; shows lines, creases, wedges)."""
    import time as _t
    P = _proj(project); P.require("s1_highpoly"); t0 = _t.time(); L = _L(P); cfg = P.cfg
    src = obj or f"{_asset(P)}_cand_{tag}"; name = f"{_asset(P)}_trial_{tag}"
    old = bpy.data.objects.get(name)
    if old: me = old.data; bpy.data.objects.remove(old); bpy.data.meshes.remove(me)
    so = bpy.data.objects[src]; ob = so.copy(); ob.data = so.data.copy(); ob.name = name; ob.data.name = name
    for c in so.users_collection: c.objects.link(ob)
    ob.hide_set(False); ob.hide_render = True
    for p in ob.data.polygons: p.use_smooth = True
    for md in list(ob.modifiers): ob.modifiers.remove(md)
    tex = cfg["texture_size"]
    if keep_uv:                                                           # bake the layout the object already has (s3 result)
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL"); wn.keep_sharp = True; wn.weight = 50
    else:                                                                 # the final 4K layout, baked small for speed
        unwrap_object(name, tex=tex, pad_px=cfg["uv_padding_px"], method=method, anatomy=P.state["anatomy"])
    uvr = uv_report(name, tex=tex); her = hard_edge_report(name)
    ua, uC, arrs, regs, _ = uv_audit_object(P, name, "UV_game", tex)
    out = P.p("work", "trials", tag, f"bake_{size}"); pre = f"T_trial_{tag}"
    hook = P.state["settings"].get("before_bake")
    if hook: exec(hook, globals())
    cage = cage or 0.0032 * L; max_ray = max_ray or 0.0095 * L
    start_bake(name, _highs(P), out, prefix=pre, size=size, cage=cage, max_ray=max_ray)
    hook = P.state["settings"].get("after_bake")
    if hook: exec(hook, globals())
    log = open(os.path.join(out, "bake_log.txt")).read()
    game_material([name], out, pre, f"M_trial_{tag}")
    rd = P.gate_dir("trials", tag); views = [v for v in inspection_views(P.state["anatomy"]) if _vin(v[0], TRIAL_VIEWS)]
    hv_dir = P.gate_dir("trials", "_high")
    hl = [os.path.join(hv_dir, f"lit_{v[0]}.png") for v in views]
    if not all(os.path.exists(p) for p in hl):
        hook = P.state["settings"].get("before_bake")                    # high poly without preview overlays
        if hook: exec(hook, globals())
        hl = render_views(set(_highs(P)), views, hv_dir, "lit")
        hook = P.state["settings"].get("after_bake")
        if hook: exec(hook, globals())
    ll = render_views({name}, views, rd, "lit")
    gm = _diag_metal()
    hn = [os.path.join(hv_dir, f"metal_{v[0]}.png") for v in views]
    if not all(os.path.exists(p) for p in hn):
        hn = render_views(set(_highs(P)), views, hv_dir, "metal", override_mat=gm)
    nimg = bpy.data.images.load(os.path.join(out, f"{pre}_Normal.png"), check_existing=True)
    nm = _diag_metal(f"FORGE_diag_metal_{tag}", nimg)
    keep = [s_.material for s_ in ob.material_slots]
    for s_ in ob.material_slots: s_.material = nm
    ln = render_views({name}, views, rd, "metal_normal")
    for s_, m_ in zip(ob.material_slots, keep): s_.material = m_
    flat = render_views({name}, views, rd, "flat_geometry", engine="WORKBENCH")
    im_lit = {v[0]: image_metrics(a, b) for v, a, b in zip(views, hl, ll)}
    im_met = {v[0]: image_metrics(a, b) for v, a, b in zip(views, hn, ln)}
    rep = {"tag": tag, "object": src, "size": size, "tris": sum(len(p.vertices) - 2 for p in ob.data.polygons),
           "uv": uvr, "edges": her, "bake_done": "done" in log,
           "image_lit": im_lit, "image_metal_normal": im_met,
           "sheets": {"lit": compare_sheet(hl, ll, os.path.join(rd, "sheet_lit_high_vs_low.png")),
                      "metal_normal": compare_sheet(hn, ln, os.path.join(rd, "sheet_metal_high_vs_lownormal.png"))},
           "normal_map": os.path.join(out, f"{pre}_Normal.png"), "flat_geometry": flat, "seconds": round(_t.time() - t0, 1),
           "cage_m": cage, "max_ray_m": max_ray, "bake_log": log,
           "uv_audit": {k: v for k, v in ua.items() if k != "definitions"}, "uv_checks": uC,
           "normal_map_stats": normal_map_stats(os.path.join(out, f"{pre}_Normal.png"), arrs[2], regs)}
    json.dump(rep, open(os.path.join(rd, "trial.json"), "w"), indent=2, default=str)
    ledger("trial", project=P.name, tag=tag, size=size, tris=rep["tris"], bake_done=rep["bake_done"],
           ssim_lit_mean=round(float(np.mean([v["ssim"] for v in im_lit.values()])), 4),
           ssim_metal_mean=round(float(np.mean([v["ssim"] for v in im_met.values()])), 4),
           hard_inside=her["hard_edges_inside_islands"], uv_cov=uvr["coverage"], seconds=rep["seconds"])
    ob.hide_set(True)
    return {k: rep[k] for k in ("tag", "tris", "bake_done", "seconds")}


def trial_compare(project, tags, focus=("junction", "tip", "blade_mid", "guard_center", "guard_left", "guard_right")):
    """side-by-side of two (or more) trials on the focus views + a metrics table (no automatic winner:
    the user decides; numbers and pictures are the evidence)."""
    P = _proj(project); rows = {}; d = P.gate_dir("trials")
    for t in tags:
        rows[t] = json.load(open(os.path.join(P.gate_dir("trials", t), "trial.json")))
    L_ = ["| view | " + " | ".join(f"{t} SSIM lit / metal+normal" for t in tags) + " |", "|---|" + "---|" * len(tags)]
    for v in rows[tags[0]]["image_lit"]:
        L_.append(f"| {v} | " + " | ".join(f"{rows[t]['image_lit'][v]['ssim']} / {rows[t]['image_metal_normal'][v]['ssim']}" for t in tags) + " |")
    L_ += ["", "| | " + " | ".join(tags) + " |", "|---|" + "---|" * len(tags)]
    for k in ("tris", "seconds"):
        L_.append(f"| {k} | " + " | ".join(str(rows[t][k]) for t in tags) + " |")
    for k in ("coverage", "islands", "flipped_tris", f"overlap_px@2048"):
        L_.append(f"| uv {k} | " + " | ".join(str(rows[t]["uv"].get(k)) for t in tags) + " |")
    for k in ("hard_edges_inside_islands", "seam_length_on_smooth_m"):
        L_.append(f"| {k} | " + " | ".join(str(rows[t]["edges"].get(k)) for t in tags) + " |")
    sheets = {}
    if len(tags) == 2:
        a, b = tags
        for kind, pref in (("lit", "lit"), ("metal_normal", "metal_normal")):
            la = [os.path.join(P.gate_dir("trials", a), f"{pref}_{v}.png") for v in focus]
            lb = [os.path.join(P.gate_dir("trials", b), f"{pref}_{v}.png") for v in focus]
            sheets[kind] = compare_sheet(la, lb, os.path.join(d, f"AvsB_{kind}_{a}_vs_{b}.png"))
    open(os.path.join(d, "trials.md"), "w", encoding="utf-8").write("\n".join(L_))
    json.dump({"tags": tags, "sheets": sheets}, open(os.path.join(d, "trials.json"), "w"), indent=2)
    ledger("trial_compare", project=P.name, tags=list(tags), sheets=list(sheets.values()))
    return {"table": os.path.join(d, "trials.md"), "sheets": sheets}

def trial_rescore(project, tags, focus=("junction", "tip", "blade_mid", "guard_center", "guard_left", "guard_right", "guard_back", "pommel")):
    """re-measure several trials with the SAME current code (older trial.json files may come from older metrics):
    SSIM/MAE lit and metal+normal per view, normal-map health (overall and per region), and a difference heat image
    per focus view (|high - low| of the metal+normal renders: lines, creases and wedges light up)."""
    P = _proj(project); hv = P.gate_dir("trials", "_high"); out = {}; d = P.gate_dir("trials", "rescore")
    for t in tags:
        td = P.gate_dir("trials", t); r = {"lit": {}, "metal_normal": {}}
        for v in TRIAL_VIEWS:
            for kind, hp, lp in (("lit", f"lit_{v}.png", f"lit_{v}.png"), ("metal_normal", f"metal_{v}.png", f"metal_normal_{v}.png")):
                a = os.path.join(hv, hp); b = os.path.join(td, lp)
                if os.path.exists(a) and os.path.exists(b): r[kind][v] = image_metrics(a, b)
        name = f"{_asset(P)}_trial_{t}"; import glob as _g
        nms = sorted(_g.glob(P.p("work", "trials", t, "bake_*", f"T_trial_{t}_Normal.png"))); nm = nms[-1] if nms else ""
        if bpy.data.objects.get(name) is not None and os.path.exists(nm):
            co, tv, _, uvt, _ = tri_arrays(name, "UV_game")
            if uvt is not None:
                regs = uv_regions(co, tv, P.state["anatomy"], P.state["settings"].get("protect_zones", []))
                r["normal_map"] = normal_map_stats(nm, uvt, regs)
        heat = {}
        for v in focus:
            a = os.path.join(hv, f"metal_{v}.png"); b = os.path.join(td, f"metal_normal_{v}.png")
            if not (os.path.exists(a) and os.path.exists(b)): continue
            A = _gray(a); B = _gray(b); h = min(A.shape[0], B.shape[0]); w = min(A.shape[1], B.shape[1])
            D = np.abs(A[:h, :w] - B[:h, :w]); rgb = (_heat_rgb(D / 0.25) * 255).astype(np.uint8)
            p_ = os.path.join(d, f"diff_{t}_{v}.png"); write_png(p_, rgb[::-1]); heat[v] = p_
        r["diff_heat"] = heat
        r["mean"] = {k: round(float(np.mean([x["ssim"] for x in r[k].values()])), 4) for k in ("lit", "metal_normal") if r[k]}
        out[t] = r
    json.dump(out, open(os.path.join(d, "rescore.json"), "w"), indent=2, default=str)
    L_ = ["| view | " + " | ".join(f"{t} SSIM lit / metal+normal" for t in tags) + " |", "|---|" + "---|" * len(tags)]
    for v in TRIAL_VIEWS:
        L_.append(f"| {v} | " + " | ".join(f"{out[t]['lit'].get(v, {}).get('ssim')} / {out[t]['metal_normal'].get(v, {}).get('ssim')}" for t in tags) + " |")
    L_.append("| mean | " + " | ".join(f"{out[t]['mean'].get('lit')} / {out[t]['mean'].get('metal_normal')}" for t in tags) + " |")
    open(os.path.join(d, "rescore.md"), "w", encoding="utf-8").write("\n".join(L_))
    ledger("trial_rescore", project=P.name, tags=list(tags), means={t: out[t]["mean"] for t in tags})
    return {"table": os.path.join(d, "rescore.md"), "means": {t: out[t]["mean"] for t in tags}}
