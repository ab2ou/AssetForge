"""forge_look - our own PBR textures for s5, painted in texture space with numpy (no external tools, no AI textures).

1. texel_maps(): every texel of the low poly's UV knows its world position, normal, triangle and part (blade, guard,
   grip, pommel, gem) -> masks never depend on the UV layout and 3D noise is seamless across islands.
2. bake inputs: AO (cavities) and the tangent normal map (curvature = divergence of its x/y inside islands).
3. layers per part (black steel, worn edges, leather wrap, red gem) + lava (blade centre channel, guard horns, gem)
   -> BaseColor (sRGB), ORM (AO, roughness, metallic) and Emissive; edge padding by dilation.
All parameters live in one dict (LOOK_DEFAULT) so a project can override them in settings.look.
"""
import math, time
import numpy as np


LOOK_DEFAULT = {
    "steel": {"base": [0.035, 0.036, 0.04], "rough": 0.38, "rough_var": 0.10, "edge_base": [0.42, 0.42, 0.44], "edge_rough": 0.22,
              "edge_gain": 6.0, "cavity_dark": 0.55, "noise_freq": 40.0},
    "grip": {"base": [0.030, 0.022, 0.018], "rough": 0.62, "metal": 0.0, "noise_freq": 120.0},
    "gem": {"base": [0.55, 0.02, 0.01], "rough": 0.08, "emit": [1.0, 0.08, 0.02], "emit_amount": 0.55},
    "lava": {"crust": [0.10, 0.012, 0.004], "hot": [1.0, 0.22, 0.03], "core": [1.0, 0.55, 0.12],
             "blade_half_width_m": 0.0045, "blade_tip_fade_m": 0.06, "wobble_m": 0.0015, "noise_freq": 25.0,
             "horn_start": 0.62, "horn_emit": 0.35},
}


# ----------------------------------------------------------------------------------------- texel maps
def _tri_pix(P, thresh=0.0):
    """(row, col, tri) of pixel centres inside triangles P (T,3,2) in pixel units (same as forge_uv._tri_pixels)."""
    lo = np.floor(P.min(1) - 1).astype(np.int64); hi = np.ceil(P.max(1) + 1).astype(np.int64)
    w = hi[:, 0] - lo[:, 0] + 1; h = hi[:, 1] - lo[:, 1] + 1; n = w * h
    tri = np.repeat(np.arange(len(P)), n); k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    cx = lo[tri, 0] + k % w[tri]; cy = lo[tri, 1] + k // w[tri]
    x = cx + 0.5; y = cy + 0.5; a = P[tri, 0]; b = P[tri, 1]; c = P[tri, 2]
    cr = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    s = np.sign(cr); s[s == 0] = 1
    def side(p, q):
        e = q - p; L = np.maximum(np.hypot(e[:, 0], e[:, 1]), 1e-12)
        return s * (e[:, 0] * (y - p[:, 1]) - e[:, 1] * (x - p[:, 0])) / L
    d = np.minimum(np.minimum(side(a, b), side(b, c)), side(c, a))
    m = d > -thresh
    return cy[m], cx[m], tri[m], x[m], y[m]


def texel_maps(co, tv, tl, uv, cn, size, chunk=4000):
    """-> dict(idx flat texel index (row = v * size, Blender order), P (n,3) world, N (n,3), tri (n,), size)."""
    Puv = uv[tl] * size; out_i, out_t, out_b = [], [], []
    for s in range(0, len(tv), chunk):
        sl = slice(s, s + chunk); P = Puv[sl]
        r, c, t, x, y = _tri_pix(P, 0.0)
        ok = (r >= 0) & (r < size) & (c >= 0) & (c < size); r, c, t, x, y = r[ok], c[ok], t[ok], x[ok], y[ok]
        a = P[t, 0]; b = P[t, 1]; cc = P[t, 2]
        v0 = b - a; v1 = cc - a; den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]; den = np.where(np.abs(den) < 1e-12, 1e-12, den)
        px = x - a[:, 0]; py = y - a[:, 1]
        w1 = (px * v1[:, 1] - v1[:, 0] * py) / den; w2 = (v0[:, 0] * py - px * v0[:, 1]) / den; w0 = 1 - w1 - w2
        out_i.append(r * size + c); out_t.append(t + s); out_b.append(np.stack([w0, w1, w2], 1))
    idx = np.concatenate(out_i); tri = np.concatenate(out_t); bw = np.concatenate(out_b).astype(np.float32)
    idx, first = np.unique(idx, return_index=True); tri = tri[first]; bw = np.clip(bw[first], 0, 1)
    bw /= np.maximum(bw.sum(1, keepdims=True), 1e-9)
    P = np.einsum("nk,nkc->nc", bw, co[tv[tri]]).astype(np.float32)
    N = np.einsum("nk,nkc->nc", bw, cn[tl[tri]]); N = (N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)).astype(np.float32)
    return {"idx": idx, "P": P, "N": N, "tri": tri, "size": size}


def tangent_frames(co, tv, tl, uv, tm):
    """per texel T, B, N (world) in Blender's convention for tangent-space normal maps (OpenGL, checked against the
    baked map: decoded normals match the high poly better than the low normals, 0.973 vs 0.939)."""
    P0, P1, P2 = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]; U = uv[tl]; du1 = U[:, 1] - U[:, 0]; du2 = U[:, 2] - U[:, 0]
    e1 = P1 - P0; e2 = P2 - P0; r = du1[:, 0] * du2[:, 1] - du2[:, 0] * du1[:, 1]; r = np.where(np.abs(r) < 1e-12, 1e-12, r)
    T = (e1 * du2[:, 1:2] - e2 * du1[:, 1:2]) / r[:, None]; Bt = (e2 * du1[:, 0:1] - e1 * du2[:, 0:1]) / r[:, None]
    t = tm["tri"]; N = tm["N"].astype(np.float64); Tt = T[t] - N * (N * T[t]).sum(1, keepdims=True)
    Tt /= np.maximum(np.linalg.norm(Tt, axis=1, keepdims=True), 1e-12)
    sg = np.sign((np.cross(N, Tt) * Bt[t]).sum(1)); sg[sg == 0] = 1
    return Tt, np.cross(N, Tt) * sg[:, None], N


