"""forge_uv - the high-coverage UV recipe (charts -> LSCM -> fix overlaps -> merge -> FFT packing) in pure numpy.
Port of the proven container tools unwrap_lscm.py + uvpack4.py (74 % coverage, 16 px padding at 4K on the dragon
sword) without scipy/PIL, so it runs inside Blender. Public entry points:
    uv_charts(co, tv, cls=None, ...)  -> per-triangle chart UVs (T,3,2), chart id per triangle
    uv_pack(tri_uv, tv, G=2048, margin=4, ...) -> per-triangle packed UVs in 0..1, report
"""
import numpy as np, heapq, time


def _c2(a, b): return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


# ----------------------------------------------------------------------------- mesh helpers
def _adjacency(tv):
    edges = {}
    for t in range(len(tv)):
        for j in range(3):
            a, b = int(tv[t, j]), int(tv[t, (j + 1) % 3])
            edges.setdefault((min(a, b), max(a, b)), []).append(t)
    nbr = [[] for _ in range(len(tv))]
    for ts in edges.values():
        if len(ts) == 2:
            a, b = ts; nbr[a].append(b); nbr[b].append(a)
    return nbr


def _conn(faces, nbr):
    fs = set(np.asarray(faces).tolist()); seen = set(); out = []
    for f in np.asarray(faces).tolist():
        if f in seen: continue
        st = [f]; seen.add(f); comp = []
        while st:
            x = st.pop(); comp.append(x)
            for g in nbr[x]:
                if g in fs and g not in seen: seen.add(g); st.append(g)
        out.append(np.array(comp))
    return out


def _raster_count(P, res, mode="count"):
    """P (n,3,2) in pixel units. count: pixel coverage counts; own: returns set of overlapping triangle ids."""
    cnt = np.zeros((res, res), np.int32); own = -np.ones((res, res), np.int64); bad = set()
    for i, t in enumerate(P):
        x0, y0 = np.floor(t.min(0)).astype(int); x1, y1 = np.ceil(t.max(0)).astype(int)
        x0 = max(x0, 0); y0 = max(y0, 0); x1 = min(x1, res - 1); y1 = min(y1, res - 1)
        if x1 < x0 or y1 < y0: continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        p0, p1, p2 = t; d = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
        if abs(d) < 1e-12: continue
        l1 = ((p1[1] - p2[1]) * (xs - p2[0]) + (p2[0] - p1[0]) * (ys - p2[1])) / d
        l2 = ((p2[1] - p0[1]) * (xs - p2[0]) + (p0[0] - p2[0]) * (ys - p2[1])) / d
        e = 1e-6; ins = (l1 > e) & (l2 > e) & (1 - l1 - l2 > e)
        yy = ys[ins].astype(int); xx = xs[ins].astype(int)
        if mode == "count":
            np.add.at(cnt, (yy, xx), 1)
        else:
            prev = own[yy, xx]; hit = prev >= 0
            if hit.any(): bad.add(i); bad.update(int(j) for j in np.unique(prev[hit]))
            own[yy, xx] = i
    return cnt if mode == "count" else bad


def self_overlap(tu, res=384):
    P = tu - tu.reshape(-1, 2).min(0); sc = (res - 2) / max(P.reshape(-1, 2).max(), 1e-20)
    return int((_raster_count(P * sc, res) > 1).sum())


def overlap_tris(tu, res=1536):
    P = tu - tu.reshape(-1, 2).min(0); sc = (res - 2) / max(P.reshape(-1, 2).max(), 1e-20)
    return _raster_count(P * sc, res, mode="own")


# ----------------------------------------------------------------------------- LSCM (conjugate gradient, no scipy)
def lscm(co, tv, A3, N, faces, iters=None, tol=1e-9):
    """least-squares conformal map of one chart: vectorised assembly, two pinned vertices, preconditioned conjugate
    gradient (Jacobi) warm-started from the best-fit plane projection (thin or flattened parts converge fast)."""
    faces = np.asarray(faces)
    vs, loc = np.unique(tv[faces], return_inverse=True); loc = loc.reshape(-1, 3); n = len(vs); F = len(faces)
    p = co[tv[faces]]; x_ax = p[:, 1] - p[:, 0]; L = np.linalg.norm(x_ax, axis=1)
    ok = (L > 1e-12) & (A3[faces] > 1e-14)
    x_ax = x_ax / np.maximum(L, 1e-30)[:, None]; y_ax = np.cross(N[faces], x_ax)
    d = p - p[:, :1]; q = np.stack([(d * x_ax[:, None]).sum(2), (d * y_ax[:, None]).sum(2)], 2)     # (F,3,2)
    sd = np.sqrt(2 * np.maximum(A3[faces], 1e-30)); k = np.arange(F)
    R, C, V = [], [], []
    for j in range(3):
        w = (q[:, (j + 2) % 3] - q[:, (j + 1) % 3]) / sd[:, None]; vj = loc[:, j]
        R += [2 * k, 2 * k, 2 * k + 1, 2 * k + 1]; C += [vj, n + vj, vj, n + vj]; V += [w[:, 0], -w[:, 1], w[:, 1], w[:, 0]]
    keep = np.tile(ok, 4 * 3)
    rows = np.concatenate(R)[keep]; cols = np.concatenate(C)[keep]; vals = np.concatenate(V)[keep]; m = 2 * F
    P = co[vs]; c = P - P.mean(0)
    ax3 = np.linalg.svd(c, full_matrices=False)[2]; dd = c @ ax3[0]
    p0, p1 = int(np.argmin(dd)), int(np.argmax(dd)); Lp = np.linalg.norm(P[p1] - P[p0])
    fixed = np.zeros(2 * n, bool); fixed[[p0, p1, n + p0, n + p1]] = True
    # warm start: best-fit plane projection, p0 -> (0,0), p1 -> (Lp,0)
    uv0 = np.stack([c @ ax3[0], c @ ax3[1]], 1); uv0 -= uv0[p0]
    t = uv0[p1]; ang = -np.arctan2(t[1], t[0]); Rm = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    uv0 = uv0 @ Rm.T; uv0 *= Lp / max(np.linalg.norm(uv0[p1]), 1e-30)
    x = np.concatenate([uv0[:, 0], uv0[:, 1]]); x[[p0, n + p0]] = 0.0; x[p1] = Lp; x[n + p1] = 0.0

    def Ax(z): return np.bincount(rows, vals * z[cols], minlength=m)
    def ATy(y): return np.bincount(cols, vals * y[rows], minlength=2 * n)
    diag = np.bincount(cols, vals * vals, minlength=2 * n); Minv = np.where(fixed | (diag <= 0), 0.0, 1.0 / np.maximum(diag, 1e-30))
    xf = np.where(fixed, x, 0.0); z = np.where(fixed, 0.0, x)
    b = -ATy(Ax(xf)); b[fixed] = 0
    r = b - ATy(Ax(z)); r[fixed] = 0
    y = Minv * r; pdir = y.copy(); ry = r @ y; b0 = max(np.sqrt(b @ b), 1e-30)
    for _ in range(iters or max(200, 4 * n)):
        if np.sqrt(r @ r) < tol * b0: break
        Ap = ATy(Ax(pdir)); Ap[fixed] = 0
        alpha = ry / max(pdir @ Ap, 1e-300); z += alpha * pdir; r -= alpha * Ap
        y = Minv * r; ry2 = r @ y
        pdir = y + (ry2 / max(ry, 1e-300)) * pdir; ry = ry2
    x = np.where(fixed, x, z)
    U = np.stack([x[:n], x[n:]], 1)
    return vs, loc, U


