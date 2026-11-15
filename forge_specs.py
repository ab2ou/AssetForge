"""forge_specs - is this AI model a usable weapon of its type?  (pure numpy; the s0_spec gate evidence)

Measures the mesh (overall length, blade / grip / head lengths, width, thickness, volume, estimated mass, centre of
mass and point of balance) and compares it with weapon_profiles.json (sourced reference ranges per type, widened
for the fantasy style) and with a character (grip fits the hands, weapon not taller than the user).

Rule (CONTRIBUTING, evidence first): a range whose source is null is a guess. It can raise REVIEW, never FAIL.
"""
import json, os, time
import numpy as np


def load_profiles(path=None):
    path = path or os.path.join(FORGE_DIR, "weapon_profiles.json")
    return json.load(open(path, encoding="utf-8"))


def _edges_closed(tv):
    e = np.sort(np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    return int((cnt != 2).sum())


def volume_profile(co, tv, along=2, proj=None, cell=0.002, bins=None, chunk=150000):
    """volume per slab along axis `along`, by projecting the surface on the plane (along, other) and summing
    sign(n_proj) * depth over every surface crossing (divergence theorem on a grid). Works on several closed parts;
    open or overlapping parts make it approximate (reported). Returns (edges, volume per bin, total)."""
    co = np.asarray(co, float); tv = np.asarray(tv)
    ext = np.ptp(co, 0)
    if proj is None:                                       # project along the thinnest of the two other axes
        others = [a for a in range(3) if a != along]; proj = others[int(np.argmin(ext[others]))]
    u = [a for a in range(3) if a not in (along, proj)][0]
    lo = co.min(0)
    nb = bins or int(np.ceil(ext[along] / cell)) + 1
    vol = np.zeros(nb)
    for s in range(0, len(tv), chunk):
        T = tv[s:s + chunk]; A = co[T[:, 0]]; B = co[T[:, 1]]; C = co[T[:, 2]]
        n = np.cross(B - A, C - A); ny = n[:, proj]; keep = np.abs(ny) > 1e-18
        T, A, B, C, n, ny = T[keep], A[keep], B[keep], C[keep], n[keep], ny[keep]
        P = np.stack([(co[T][:, :, u] - lo[u]) / cell, (co[T][:, :, along] - lo[along]) / cell], 2)
        r, c, t = _tri_pixels(P, 1.0, 0.0)                 # r = along index, c = u index
        x = (c + 0.5) * cell + lo[u]; z = (r + 0.5) * cell + lo[along]
        y = A[t, proj] - (n[t, u] * (x - A[t, u]) + n[t, along] * (z - A[t, along])) / ny[t]
        contrib = np.sign(ny[t]) * (y - lo[proj]) * cell * cell
        ok = (r >= 0) & (r < nb)
        np.add.at(vol, r[ok], contrib[ok])
    edges = lo[along] + np.arange(nb + 1) * cell
    return edges, vol, float(vol.sum())


def measure_weapon(co, tv, anatomy=None, densities=None, cell=0.002):
    """co/tv may be the concatenation of several parts. anatomy: the s0 sword anatomy (tip low on Z) or None."""
    co = np.asarray(co, float); tv = np.asarray(tv); t0 = time.time()
    ext = np.ptp(co, 0); dens = densities or {"steel": 7850, "grip": 1200, "wood": 600}
    cell = max(cell, float(ext.max()) / 600.0)        # a model in wrong units (e.g. x100) must not explode the grid
    open_edges = _edges_closed(tv)
    edges, vol, V = volume_profile(co, tv, 2, cell=cell)
    zc = (edges[:-1] + edges[1:]) / 2
    m = {"extent_m": [round(float(v), 4) for v in ext], "overall_m": round(float(ext[2]), 4),
         "width_m": round(float(max(ext[0], ext[1])), 4), "thickness_m": round(float(min(ext[0], ext[1])), 4),
         "open_edges": open_edges, "watertight": open_edges == 0, "volume_m3": V}
    rho = np.full(len(zc), dens["steel"], float)
    if anatomy:
        an = anatomy
        m.update(blade_m=round(an["guard_z0"] - an["tip_z"], 4), guard_band_m=round(an["guard_z1"] - an["guard_z0"], 4),
                 grip_m=round(an["grip_z1"] - an["grip_z0"], 4), pommel_m=round(an["pommel_z1"] - an["grip_z1"], 4),
                 guard_width_m=round(2 * an["guard_half_width"], 4), overall_m=round(an["pommel_z1"] - an["tip_z"], 4))
        rho[(zc >= an["grip_z0"]) & (zc < an["grip_z1"])] = dens["grip"]
        # blade cross-section from the slab volumes (mean thickness x width is not needed: we report the area)
        bl = (zc > an["tip_z"] + 0.1 * m["blade_m"]) & (zc < an["guard_z0"] - 0.05 * m["blade_m"])
        if bl.any(): m["blade_section_mm2_median"] = round(float(np.median(vol[bl] / cell)) * 1e6, 1)
    mass = vol * rho; M = float(mass.sum())
    m["mass_kg"] = round(M, 3)
    if M > 0:
        zcom = float((mass * zc).sum() / M); m["com_z_m"] = round(zcom, 4)
        if anatomy: m["pob_from_guard_m"] = round(anatomy["guard_z0"] - zcom, 4)   # + = towards the tip
    m["mass_note"] = "estimate: volume x density per zone (steel; grip " + str(dens["grip"]) + " kg/m3)" + \
                     ("" if open_edges == 0 else f"; {open_edges} open/non-manifold edges -> volume approximate")
    m["seconds"] = round(time.time() - t0, 1)
    return m, {"z": zc, "volume": vol, "mass": mass}


def guess_type(m):
    """a first guess from proportions only; the declared type always wins and an undeclared type is REVIEW."""
    L = m["overall_m"]; w = m["width_m"]; t = m["thickness_m"]; why = []
    ext = sorted(m["extent_m"])
    if ext[1] > 0.6 * ext[2] and ext[0] < 0.25 * ext[2]:
        return "round_shield", "two large similar extents and a thin one", 0.6
    if L > 1.7 and t < 0.08 and w < 0.4:
        return "spear", "long and thin", 0.5
    g = m.get("grip_m")
    if g is not None:
        if L < 0.5: return "dagger", "short", 0.6
        if L >= 1.4: return "greatsword", f"overall {L:.2f} m", 0.5
        if g >= 0.15 or L >= 1.0: return "longsword", f"grip {g:.2f} m / overall {L:.2f} m", 0.5
        return "arming_sword", f"grip {g:.2f} m / overall {L:.2f} m", 0.5
    return "unknown", "no anatomy", 0.0


def spec_checks(m, wtype, style, profiles, character=None, hands=None):
    """-> list of (id, value, status, rule, source). Never FAIL on a range without a source."""
    prof = profiles["types"].get(wtype); C = []
    ch = dict(profiles["character"]); ch.update(character or {})
    st = profiles["styles"].get(style, profiles["styles"]["realistic"])
    def rng(cid, key, val, kind):
        if prof is None or key not in prof or val is None: return
        lo, hi, src = prof[key]; f = st["length" if kind == "length" else "mass"]
        wl, wh = lo * f[0], hi * f[1]
        if lo <= val <= hi: s = "PASS"
        elif wl <= val <= wh: s = "PASS" if style == "fantasy" else "REVIEW"
        else: s = "FAIL" if (src and not (kind == "mass" and st.get("physics_review_only"))) else "REVIEW"
        rule = f"{lo}-{hi}" + (f" (style {style}: {wl:.3g}-{wh:.3g})" if style != "realistic" else "")
        if s != "PASS" and kind == "length" and st.get("geometry_info_only"):   # user decision 2026-10-27 (LESSON 44)
            s = "PASS"; rule = f"INFO, not a gate (style {style}: geometry may leave the real range): " + rule
        C.append((cid, round(float(val), 4), s, rule, src or "no source: guess (REVIEW only)"))
    if prof is None:
        C.append(("weapon_type_known", wtype, "REVIEW", "add this type to weapon_profiles.json with sourced ranges", None)); return C
    L = m.get("overall_m"); key = "diameter" if "diameter" in prof else "overall"
    mid = np.mean(prof[key][:2]); r = L / mid if mid else 1
    s = "PASS" if 0.5 <= r <= 2.0 else "FAIL"
    C.append(("scale_plausible", round(float(r), 3), s, f"overall/typical between 0.5 and 2 (else wrong units or scale; suggested scale x{1 / r:.3f})",
              "mesh units are metres in Blender"))
    rng("overall_length_m", key, L, "length")
    rng("blade_length_m", "blade", m.get("blade_m"), "length")
    rng("grip_length_m", "grip", m.get("grip_m"), "length")
    rng("thickness_m", "thickness", m.get("thickness_m"), "length")
    rng("mass_kg", "mass", m.get("mass_kg"), "mass")
    rng("point_of_balance_from_guard_m", "pob_from_guard", m.get("pob_from_guard_m"), "mass")   # physics, like mass
    h = hands or prof.get("hands", 1); g = m.get("grip_m")
    if g is not None:
        need = h * ch["hand_breadth_m"]
        C.append(("grip_fits_hands", round(g, 4), "PASS" if g >= need else ("REVIEW" if g >= ch["hand_breadth_m"] else "FAIL"),
                  f">= {h} x hand breadth {ch['hand_breadth_m']} m = {need:.3f} m", ch.get("source")))
    fam = prof.get("family"); lim = {"sword": 0.95, "axe": 0.95, "polearm": 1.9, "shield": 0.7}.get(fam, 1.0)
    C.append(("usable_by_character", round(L / ch["height_m"], 3), "PASS" if L <= lim * ch["height_m"] else "REVIEW",
              f"length <= {lim} x character height {ch['height_m']} m", "guess (REVIEW only)"))
    if not m.get("watertight"):
        C.append(("volume_reliable", m.get("open_edges"), "REVIEW", "0 open edges for an exact volume/mass", None))
    return C