def gem_dome(tm, spec):
    """the flat AI gem drawn as a round pearl in the textures (no geometry change): texels of the gem face (inside a
    circle in x/z, at |y| in face_abs_y, facing front or back) get the normal of a sphere of radius `sphere_m`.
    spec: {"center": [x, z], "radius_m": r, "sphere_m": R, "face_abs_y": [y0, y1], "edge_m": soft edge}.
    -> (mask, weight 0..1, world normal (n,3), r/R)."""
    P = tm["P"].astype(np.float64); N = tm["N"]; cx, cz = spec["center"]
    dx = P[:, 0] - cx; dz = P[:, 2] - cz; rr = np.hypot(dx, dz); ay = np.abs(P[:, 1]); y0, y1 = spec["face_abs_y"]
    m = (rr < spec["radius_m"]) & (ay > y0) & (ay < y1) & (np.abs(N[:, 1]) > 0.6)
    R = spec["sphere_m"]; q = np.clip(rr / R, 0, 0.995)
    ny = np.sqrt(1 - q ** 2) * np.sign(P[:, 1]); n = np.stack([dx / R, ny, dz / R], 1)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    w = np.clip((spec["radius_m"] - rr) / spec.get("edge_m", 0.0015), 0, 1) * m
    return m, w.astype(np.float32), n, (rr / R).astype(np.float32)


def parts(tm, anatomy, gem_zones=(), gem_ellipsoids=()):
    """part label per texel from the anatomy (z bands) and gems: 0 blade 1 guard 2 grip 3 pommel 4 gem.
    gem_ellipsoids [[cx, cy, cz, rx, ry, rz]] (from add_gem) mark only texels ON the gem surface; gem_zones
    [[x, y, z, r]] (older projects) mark everything inside the sphere."""
    z = tm["P"][:, 2]; an = anatomy; lab = np.zeros(len(z), np.int8)
    lab[(z >= an["guard_z0"]) & (z < an["guard_z1"])] = 1
    lab[(z >= an["grip_z0"]) & (z < an["grip_z1"])] = 2
    lab[z >= an["grip_z1"]] = 3
    if gem_ellipsoids:
        for cx, cy, cz, rx, ry, rz in gem_ellipsoids:
            q = np.linalg.norm((tm["P"] - np.array([cx, cy, cz], np.float32)) / np.array([rx, ry, rz], np.float32), axis=1)
            lab[np.abs(q - 1) < 0.03] = 4
    else:
        for x, y, zz, r in gem_zones:
            lab[np.linalg.norm(tm["P"] - np.array([x, y, zz], np.float32), axis=1) < r] = 4
    return lab


# ----------------------------------------------------------------------------------------- noise
def _hash3(ix, iy, iz, seed):
    h = (ix * 374761393 + iy * 668265263 + iz * 2147483647 + seed * 144665) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def value_noise(P, freq, seed=0):
    q = P.astype(np.float64) * freq; i = np.floor(q).astype(np.int64); f = q - i; f = f * f * (3 - 2 * f)
    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2])
                out = out + w * _hash3(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, seed)
    return out


def fbm(P, freq, octaves=4, seed=0):
    s, a, tot = 0.0, 1.0, 0.0
    for o in range(octaves):
        s = s + a * value_noise(P, freq * 2 ** o, seed + o); tot += a; a *= 0.5
    return (s / tot).astype(np.float32)


# ----------------------------------------------------------------------------------------- inputs from the bake
def curvature_from_normal(nm, valid):
    """nm (H,W,3) tangent normal 0..1, valid (H,W) bool -> divergence of (nx, ny) where both neighbours are valid
    (island borders give 0, never a fake edge)."""
    n = nm[..., :2] * 2 - 1; H, W = valid.shape; cur = np.zeros((H, W), np.float32)
    okx = valid[:, 2:] & valid[:, :-2] & valid[:, 1:-1]; oky = valid[2:, :] & valid[:-2, :] & valid[1:-1, :]
    cur[:, 1:-1] += np.where(okx, (n[:, 2:, 0] - n[:, :-2, 0]) * 0.5, 0)
    cur[1:-1, :] += np.where(oky, (n[2:, :, 1] - n[:-2, :, 1]) * 0.5, 0)
    return cur


def blade_ridge(co, tv, anatomy, bin_m=0.005, deg=4):
    """x of the blade's central ridge per z bin (where the blade is thickest), smoothed -> (z centres, x)."""
    an = anatomy; v = co[np.unique(tv)]; v = v[v[:, 2] < an["guard_z0"]]
    yc = an.get("axis_xy", (0, 0))[1]; zb = np.arange(an["tip_z"], an["guard_z0"] + bin_m, bin_m); xs = []
    for a in zb:
        s = v[(v[:, 2] >= a) & (v[:, 2] < a + bin_m)]
        if len(s) < 3: xs.append(np.nan); continue
        t = np.abs(s[:, 1] - yc); top = s[t >= np.percentile(t, 85)]
        xs.append(float(np.median(top[:, 0])))
    xs = np.array(xs); zc = zb + bin_m / 2; good = ~np.isnan(xs)
    keep = good.copy()                                  # robust smooth curve: polynomial fit, outliers (spikes) rejected
    for _ in range(4):
        c = np.polyfit(zc[keep], xs[keep], deg); r = np.abs(xs - np.polyval(c, zc))
        thr = max(2.5 * np.median(r[keep]), 0.001); keep = good & (r < thr)
    return zc, np.polyval(c, zc)