def _evaluate(co, tv, A3, N, faces):
    vs, loc, U = lscm(co, tv, A3, N, faces)
    tu = U[loc]; sa = _c2(tu[:, 1] - tu[:, 0], tu[:, 2] - tu[:, 0]) / 2
    if np.sum(sa * (A3[faces] > 1e-12)) < 0: U[:, 1] *= -1; tu = U[loc]; sa = -sa
    flips = int(np.sum((sa < 0) & (A3[faces] > 1e-12)))
    sc = np.sqrt(A3[faces].sum() / max(np.abs(sa).sum(), 1e-20)); tu = tu * sc; U = U * sc
    r = np.abs(sa) * sc * sc / np.maximum(A3[faces], 1e-20); w = A3[faces] / A3[faces].sum()
    spread = float(np.exp(np.sum(w * np.abs(np.log(np.clip(r, 1e-6, None))))))
    return vs, loc, U, tu, sa, flips, spread


def _boundary_crossing(loc, U):
    cnt = {}
    for k in range(len(loc)):
        for j in range(3):
            a, b = loc[k, j], loc[k, (j + 1) % 3]; e = (min(a, b), max(a, b)); cnt[e] = cnt.get(e, 0) + 1
    E = np.array([e for e, c in cnt.items() if c == 1])
    if len(E) < 4: return False
    P, Q = U[E[:, 0]], U[E[:, 1]]
    def orient(a, b, c): return np.sign((b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0]))
    for i0 in range(0, len(E), 400):
        Pi, Qi = P[i0:i0 + 400, None], Q[i0:i0 + 400, None]
        hit = (orient(Pi, Qi, P[None]) * orient(Pi, Qi, Q[None]) < 0) & (orient(P[None], Q[None], Pi) * orient(P[None], Q[None], Qi) < 0)
        Ei = E[i0:i0 + 400]
        share = (Ei[:, None, 0] == E[None, :, 0]) | (Ei[:, None, 0] == E[None, :, 1]) | (Ei[:, None, 1] == E[None, :, 0]) | (Ei[:, None, 1] == E[None, :, 1])
        if (hit & ~share).any(): return True
    return False


def _bad_vertices(loc, U):
    ang = np.zeros(len(U))
    for j in range(3):
        a, b, c = U[loc[:, j]], U[loc[:, (j + 1) % 3]], U[loc[:, (j + 2) % 3]]
        u, v = b - a, c - a
        np.add.at(ang, loc[:, j], np.arctan2(np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]), (u * v).sum(1)))
    return bool((ang > 2 * np.pi + 1e-3).any())


def _flat(co, tv, N, f):
    p = co[tv[f]]; x = p[1] - p[0]; x = x / max(np.linalg.norm(x), 1e-20); y = np.cross(N[f], x)
    return np.stack([(p - p[0]) @ x, (p - p[0]) @ y], 1)[None]


