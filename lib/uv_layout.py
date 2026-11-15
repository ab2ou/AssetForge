"""uv_layout.py - Fab pipeline F2: clean UVs for the game mesh + LODs that share them.

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\uv_layout.py").read())
    rep = unwrap("SM_DragonSword_B_LOD0", tex=4096, margin_px=16)
    rep = lods_from("SM_DragonSword_B_LOD0", "SM_DragonSword_B", targets=(22000, 11000))
"""
import bpy, bmesh
import numpy as np


def _ctx_edit(ob):
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="DESELECT"); ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")


def texel_report(ob, uv_name, tex=4096):
    me = ob.data; me.calc_loop_triangles()
    uv = me.uv_layers[uv_name].data
    co = np.array([v.co for v in me.vertices])
    a3 = []; a2 = []
    for t in me.loop_triangles:
        p = co[list(t.vertices)]; q = np.array([uv[l].uv for l in t.loops])
        a3.append(np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0])) / 2)
        a2.append(abs(np.cross(q[1] - q[0], q[2] - q[0])) / 2)
    a3 = np.array(a3); a2 = np.array(a2)
    dens = np.sqrt(a2 / np.maximum(a3, 1e-12)) * tex / 100      # px per cm
    w = a3 / a3.sum()
    return {"uv_coverage_pct": round(float(a2.sum()) * 100, 1),
            "texel_px_per_cm_median": round(float(np.median(dens)), 1),
            "texel_spread_p10_p90": [round(float(np.percentile(dens, 10)), 1), round(float(np.percentile(dens, 90)), 1)],
            "flipped_or_zero_uv_tris": int((a2 < 1e-12).sum())}


def unwrap(name, tex=4096, margin_px=16, angle=60.0, uv_name="UV_game"):
    ob = bpy.data.objects[name]; me = ob.data
    for u in list(me.uv_layers):
        if u.name != uv_name:
            pass
    uvl = me.uv_layers.get(uv_name) or me.uv_layers.new(name=uv_name)
    me.uv_layers.active = uvl; uvl.active_render = True
    _ctx_edit(ob)
    margin = margin_px / tex
    bpy.ops.uv.smart_project(angle_limit=np.radians(angle), island_margin=margin, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action="SELECT")
    try:
        bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=True, margin_method="FRACTION", margin=margin, shape_method="CONCAVE")
    except TypeError:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    # remove the generator's old UV map from the game mesh (keeps exports clean)
    for u in list(me.uv_layers):
        if u.name != uv_name:
            me.uv_layers.remove(u)
    rep = texel_report(ob, uv_name, tex); rep["islands_margin_px"] = margin_px
    return rep


def lods_from(lod0, base, targets=(22000, 11000)):
    src = bpy.data.objects[lod0]; out = {}
    for i, tgt in enumerate(targets, start=1):
        name = f"{base}_LOD{i}"
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        o = src.copy(); o.data = src.data.copy(); o.name = name; o.data.name = name
        bpy.context.scene.collection.objects.link(o)
        for m in list(o.modifiers):
            o.modifiers.remove(m)
        cur = sum(len(p.vertices) - 2 for p in o.data.polygons)
        md = o.modifiers.new("dec", "DECIMATE"); md.decimate_type = "COLLAPSE"; md.ratio = tgt / cur
        md.use_collapse_triangulate = True; md.delimit = {"UV", "SEAM", "SHARP"}
        bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier="dec")
        wn = o.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL"); wn.keep_sharp = True
        out[name] = {"tris": sum(len(p.vertices) - 2 for p in o.data.polygons)}
    return out


