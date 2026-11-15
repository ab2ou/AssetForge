"""forge_mesh - geometry and UV measurements with bpy + numpy only (no scipy).
All functions take object names and work in WORLD space."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


# ------------------------------------------------------------------ arrays
def tri_arrays(name, uv_layer=None, evaluated=False):
    """co (V,3) world, tv (T,3) vertex ids, tl (T,3) loop ids, uv (T,3,2) or None, poly (T,) source polygon."""
    ob = bpy.data.objects[name]
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get(); me = ob.evaluated_get(dg).to_mesh()
    else:
        me = ob.data
    me.calc_loop_triangles()
    M = np.array(ob.matrix_world)
    co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
    T = len(me.loop_triangles)
    tv = np.empty(T * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv); tv = tv.reshape(-1, 3)
    tl = np.empty(T * 3, np.int64); me.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    pi = np.empty(T, np.int64); me.loop_triangles.foreach_get("polygon_index", pi)
    uv = None
    L = me.uv_layers.get(uv_layer) if uv_layer else me.uv_layers.active
    if L is not None:
        a = np.empty(len(me.loops) * 2, np.float64); L.data.foreach_get("uv", a); uv = a.reshape(-1, 2)[tl]
    if evaluated: ob.evaluated_get(dg).to_mesh_clear()
    return co, tv, tl, uv, pi


def tri_normals(co, tv):
    n = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]])
    a = np.linalg.norm(n, axis=1)
    return n / np.maximum(a, 1e-30)[:, None], a / 2


def edge_faces(tv):
    """manifold edge table: E (M,2) vertex ids, F (M,2) faces, opp (M,2) opposite vertex of each face; plus counts."""
    T = len(tv)
    e = np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]])
    opp = np.concatenate([tv[:, 2], tv[:, 0], tv[:, 1]])
    f = np.tile(np.arange(T), 3)
    k = np.sort(e, 1)
    key = k[:, 0] * (int(k.max()) + 1) + k[:, 1]
    order = np.argsort(key, kind="stable"); key = key[order]
    uniq, start, cnt = np.unique(key, return_index=True, return_counts=True)
    two = cnt == 2
    s = start[two]
    i0 = order[s]; i1 = order[s + 1]
    # consistent winding: the two faces of a manifold edge must traverse it in opposite directions
    fwd = e[:, 0] < e[:, 1]; n_incons = int((fwd[i0] == fwd[i1]).sum())
    return {"E": k[i0], "F": np.stack([f[i0], f[i1]], 1), "opp": np.stack([opp[i0], opp[i1]], 1),
            "n_boundary": int((cnt == 1).sum()), "n_nonmanifold": int((cnt > 2).sum()), "n_edges": int(len(uniq)),
            "n_inconsistent_winding": n_incons}


def dihedral(co, tv, et=None):
    """angle between face normals (deg) and concavity flag for every manifold edge."""
    et = et or edge_faces(tv)
    N, _ = tri_normals(co, tv)
    F = et["F"]; E = et["E"]
    ang = np.degrees(np.arccos(np.clip((N[F[:, 0]] * N[F[:, 1]]).sum(1), -1, 1)))
    concave = ((co[et["opp"][:, 1]] - co[E[:, 0]]) * N[F[:, 0]]).sum(1) > 0
    return ang, concave, et


def min_angles(co, tv):
    P = co[tv]; out = np.full(len(tv), 180.0)
    for k in range(3):
        a = P[:, (k + 1) % 3] - P[:, k]; b = P[:, (k + 2) % 3] - P[:, k]
        c = (a * b).sum(1) / np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-30)
        out = np.minimum(out, np.degrees(np.arccos(np.clip(c, -1, 1))))
    return out


# ------------------------------------------------------------------ deviation (BVH, no scipy)
def bvh_of(names):
    """one BVH over several objects (world space, evaluated)."""
    verts = []; polys = []; off = 0
    dg = bpy.context.evaluated_depsgraph_get()
    for n in names:
        ob = bpy.data.objects[n]; me = ob.evaluated_get(dg).to_mesh(); me.calc_loop_triangles()
        M = np.array(ob.matrix_world)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        tv = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv)
        verts.append(co); polys.append(tv.reshape(-1, 3) + off); off += len(co)
        ob.evaluated_get(dg).to_mesh_clear()
    V = np.concatenate(verts); P = np.concatenate(polys)
    return BVHTree.FromPolygons(V.tolist(), P.tolist(), all_triangles=True), V, P


def sample_surface(co, tv, n, seed=0):
    rng = np.random.default_rng(seed)
    _, A = tri_normals(co, tv)
    f = rng.choice(len(tv), n, p=A / A.sum())
    w = rng.dirichlet((1, 1, 1), n)
    return (co[tv[f]] * w[:, :, None]).sum(1), f


def nearest_dist(bvh, pts):
    out = np.empty(len(pts))
    for i, p in enumerate(pts):
        r = bvh.find_nearest(Vector(p))
        out[i] = (r[3] if r[0] is not None else np.inf)
    return out


def deviation(low, highs, n=40000):
    """two-sided surface distance (m). low->high: bulges/folds; high->low: lost detail/silhouette."""
    co, tv, _, _, _ = tri_arrays(low)
    Bh, Vh, Ph = bvh_of(highs); Bl = BVHTree.FromPolygons(co.tolist(), tv.tolist(), all_triangles=True)
    pl, fl = sample_surface(co, tv, n); dl = nearest_dist(Bh, pl)
    ph, _ = sample_surface(Vh, Ph, n, seed=1); dh = nearest_dist(Bl, ph)
    per_tri = np.zeros(len(tv)); np.maximum.at(per_tri, fl, dl)
    q = lambda d: dict({k: float(np.percentile(d, p)) for k, p in (("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))}, mean=float(d.mean()))
    return {"low_to_high": q(dl), "high_to_low": q(dh)}, per_tri


# ------------------------------------------------------------------ UV analysis
def uv_islands(tv, tl, uv):
    """islands = faces connected through edges whose two corners share the same UVs."""
    T = len(tv); parent = np.arange(T)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    key = {}
    q = np.round(uv * 2 ** 20).astype(np.int64)
    for f in range(T):
        for j in range(3):
            a, b = tv[f, j], tv[f, (j + 1) % 3]
            ua, ub = tuple(q[f, j]), tuple(q[f, (j + 1) % 3])
            k = (a, b) if a < b else (b, a)
            sig = (ua, ub) if a < b else (ub, ua)
            g = key.get(k)
            if g is None: key[k] = (f, sig)
            elif g[1] == sig:
                ra, rb = find(f), find(g[0])
                if ra != rb: parent[ra] = rb
    return np.array([find(f) for f in range(T)])


def _raster(uv, res, ids=None, shrink=0.0):
    """count / id raster of UV triangles (pixel centres strictly inside, optional shrink in px)."""
    cnt = np.zeros((res, res), np.int16); idr = np.full((res, res), -1, np.int32)
    Q = uv * res
    for f in range(len(Q)):
        t = Q[f]; x0, y0 = np.floor(t.min(0)).astype(int); x1, y1 = np.ceil(t.max(0)).astype(int)
        x0 = max(x0, 0); y0 = max(y0, 0); x1 = min(x1, res - 1); y1 = min(y1, res - 1)
        if x1 < x0 or y1 < y0: continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a, b, c = t; d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12: continue
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l3 = 1 - l1 - l2
        e = shrink / max(np.abs(d) ** 0.5, 1e-9)
        m = (l1 > e) & (l2 > e) & (l3 > e)
        yy = ys[m].astype(int); xx = xs[m].astype(int)
        cnt[yy, xx] += 1
        if ids is not None: idr[yy, xx] = ids[f]
    return cnt, idr


def uv_report(name, uv_layer="UV_game", tex=4096, res=2048):
    co, tv, tl, uv, _ = tri_arrays(name, uv_layer)
    if uv is None: return {"error": "no uv layer"}
    N, A3 = tri_normals(co, tv)
    sa = ((uv[:, 1, 0] - uv[:, 0, 0]) * (uv[:, 2, 1] - uv[:, 0, 1]) - (uv[:, 2, 0] - uv[:, 0, 0]) * (uv[:, 1, 1] - uv[:, 0, 1])) / 2
    isl = uv_islands(tv, tl, uv)
    # flips: minority orientation inside an island
    flips = 0
    for i in np.unique(isl):
        m = isl == i; s = np.sign(sa[m]); flips += int(min((s > 0).sum(), (s < 0).sum()))
    zero_area = int((np.abs(sa) < 1e-12).sum())
    inside = bool((uv >= -1e-6).all() and (uv <= 1 + 1e-6).all())
    cnt, idr = _raster(uv, res, ids=isl, shrink=0.35)
    overlap_px = int((cnt > 1).sum())
    coverage = float((cnt > 0).mean())
    # padding: smallest gap (px at `tex`) between different islands, checked up to the required padding
    need = int(round(16 * res / tex)) + 1
    gap = None
    occ = idr >= 0
    for g in range(1, need + 1):
        hit = False
        for dy in range(-g, g + 1):
            for dx in (-g, g) if abs(dy) != g else range(-g, g + 1):
                a = idr[max(dy, 0):res + min(dy, 0), max(dx, 0):res + min(dx, 0)]
                b = idr[max(-dy, 0):res + min(-dy, 0), max(-dx, 0):res + min(-dx, 0)]
                if ((a >= 0) & (b >= 0) & (a != b)).any(): hit = True; break
            if hit: break
        if hit: gap = g * tex / res; break
    dens = np.sqrt(np.abs(sa) / np.maximum(A3, 1e-30)) * tex / 100.0     # px per cm
    w = A3 / A3.sum()
    order = np.argsort(dens); cw = np.cumsum(w[order])
    pct = lambda p: float(dens[order][np.searchsorted(cw, p)])
    return {"islands": int(len(np.unique(isl))), "flipped_tris": flips, "zero_area_tris": zero_area,
            "inside_0_1": inside, "overlap_px@%d" % res: overlap_px, "coverage": round(coverage, 4),
            "min_gap_px@%d" % tex: (gap if gap is not None else ">=%d" % (need * tex // res)),
            "texel_px_per_cm": {"p5": round(pct(0.05), 1), "p50": round(pct(0.5), 1), "p95": round(pct(0.95), 1)}}


def hard_edge_report(name, uv_layer="UV_game", smooth_deg=35.0):
    """the line/crease bug: a hard (sharp/flat-shaded) edge whose UVs are continuous breaks the normal map."""
    ob = bpy.data.objects[name]; bm = bmesh.new(); bm.from_mesh(ob.data)
    uvl = bm.loops.layers.uv.get(uv_layer)
    hard_inside = 0; seams = 0; smooth_seam_len = 0.0; hard = 0
    flat_faces = sum(1 for f in bm.faces if not f.smooth)
    for e in bm.edges:
        if len(e.link_faces) != 2: continue
        f1, f2 = e.link_faces
        is_hard = (not e.smooth) or (not f1.smooth) or (not f2.smooth)
        seam = False
        if uvl is not None:
            d1 = {l.vert: l[uvl].uv for l in f1.loops if l.vert in e.verts}
            d2 = {l.vert: l[uvl].uv for l in f2.loops if l.vert in e.verts}
            seam = any((d1[v] - d2[v]).length > 1e-6 for v in d1)
        hard += is_hard; seams += seam
        if is_hard and not seam: hard_inside += 1
        if seam and math.degrees(f1.normal.angle(f2.normal, 0)) < smooth_deg:
            smooth_seam_len += e.calc_length()
    bm.free()
    return {"hard_edges": hard, "hard_edges_inside_islands": hard_inside, "seam_edges": seams,
            "flat_shaded_faces": flat_faces, "seam_length_on_smooth_m": round(smooth_seam_len, 3)}


# ------------------------------------------------------------------ fold repair (edge flips, no UVs yet)
def fold_repair(co, tv, high_bvh, z_skip=None, rounds=6, dev_tol=0.0003):
    """flip the diagonal of folded quads when it lowers the fold cost without increasing deviation."""
    W = np.random.default_rng(0).dirichlet((1, 1, 1), 8)
    tv = tv.copy()

    def nrm(t):
        a, b, c = co[t[0]], co[t[1]], co[t[2]]; n = np.cross(b - a, c - a); L = np.linalg.norm(n)
        return (n / L if L > 0 else n), L / 2

    def dev(t):
        return max(high_bvh.find_nearest(Vector(p))[3] for p in W @ co[list(t)])

    def minang(t):
        P = co[list(t)]; m = 180
        for k in range(3):
            x = P[(k + 1) % 3] - P[k]; y = P[(k + 2) % 3] - P[k]
            m = min(m, math.degrees(math.acos(max(-1, min(1, x @ y / max(np.linalg.norm(x) * np.linalg.norm(y), 1e-30))))))
        return m
    total = 0
    for _ in range(rounds):
        ang, conc, et = dihedral(co, tv)
        E = et["E"]; F = et["F"]; edge_set = {(int(a), int(b)) for a, b in E}
        order = np.argsort(-np.where(conc, ang, ang * 0.5))
        done = set(); flips = 0
        for i in order:
            if ang[i] < 100: break
            f1, f2 = int(F[i, 0]), int(F[i, 1])
            if f1 in done or f2 in done: continue
            u, v = int(E[i, 0]), int(E[i, 1])
            if z_skip is not None and max(co[u, 2], co[v, 2]) > z_skip: continue
            t1 = list(tv[f1]); t2 = list(tv[f2])
            k = [j for j in range(3) if {t1[j], t1[(j + 1) % 3]} == {u, v}]
            if not k: continue
            a, b = t1[k[0]], t1[(k[0] + 1) % 3]; p1 = t1[(k[0] + 2) % 3]
            p2 = [x for x in t2 if x not in (a, b)][0]
            if (min(p1, p2), max(p1, p2)) in edge_set: continue
            nA, nB = [a, p2, p1], [p2, b, p1]
            n1, _ = nrm(t1); nA_n, arA = nrm(nA); nB_n, arB = nrm(nB)
            if min(arA, arB) < 1e-10 or nA_n @ n1 < 0 or nB_n @ n1 < 0: continue
            new_ang = math.degrees(math.acos(max(-1, min(1, nA_n @ nB_n))))
            if new_ang > ang[i] - 10: continue
            if min(minang(nA), minang(nB)) < min(2.0, minang(t1), minang(t2)): continue
            if max(dev(nA), dev(nB)) > max(dev(t1), dev(t2)) + dev_tol: continue
            tv[f1] = nA; tv[f2] = nB; done |= {f1, f2}; flips += 1
            edge_set.discard((u, v)); edge_set.add((min(p1, p2), max(p1, p2)))
        total += flips
        if flips == 0: break
    return tv, total


def drop_duplicate_faces(tv):
    """remove triangles that repeat the same three vertices (decimation artefact): a back-to-back pair (opposite
    winding, a zero-volume fin) is removed completely; same-winding copies keep one. Returns (tv, removed)."""
    tv = np.asarray(tv); key = np.sort(tv, 1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True); inv = inv.ravel()
    keep = np.ones(len(tv), bool)
    for g in np.nonzero(cnt > 1)[0]:
        idx = np.nonzero(inv == g)[0]
        ref = tv[idx[0]]
        def same_winding(t):
            k = int(np.nonzero(t == ref[0])[0][0]); return t[(k + 1) % 3] == ref[1]
        pos = [i for i in idx if same_winding(tv[i])]; neg = [i for i in idx if not same_winding(tv[i])]
        n = min(len(pos), len(neg))
        for i in pos[:n] + neg[:n]: keep[i] = False                 # opposite pairs cancel
        rest = pos[n:] + neg[n:]
        for i in rest[1:]: keep[i] = False                          # same-winding copies: keep one
    return tv[keep], int((~keep).sum())


def merge_tiny_nonmanifold_edges(co, tv, max_len, rounds=3):
    """1.4.9: an edge used by 3+ triangles (non-manifold) and shorter than max_len is a decimation artefact (a tiny
    fin): merge its two vertices at the midpoint, drop the triangles that collapse, compact the vertex list. Longer
    non-manifold edges are left alone. Nothing to merge -> inputs returned unchanged.
    Returns (co, tv, merged_edges, nonmanifold_left)."""
    co = np.array(co, float); tv = np.asarray(tv).copy(); merged = 0
    def _nm(t):
        e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), 1)
        uk, cnt = np.unique(e, axis=0, return_counts=True); return uk[cnt > 2]
    for _ in range(rounds):
        bad = _nm(tv)
        if not len(bad): break
        bad = bad[np.linalg.norm(co[bad[:, 0]] - co[bad[:, 1]], axis=1) <= max_len]
        if not len(bad): break
        par = np.arange(len(co)); used = set(); n0 = merged
        for a, b in bad:
            a = int(a); b = int(b)
            if a in used or b in used: continue                  # one merge per vertex per round (no chains)
            co[a] = (co[a] + co[b]) / 2; par[b] = a; used.update((a, b)); merged += 1
        if merged == n0: break
        tv = par[tv]
        tv = tv[(tv[:, 0] != tv[:, 1]) & (tv[:, 1] != tv[:, 2]) & (tv[:, 0] != tv[:, 2])]
        tv, _ = drop_duplicate_faces(tv)
    if not merged: return np.asarray(co), np.asarray(tv), 0, int(len(_nm(tv)))
    ref = np.unique(tv); remap = -np.ones(len(co), np.int64); remap[ref] = np.arange(len(ref))
    co = co[ref]; tv = remap[tv]
    return co, tv, merged, int(len(_nm(tv)))


def replace_mesh(name, co_world, tv):
    """rebuild an object's mesh from world-space vertices + triangles (keeps object transform & materials)."""
    ob = bpy.data.objects[name]
    Mi = np.array(ob.matrix_world.inverted())
    co = co_world @ Mi[:3, :3].T + Mi[:3, 3]
    me = ob.data; mats = list(me.materials)
    new = bpy.data.meshes.new(me.name + "_tmp")
    new.from_pydata(co.tolist(), [], tv.tolist()); new.update()
    for m in mats: new.materials.append(m)
    old = ob.data; ob.data = new; nm = old.name; bpy.data.meshes.remove(old); new.name = nm
    return ob