# ----------------------------------------------------------------------------- charts
def uv_charts(co, tv, cls=None, cone_deg=60, sharp_deg=75, min_faces=6, spread_max=1.6, smooth=1, merge_area=0.008,
              texel_check_px_per_m=5800, merge_max_faces=1500, log=print):
    co = np.asarray(co, float); tv = np.asarray(tv); T = len(tv); t0 = time.time()
    cr = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]]); A3 = np.linalg.norm(cr, axis=1) / 2
    N = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-20)
    cls = np.zeros(T, int) if cls is None else np.asarray(cls)
    nbr = _adjacency(tv); cone = np.radians(cone_deg); sharp = np.radians(sharp_deg)

    def grow():
        chart = -np.ones(T, int); cid = 0
        for s in np.argsort(-A3):
            if chart[s] >= 0: continue
            nsum = N[s] * A3[s]; chart[s] = cid; heap = [(-A3[n], n) for n in nbr[s]]; heapq.heapify(heap)
            while heap:
                _, f = heapq.heappop(heap)
                if chart[f] >= 0 or cls[f] != cls[s]: continue
                nav = nsum / max(np.linalg.norm(nsum), 1e-20)
                if N[f] @ nav < np.cos(cone): continue
                if not any(chart[g] == cid and N[f] @ N[g] > np.cos(sharp) for g in nbr[f]): continue
                chart[f] = cid; nsum = nsum + N[f] * A3[f]
                for g in nbr[f]:
                    if chart[g] < 0: heapq.heappush(heap, (-A3[g], g))
            cid += 1
        return chart

    def merge_small(chart):
        for _ in range(3):
            ids, cnt = np.unique(chart, return_counts=True); small = set(ids[cnt < min_faces].tolist())
            if not small: break
            for t in range(T):
                if chart[t] in small:
                    best = None
                    for g in nbr[t]:
                        if chart[g] not in small and cls[g] == cls[t]:
                            d = N[t] @ N[g]
                            if best is None or d > best[0]: best = (d, chart[g])
                    if best: chart[t] = best[1]
        return np.unique(chart, return_inverse=True)[1].ravel()

    chart = merge_small(grow())
    for it in range(smooth):
        nc = chart.max() + 1; cn = np.zeros((nc, 3)); np.add.at(cn, chart, N * A3[:, None])
        cn /= np.maximum(np.linalg.norm(cn, axis=1, keepdims=True), 1e-20)
        for t in range(T):
            labs = [chart[g] for g in nbr[t]]
            for L in set(labs):
                if L != chart[t] and labs.count(L) >= 2 and N[t] @ cn[L] > np.cos(cone + np.radians(10)): chart[t] = L; break
        newc = -np.ones(T, int); k = 0
        for L in range(nc):
            fs = np.nonzero(chart == L)[0]
            for comp in (_conn(fs, nbr) if len(fs) else []): newc[comp] = k; k += 1
        chart = merge_small(newc)
    log(f"charts {chart.max() + 1} ({time.time() - t0:.0f}s)")
    queue = [np.nonzero(chart == c)[0] for c in range(chart.max() + 1)]; final = []; stretch = []; bad = 0
    while queue:
        faces = queue.pop()
        vs, loc, U, tu, sa, flips, spread = _evaluate(co, tv, A3, N, faces)
        pos = sa > 0
        ov = self_overlap(tu[pos], 3072 if len(faces) > 600 else (1536 if len(faces) > 150 else 512)) if pos.sum() > 1 else 0
        if ov == 0 and flips == 0 and 1 < len(faces) < 150:
            ov = int(_bad_vertices(loc, U) or _boundary_crossing(loc, U))
        if ov > 0 and len(faces) > 40 and spread <= spread_max:
            pidx = np.nonzero(pos)[0]
            bt = overlap_tris(tu[pidx], 3072 if len(faces) > 600 else (1536 if len(faces) > 150 else 768))
            badf = set(faces[pidx[list(bt)]].tolist()) | set(faces[~pos].tolist())
            if 0 < len(badf) < 0.1 * len(faces):
                keep = np.array([f for f in faces if f not in badf]); badl = np.array(sorted(badf))
                queue.extend(_conn(keep, nbr)); queue.extend(_conn(badl, nbr)); continue
        if (spread > spread_max and len(faces) > 8) or (ov > 0 and len(faces) > 1):
            C = co[tv[faces]].mean(1); C = C - C.mean(0)
            ax = np.linalg.svd(C * np.sqrt(A3[faces])[:, None], full_matrices=False)[2][0]
            d = C @ ax; lab = d > np.median(d)
            parts = _conn(faces[lab], nbr) + _conn(faces[~lab], nbr)
            big = [p for p in parts if len(p) >= 6]; small = [p for p in parts if len(p) < 6]
            if not big or len(faces) < 12: big, small = parts, []
            owner = {}
            for k, p in enumerate(big):
                for f in p: owner[int(f)] = k
            big = [list(p) for p in big]
            for p in small:
                tgt = next((owner[g] for f in p for g in nbr[f] if g in owner), None)
                if tgt is None: big.append(list(p))
                else: big[tgt] += list(p)
            if max(len(p) for p in big) >= len(faces):
                final.append((faces, tu)); bad += flips; stretch.append(spread); continue
            for p in big: queue.extend(_conn(np.array(p), nbr))
            continue
        final.append((faces, tu)); bad += flips; stretch.append(spread)
    log(f"split/repair: {len(final)} charts ({time.time() - t0:.0f}s)")
    # merge small charts into neighbours when the result is still clean
    tot3 = A3.sum(); owner = -np.ones(T, int)
    for k, (f_, _) in enumerate(final): owner[f_] = k
    alive = [True] * len(final); merged = 0
    for i in sorted([k for k, (f_, _) in enumerate(final) if A3[f_].sum() < merge_area * tot3], key=lambda k: A3[final[k][0]].sum()):
        if not alive[i]: continue
        fi = final[i][0]; cntn = {}
        for f in fi:
            for g in nbr[f]:
                j = owner[g]
                if j != i and j >= 0 and alive[j]: cntn[j] = cntn.get(j, 0) + 1
        cand = [j for j in sorted(cntn, key=lambda j: -cntn[j])[:3] if len(final[j][0]) + len(fi) <= merge_max_faces]
        for j in sorted(cand, key=lambda j: len(final[j][0])):        # cheapest first; big charts are left alone
            U_f = np.concatenate([final[j][0], fi])
            vs, loc, U, tu, sa, flips, spread = _evaluate(co, tv, A3, N, U_f)
            if flips or spread > spread_max or _bad_vertices(loc, U) or _boundary_crossing(loc, U): continue
            final[j] = (U_f, tu); owner[fi] = j; alive[i] = False; merged += 1; break
    final = [final[k] for k in range(len(final)) if alive[k]]
    log(f"merged {merged} small charts ({time.time() - t0:.0f}s)")
    ext = []
    for k, (faces, tu) in enumerate(final):                       # detach remaining flipped triangles
        fl = _c2(tu[:, 1] - tu[:, 0], tu[:, 2] - tu[:, 0]) <= 0
        if fl.any() and not fl.all():
            for f in faces[fl]: ext.append((np.array([f]), _flat(co, tv, N, f)))
            final[k] = (faces[~fl], tu[~fl])
    final += ext; fixed = 0; extra = []
    for k, (faces, tu) in enumerate(final):                       # last overlap validation at ~2x texel density
        if len(faces) < 2: continue
        res = int(np.clip(np.ptp(tu.reshape(-1, 2), 0).max() * texel_check_px_per_m * 2, 64, 4096))
        for _ in range(6):
            bt = overlap_tris(tu, res)
            if not bt: break
            bt = sorted(bt); keep = np.setdiff1d(np.arange(len(faces)), bt)
            for b in bt: extra.append((np.array([faces[b]]), _flat(co, tv, N, faces[b])))
            faces, tu = faces[keep], tu[keep]; fixed += len(bt)
        final[k] = (faces, tu)
    final = [c for c in final if len(c[0])] + extra
    UV = np.zeros((T, 3, 2)); ch = np.zeros(T, int)
    for k, (faces, tu) in enumerate(final): UV[faces] = tu + np.array([k * 10.0, 0]); ch[faces] = k
    rep = {"charts": len(final), "merged": merged, "detached_flips": len(ext), "detached_overlaps": fixed, "flipped": int(bad),
           "spread_median": round(float(np.median(stretch)), 3), "spread_p90": round(float(np.percentile(stretch, 90)), 3),
           "seconds": round(time.time() - t0, 1)}
    log(f"charts final {rep}")
    return UV, ch, rep


# ----------------------------------------------------------------------------- packing (FFT, no scipy/PIL)
def _hull(p):
    p = np.unique(np.round(p, 12), axis=0)
    if len(p) < 3: return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]
    def half(pts):
        h = []
        for q in pts:
            while len(h) >= 2 and _c2(h[-1] - h[-2], q - h[-2]) <= 0: h.pop()
            h.append(q)
        return h
    lo = half(p); up = half(p[::-1])
    return np.array(lo[:-1] + up[:-1])


def _poly_area(h):
    if len(h) < 3: return 0.0
    return 0.5 * abs(np.sum(h[:, 0] * np.roll(h[:, 1], -1) - np.roll(h[:, 0], -1) * h[:, 1]))


