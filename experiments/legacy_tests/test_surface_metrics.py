"""Hausdorff / Chamfer metrics test: blender -b --factory-startup -P forge/test_surface_metrics.py"""
import json, os
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=1.0); a = bpy.context.active_object; a.name = "A"
bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=1.01); b = bpy.context.active_object; b.name = "B"
for o in (a, b):
    o.select_set(True); bpy.context.view_layer.objects.active = o; bpy.ops.object.modifier_add(type="TRIANGULATE"); bpy.ops.object.modifier_apply(modifier="Triangulate")
d, _ = deviation("B", ["A"], n=20000); H = max(d["low_to_high"]["max"], d["high_to_low"]["max"]); C = (d["low_to_high"]["mean"] + d["high_to_low"]["mean"]) / 2
exp = {"mean_present": "mean" in d["low_to_high"], "hausdorff_about_1cm": 0.009 < H < 0.0115, "chamfer_about_1cm": 0.009 < C < 0.0105, "chamfer_le_hausdorff": C <= H}
out_dir = Project("forge_selftest").gate_dir("surface_metrics_test"); out = os.path.join(out_dir, "surface_metrics_test.json")
json.dump({"exp": exp, "H": H, "C": C}, open(out, "w"), indent=2)
print("SM_TEST " + json.dumps({"all_ok": all(exp.values()), "exp": exp, "H_mm": round(H * 1000, 3), "C_mm": round(C * 1000, 3)}), flush=True)