# ------------------------------------------------------------------ diagnostics: paint defects onto the model
def paint_tris(name, tri_rgb, attr="FORGE_diag"):
    """per-triangle colours -> a corner colour attribute (shown by Workbench color_type='VERTEX')."""
    ob = bpy.data.objects[name]; me = ob.data; me.calc_loop_triangles()
    if attr in me.color_attributes: me.color_attributes.remove(me.color_attributes[attr])
    ca = me.color_attributes.new(attr, "BYTE_COLOR", "CORNER")
    tl = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    col = np.ones((len(me.loops), 4), np.float32) * np.array([0.6, 0.6, 0.62, 1.0], np.float32)
    rgb = np.asarray(tri_rgb, np.float32)
    for j in range(3): col[tl[:, j], :3] = rgb
    ca.data.foreach_set("color", col.ravel())
    me.color_attributes.active_color = ca
    return attr


def heat(v, vmax):
    """0 -> blue, vmax/2 -> green, >= vmax -> red."""
    t = np.clip(np.asarray(v, float) / max(vmax, 1e-12), 0, 1)
    return np.stack([t, 1 - np.abs(2 * t - 1), 1 - t], 1)


def uv_layout_png(name, path, uv_layer="UV_game", res=1024):
    """UV layout image: islands in muted colours, overlaps in red, background dark."""
    co, tv, tl, uv, _ = tri_arrays(name, uv_layer)
    isl = uv_islands(tv, tl, uv)
    cnt, idr = _raster(uv, res, ids=isl, shrink=0.0)
    rng = np.random.default_rng(3); pal = rng.uniform(0.25, 0.75, (int(isl.max()) + 1, 3))
    img = np.zeros((res, res, 4), np.float32); img[..., 3] = 1; img[..., :3] = 0.08
    m = idr >= 0; img[m, :3] = pal[idr[m]]
    img[cnt > 1, :3] = (1, 0, 0)
    im = bpy.data.images.new("FORGE_uv", res, res, alpha=True); im.pixels.foreach_set(img.ravel())
    im.filepath_raw = path; im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)
    return path


