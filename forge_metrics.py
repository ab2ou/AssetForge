"""forge_metrics - quality measurements that do not depend on materials or lights.

Geometry is compared by RAY CASTING from the same cameras into the high and the low mesh:
  silhouette IoU (outline), depth error in mm (surface position), normal angle in deg (surface direction).
Rendered images (bake test) are compared with MAE and a windowed SSIM (numpy only), as helper numbers.
No thresholds are final until calibrated on several swords (see CALIBRATION.md)."""
import bpy, math
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree


def view_rays(view, res=(192, 108), lens=50.0, sensor=36.0):
    """origins/directions for a pinhole camera placed like forge_render._aim (roll in degrees)."""
    name, tgt, d, dist = view[:4]; roll = view[4] if len(view) > 4 else 0.0
    d = Vector(d).normalized(); t = Vector(tgt); loc = t + d * dist
    q = (-d).to_track_quat("-Z", "Y"); R = (q.to_matrix().to_4x4() @ Matrix.Rotation(math.radians(roll), 4, "Z")).to_3x3()
    W, H = res; sw = sensor; sh = sensor * H / W
    xs = (np.arange(W) + 0.5) / W - 0.5; ys = 0.5 - (np.arange(H) + 0.5) / H
    X, Y = np.meshgrid(xs * sw, ys * sh)
    dirs = np.stack([X, Y, -np.full_like(X, lens)], -1).reshape(-1, 3)
    Rm = np.array(R); dirs = dirs @ Rm.T; dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    return np.array(loc), dirs, (H, W)


def cast(bvh, origin, dirs, far=100.0):
    n = len(dirs); hit = np.zeros(n, bool); depth = np.full(n, np.nan); nrm = np.zeros((n, 3))
    o = Vector(origin)
    for i in range(n):
        loc, no, idx, dd = bvh.ray_cast(o, Vector(dirs[i]), far)
        if loc is not None:
            hit[i] = True; depth[i] = dd; nrm[i] = no
    return hit, depth, nrm


def bvh_object(name):
    co, tv, _, _, _ = tri_arrays(name, evaluated=True)
    return BVHTree.FromPolygons(co.tolist(), tv.tolist(), all_triangles=True)


def compare_geometry(high_bvh, low_bvh, views, res=(192, 108)):
    """per view: silhouette IoU, depth MAE/p95 (mm) and normal angle mean/p95 (deg) where both are hit."""
    out = {}
    for v in views:
        o, dirs, (H, W) = view_rays(v, res)
        h1, d1, n1 = cast(high_bvh, o, dirs); h2, d2, n2 = cast(low_bvh, o, dirs)
        inter = (h1 & h2).sum(); union = (h1 | h2).sum()
        both = h1 & h2
        dd = np.abs(d1[both] - d2[both]) * 1000
        ang = np.degrees(np.arccos(np.clip(np.abs((n1[both] * n2[both]).sum(1)), -1, 1)))
        out[v[0]] = {"silhouette_iou": round(float(inter / max(union, 1)), 4),
                     "only_high_px": int((h1 & ~h2).sum()), "only_low_px": int((h2 & ~h1).sum()),
                     "depth_mae_mm": round(float(dd.mean()), 3) if len(dd) else None,
                     "depth_p95_mm": round(float(np.percentile(dd, 95)), 3) if len(dd) else None,
                     "normal_mean_deg": round(float(ang.mean()), 2) if len(ang) else None,
                     "normal_p95_deg": round(float(np.percentile(ang, 95)), 2) if len(ang) else None}
    return out


def summarize_geometry(per_view):
    keys = ["silhouette_iou", "depth_mae_mm", "depth_p95_mm", "normal_mean_deg", "normal_p95_deg"]
    s = {}
    for k in keys:
        vals = [v[k] for v in per_view.values() if v.get(k) is not None]
        if vals: s[k + ("_min" if k == "silhouette_iou" else "_worst")] = (min(vals) if k == "silhouette_iou" else max(vals))
    return s


# ---------------- image metrics (helpers for bake tests)
def _gray(path):
    im = bpy.data.images.load(path, check_existing=False); w, h = im.size
    a = np.empty(w * h * 4, np.float32); im.pixels.foreach_get(a); bpy.data.images.remove(im)
    a = a.reshape(h, w, 4)
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def _box(x, k):
    c = np.cumsum(np.cumsum(np.pad(x, ((1, 0), (1, 0))), 0), 1)
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def image_metrics(path_a, path_b, k=8):
    A = _gray(path_a); B = _gray(path_b)
    h = min(A.shape[0], B.shape[0]); w = min(A.shape[1], B.shape[1]); A = A[:h, :w]; B = B[:h, :w]
    mae = float(np.abs(A - B).mean())
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    mA, mB = _box(A, k), _box(B, k)
    sA = np.maximum(_box(A * A, k) - mA ** 2, 0); sB = np.maximum(_box(B * B, k) - mB ** 2, 0); sAB = _box(A * B, k) - mA * mB
    ssim = np.clip(((2 * mA * mB + C1) * (2 * sAB + C2)) / ((mA ** 2 + mB ** 2 + C1) * (sA + sB + C2)), -1, 1)
    return {"mae": round(mae, 4), "ssim": round(float(ssim.mean()), 4), "ssim_p5": round(float(np.percentile(ssim, 5)), 4)}
