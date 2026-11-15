"""1.4.2 fixes unit test (headless): blender -b --factory-startup -P forge/test_142_fixes.py
Covers: curved-blade centreline + cameras, studio lights for s8, gallery brightness, empty-map detection,
README emissive text, 2K file naming in export, bake ray defaults. Integration evidence: zz_green_check, zz_dagger_check."""
import json, os, tempfile, shutil
import numpy as np
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
import bpy
exp = {}
# 1. centreline of a synthetic curved blade (x = 0.3 * (1 - z)^2 for z in 0..0.7), guard at 0.7
z = np.linspace(0, 0.7, 400); V = np.stack([0.3 * (1 - z) ** 2, np.zeros_like(z), z], 1)
an = {"length": 1.0, "tip_z": 0.0, "guard_z0": 0.7, "guard_z1": 0.8, "grip_z0": 0.8, "grip_z1": 0.95, "pommel_z1": 1.0,
      "guard_half_width": 0.1, "axis_xy": [0.0, 0.0]}
g = _anatomy_geometry(V, an); an.update(g)
x_mid = dict((v[0], v[1]) for v in inspection_views(an))["blade_mid"][0]
exp["centerline_follows_curve"] = abs(x_mid - 0.3 * (1 - 0.35) ** 2) < 0.01
an_old = {k: v for k, v in an.items() if k not in ("centerline", "bbox_center", "tip_point")}
exp["no_centerline_keeps_old_targets"] = dict((v[0], v[1]) for v in inspection_views(an_old))["tip"][:2] == (0.0, 0.0)
an2 = dict(an); an2.update(_anatomy_geometry(V, an)); tv = dict((v[0], v[1]) for v in inspection_views(an2))["tip"]
exp["tip_point_targeted"] = abs(tv[2] - 0.035) < 0.005 and abs(an2["tip_point"][0] - 0.3) < 1e-6
exp["bbox_center"] = abs(g["bbox_center"][0] - (0.3 + 0.3 * 0.3 ** 2) / 2) < 0.002
# 2. studio lights: empty scene -> 3 lights; scene with a light -> untouched
sc = bpy.context.scene
for o in list(sc.objects):
    if o.type == "LIGHT": bpy.data.objects.remove(o)
r1 = _ensure_studio(sc); exp["studio_added_when_dark"] = r1["added"] and len(r1["lights"]) == 3
r2 = _ensure_studio(sc); exp["studio_not_duplicated"] = not r2["added"]
# 3. brightness: synthetic renders (bright product vs dark product on the same grey background)
td = tempfile.mkdtemp()
def png(path, val):
    a = np.full((270, 480, 4), 0.22, np.float32); a[..., 3] = 1; a[100:170, 100:380, :3] = val
    im = bpy.data.images.new("t", 480, 270); im.pixels.foreach_set(a.ravel()); im.filepath_raw = path; im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)
png(os.path.join(td, "b.png"), 0.8); png(os.path.join(td, "d.png"), 0.08)
lb, cb = _product_brightness(os.path.join(td, "b.png")); ld, cd = _product_brightness(os.path.join(td, "d.png"))
exp["brightness_bright"] = abs(lb - 0.8) < 0.03 and cb > 0.1
exp["brightness_dark_below_ratio"] = ld / 0.62 < 0.6
# 4. empty map detection
png(os.path.join(td, "black.png"), 0.0)
a = np.zeros((64, 64, 4), np.float32); a[..., 3] = 1
im = bpy.data.images.new("k", 64, 64); im.pixels.foreach_set(a.ravel()); im.filepath_raw = os.path.join(td, "allblack.png"); im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)
exp["map_black_has_no_signal"] = _map_has_signal(os.path.join(td, "allblack.png")) is False
exp["map_bright_has_signal"] = _map_has_signal(os.path.join(td, "b.png")) is True
exp["map_missing_no_signal"] = _map_has_signal(os.path.join(td, "nope.png")) is False
# 5. README emissive line + 2K naming in the package
root = os.path.join(td, "exp"); 
for d in ("FBX", "GLB", "OBJ", "Blend", "Textures/4K", "Textures/2K"): os.makedirs(os.path.join(root, d), exist_ok=True)
open(os.path.join(root, "FBX", "a.fbx"), "w").write("x"); open(os.path.join(root, "Textures/4K", "T_X_BaseColor.png"), "w").write("x")
import zipfile
rp = package(root, os.path.join(td, "pk"), base="X", title="X", tris=(3, 2, 1), height_m=1.0, emissive=False)
txt = zipfile.ZipFile(os.path.join(td, "pk", "X_FBX.zip")).read("X/README.txt").decode()
exp["readme_no_lava_text"] = "lava" not in txt and "no glowing parts" in txt
rp = package(root, os.path.join(td, "pk2"), base="X", title="X", tris=(3, 2, 1), height_m=1.0)
exp["readme_default_glow_text"] = "glowing parts" in zipfile.ZipFile(os.path.join(td, "pk2", "X_FBX.zip")).read("X/README.txt").decode()
src = open(r"<forge>\lib\fab_export_v2.py", encoding="utf-8").read()
exp["export_2k_strips_suffix"] = 'f.replace("_2K.png", ".png")' in src
# 6. bake ray defaults (fake project state)
class _P: pass
P = _P(); P.state = {"anatomy": {"length": 1.2}, "settings": {}, "stages": {}}
c, r = _bake_ray_defaults(P); exp["ray_default_preview_values"] = abs(c - 0.0018) < 1e-9 and abs(r - 0.006) < 1e-9
rp_ = os.path.join(td, "s2.json"); json.dump({"data": {"hausdorff_mm": 4.0}}, open(rp_, "w"))
P.state["stages"]["s2_lowpoly"] = {"report": rp_}; c, r = _bake_ray_defaults(P); exp["ray_covers_hausdorff"] = abs(r - 0.012) < 1e-9
P.state["settings"]["bake_ray_rel"] = 0.0095; P.state["stages"] = {}; exp["ray_override"] = abs(_bake_ray_defaults(P)[1] - 0.0114) < 1e-9
# 7. profiles
prof = load_profiles(); exp["curved_profiles"] = all(k in prof["types"] for k in ("sabre", "scimitar", "katana"))
shutil.rmtree(td, ignore_errors=True)
ok = all(exp.values())
print("TEST_142 " + ("PASS" if ok else "FAIL") + " " + json.dumps(exp), flush=True)