# ----------------------------------------------------------------------------------------- painting
def _srgb(c):
    c = np.clip(c, 0, 1); return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def paint(tm, lab, ao, curv, ridge, anatomy, look=None, gem_rr=None):
    """-> dict of per-texel arrays: base (n,3 linear), rough, metal, emit (n,3 linear 0..1), masks for the report."""
    L = {k: dict(v) for k, v in LOOK_DEFAULT.items()}
    for k, v in (look or {}).items(): L.setdefault(k, {}).update(v)
    P = tm["P"]; n = len(P); an = anatomy; st = L["steel"]
    base = np.zeros((n, 3), np.float32); rough = np.zeros(n, np.float32); metal = np.zeros(n, np.float32); emit = np.zeros((n, 3), np.float32)
    nz = fbm(P, st["noise_freq"], 4, 1); nz2 = fbm(P, st["noise_freq"] * 4, 3, 7)
    edge = np.clip(curv * st["edge_gain"], 0, 1) * (0.6 + 0.4 * nz2)                 # convex edges: worn bright steel
    cav = np.clip(1 - ao, 0, 1)                                                        # cavities: darker, rougher
    metal_parts = (lab == 0) | (lab == 1) | (lab == 3)
    b0 = np.array(st["base"], np.float32) * (0.8 + 0.4 * nz)[:, None]
    bs = b0 * (1 - edge[:, None]) + np.array(st["edge_base"], np.float32) * edge[:, None]
    bs *= (1 - st["cavity_dark"] * cav)[:, None]
    base[metal_parts] = bs[metal_parts]; metal[metal_parts] = 1.0
    rough[metal_parts] = (st["rough"] + st["rough_var"] * (nz - 0.5) * 2) [metal_parts] * (1 - edge[metal_parts]) + st["edge_rough"] * edge[metal_parts]
    rough[metal_parts] += 0.25 * cav[metal_parts]
    g = L["grip"]; gm = lab == 2; ng = fbm(P[gm], g["noise_freq"], 3, 3)
    base[gm] = np.array(g["base"], np.float32) * (0.75 + 0.5 * ng)[:, None] * (1 - 0.5 * cav[gm])[:, None]
    rough[gm] = g["rough"] + 0.1 * (ng - 0.5); metal[gm] = g["metal"]
    # ---- lava: blade centre channel (both faces), tapering to the tip, wobbling with noise
    lv = L["lava"]; lava = np.zeros(n, np.float32)
    bm = lab == 0
    if bm.any():
        xr = np.interp(P[bm, 2], ridge[0], ridge[1]); wob = (fbm(P[bm], lv["noise_freq"], 3, 11) - 0.5) * 2 * lv["wobble_m"]
        d = np.abs(P[bm, 0] - xr - wob)
        taper = np.clip((P[bm, 2] - an["tip_z"]) / lv["blade_tip_fade_m"], 0, 1)
        hw = lv["blade_half_width_m"] * (0.35 + 0.65 * taper)
        lava[bm] = np.clip(1 - d / np.maximum(hw, 1e-5), 0, 1) ** 0.7 * np.clip(taper * 3, 0, 1)
    # ---- guard horns: outer part heats up (red, slight glow)
    gu = lab == 1; ax = an.get("axis_xy", (0, 0))[0]
    if gu.any():
        rr = np.abs(P[gu, 0] - ax) / an["guard_half_width"]
        heat = np.clip((rr - lv["horn_start"]) / (1 - lv["horn_start"]), 0, 1) ** 1.5 * (0.7 + 0.3 * fbm(P[gu], lv["noise_freq"], 3, 5))
        lava[gu] = np.maximum(lava[gu], heat * 0.8)
    crack = fbm(P, lv["noise_freq"] * 3, 3, 21)
    hot = np.clip(lava * (0.75 + 0.5 * crack), 0, 1)
    col = np.array(lv["crust"], np.float32)[None] * (1 - hot[:, None]) + np.array(lv["hot"], np.float32)[None] * hot[:, None]
    col = col * (1 - np.clip(hot - 0.7, 0, 1)[:, None] / 0.3) + np.array(lv["core"], np.float32)[None] * (np.clip(hot - 0.7, 0, 1) / 0.3)[:, None]
    k = np.clip(lava * 1.6, 0, 1)
    base = base * (1 - k[:, None]) + col * k[:, None]; metal = metal * (1 - k); rough = rough * (1 - k) + 0.75 * k
    glow = hot.copy(); glow[gu] *= lv["horn_emit"]
    emit = np.array(lv["hot"], np.float32)[None] * glow[:, None]
    emit = emit * (1 - np.clip(hot - 0.7, 0, 1)[:, None] / 0.3) + np.array(lv["core"], np.float32)[None] * (np.clip(hot - 0.7, 0, 1) / 0.3 * glow)[:, None]
    # ---- gem: deep red crystal with a glowing core
    ge = lab == 4; G_ = L["gem"]
    if ge.any():
        ng = fbm(P[ge], 80.0, 4, 31)
        core = np.ones(int(ge.sum()), np.float32) if gem_rr is None else np.clip(1 - gem_rr[ge] ** 2, 0, 1)   # pearl: glows from inside
        base[ge] = np.array(G_["base"], np.float32) * ((0.55 + 0.45 * core) * (0.8 + 0.4 * ng))[:, None]; metal[ge] = 0; rough[ge] = G_["rough"]
        emit[ge] = np.array(G_["emit"], np.float32) * (G_["emit_amount"] * (0.3 + 0.9 * core) * (0.75 + 0.5 * ng))[:, None]
    return {"base": np.clip(base, 0, 1), "rough": np.clip(rough, 0.04, 1), "metal": np.clip(metal, 0, 1), "emit": np.clip(emit, 0, 1),
            "lava": lava, "edge": edge}