def _dilate_disk(m, r):
    """Euclidean dilation: a cell is set when a set cell centre lies within r cells (a diamond/cross dilation only
    gives r/sqrt(2) along diagonals; that is why the old 16 px layout measured 10.5 px)."""
    R = int(np.floor(r)); h, w = m.shape; o = np.zeros_like(m)
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            if dx * dx + dy * dy > r * r: continue
            o[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] |= m[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return o


def _dilate(m, it=1):
    m = m.copy()
    for _ in range(it):
        n = m.copy(); n[1:] |= m[:-1]; n[:-1] |= m[1:]; n[:, 1:] |= m[:, :-1]; n[:, :-1] |= m[:, 1:]; m = n
    return m


def _tri_pixels(P, pad=1.0, thresh=0.0):
    """vectorised raster: all (row, col, tri) whose pixel centre (c+0.5, r+0.5) lies within thresh px of triangle P[i]
    (thresh > 0 grows the triangle, < 0 shrinks it)."""
    lo = np.floor(P.min(1) - pad).astype(np.int64); hi = np.ceil(P.max(1) + pad).astype(np.int64)
    w = hi[:, 0] - lo[:, 0] + 1; h = hi[:, 1] - lo[:, 1] + 1; n = w * h
    tri = np.repeat(np.arange(len(P)), n); k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    cx = lo[tri, 0] + k % w[tri]; cy = lo[tri, 1] + k // w[tri]
    x = cx + 0.5; y = cy + 0.5; a = P[tri, 0]; b = P[tri, 1]; c = P[tri, 2]
    s = np.sign(_c2(b - a, c - a)); s[s == 0] = 1
    def side(p, q):
        e = q - p; L = np.maximum(np.hypot(e[:, 0], e[:, 1]), 1e-12)
        return s * (e[:, 0] * (y - p[:, 1]) - e[:, 1] * (x - p[:, 0])) / L
    d = np.minimum(np.minimum(side(a, b), side(b, c)), side(c, a))
    m = d > -thresh
    return cy[m], cx[m], tri[m]


def _raster_mask(tris, thresh=0.5):
    """mask of triangles (pixel units): a pixel is set when its centre is within `thresh` px of a triangle
    (like PIL polygon fill + outline, as in the old uvpack4)."""
    mn = tris.reshape(-1, 2).min(0); P = tris - mn + 1.0
    w = int(np.ceil(P[..., 0].max())) + 2; h = int(np.ceil(P[..., 1].max())) + 2
    m = np.zeros((h, w), bool); r, c, _ = _tri_pixels(P, 1.0, thresh)
    ok = (r >= 0) & (r < h) & (c >= 0) & (c < w); m[r[ok], c[ok]] = True
    return m, mn - 1.0


def uv_pack(tri_uv, tv, G=2048, margin=4, solidity=0.70, coverage_try=(0.70, 0.68, 0.65, 0.62, 0.60, 0.55, 0.50),
            nrot=4, small_area=0.002, lmax=9.0, mask_thresh=0.71, disk_extra=0.5, min_cov_unsplit=0.60, protect=None, log=print):
    """tri_uv (T,3,2) chart-space UVs (charts separated). Returns packed UVs (T,3,2) in 0..1 and a report.
    margin = half the island gap in grid cells (G=2048, margin 4 -> 8 cells = 16 px at 4K). Pieces are rastered
    conservatively (mask_thresh) and dilated with a Euclidean disk of margin + disk_extra cells.
    solidity 0.70 (was 0.85, lesson 60): green_sword 225 -> 140 islands, look 0.0073 -> 0.0074, coverage 0.62 -> 0.60."""
    t0 = time.time(); TU = np.asarray(tri_uv, float); T = len(TU)
    a2 = np.abs(_c2(TU[:, 1] - TU[:, 0], TU[:, 2] - TU[:, 0])) / 2; A = a2.sum()
    key = np.round(TU * 1e6).astype(np.int64)
    ids = {}; tk = np.zeros((T, 3), np.int64)
    for t in range(T):
        for j in range(3):
            k = (int(tv[t, j]), int(key[t, j, 0]), int(key[t, j, 1])); tk[t, j] = ids.setdefault(k, len(ids))
    cen = TU.mean(1)

    def components(idx):
        idx = np.asarray(idx); par = {int(t): int(t) for t in idx}
        def f(a):
            while par[a] != a: par[a] = par[par[a]]; a = par[a]
            return a
        first = {}
        for t in idx:
            k = tk[t]
            for e in ((k[0], k[1]), (k[1], k[2]), (k[2], k[0])):
                e = (min(e), max(e))
                if e in first:
                    ra, rb = f(int(t)), f(first[e])
                    if ra != rb: par[ra] = rb
                else: first[e] = int(t)
        roots = np.array([f(int(t)) for t in idx])
        return [idx[roots == r] for r in np.unique(roots)]

    def hull_area(idx): return max(_poly_area(_hull(TU[idx].reshape(-1, 2))), 1e-15)

    def split(idx, depth, amin):
        s = a2[idx].sum() / hull_area(idx)
        if s >= solidity or a2[idx].sum() < amin or depth > 7 or len(idx) < 8: return [idx]
        best = None; c = cen[idx]
        for th in np.radians(np.arange(0, 180, 15)):
            d = c @ np.array([np.cos(th), np.sin(th)])
            for q in (0.25, 0.35, 0.5, 0.65, 0.75):
                cut = np.quantile(d, q); Aa, Bb = idx[d < cut], idx[d >= cut]
                if len(Aa) < 4 or len(Bb) < 4: continue
                parts = components(Aa) + components(Bb)
                score = a2[idx].sum() / sum(hull_area(p) for p in parts) - 0.01 * len(parts)
                if best is None or score > best[0]: best = (score, parts)
        if best is None or best[0] <= s + 0.02: return [idx]
        out = []
        for p in best[1]: out += split(p, depth + 1, amin)
        return out

    isl = components(np.arange(T)); pieces = []
    for i in isl: pieces += split(i, 0, A * 0.002)
    LM = lmax / np.sqrt(0.85 / A); q = list(pieces); pieces = []
    while q:
        p = q.pop(); pc = TU[p].reshape(-1, 2); c = pc - pc.mean(0)
        ax = np.linalg.svd(c, full_matrices=False)[2][0]; dd = c @ ax
        if dd.max() - dd.min() <= LM or len(p) < 8: pieces.append(p); continue
        d = cen[p] @ ax; cut = np.median(d); q += components(p[d < cut]) + components(p[d >= cut])
    log(f"islands {len(isl)} pieces {len(pieces)} ({time.time() - t0:.0f}s)")

    def min_rect_angle(idx):
        h = _hull(TU[idx].reshape(-1, 2))
        if len(h) < 3: return 0.0
        best = (1e18, 0.0)
        for i in range(len(h)):
            e = h[(i + 1) % len(h)] - h[i]; th = -np.arctan2(e[1], e[0])
            R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]); qq = h @ R.T
            ar = np.ptp(qq[:, 0]) * np.ptp(qq[:, 1])
            if ar < best[0]: best = (ar, th)
        return best[1]

    rot0 = [min_rect_angle(p) for p in pieces]; GP = G + 2

    def long_side_p(p):
        th = min_rect_angle(p); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        return float(np.ptp(TU[p].reshape(-1, 2) @ R.T, 0).max())

    room = G - 2 * (margin + 3)                                  # cells available for the longest side of a piece
    Lp = [long_side_p(p) for p in pieces]
    def fits(cov): return max(Lp) * np.sqrt(cov / A) * G <= room
    levels = [c for c in coverage_try if fits(c) and c >= min_cov_unsplit]
    long_splits = 0
    if not levels:                                             # a piece is longer than the sheet: cut it across its length
        s_t = np.sqrt(coverage_try[0] / A); q = list(pieces); newp = []
        while q:
            p = q.pop()
            if long_side_p(p) * s_t * G <= room * 0.97 or len(p) < 4: newp.append(p); continue
            pc = TU[p].reshape(-1, 2); c = pc - pc.mean(0); ax = np.linalg.svd(c, full_matrices=False)[2][0]
            d = cen[p] @ ax; cut = np.median(d); long_splits += 1
            parts = components(p[d < cut]) + components(p[d >= cut])
            if len(parts) < 2: newp.append(p); continue
            q += parts
        pieces = newp; rot0 = [min_rect_angle(p) for p in pieces]; Lp = [long_side_p(p) for p in pieces]
        levels = list(coverage_try)
        log(f"split {long_splits} times; pieces {len(pieces)}; still too long (will be scaled down): "
            f"{sum(1 for L in Lp if L * s_t * G > room)}")
    Lp = np.array(Lp)

    def order_for(scale):                                      # very long pieces first (they need a free row), then by area
        lng = Lp * scale * G > 0.5 * G
        return sorted(range(len(pieces)), key=lambda i: (0, -Lp[i]) if lng[i] else (1, -a2[pieces[i]].sum()))
    A_SMALL = small_area * A
    prot = [bool(np.asarray(protect)[p].any()) if protect is not None else False for p in pieces]

    def rot_tris(i, th, scale):
        R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        return (TU[pieces[i]] @ R.T) * scale * G

    def corr(Focc, k):
        K = np.zeros((GP, GP), np.float32); K[:k.shape[0], :k.shape[1]] = k
        return np.fft.irfft2(Focc * np.conj(np.fft.rfft2(K)), s=(GP, GP))

    def pack(scale):
        OCC = np.ones((GP, GP), np.float32); OCC[1:-1, 1:-1] = 0; place = {}; shrunk = 0
        for n, i in enumerate(order_for(scale)):
            Focc = np.fft.rfft2(OCC); best = None
            cap = min(1.0, room * 0.97 / max(Lp[i] * scale * G, 1e-9))   # an unsplittable long sliver is scaled to fit
            for fct in (1.0, 0.85, 0.7, 0.55, 0.4):
                if best is not None: break
                if fct < 1.0 and (a2[pieces[i]].sum() > A_SMALL or prot[i]): break   # critical regions are never shrunk to fit
                sc_i = scale * fct * cap
                for th in [rot0[i] + k * np.pi / (nrot / 2) for k in range(nrot)]:
                    m, mn = _raster_mask(rot_tris(i, th, sc_i), mask_thresh)
                    md = _dilate_disk(np.pad(m, margin + 1), margin + disk_extra); h, w = md.shape
                    if h > G or w > G: continue
                    k = np.pad(md, 1); ring = _dilate(k) & ~k
                    blk = corr(Focc, k.astype(np.float32))[:G - h + 1, :G - w + 1] > 0.5
                    if blk.all(): continue
                    con = corr(Focc, ring.astype(np.float32))[:G - h + 1, :G - w + 1]
                    Y, X = np.mgrid[:G - h + 1, :G - w + 1]
                    score = np.where(blk, -1e9, con / ring.sum() - 0.05 * (Y + h) / G - 0.01 * X / G)
                    y, x = np.unravel_index(np.argmax(score), score.shape)
                    if best is None or score[y, x] > best[0]: best = (score[y, x], y, x, th, md, mn, sc_i)
            if best is None:
                log(f"  piece {i}: tris {len(pieces[i])} area {a2[pieces[i]].sum() / A:.4f} long {Lp[i] * scale * G:.0f} cells cap {cap:.3f} occ {OCC[1:-1, 1:-1].mean():.3f}")
                return None, n
            _, y, x, th, md, mn, sc_i = best; shrunk += sc_i < scale * 0.999
            OCC[1 + y:1 + y + md.shape[0], 1 + x:1 + x + md.shape[1]] = np.maximum(OCC[1 + y:1 + y + md.shape[0], 1 + x:1 + x + md.shape[1]], md)
            place[i] = (y, x, th, mn, sc_i)
        return place, shrunk

    place = None; used = None
    for cov in levels:
        s = np.sqrt(cov / A); t = time.time(); place, info = pack(s)
        log(f"pack coverage {cov:.2f}: {'ok' if place else 'fail at piece %s' % info} ({time.time() - t:.0f}s)")
        if place: used = (cov, s, info); break
    if place is None: raise RuntimeError(f"uv_pack failed at every coverage level {levels}")
    out = np.zeros_like(TU); tri_scale = np.ones(T); shrunk_list = []
    for i, (y, x, th, mn, si) in place.items():
        f = si / used[1]
        if f < 0.999:
            tri_scale[pieces[i]] = f
            shrunk_list.append({"piece": int(i), "tris": int(len(pieces[i])), "factor": round(float(f), 3),
                                "area_share": round(float(a2[pieces[i]].sum() / A), 5), "protected": prot[i],
                                "why": "longer than the sheet" if f < 0.999 and Lp[i] * used[1] * G > room else "no free space at full size"})
        out[pieces[i]] = (rot_tris(i, th, si) - mn + np.array([x + margin + 1, y + margin + 1])) / G
    rep = {"islands": len(isl), "pieces": len(pieces), "long_splits": long_splits, "target_coverage": used[0], "shrunk_pieces": int(used[2]),
           "shrunk": shrunk_list, "_tri_scale": tri_scale, "G": G, "margin_cells": margin, "disk_radius_cells": margin + disk_extra, "mask_thresh": mask_thresh, "seconds": round(time.time() - t0, 1)}
    return out, rep