def hard_edge_tris(name, uv_layer="UV_game", smooth_deg=35.0):
    """triangles next to (a) hard edges inside islands -> red, (b) seams on smooth surfaces -> orange."""
    ob = bpy.data.objects[name]; me = ob.data; me.calc_loop_triangles()
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table(); uvl = bm.loops.layers.uv.get(uv_layer)
    bad_poly = {}; 
    for e in bm.edges:
        if len(e.link_faces) != 2: continue
        f1, f2 = e.link_faces
        hard = (not e.smooth) or (not f1.smooth) or (not f2.smooth)
        seam = False
        if uvl is not None:
            d1 = {l.vert: l[uvl].uv for l in f1.loops if l.vert in e.verts}; d2 = {l.vert: l[uvl].uv for l in f2.loops if l.vert in e.verts}
            seam = any((d1[v] - d2[v]).length > 1e-6 for v in d1)
        if hard and not seam: bad_poly[f1.index] = bad_poly[f2.index] = 2
        elif seam and math.degrees(f1.normal.angle(f2.normal, 0)) < smooth_deg:
            bad_poly.setdefault(f1.index, 1); bad_poly.setdefault(f2.index, 1)
    bm.free()
    pi = np.empty(len(me.loop_triangles), np.int64); me.loop_triangles.foreach_get("polygon_index", pi)
    rgb = np.tile(np.array([0.6, 0.6, 0.62]), (len(pi), 1))
    for k, v in bad_poly.items():
        rgb[pi == k] = (1, 0, 0) if v == 2 else (1, 0.55, 0)
    return rgb