def to_image(tm, vals, fill=0.0, pad_px=16):
    """scatter per-texel values into an (H,W,C) image (Blender row order) and dilate them pad_px into empty texels."""
    S = tm["size"]; v = vals if vals.ndim == 2 else vals[:, None]; C = v.shape[1]
    img = np.full((S * S, C), fill, np.float32); img[tm["idx"]] = v; img = img.reshape(S, S, C)
    m = np.zeros(S * S, bool); m[tm["idx"]] = True; m = m.reshape(S, S)
    for _ in range(pad_px):
        acc = np.zeros_like(img); cnt = np.zeros((S, S), np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            mm = np.roll(m, (dy, dx), (0, 1)); acc += np.roll(img * m[..., None], (dy, dx), (0, 1)); cnt += mm
        grow = (~m) & (cnt > 0); img[grow] = acc[grow] / cnt[grow][:, None]; m = m | grow
    return img


# ----------------------------------------------------------------------------------------- "molten" look (user ref.)
MOLTEN_DEFAULT = {
    "steel": {"base": [0.018, 0.016, 0.017], "rough": 0.22, "rough_var": 0.06, "cavity_dark": 0.5},
    "rim": {"width_m": 0.006, "base": [0.22, 0.008, 0.002], "emit": [0.55, 0.03, 0.0], "emit_amount": 0.35, "rough": 0.3},
    "band": {"lo": 0.55, "hi": 0.75, "tip_fade_m": 0.05, "junction_to_z": 0.80, "junction_half_width_m": 0.012,
             "max_half_width_m": 0.035, "narrow_from_m": 0.10},
    "cracks": {"cell_m": 0.011, "warp_m": 0.006, "width": 0.12, "crust": [0.012, 0.008, 0.007], "crust_rough": 0.7,
               "core": [1.0, 0.70, 0.12], "hot": [1.0, 0.28, 0.02], "warm": [0.45, 0.02, 0.0], "emit_amount": 1.0},
    "socket": {"base": [0.16, 0.008, 0.004], "rough": 0.28, "radius_m": 0.046, "center": [0.0, 0.8257]},
    "grip": {"base": [0.012, 0.009, 0.008], "rough": 0.6, "noise_freq": 120.0},
    "gem": {"glass": [0.12, 0.004, 0.002], "rough": 0.06, "flame": [1.0, 0.32, 0.03], "deep": [0.6, 0.02, 0.0], "deep_amount": 0.15},
}


def silhouette_distance(co, tv, cell=0.0005, max_m=0.03, box=None):
    """front (x-z) silhouette of the mesh and, for every cell, the distance to the outline (8-neighbour chamfer, numpy
    only). -> (dist (H,W) metres, origin (x0, z0), cell)."""
    A = co[tv]; x0, z0 = A[..., 0].min() - 0.002, A[..., 2].min() - 0.002; x1, z1 = A[..., 0].max() + 0.002, A[..., 2].max() + 0.002
    W = int((x1 - x0) / cell) + 1; H = int((z1 - z0) / cell) + 1
    P2 = np.stack([(A[..., 0] - x0) / cell, (A[..., 2] - z0) / cell], -1)
    inside = np.zeros(H * W, bool)
    for s in range(0, len(P2), 3000):
        r, c, _, _, _ = _tri_pix(P2[s:s + 3000], 0.5)
        ok = (r >= 0) & (r < H) & (c >= 0) & (c < W); inside[r[ok] * W + c[ok]] = True
    inside = inside.reshape(H, W)
    d = np.where(inside, np.inf, 0.0).astype(np.float32); s2 = math.sqrt(2)
    for _ in range(int(max_m / cell)):
        n = d.copy()
        for dy, dx, w in ((0, 1, 1), (0, -1, 1), (1, 0, 1), (-1, 0, 1), (1, 1, s2), (1, -1, s2), (-1, 1, s2), (-1, -1, s2)):
            n = np.minimum(n, np.roll(d, (dy, dx), (0, 1)) + w)
        if np.array_equal(n, d): break
        d = n
    d = np.where(np.isinf(d), max_m / cell, d) * cell
    return d, (x0, z0), cell


def sample_grid(G, origin, cell, P):
    c = np.clip(((P[:, 0] - origin[0]) / cell).astype(np.int64), 0, G.shape[1] - 1)
    r = np.clip(((P[:, 2] - origin[1]) / cell).astype(np.int64), 0, G.shape[0] - 1)
    return G[r, c]


def voronoi_edges(P, cell, seed=0, chunk=400000):
    """distance (in cell units) from each point to the nearest Voronoi border of jittered 3D cells (F2 - F1)."""
    out = np.empty(len(P), np.float32)
    for s in range(0, len(P), chunk):
        q = P[s:s + chunk].astype(np.float64) / cell; i = np.floor(q).astype(np.int64)
        f1 = np.full(len(q), 9.0); f2 = np.full(len(q), 9.0)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    jx, jy, jz = i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz
                    p = np.stack([jx + _hash3(jx, jy, jz, seed), jy + _hash3(jx, jy, jz, seed + 1), jz + _hash3(jx, jy, jz, seed + 2)], 1)
                    dd = np.linalg.norm(q - p, axis=1)
                    f2 = np.where(dd < f1, f1, np.minimum(f2, dd)); f1 = np.minimum(f1, dd)
        out[s:s + chunk] = f2 - f1
    return out


def paint_molten(tm, lab, ao, sil, ridge, anatomy, look=None, gem_rr=None):
    """the look of the user's reference: glossy black steel, dark-red glowing rims along every outline, a band of
    cracked lava (yellow-orange veins in a dark crust) down the middle of the blade into the guard, red socket ring,
    red glass gem with a flame inside."""
    L = {k: dict(v) for k, v in MOLTEN_DEFAULT.items()}
    for k, v in (look or {}).items():
        if isinstance(v, dict): L.setdefault(k, {}).update(v)
    P = tm["P"]; n = len(P); an = anatomy; st = L["steel"]
    dist, org, cs = sil
    de = sample_grid(dist, org, cs, P).astype(np.float32)                       # distance to the outline (m)
    nz = fbm(P, 40.0, 3, 1); cav = np.clip(1 - ao, 0, 1)
    base = np.array(st["base"], np.float32)[None] * (0.85 + 0.3 * nz)[:, None] * (1 - st["cavity_dark"] * cav)[:, None]
    rough = (st["rough"] + st["rough_var"] * (nz - 0.5) * 2 + 0.2 * cav).astype(np.float32); metal = np.ones(n, np.float32)
    emit = np.zeros((n, 3), np.float32)
    # ---- red rims along every outline
    rm = L["rim"]; rim = np.clip(1 - de / rm["width_m"], 0, 1) ** 1.6 * (0.75 + 0.5 * fbm(P, 60.0, 2, 4))
    rim[lab == 2] = 0; rim[lab == 4] = 0
    base = base * (1 - rim[:, None]) + np.array(rm["base"], np.float32)[None] * rim[:, None]
    rough = rough * (1 - rim) + rm["rough"] * rim
    emit += np.array(rm["emit"], np.float32)[None] * (rim * rm["emit_amount"])[:, None]
    # ---- lava band: medial part of the blade outline (distance to the outline relative to the local maximum)
    bd = L["band"]; band = np.zeros(n, np.float32); bl = lab == 0
    if bl.any():
        zb = P[bl, 2]; bins = np.clip(((zb - an["tip_z"]) / 0.005).astype(np.int64), 0, None)
        mx = np.zeros(bins.max() + 1, np.float32); np.maximum.at(mx, bins, de[bl])
        k = np.ones(9) / 9; mx = np.convolve(np.pad(mx, 4, mode="edge"), k, "valid")
        rel = de[bl] / np.maximum(mx[bins], 1e-4)
        band[bl] = np.clip((rel - bd["lo"]) / (bd["hi"] - bd["lo"]), 0, 1) * np.clip((zb - an["tip_z"]) / bd["tip_fade_m"], 0, 1)
        # near the guard the band narrows smoothly into the junction line (no step at guard_z0)
        xr = np.interp(zb, ridge[0], ridge[1]); u = np.clip((an["guard_z0"] - zb) / bd["narrow_from_m"], 0, 1)
        hw = bd["junction_half_width_m"] + (bd["max_half_width_m"] - bd["junction_half_width_m"]) * u
        band[bl] *= np.clip(1 - np.abs(P[bl, 0] - xr) / hw, 0, 1) ** 0.35
    jn = (lab == 1) & (P[:, 2] < bd["junction_to_z"])                       # lava runs on into the guard, up to the gem
    if jn.any():
        xr = np.interp(P[jn, 2], ridge[0], ridge[1], right=ridge[1][-1])
        band[jn] = np.clip(1 - np.abs(P[jn, 0] - xr) / bd["junction_half_width_m"], 0, 1) ** 0.35 * np.clip((bd["junction_to_z"] - P[jn, 2]) / 0.03, 0, 1)
    # ---- cracks: Voronoi borders, warped by noise
    ck = L["cracks"]; sel = band > 0.01
    if sel.any():
        Pw = P[sel] + (np.stack([fbm(P[sel], 1 / ck["cell_m"] * 0.7, 3, s) for s in (41, 42, 43)], 1) - 0.5) * 2 * ck["warp_m"]
        ve = voronoi_edges(Pw, ck["cell_m"], 51)
        w = ck["width"] * (0.6 + 0.8 * fbm(P[sel], 90.0, 2, 61))
        heat = 0.35 + 0.65 * np.clip((fbm(P[sel], 45.0, 3, 63) - 0.3) * 2.2, 0, 1)   # some veins bright, some dim red
        vein = np.clip(1 - ve / w, 0, 1) ** 0.8 * band[sel]                  # 1 on a crack, 0 in the crust
        glow = np.clip(vein * heat * 1.5, 0, 1)
        col = (np.array(ck["warm"], np.float32)[None] * (1 - glow[:, None]) + np.array(ck["hot"], np.float32)[None] * glow[:, None])
        col = col * (1 - np.clip(glow - 0.6, 0, 1)[:, None] / 0.4) + np.array(ck["core"], np.float32)[None] * (np.clip(glow - 0.6, 0, 1) / 0.4)[:, None]
        crust = np.array(ck["crust"], np.float32)[None] * (0.7 + 0.6 * fbm(P[sel], 150.0, 2, 71))[:, None]
        ember = np.clip((fbm(P[sel], 70.0, 3, 73) - 0.55) * 3, 0, 1) * band[sel] * 0.5     # faint glow in the crust
        crust = crust * (1 - ember[:, None]) + np.array(ck["warm"], np.float32)[None] * ember[:, None]
        bsel = band[sel][:, None]; on = np.clip(vein * 2.5, 0, 1)[:, None]
        newb = crust * (1 - on) + col * on
        base[sel] = base[sel] * (1 - bsel) + newb * bsel
        rough[sel] = rough[sel] * (1 - band[sel]) + ck["crust_rough"] * band[sel]
        metal[sel] = metal[sel] * (1 - band[sel])
        emit[sel] = emit[sel] * (1 - bsel) + col * (on * bsel * ck["emit_amount"])
    # ---- red socket ring around the gem
    so = L["socket"]; ring = (lab == 1) & (np.hypot(P[:, 0] - so["center"][0], P[:, 2] - so["center"][1]) < so["radius_m"])
    base[ring] = np.array(so["base"], np.float32) * (0.8 + 0.4 * nz[ring])[:, None]; rough[ring] = so["rough"]
    # ---- grip: dark leather
    g = L["grip"]; gm = lab == 2; ng = fbm(P[gm], g["noise_freq"], 3, 3)
    base[gm] = np.array(g["base"], np.float32) * (0.75 + 0.5 * ng)[:, None] * (1 - 0.5 * cav[gm])[:, None]; rough[gm] = g["rough"]; metal[gm] = 0
    # ---- gem: red glass with a flame swirl
    ge = lab == 4; G_ = L["gem"]
    if ge.any():
        rr = np.zeros(int(ge.sum()), np.float32) if gem_rr is None else gem_rr[ge]
        sw = fbm(P[ge] + (fbm(P[ge], 60.0, 2, 81)[:, None] - 0.5) * 0.02, 70.0, 4, 91)
        flame = np.clip((sw - 0.45) * 4, 0, 1) * np.clip(1 - rr * 1.15, 0, 1)
        base[ge] = np.array(G_["glass"], np.float32)[None] * (1 - flame[:, None]) + np.array(G_["flame"], np.float32)[None] * flame[:, None] * 0.6
        rough[ge] = G_["rough"]; metal[ge] = 0
        emit[ge] = np.array(G_["deep"], np.float32)[None] * (G_.get("deep_amount", 0.25) * (1 - rr))[:, None] + np.array(G_["flame"], np.float32)[None] * flame[:, None]
    lava = band
    return {"base": np.clip(base, 0, 1), "rough": np.clip(rough, 0.04, 1), "metal": np.clip(metal, 0, 1), "emit": np.clip(emit, 0, 1),
            "lava": lava, "edge": rim}


# ----------------------------------------------------------------------------------------- "ai_lava": the method of
# the first dragon sword (tools/lava_edge.py + masks.py, params lava_maps/v6_arms): keep the AI bake (BaseColor,
# Emissive, ORM) and paint cracked lava only where the AI painted red inside the blade, 4-8 mm away from the outline,
# on the flat faces, with Voronoi cracks + molten flow in x/z millimetres. Positions are re-anchored on the anatomy.
AI_LAVA_DEFAULT = dict(cell_mm=9.0, stretch=0.45, warp_mm=4.0, crack_w=0.08, lava_d0=4.0, lava_d1=8.0, red_lo=28, red_hi=60,
                       seed=7, crack_lo=0.38, crack_hi=0.7, flow_lo=0.83, gain=0.75, ythr=0.0125,
                       # old model anchors (guard_z0 0.672, gem centre z 0.812) -> offsets used on any sword
                       cut_above_guard=0.003, ext_above_guard=0.028, ext_half_x=0.045, v_wide_above_guard=0.028,
                       v_wide_x=0.07, v_narrow_below_guard=0.012, v_narrow_x=0.04, v_top_below_gem=0.022, gem_r=0.034,
                       thin_above_guard=0.018, fade_below_gem=(0.080, 0.067),
                       whole=0, red_rule=None, hue_lo=0.10, hue_hi=0.25, gem_lava=0, keep_grip=0, gem_glow=0.0, sharp=0, crust=(0.075, 0.018, 0.014), emit_pow=1.15,
                       hot_top=(1.00, 0.86, 0.45), gem_style="cracks", gem_flame_r=0.0, gem_floor_y=0.0205, gem_clear_r=0.0,
                       clear_grey=(0.33, 0.33, 0.35), gem_clear_above=-9.0,
                       gem_shadow_r=0.0, gem_clear_low_r=0.0, gem_clear_low_x=0.010, gem_face_ny=0.0,
                       black_below_grip_m=0.0, black_half_x=0.05, black_col=(0.03, 0.03, 0.032))   # lava/red just below the grip -> black   # shadow ring under the ring; lower spots -> grey   # red/lava left inside the ring (r < gem_clear_r) -> grey metal   # flame up to gem_flame_r (socket floor around the pearl)   # gem_style "flame": red glass with a swirling flame   # colour of the hottest cracks (old: pale yellow; (1, .72, .22) = no white)   # gem_glow > 0: the pearl's lava glows (brighter cracks + warm core)   # whole=1: lava wherever the AI painted red on the whole weapon (gem excluded)


def _ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t)