def _uv_overlaps(uv_tris, res=2048):
    """uv_tris: (F,3,2) in 0..1. returns bool per triangle: covers a pixel centre also covered by another."""
    owner = np.full((res, res), -1, np.int64); hit = np.zeros(len(uv_tris), bool)
    P = uv_tris * res
    for i, t in enumerate(P):
        x0, y0 = np.floor(t.min(0)).astype(int); x1, y1 = np.ceil(t.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, res - 1), min(y1, res - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a, b, c = t
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        inside = (l1 > 0) & (l2 > 0) & (1 - l1 - l2 > 0)
        if not inside.any():
            continue
        yy = ys[inside].astype(int); xx = xs[inside].astype(int)
        prev = owner[yy, xx]
        clash = prev[prev >= 0]
        if len(clash):
            hit[i] = True; hit[np.unique(clash)] = True
        owner[yy, xx] = i
    return hit


def unwrap_planar(name, tex=4096, margin_px=12, ny_lim=0.5, uv_name="UV_game",
                  grip=(0.946, 1.137, (-0.0033, -0.0006), 0.035), collars=((0.930, 0.955), (1.128, 1.153))):
    """front/back planar projection (thin weapons), cylindrical grip & collars, smart-project for the rest,
    overlap check, then tight packing. Returns a texel/coverage report."""
    ob = bpy.data.objects[name]; me = ob.data
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for u in list(me.uv_layers):
        me.uv_layers.remove(u)
    uvl = me.uv_layers.new(name=uv_name); me.uv_layers.active = uvl
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.verify()
    M = np.array(ob.matrix_world)
    ax = grip[2]
    groups = {"front": [], "back": [], "cyl": [], "rest": []}
    for f in bm.faces:
        c = M[:3, :3] @ np.array(f.calc_center_median()) + M[:3, 3]
        n = M[:3, :3] @ np.array(f.normal); n /= max(np.linalg.norm(n), 1e-12)
        r = np.hypot(c[0] - ax[0], c[1] - ax[1])
        in_grip = grip[0] <= c[2] <= grip[1] and r < grip[3]
        in_col = any(a <= c[2] <= b for a, b in collars) and r < 0.034
        if (in_grip or in_col) and abs(n[2]) < 0.6:
            groups["cyl"].append(f)
        elif n[1] < -ny_lim:
            groups["front"].append(f)
        elif n[1] > ny_lim:
            groups["back"].append(f)
        else:
            groups["rest"].append(f)
    def wco(v):
        return M[:3, :3] @ np.array(v.co) + M[:3, 3]
    for f in groups["front"]:
        for l in f.loops:
            p = wco(l.vert); l[uv].uv = (p[0], p[2])
    for f in groups["back"]:
        for l in f.loops:
            p = wco(l.vert); l[uv].uv = (-p[0] + 1.0, p[2])          # mirrored, shifted away
    for f in groups["cyl"]:
        ps = [wco(l.vert) for l in f.loops]
        angs = [np.arctan2(p[1] - ax[1], p[0] - ax[0]) for p in ps]
        ref = angs[0]
        angs = [a + 2 * np.pi * round((ref - a) / (2 * np.pi)) for a in angs]   # keep a face on one side of the seam
        for l, p, a in zip(f.loops, ps, angs):
            l[uv].uv = (2.0 + a * 0.021, p[2])                                # u = arc length at r~21 mm
    # overlap check inside the projected groups -> move offenders to "rest"
    for key in ("front", "back"):
        fl = groups[key]
        if not fl:
            continue
        T = np.array([[l[uv].uv[:] for l in f.loops][:3] for f in fl], float)
        mn, mx = T.reshape(-1, 2).min(0), T.reshape(-1, 2).max(0); s = (mx - mn).max()
        hit = _uv_overlaps((T - mn) / s, res=4096)
        keep = [f for f, h in zip(fl, hit) if not h]; move = [f for f, h in zip(fl, hit) if h]
        groups[key] = keep; groups["rest"] += move
    rest_idx = {f.index for f in groups["rest"]}
    counts = {k: len(v) for k, v in groups.items()}
    bm.to_mesh(me); bm.free(); me.update()
    # smart-project only the remaining faces
    _ctx_edit(ob); bpy.ops.mesh.select_all(action="DESELECT"); bpy.ops.object.mode_set(mode="OBJECT")
    for p in me.polygons:
        p.select = p.index in rest_idx
    bpy.ops.object.mode_set(mode="EDIT")
    if rest_idx:
        bpy.ops.uv.smart_project(angle_limit=np.radians(66), island_margin=margin_px / tex, area_weight=0.0,
                                 correct_aspect=True, scale_to_bounds=False)
    bpy.ops.mesh.select_all(action="SELECT"); bpy.ops.uv.select_all(action="SELECT")
    # keep the texel density uniform before packing
    try:
        bpy.ops.uv.average_islands_scale()
    except Exception:
        pass
    try:
        bpy.ops.uv.pack_islands(rotate=True, margin_method="FRACTION", margin=margin_px / tex, shape_method="CONCAVE")
    except TypeError:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin_px / tex)
    bpy.ops.object.mode_set(mode="OBJECT")
    rep = texel_report(ob, uv_name, tex)
    rep["faces"] = counts
    return rep