# ----------------------------------------------------------------------------- audit (pure numpy; the s3 gate evidence)
def _seg_dist(p1, q1, p2, q2):
    """min distance between segments p1q1 and p2q2 (arrays (n,2))."""
    def pt_seg(p, a, b):
        ab = b - a; t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-30), 0, 1)
        return np.linalg.norm(p - (a + ab * t[:, None]), axis=1)
    d = np.minimum(np.minimum(pt_seg(p1, p2, q2), pt_seg(q1, p2, q2)), np.minimum(pt_seg(p2, p1, q1), pt_seg(q2, p1, q1)))
    def orient(a, b, c): return np.sign(_c2(b - a, c - a))
    cross = (orient(p1, q1, p2) * orient(p1, q1, q2) < 0) & (orient(p2, q2, p1) * orient(p2, q2, q1) < 0)
    return np.where(cross, 0.0, d)


def uv_islands_np(tv, uvt):
    """islands = triangles connected through an edge whose two vertices have the same UVs on both sides."""
    T = len(tv); key = np.round(uvt * 1e7).astype(np.int64); par = np.arange(T)
    def f(a):
        while par[a] != a: par[a] = par[par[a]]; a = par[a]
        return a
    first = {}
    for t in range(T):
        for j in range(3):
            a, b = (j, (j + 1) % 3)
            va, vb = int(tv[t, a]), int(tv[t, b])
            ka = (va, key[t, a, 0], key[t, a, 1]); kb = (vb, key[t, b, 0], key[t, b, 1])
            e = (ka, kb) if va < vb else (kb, ka)
            if e in first:
                r1, r2 = f(t), f(first[e])
                if r1 != r2: par[r1] = r2
            else: first[e] = t
    return np.array([f(t) for t in range(T)])