def _h2(ix, iy, s):
    h = (ix * 374761393 + iy * 668265263 + s * 1442695041) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)).astype(np.float64) / 4294967295.0


def _vn2(x, y, s):
    ix = np.floor(x).astype(np.int64); iy = np.floor(y).astype(np.int64); fx = x - ix; fy = y - iy
    u = fx * fx * (3 - 2 * fx); v = fy * fy * (3 - 2 * fy)
    a = _h2(ix, iy, s); b = _h2(ix + 1, iy, s); c = _h2(ix, iy + 1, s); d = _h2(ix + 1, iy + 1, s)
    return (a + (b - a) * u) + ((c + (d - c) * u) - (a + (b - a) * u)) * v


def _fbm2(x, y, s, oct=4):
    t = 0; amp = 0.5; f = 1.0
    for o in range(oct):
        t = t + amp * _vn2(x * f, y * f, s + o * 17); amp *= 0.5; f *= 2.03
    return t


def _vor2(x, y, s):
    ix = np.floor(x).astype(np.int64); iy = np.floor(y).astype(np.int64)
    F1 = np.full(x.shape, 9.0); F2 = np.full(x.shape, 9.0)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            cx = ix + dx; cy = iy + dy
            px = cx + 0.1 + 0.8 * _h2(cx, cy, s); py = cy + 0.1 + 0.8 * _h2(cx, cy, s + 99)
            dd = np.hypot(px - x, py - y)
            F2 = np.where(dd < F1, F1, np.minimum(F2, dd)); F1 = np.minimum(F1, dd)
    return F1, F2