def fold_edges(co, tv, cos_lim, pairs=None):
    """edges whose two faces are folded beyond the angle with cosine cos_lim (dot of unit normals < cos_lim).
    Faces of zero area have no normal and are ignored. Returns (mask over pairs, pairs=(fa, fb, edge verts))."""
    if pairs is None:
        V = len(co); T = len(tv); ee = np.sort(np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]]), 1)
        f = np.tile(np.arange(T), 3); key = ee[:, 0] * V + ee[:, 1]; o = np.argsort(key, kind="stable"); k = key[o]
        same = k[1:] == k[:-1]; pairs = (f[o][:-1][same], f[o][1:][same], ee[o][:-1][same])
    fa, fb, _ = pairs
    cr = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]]); ln = np.linalg.norm(cr, axis=1)
    ok = ln > 1e-18; nn = cr / np.maximum(ln, 1e-30)[:, None]
    return ((nn[fa] * nn[fb]).sum(1) < cos_lim) & ok[fa] & ok[fb], pairs


def fold_relax(co0, tv, angle_deg=90.0, rings=(0, 1, 2), iters=30, max_move=0.0003, lam=0.5):
    """local Laplacian relaxation of folded micro-faces. For each entry of rings (tried in order until no fold is
    left): vertices of folded edges + that many neighbour rings are moved towards their neighbour mean, iters times,
    each vertex never further than max_move from its original position. Other vertices are untouched.
    -> (new co, report)."""
    co0 = np.asarray(co0, float); co = co0.copy(); V = len(co); lim = math.cos(math.radians(angle_deg))
    e = np.unique(np.sort(np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]]), 1), axis=0)
    deg = np.bincount(e.ravel(), minlength=V).astype(float)
    bad, pairs = fold_edges(co, tv, lim); b0 = int(bad.sum()); tried = []
    for r in rings:
        if not bad.any(): break
        S = np.zeros(V, bool); S[pairs[2][bad].ravel()] = True
        for _ in range(r):
            hit = S[e[:, 0]] | S[e[:, 1]]; S[e[hit].ravel()] = True
        es = e[S[e[:, 0]] | S[e[:, 1]]]; idx = np.flatnonzero(S)
        for _ in range(iters):
            sm = np.zeros((V, 3))
            for c in range(3):
                sm[:, c] = np.bincount(es[:, 0], co[es[:, 1], c], V) + np.bincount(es[:, 1], co[es[:, 0], c], V)
            co[idx] += lam * (sm[idx] / deg[idx, None] - co[idx])
            dv = co[idx] - co0[idx]; Ln = np.linalg.norm(dv, axis=1); over = Ln > max_move
            co[idx[over]] = co0[idx[over]] + dv[over] * (max_move / Ln[over])[:, None]
        bad, _ = fold_edges(co, tv, lim, pairs); tried.append({"rings": r, "vertices": int(S.sum()), "folds_left": int(bad.sum())})
    mv = np.linalg.norm(co - co0, axis=1)
    return co, {"angle_deg": angle_deg, "folded_edges_before": b0, "folded_edges_after": int(bad.sum()),
                "folded_edges_120_after": int(fold_edges(co, tv, math.cos(math.radians(120)), pairs)[0].sum()),
                "vertices_moved": int((mv > 1e-12).sum()), "max_move_mm": round(float(mv.max()) * 1000, 4),
                "max_move_limit_mm": max_move * 1000, "passes": tried}