def uv_audit(co, tv, uvt, tex=4096, regions=None, pad_px=16, cfg=None, sharp_deg=45.0):
    """Measure a UV layout. co (V,3), tv (T,3), uvt (T,3,2) in 0..1, regions {name: bool mask (T,)}.
    Every number states its definition. Returns (report, per-check list [(id, value, status, rule)])."""
    cfg = dict(cfg or {}); t0 = time.time()
    co = np.asarray(co, float); tv = np.asarray(tv); uvt = np.asarray(uvt, float); T = len(tv)
    cr = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]]); A3 = np.linalg.norm(cr, axis=1) / 2
    sa = _c2(uvt[:, 1] - uvt[:, 0], uvt[:, 2] - uvt[:, 0]) / 2
    isl = uv_islands_np(tv, uvt); ids, isl = np.unique(isl, return_inverse=True); nI = len(ids)
    # orientation: each island's majority sign; minority = flipped
    sgn = np.sign(sa); flips = 0
    maj = np.zeros(nI)
    np.add.at(maj, isl, np.where(np.abs(sa) > 1e-14, sgn * A3, 0)); flipped = (sgn * np.sign(maj)[isl] < 0) & (np.abs(sa) > 1e-14)
    flips = int(flipped.sum()); zero = int((np.abs(sa) < 1e-12).sum()); mirrored_isl = int((maj < 0).sum())
    inside = bool((uvt >= -1e-6).all() and (uvt <= 1 + 1e-6).all())
    # coverage, two definitions
    cov_area = float(np.abs(sa).sum())                        # old uvpack definition: sum of |UV triangle areas|
    P = uvt * tex; cnt = np.zeros((tex, tex), np.uint8)
    own = -np.ones((tex, tex), np.int32); ovp = set()
    for i, t in enumerate(P):
        x0, y0 = np.floor(t.min(0)).astype(int); x1, y1 = np.ceil(t.max(0)).astype(int)
        x0 = max(x0, 0); y0 = max(y0, 0); x1 = min(x1, tex - 1); y1 = min(y1, tex - 1)
        if x1 < x0 or y1 < y0: continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a, b, c = t; d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12: continue
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d; l3 = 1 - l1 - l2
        e = [np.linalg.norm(c - b), np.linalg.norm(a - c), np.linalg.norm(b - a)]; A2 = abs(d)
        dist = np.minimum(np.minimum(l1 * A2 / max(e[0], 1e-9), l2 * A2 / max(e[1], 1e-9)), l3 * A2 / max(e[2], 1e-9))
        ins = dist > 0.05                                     # pixel centre strictly inside (shared edges not double counted)
        yy = ys[ins].astype(int); xx = xs[ins].astype(int)
        if len(yy) == 0: continue
        prev = own[yy, xx]; hit = prev >= 0
        if hit.any(): ovp.add(i); ovp.update(int(j) for j in np.unique(prev[hit]))
        cnt[yy, xx] = np.minimum(cnt[yy, xx].astype(int) + 1, 255); own[yy, xx] = i
    ov_px = int((cnt > 1).sum()); cov_px = float((cnt > 0).mean())
    ov_isl = len(set(isl[list(ovp)].tolist())) if ovp else 0
    # padding: exact min distance (px at tex) between boundary edges of different islands, and to the texture border
    bnd = {}
    for t in range(T):
        for j in range(3):
            a_, b_ = int(tv[t, j]), int(tv[t, (j + 1) % 3]); k = (min(a_, b_), max(a_, b_))
            bnd.setdefault(k, []).append((t, j))
    segs = []
    for k, lst in bnd.items():
        if len(lst) == 2:
            (t1, j1), (t2, j2) = lst
            if isl[t1] == isl[t2]: continue
        for t, j in lst: segs.append((P[t, j], P[t, (j + 1) % 3], isl[t]))
    S0 = np.array([s[0] for s in segs]); S1 = np.array([s[1] for s in segs]); SI = np.array([s[2] for s in segs])
    R = float(cfg.get("gap_search_px", 24)); cell = R          # pairs closer than R always share a cell
    lo = np.floor((np.minimum(S0, S1) - R / 2) / cell).astype(int); hi = np.floor((np.maximum(S0, S1) + R / 2) / cell).astype(int)
    grid = {}
    for s in range(len(S0)):
        for gx in range(lo[s, 0], hi[s, 0] + 1):
            for gy in range(lo[s, 1], hi[s, 1] + 1): grid.setdefault((gx, gy), []).append(s)
    best = np.full(nI, np.inf); pairs = []
    for lst in grid.values():
        if len(lst) < 2: continue
        a = np.array(lst); I, Jx = np.triu_indices(len(a), 1); m = SI[a[I]] != SI[a[Jx]]
        if m.any(): pairs.append(np.stack([a[I[m]], a[Jx[m]]], 1))
    pairs_a = pairs_b = None
    if pairs:
        pp = np.unique(np.concatenate(pairs), axis=0); pairs_a = [pp[:, 0]]; pairs_b = [pp[:, 1]]
    gap_min = None; gap_hist = {}
    if pairs_a:
        pa = np.concatenate(pairs_a); pb = np.concatenate(pairs_b)
        dd = _seg_dist(S0[pa], S1[pa], S0[pb], S1[pb])
        np.minimum.at(best, SI[pa], dd); np.minimum.at(best, SI[pb], dd)
        gap_min = float(dd.min())
        for lim in (4, 8, 12, 16):
            gap_hist[f"island_pairs_below_{lim}px"] = int(len({(min(SI[x], SI[y]), max(SI[x], SI[y])) for x, y in zip(pa[dd < lim], pb[dd < lim])}))
    border = float(min(P.min(), tex - P.max()))
    # distortion: Jacobian singular values (3D -> UV), area-weighted; texel density in px/cm
    e1 = co[tv[:, 1]] - co[tv[:, 0]]; e2 = co[tv[:, 2]] - co[tv[:, 0]]
    L1 = np.linalg.norm(e1, axis=1); xa = e1 / np.maximum(L1, 1e-20)[:, None]
    nrm = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-20); ya = np.cross(nrm, xa)
    q1 = np.stack([L1, np.zeros(T)], 1); q2 = np.stack([(e2 * xa).sum(1), (e2 * ya).sum(1)], 1)
    u1 = (uvt[:, 1] - uvt[:, 0]) * tex; u2 = (uvt[:, 2] - uvt[:, 0]) * tex
    Q = np.stack([q1, q2], 2); U = np.stack([u1, u2], 2)                      # columns are edges
    good = A3 > 1e-12 * max(A3.max(), 1e-30)
    Qi = np.zeros_like(Q); Qi[good] = np.linalg.inv(Q[good])
    J = U @ Qi; sv = np.linalg.svd(J, compute_uv=False)                      # px per metre
    aniso = sv[:, 0] / np.maximum(sv[:, 1], 1e-12); dens = np.sqrt(np.maximum(sv[:, 0] * sv[:, 1], 0)) / 100.0
    w = np.where(good, A3, 0); w = w / w.sum()
    def wq(v, q, m=None):
        ww = w if m is None else w * m
        if ww.sum() <= 0: return None
        o = np.argsort(v); c = np.cumsum(ww[o]) / ww.sum(); return float(v[o][min(np.searchsorted(c, q), len(v) - 1)])
    td = {"p5": wq(dens, 0.05), "p50": wq(dens, 0.5), "p95": wq(dens, 0.95)}
    dist = {"aniso_p50": wq(aniso, 0.5), "aniso_p95": wq(aniso, 0.95), "aniso_p99": wq(aniso, 0.99),
            "area_stretch_p95_over_p5": (td["p95"] / max(td["p5"], 1e-9)) if td["p5"] else None}
    # sharp feature edges and seams (per region)
    ek = {}
    for t in range(T):
        for j in range(3):
            a_, b_ = int(tv[t, j]), int(tv[t, (j + 1) % 3]); ek.setdefault((min(a_, b_), max(a_, b_)), []).append((t, j))
    sharp_cos = np.cos(np.radians(sharp_deg)); seam_tri = np.zeros(T, bool); sharp_noseam_tri = np.zeros(T, bool)
    seam_len_smooth = 0.0; smooth_cos = np.cos(np.radians(cfg.get("smooth_deg", 35.0)))
    for (a_, b_), lst in ek.items():
        if len(lst) != 2: continue
        (t1, j1), (t2, j2) = lst
        u_a1 = uvt[t1, j1] if tv[t1, j1] == a_ else uvt[t1, (j1 + 1) % 3]; u_b1 = uvt[t1, (j1 + 1) % 3] if tv[t1, j1] == a_ else uvt[t1, j1]
        u_a2 = uvt[t2, j2] if tv[t2, j2] == a_ else uvt[t2, (j2 + 1) % 3]; u_b2 = uvt[t2, (j2 + 1) % 3] if tv[t2, j2] == a_ else uvt[t2, j2]
        seam = np.abs(u_a1 - u_a2).max() > 1e-6 or np.abs(u_b1 - u_b2).max() > 1e-6
        c = float(nrm[t1] @ nrm[t2])
        if seam: seam_tri[[t1, t2]] = True
        if seam and c > smooth_cos: seam_len_smooth += float(np.linalg.norm(co[a_] - co[b_]))
        if c < sharp_cos and not seam: sharp_noseam_tri[[t1, t2]] = True
    reg = {}
    for name, m in (regions or {}).items():
        m = np.asarray(m, bool)
        if not m.any(): reg[name] = {"tris": 0}; continue
        reg[name] = {"tris": int(m.sum()), "islands": int(len(np.unique(isl[m]))),
                     "texel_p50": wq(dens, 0.5, m), "texel_p5": wq(dens, 0.05, m),
                     "texel_p50_vs_global": (wq(dens, 0.5, m) / td["p50"]) if td["p50"] else None,
                     "aniso_p95": wq(aniso, 0.95, m), "flipped": int((flipped & m).sum()),
                     "overlap_tris": int(sum(1 for i in ovp if m[i])),
                     "seam_tri_share": float(seam_tri[m].mean()), "sharp_without_seam_tris": int((sharp_noseam_tri & m).sum())}
    rep = {"definitions": {
        "coverage_area_sum": "sum of |UV triangle area| in 0..1 space (the old uvpack4 '74 %' number)",
        "coverage_raster": f"share of {tex}x{tex} pixel centres strictly inside at least one UV triangle",
        "overlap_px": f"pixel centres at {tex} inside two or more triangles",
        "min_gap_px": f"exact min distance between boundary edges of different islands, px at {tex}",
        "texel_px_per_cm": "sqrt(s1*s2) of the 3D->UV Jacobian, area-weighted quantiles",
        "aniso": "s1/s2 of the Jacobian (1 = conformal, no shape distortion)"},
        "tris": T, "islands": nI, "flipped_tris": flips, "mirrored_islands": mirrored_isl, "zero_area_tris": zero, "inside_0_1": inside,
        "coverage_area_sum": round(cov_area, 4), "coverage_raster": round(cov_px, 4),
        "overlap_px": ov_px, "overlap_tris": len(ovp), "overlap_islands": ov_isl,
        "min_gap_px": None if gap_min is None else round(gap_min, 2), "gap_search_px": R, "border_px": round(border, 2), **gap_hist,
        "texel_px_per_cm": {k: (round(v, 2) if v is not None else None) for k, v in td.items()},
        "distortion": {k: (round(v, 3) if v is not None else None) for k, v in dist.items()},
        "seam_length_on_smooth_m": round(seam_len_smooth, 3), "sharp_edges_without_seam_tris": int(sharp_noseam_tri.sum()),
        "regions": reg, "seconds": round(time.time() - t0, 1)}
    # ---- checks: PASS / FAIL / REVIEW. Thresholds come from cfg (calibrated per family); defaults are provisional.
    th = {"pad_px": pad_px, "pad_review_px": 0.75 * pad_px, "border_px": pad_px / 2, "cov": (0.62, 0.55), "cov_high": 0.80,
          "aniso_p95": (1.35, 1.8), "td_ratio": (2.0, 3.0), "region_td": (0.85, 0.6), **cfg.get("uv_thresholds", {})}
    C = []
    def chk(cid, val, ok, review=False, rule=""):
        C.append((cid, val, "PASS" if ok else ("REVIEW" if review else "FAIL"), rule))
    chk("uv_inside_0_1", inside, inside, rule="all UVs in 0..1")
    chk("uv_flipped_tris", flips, flips == 0, rule="0 triangles with the minority orientation of their island")
    chk("uv_zero_area_tris", zero, zero == 0, rule="0 degenerate UV triangles")
    chk("uv_overlap_px", ov_px, ov_px == 0, rule=f"0 pixel centres shared by two triangles at {tex}")
    g = rep["min_gap_px"]
    chk("uv_min_gap_px", g, g is None or g >= th["pad_px"], review=g is not None and g >= th["pad_review_px"],
        rule=f">= {th['pad_px']} px between islands at {tex} (REVIEW >= {th['pad_review_px']:.0f})")
    chk("uv_border_px", round(border, 2), border >= th["border_px"], rule=f">= {th['border_px']:.0f} px to the texture edge")
    c_ok, c_rev = th["cov"]
    chk("uv_coverage_area_sum", rep["coverage_area_sum"], c_ok <= cov_area <= th["cov_high"], review=cov_area >= c_rev,
        rule=f"{c_ok}-{th['cov_high']} (REVIEW >= {c_rev}); higher is not better (lesson 3)")
    a_ok, a_rev = th["aniso_p95"]; a95 = dist["aniso_p95"]
    chk("uv_distortion_aniso_p95", round(a95, 3), a95 <= a_ok, review=a95 <= a_rev, rule=f"<= {a_ok} (REVIEW <= {a_rev}); provisional, calibrate")
    r_ok, r_rev = th["td_ratio"]; rr = dist["area_stretch_p95_over_p5"] or 99
    chk("uv_texel_spread_p95_p5", round(rr, 3), rr <= r_ok, review=rr <= r_rev, rule=f"<= {r_ok} (REVIEW <= {r_rev})")
    t_ok, t_rev = th["region_td"]
    for name, r in reg.items():
        if not r.get("tris"): continue
        v = r["texel_p50_vs_global"] or 0
        chk(f"region_{name}_texel", round(v, 3), v >= t_ok, review=v >= t_rev, rule=f"median density >= {t_ok} x global (REVIEW >= {t_rev})")
        bad = r["flipped"] + r["overlap_tris"]
        chk(f"region_{name}_clean", bad, bad == 0, rule="no flipped or overlapping triangles in this region")
    return rep, C