def _ramp(t, top=(1.00, 0.86, 0.45)):
    stops = np.array([[0.00, 0.06, 0.012, 0.010], [0.25, 0.42, 0.04, 0.01], [0.55, 0.86, 0.22, 0.03],
                      [0.80, 1.00, 0.52, 0.10], [1.00] + list(top)])
    out = np.empty(t.shape + (3,))
    for c in range(3): out[..., c] = np.interp(t, stops[:, 0], stops[:, c + 1])
    return out


def grid_component(mask, seed_rc, step=2):
    """connected component of `mask` containing seed (row, col), by repeated constrained dilation (numpy only).
    Works on a grid sub-sampled by `step` and is scaled back."""
    m = mask[::step, ::step]; cur = np.zeros_like(m); r, c = seed_rc[0] // step, seed_rc[1] // step
    if not m[r, c]:
        ys, xs = np.nonzero(m); k = np.argmin((ys - r) ** 2 + (xs - c) ** 2); r, c = ys[k], xs[k]
    cur[r, c] = True
    while True:
        n = cur | (m & (np.roll(cur, 1, 0) | np.roll(cur, -1, 0) | np.roll(cur, 1, 1) | np.roll(cur, -1, 1)))
        if n.sum() == cur.sum(): break
        cur = n
    big = np.repeat(np.repeat(cur, step, 0), step, 1)[:mask.shape[0], :mask.shape[1]]
    return big & mask