def pack_custom(name, uv_name="UV_game", tex=4096, margin_px=12):
    """operator-free packer: islands (UV-connected faces) -> uniform texel density -> optional 90deg rotation
    (tall) -> shelf packing into the unit square. Returns coverage/texel report."""
    ob = bpy.data.objects[name]; me = ob.data
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    uvl = bm.loops.layers.uv[uv_name]
    nf = len(bm.faces); parent = list(range(nf))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for e in bm.edges:
        if len(e.link_loops) != 2:
            continue
        l1, l2 = e.link_loops
        # same UV at both ends of the shared edge?
        a1, b1 = l1[uvl].uv, l1.link_loop_next[uvl].uv
        a2, b2 = l2.link_loop_next[uvl].uv, l2[uvl].uv
        if (a1 - a2).length < 1e-6 and (b1 - b2).length < 1e-6:
            ra, rb = find(l1.face.index), find(l2.face.index)
            if ra != rb:
                parent[ra] = rb
    isl = {}
    for f in bm.faces:
        isl.setdefault(find(f.index), []).append(f)
    islands = []
    for faces in isl.values():
        a3 = sum(f.calc_area() for f in faces)
        pts = [l[uvl].uv.copy() for f in faces for l in f.loops]
        a2 = 0.0
        for f in faces:
            q = [l[uvl].uv for l in f.loops]
            for k in range(1, len(q) - 1):
                a2 += abs((q[k] - q[0]).cross(q[k + 1] - q[0])) / 2
        s = np.sqrt(a3 / a2) if a2 > 1e-14 else 1.0
        P = np.array([[p.x, p.y] for p in pts]) * s
        mn = P.min(0); w, h = P.max(0) - mn
        rot = w > h * 1.15                                  # stand islands up -> better shelves
        islands.append({"faces": faces, "s": s, "mn": mn, "w": h if rot else w, "h": w if rot else h, "rot": rot})
    # shelf packing; find the smallest square side by bisection
    def try_pack(side, gap):
        order = sorted(range(len(islands)), key=lambda i: -islands[i]["h"])
        x = y = shelf = 0.0; pos = {}
        for i in order:
            w, h = islands[i]["w"] + gap, islands[i]["h"] + gap
            if w > side:
                return None
            if x + w > side:
                y += shelf; x = 0.0; shelf = 0.0
            if y + h > side:
                return None
            pos[i] = (x, y); x += w; shelf = max(shelf, h)
        return pos
    tot = sum(i["w"] * i["h"] for i in islands)
    lo, hi = np.sqrt(tot), np.sqrt(tot) * 3
    best = None
    for _ in range(30):
        mid = (lo + hi) / 2; gap = mid * margin_px / tex
        p = try_pack(mid, gap)
        if p is None:
            lo = mid
        else:
            hi = mid; best = (mid, p)
    side, pos = best
    for i, isd in enumerate(islands):
        ox, oy = pos[i]
        for f in isd["faces"]:
            for l in f.loops:
                u = (np.array([l[uvl].uv.x, l[uvl].uv.y]) * isd["s"]) - isd["mn"]
                if isd["rot"]:
                    u = np.array([u[1], (isd["h"]) - u[0]])
                u = (u + np.array([ox, oy]) + side * margin_px / tex / 2) / side
                l[uvl].uv = (float(u[0]), float(u[1]))
    bm.to_mesh(me); bm.free(); me.update()
    rep = texel_report(ob, uv_name, tex); rep["islands"] = len(islands)
    return rep