def uv_flipped_tris(name, uv_layer="UV_game"):
    """indices of the source polygons of UV triangles with the minority winding of their island."""
    co, tv, tl, uv, pi = tri_arrays(name, uv_layer)
    sa = (uv[:, 1, 0] - uv[:, 0, 0]) * (uv[:, 2, 1] - uv[:, 0, 1]) - (uv[:, 2, 0] - uv[:, 0, 0]) * (uv[:, 1, 1] - uv[:, 0, 1])
    isl = uv_islands(tv, tl, uv); bad = []
    for i in np.unique(isl):
        m_ = np.flatnonzero(isl == i); s = np.sign(sa[m_]); pos, neg = (s > 0).sum(), (s < 0).sum()
        if min(pos, neg): bad += m_[s == (1 if pos < neg else -1)].tolist()
    return sorted(set(int(pi[k]) for k in bad))


def uv_unfold_collapse(name, uv_layer="UV_game", rounds=6):
    """repair UV triangles folded by decimation: the shortest edge of each folded triangle is collapsed (UVs
    interpolated), which removes the small fold; repeated until none is left. Changes a few triangles of the LOD.
    (A UV-only relaxation was tried first and made it worse on the dragon: 7 -> 9 and 7 -> 10.)"""
    import bmesh
    ob = bpy.data.objects[name]; me = ob.data; b0 = len(uv_flipped_tris(name, uv_layer)); t0 = len(me.polygons); r = 0
    bad = uv_flipped_tris(name, uv_layer)
    while bad and r < rounds:
        bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table(); es = set()
        for f in bad:
            if f < len(bm.faces): es.add(min(bm.faces[f].edges, key=lambda e: e.calc_length()))
        bmesh.ops.collapse(bm, edges=list(es), uvs=True); bm.to_mesh(me); bm.free(); me.update()
        bad = uv_flipped_tris(name, uv_layer); r += 1
    return {"flips_before": b0, "flips_after": len(bad), "rounds": r, "polygons": [t0, len(me.polygons)]}


def mirror_symmetry(co, tv, axis=0, n=20000, seed=5):
    """how mirror-symmetric a mesh is about the plane axis=0 (object/world origin): distances (m) from mirrored surface
    samples to the surface. Used to decide whether X-symmetric decimation can help (it is a no-op or harmful otherwise)."""
    from mathutils.bvhtree import BVHTree
    import mathutils
    a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]; ar = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    rng = np.random.default_rng(seed); i = rng.choice(len(tv), n, p=ar / ar.sum()); u = rng.random(n); v = rng.random(n); f = u + v > 1; u[f] = 1 - u[f]; v[f] = 1 - v[f]
    p = a[i] + (b[i] - a[i]) * u[:, None] + (c[i] - a[i]) * v[:, None]; p[:, axis] *= -1
    t = BVHTree.FromPolygons([tuple(x) for x in co], [tuple(map(int, x)) for x in tv], epsilon=0.0)
    d = np.array([t.find_nearest(mathutils.Vector(q))[3] for q in p])
    return {"p50": float(np.percentile(d, 50)), "p99": float(np.percentile(d, 99)), "max": float(d.max())}