def ai_lava(tm, bc, em, sil, anatomy, ridge, gem_center_z, look=None):
    """bc / em: the AI bake per texel (n,3, sRGB 0..1). sil: silhouette_distance(...) of the whole sword.
    -> dict(base_srgb, emit_srgb, lava_m) - same formulas as the first dragon sword (v6)."""
    PAR = dict(AI_LAVA_DEFAULT); PAR.update({k: v for k, v in (look or {}).items() if k in AI_LAVA_DEFAULT})
    an = anatomy; g0 = an["guard_z0"]; P = tm["P"].astype(np.float64); N = tm["N"]; X = P[:, 0]; Z = P[:, 2]
    dist, org, cs = sil; inside = dist > cs * 0.5
    def grid_of(z): return int((z - org[1]) / cs)
    # blade component below the guard (wings that hang below the guard are other components)
    cut = inside.copy(); cut[grid_of(g0 + PAR["cut_above_guard"]):] = False
    zr = an["tip_z"] + 0.05; xr = float(np.interp(zr, ridge[0], ridge[1]))
    blade = grid_component(cut, (grid_of(zr), int((xr - org[0]) / cs)))
    cut2 = inside.copy(); cut2[grid_of(g0 + PAR["ext_above_guard"]):] = False
    blade2 = grid_component(cut2, (grid_of(zr), int((xr - org[0]) / cs)))
    inb = sample_grid(blade, org, cs, P) & (Z < g0 + PAR["cut_above_guard"])
    inb2 = sample_grid(blade2, org, cs, P) & (Z < g0 + PAR["ext_above_guard"]) & ((Z < g0 + PAR["cut_above_guard"]) | (np.abs(X) < PAR["ext_half_x"]))
    dmm = sample_grid(dist, org, cs, P) * 1000
    gem = np.hypot(X, Z - gem_center_z) > PAR["gem_r"]
    thin = (np.abs(P[:, 1]) < PAR["ythr"]) | (Z < g0 + PAR["thin_above_guard"])
    vz = (((Z > g0 + PAR["v_wide_above_guard"]) & (np.abs(X) < PAR["v_wide_x"])) | ((Z > g0 - PAR["v_narrow_below_guard"]) & (np.abs(X) < PAR["v_narrow_x"]))) \
         & (Z < gem_center_z - PAR["v_top_below_gem"]) & gem
    inblade = (inb2 | vz) & thin
    f0, f1 = gem_center_z - PAR["fade_below_gem"][0], gem_center_z - PAR["fade_below_gem"][1]
    blade_w = inblade.astype(np.float64) * (1 - _ss(f0, f1, Z))
    if PAR["whole"]:
        blade_w = (gem | bool(PAR["gem_lava"])) * np.ones(len(Z))          # gem_lava=1: the pearl gets lava too
        if PAR["keep_grip"]: blade_w *= Z < an["grip_z0"]                  # keep_grip=1: grip and pommel keep the AI red
    rule = PAR["red_rule"] or ("hue" if PAR["whole"] else "channel")
    if rule == "hue":       # really red: R clearly above G and B (the old R-channel rule also took grey metal, R >= 28/255)
        red = _ss(PAR["hue_lo"], PAR["hue_hi"], bc[:, 0] - np.maximum(bc[:, 1], bc[:, 2]))
    else:
        red = _ss(PAR["red_lo"] / 255, PAR["red_hi"] / 255, bc[:, 0])
    facing = _ss(0.35, 0.6, np.abs(N[:, 1]))
    lava_m = blade_w * red * _ss(PAR["lava_d0"], PAR["lava_d1"], dmm) * facing
    if PAR["sharp"]:                         # a clear lava area (no muddy mix of AI red and crust at half strength)
        lava_m = _ss(0.12, 0.40, lava_m)
    sel = lava_m > 0.001
    xm = X[sel] * 1000; zm = Z[sel] * 1000; side = (N[sel, 1] > 0).astype(np.int64); s0 = PAR["seed"] + side * 1000
    wx = (_fbm2(xm / 9, zm / 9, s0 + 1) - 0.5) * 2 * PAR["warp_mm"]; wz = (_fbm2(xm / 9 + 5.2, zm / 9 + 1.3, s0 + 2) - 0.5) * 2 * PAR["warp_mm"]
    F1, F2 = _vor2((xm + wx) / PAR["cell_mm"], (zm + wz) * PAR["stretch"] / PAR["cell_mm"], s0 + 3)
    var = _fbm2(xm / 11, zm / 16, s0 + 4)
    cw = PAR["crack_w"] * (0.6 + 0.9 * _fbm2(xm / 6, zm / 6, s0 + 6))
    crack = np.exp(-((F2 - F1) / cw) ** 2) * _ss(PAR["crack_lo"], PAR["crack_hi"], var)
    rid = 1 - np.abs(2 * _fbm2(xm / 5.0 + wx / 4, zm / 16.0 + wz / 8, s0 + 7, 5) - 1)
    flow = _ss(PAR["flow_lo"], 0.96, rid)
    hot = _ss(0.45, 0.80, _fbm2(xm / 18 + 3, zm / 34, s0 + 5))
    glowbed = 0.10 + 0.25 * hot
    L = np.clip(np.maximum(crack * (0.6 + 0.7 * var), flow * (0.55 + 0.45 * hot)) + glowbed * (1 - _ss(0.0, 0.5, F2 - F1)) * 0.6 + 0.35 * hot * flow, 0, 1)
    L = L * lava_m[sel] * PAR["gain"]
    ing = None
    if PAR["gem_glow"] > 0:                                                    # pearl: brighter lava + glow from the centre
        rr = np.hypot(X[sel], Z[sel] - gem_center_z) / PAR["gem_r"]; ing = rr < 1
        core = np.clip(1 - rr, 0, 1) ** 0.7
        L[ing] = np.clip(L[ing] * (1 + 0.6 * PAR["gem_glow"]), 0, 1)        # brighter cracks, the crust stays dark
    crust = np.array(PAR["crust"], np.float64)
    bc2 = bc.astype(np.float64).copy(); em2 = em.astype(np.float64).copy(); lm = lava_m[sel][:, None]
    lava_col = crust * (1 - np.clip(L * 3, 0, 1))[:, None] + _ramp(L, PAR["hot_top"]) * np.clip(L * 3, 0, 1)[:, None]
    bc2[sel] = bc2[sel] * (1 - lm) + lava_col * lm
    em2[sel] = np.maximum(em2[sel], _ramp(L, PAR["hot_top"]) * (L ** PAR["emit_pow"])[:, None])
    if ing is not None:                                                        # pearl: glowing cracks + red light from inside
        e = em2[sel]; inner = np.array([0.35, 0.03, 0.0]) * (PAR["gem_glow"] * core[ing])[:, None]
        e[ing] = np.clip(np.maximum(e[ing], _ramp(L[ing], PAR["hot_top"]) * np.clip(L[ing] * 1.5, 0, 1)[:, None]) + inner, 0, 1); em2[sel] = e
    if PAR["gem_style"] == "flame":                                            # pearl: red glass + swirling flame
        Rf = max(PAR["gem_r"], PAR["gem_flame_r"])                             # the floor around the pearl joins it
        rr = np.hypot(X, Z - gem_center_z) / Rf
        g = (rr < 1.0) & ((rr * Rf < PAR["gem_r"]) | (np.abs(P[:, 1]) < PAR["gem_floor_y"]))
        g &= np.abs(N[:, 1]) >= PAR["gem_face_ny"]           # only the pearl face: the claw / arc flanks keep metal
        r_ = rr[g]; th = np.arctan2(Z[g] - gem_center_z, X[g]); sw = th + 2.6 * (1 - r_)       # swirl, stronger inside
        u = np.cos(sw) * r_ * 3.0; v = np.sin(sw) * r_ * 3.0; sd = PAR["seed"] + 500
        rid = 1 - np.abs(2 * _fbm2(u * 1.6 + 7, v * 1.6 + 3, sd, 5) - 1)                       # flame tongues
        flame = _ss(0.68, 0.94, rid) * _ss(1.0, 0.35, r_)
        core = _ss(1.0, 0.0, r_) ** 1.5
        glass = np.array([0.30, 0.015, 0.008]) * (0.55 + 0.45 * (1 - r_))[:, None]
        fcol = np.array([0.95, 0.16, 0.02])[None] * (1 - flame[:, None]) + np.array([1.0, 0.62, 0.10])[None] * flame[:, None]
        k = np.clip(flame * 1.2 + core * 0.35, 0, 1)[:, None]
        bc2[g] = glass * (1 - k) + fcol * k
        em2[g] = np.clip(np.array([0.55, 0.04, 0.0])[None] * (0.25 + 0.55 * core)[:, None] + fcol * (flame * 0.95)[:, None], 0, 1)
        if PAR["gem_shadow_r"] > 0:            # between the pearl and the ring: the pearl's dark edge going under the metal
            rg = np.flatnonzero(g); rr2 = rr[g] * Rf; sh = rg[rr2 > PAR["gem_shadow_r"]]
            t = np.clip((rr[sh] * Rf - PAR["gem_shadow_r"]) / max(Rf - PAR["gem_shadow_r"], 1e-4), 0, 1)[:, None]
            bc2[sh] = bc2[sh] * (1 - t) * 0.35 + np.array([0.06, 0.004, 0.002]) * t
            em2[sh] = em2[sh] * (1 - t) * 0.25
    if PAR["gem_clear_r"] > 0:                                                 # leftover lava / red around the pearl -> grey
        rc = np.hypot(X, Z - gem_center_z); fl = np.zeros(len(X), bool)
        if PAR["gem_style"] == "flame": fl[np.flatnonzero(g)] = True
        cz = (rc < PAR["gem_clear_r"]) & ~fl & ((red > 0.3) | (lava_m > 0.001)) & (Z > gem_center_z + PAR["gem_clear_above"])
        if PAR["gem_clear_low_r"] > 0:         # spots beside the lower claw (the lava band down the middle stays)
            cz |= (rc < PAR["gem_clear_low_r"]) & ~fl & ((red > 0.3) | (lava_m > 0.001)) & (Z <= gem_center_z) & (np.abs(X) > PAR["gem_clear_low_x"])
        bc2[cz] = np.array(PAR["clear_grey"]); em2[cz] = 0; lava_m = np.where(cz, 0.0, lava_m)
    if PAR["black_below_grip_m"] > 0:            # the top of the guard under the grip: black metal, no lava
        bz = (Z >= an["grip_z0"] - PAR["black_below_grip_m"]) & (Z < an["grip_z0"]) & (np.abs(X) < PAR["black_half_x"]) & ((red > 0.3) | (lava_m > 0.001))
        bc2[bz] = np.array(PAR["black_col"]); em2[bz] = 0; lava_m = np.where(bz, 0.0, lava_m)
    return {"base_srgb": np.clip(bc2, 0, 1).astype(np.float32), "emit_srgb": np.clip(em2, 0, 1).astype(np.float32),
            "lava_m": lava_m.astype(np.float32), "lava_texels": int(sel.sum())}