def unwrap_box(name, tex=4096, uv_name="UV_game", grip=(0.946, 1.137, (-0.0033, -0.0006), 0.035),
               collars=((0.930, 0.955), (1.128, 1.153)), margin_px=8):
    """6-direction box projection (+cylinders for grip/collars), overlap offenders -> smart project,
    then operator-free packing."""
    ob = bpy.data.objects[name]; me = ob.data
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for u in list(me.uv_layers):
        me.uv_layers.remove(u)
    uvl = me.uv_layers.new(name=uv_name); me.uv_layers.active = uvl
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.verify(); M = np.array(ob.matrix_world); ax = grip[2]
    groups = {k: [] for k in ("+x", "-x", "+y", "-y", "+z", "-z", "cyl", "rest")}
    offs = {"+x": 0, "-x": 2, "+y": 4, "-y": 6, "+z": 8, "-z": 10}
    def wco(v):
        return M[:3, :3] @ np.array(v.co) + M[:3, 3]
    for f in bm.faces:
        c = M[:3, :3] @ np.array(f.calc_center_median()) + M[:3, 3]
        n = M[:3, :3] @ np.array(f.normal); n /= max(np.linalg.norm(n), 1e-12)
        r = np.hypot(c[0] - ax[0], c[1] - ax[1])
        if ((grip[0] <= c[2] <= grip[1] and r < grip[3]) or any(a <= c[2] <= b for a, b in collars) and r < 0.034) and abs(n[2]) < 0.6:
            groups["cyl"].append(f); continue
        k = int(np.argmax(np.abs(n))); s = "+" if n[k] > 0 else "-"
        groups[s + "xyz"[k]].append(f)
    # ---- label smoothing: majority of neighbours, allowed if the face still sees that axis within 65 deg,
    #      then tiny parts are merged into a compatible neighbour -> few, large islands
    keys = ["+x", "-x", "+y", "-y", "+z", "-z"]
    axv = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}
    lab = {}; fn = {}
    for key in keys:
        for f in groups[key]:
            lab[f.index] = key
    for f in bm.faces:
        n = M[:3, :3] @ np.array(f.normal); fn[f.index] = n / max(np.linalg.norm(n), 1e-12)
    cosl = np.cos(np.radians(65))
    nbrs = {f.index: [g.index for e in f.edges for g in e.link_faces if g.index != f.index] for f in bm.faces if f.index in lab}
    for _ in range(10):
        changed = 0
        for fi, nb in nbrs.items():
            cnt = {}
            for g in nb:
                if g in lab:
                    cnt[lab[g]] = cnt.get(lab[g], 0) + 1
            if not cnt:
                continue
            best = max(cnt, key=cnt.get)
            if best != lab[fi] and cnt[best] >= 2 and np.dot(fn[fi], axv[best]) > cosl:
                lab[fi] = best; changed += 1
        if changed == 0:
            break
    # merge small connected parts (< 40 faces) into the neighbour label they touch most, if compatible
    for _ in range(3):
        par = {fi: fi for fi in lab}
        def fd(a):
            while par[a] != a:
                par[a] = par[par[a]]; a = par[a]
            return a
        for fi, nb in nbrs.items():
            for g in nb:
                if g in lab and lab[g] == lab[fi]:
                    ra, rb = fd(fi), fd(g)
                    if ra != rb:
                        par[ra] = rb
        comps = {}
        for fi in lab:
            comps.setdefault(fd(fi), []).append(fi)
        for c in comps.values():
            if len(c) >= 40:
                continue
            cnt = {}
            for fi in c:
                for g in nbrs[fi]:
                    if g in lab and lab[g] != lab[fi]:
                        cnt[lab[g]] = cnt.get(lab[g], 0) + 1
            for cand in sorted(cnt, key=cnt.get, reverse=True):
                if all(np.dot(fn[fi], axv[cand]) > np.cos(np.radians(75)) for fi in c):
                    for fi in c:
                        lab[fi] = cand
                    break
    for key in keys:
        groups[key] = []
    for f in bm.faces:
        if f.index in lab:
            groups[lab[f.index]].append(f)
    for key, fl in groups.items():
        if key in ("cyl", "rest"):
            continue
        k = "xyz".index(key[1]); a1, a2 = [i for i in range(3) if i != k]
        flip = -1 if key[0] == "-" else 1
        for f in fl:
            for l in f.loops:
                p = wco(l.vert); l[uv].uv = (offs[key] + flip * p[a1], p[a2])
    for f in groups["cyl"]:
        ps = [wco(l.vert) for l in f.loops]
        angs = [np.arctan2(p[1] - ax[1], p[0] - ax[0]) for p in ps]; ref = angs[0]
        angs = [a + 2 * np.pi * round((ref - a) / (2 * np.pi)) for a in angs]
        for l, p, a in zip(f.loops, ps, angs):
            l[uv].uv = (20.0 + a * 0.021, p[2])
    # split every direction group into connected parts (separate islands) and test overlaps per part only
    gid = {}
    for key, fl in groups.items():
        for f in fl:
            gid[f.index] = key
    parent = {f.index: f.index for f in bm.faces}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) == 2 and gid.get(lf[0].index) == gid.get(lf[1].index) and gid.get(lf[0].index) not in (None, "rest"):
            ra, rb = find(lf[0].index), find(lf[1].index)
            if ra != rb:
                parent[ra] = rb
    for key in ("+x", "-x", "+y", "-y", "+z", "-z", "cyl"):
        comps = {}
        for f in groups[key]:
            comps.setdefault(find(f.index), []).append(f)
        keep = []
        for fl in comps.values():
            if len(fl) < 3:
                groups["rest"] += fl; continue
            T = np.array([[l[uv].uv[:] for l in f.loops][:3] for f in fl], float)
            mn = T.reshape(-1, 2).min(0); s = max((T.reshape(-1, 2).max(0) - mn).max(), 1e-9)
            res = int(min(4096, max(64, s / 0.0002)))          # ~0.2 mm pixels
            hit = _uv_overlaps((T - mn) / s, res=res)
            keep += [f for f, h in zip(fl, hit) if not h]; groups["rest"] += [f for f, h in zip(fl, hit) if h]
        groups[key] = keep
    rest_idx = {f.index for f in groups["rest"]}; counts = {k: len(v) for k, v in groups.items()}
    bm.to_mesh(me); bm.free(); me.update()
    if rest_idx:
        _ctx_edit(ob); bpy.ops.mesh.select_all(action="DESELECT"); bpy.ops.object.mode_set(mode="OBJECT")
        for p in me.polygons:
            p.select = p.index in rest_idx
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.uv.smart_project(angle_limit=np.radians(66), island_margin=0.0, area_weight=0.0,
                                 correct_aspect=True, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    rep = pack_custom(name, uv_name, tex, margin_px)
    rep["faces"] = counts
    return rep