# ----------------------------------------------------------------------------- diagnostic images (no PIL)
def write_png(path, rgb):
    """rgb (H,W,3) uint8, row 0 = top."""
    import zlib, struct
    rgb = np.ascontiguousarray(rgb, np.uint8); h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    return path


def _heat_rgb(t):
    t = np.clip(t, 0, 1); return np.stack([t, 1 - np.abs(2 * t - 1), 1 - t], -1)


def uv_diag_pngs(co, tv, uvt, out_prefix, res=2048, regions=None, gap_px_at_tex=None, tex=4096, report=None):
    """three pictures of the layout (V up, as in Blender's UV editor):
       _islands.png  islands in muted colours, overlaps red, pixels of islands closer than the padding magenta
       _texel.png    texel density per triangle: blue = 0.5x median, green = median, red = 1.5x median
       _regions.png  critical regions (blade, gem, guard, grip, pommel, edges) in fixed colours."""
    co = np.asarray(co, float); tv = np.asarray(tv); uvt = np.asarray(uvt, float); T = len(tv)
    isl = np.unique(uv_islands_np(tv, uvt), return_inverse=True)[1]
    P = uvt * res; r, c, t = _tri_pixels(P, 1.0, -0.0)
    ok = (r >= 0) & (r < res) & (c >= 0) & (c < res); r, c, t = r[ok], c[ok], t[ok]
    cnt = np.zeros((res, res), np.int32); np.add.at(cnt, (r, c), 1)
    idr = -np.ones((res, res), np.int64); idr[r, c] = isl[t]
    rng = np.random.default_rng(3); pal = rng.uniform(0.3, 0.75, (isl.max() + 1, 3))
    out = {}
    img = np.full((res, res, 3), 0.07); m = idr >= 0; img[m] = pal[idr[m]]
    if gap_px_at_tex:                                       # islands of another id within the padding distance
        g = max(1, int(round(gap_px_at_tex * res / tex))); near = np.zeros((res, res), bool)
        for dy in range(-g, g + 1):
            for dx in range(-g, g + 1):
                if dx * dx + dy * dy > g * g: continue
                a = idr[max(dy, 0):res + min(dy, 0), max(dx, 0):res + min(dx, 0)]
                b = idr[max(-dy, 0):res + min(-dy, 0), max(-dx, 0):res + min(-dx, 0)]
                near[max(dy, 0):res + min(dy, 0), max(dx, 0):res + min(dx, 0)] |= (a >= 0) & (b >= 0) & (a != b)
        img[near] = (1, 0, 1)
    img[cnt > 1] = (1, 0, 0)
    out["islands"] = write_png(out_prefix + "_islands.png", (img[::-1] * 255).astype(np.uint8))
    cr = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]]); A3 = np.linalg.norm(cr, axis=1) / 2
    d = np.sqrt(np.abs(_c2(uvt[:, 1] - uvt[:, 0], uvt[:, 2] - uvt[:, 0])) / 2 / np.maximum(A3, 1e-20))
    med = np.median(d[A3 > 0]); tcol = _heat_rgb((d / med - 0.5) / 1.0)
    img = np.full((res, res, 3), 0.07); img[r, c] = tcol[t]
    out["texel"] = write_png(out_prefix + "_texel.png", (img[::-1] * 255).astype(np.uint8))
    if regions:
        cols = {"blade": (0.35, 0.55, 0.95), "guard": (0.95, 0.6, 0.2), "gem": (1.0, 0.15, 0.25), "grip": (0.45, 0.8, 0.4),
                "pommel": (0.8, 0.45, 0.9), "edges": (1, 1, 0.2)}
        tc = np.full((T, 3), 0.35)
        for name in ("blade", "guard", "grip", "pommel", "gem", "edges"):
            if name in regions: tc[np.asarray(regions[name], bool)] = cols[name]
        img = np.full((res, res, 3), 0.07); img[r, c] = tc[t]
        out["regions"] = write_png(out_prefix + "_regions.png", (img[::-1] * 255).astype(np.uint8))
    return out
