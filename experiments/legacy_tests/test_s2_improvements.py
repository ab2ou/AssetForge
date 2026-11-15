"""s2 improvements test (headless): blender -b bench/crimson_lava_dagger_decimate.blend -P forge/test_s2_improvements.py
winding check, auto symmetry, per-region normal gate. Old code = forge/_backup/*.20261029_154338"""
import json, os, bmesh, mathutils
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
F = r"<forge>"; TS = "20261029_154338"; exp = {}; info = {}
# A. winding
bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.triangulate(bm, faces=bm.faces)
tv = np.array([[v.index for v in f.verts] for f in bm.faces]); co = np.array([v.co[:] for v in bm.verts]); bm.free()
e0 = edge_faces(tv); tv2 = tv.copy(); tv2[0] = tv2[0][::-1]; e1 = edge_faces(tv2)
exp["winding_clean_0"] = e0["n_inconsistent_winding"] == 0; exp["winding_flipped_detected"] = e1["n_inconsistent_winding"] == 3
exp["flipped_cube_still_manifold_by_old_counts"] = e1["n_nonmanifold"] == 0 and e1["n_boundary"] == 0   # why the new count is needed
# B. symmetry decision
bpy.ops.mesh.primitive_monkey_add(size=0.5, location=(0, 0, 0)); mk = bpy.context.active_object
m_ = mk.modifiers.new("s", "SUBSURF"); m_.levels = 2; bpy.ops.object.modifier_apply(modifier="s")
s_sym = _decide_symmetry(mk.data, "auto"); mk.data.transform(mathutils.Matrix.Translation((0.05, 0, 0))); s_shift = _decide_symmetry(mk.data, "auto")
s_dag = _decide_symmetry(bpy.data.objects["SRC"].data, "auto")
info["symmetry"] = {"suzanne": s_sym[1], "suzanne_shifted": s_shift[1], "dagger": s_dag[1]}
exp["sym_detected_on_symmetric"] = s_sym[0] is True; exp["sym_off_when_shifted"] = s_shift[0] is False; exp["sym_off_on_dagger"] = s_dag[0] is False
exp["forced_modes"] = _decide_symmetry(mk.data, "on")[0] is True and _decide_symmetry(mk.data, "off")[0] is False
c2 = mk.copy(); c2.data = mk.data.copy(); bpy.context.scene.collection.objects.link(c2); _collapse(c2, 2000)
exp["collapse_runs"] = abs(sum(len(p.vertices) - 2 for p in c2.data.polygons) - 2000) < 50
# C. per-region normal gate on real benchmark candidates (dagger, same source)
for nm in ("regional_blender_symX_18k", "blender_collapse_18k", "regional_blender_symX_49k", "mo_attr_normals_32k"): bpy.data.objects[nm].location = (0, 0, 0)   # bench file spreads them on X for viewing
bpy.context.view_layer.update()
P = Project("crimson_lava_dagger"); tree, _, _ = bvh_of(["SRC"])
bad = _region_normal_p95(P, "regional_blender_symX_18k", tree); good = _region_normal_p95(P, "blender_collapse_18k", tree)
good49 = _region_normal_p95(P, "regional_blender_symX_49k", tree); mo = _region_normal_p95(P, "mo_attr_normals_32k", tree)
info["region_p95"] = {"regional_18k": bad, "uniform_18k": good, "regional_49k": good49, "meshopt_normals_32k": mo}
lr, lf = 13.0, 20.0
st = lambda d: "PASS" if max(d.values()) <= lr else ("REVIEW" if max(d.values()) <= lf else "FAIL")
info["status"] = {k: st(v) for k, v in info["region_p95"].items()}
exp["starved_gem_fails"] = info["status"]["regional_18k"] == "FAIL"; exp["uniform_passes"] = info["status"]["uniform_18k"] == "PASS"
exp["regional_49k_passes"] = info["status"]["regional_49k"] == "PASS"; exp["meshopt_normals_flagged"] = info["status"]["meshopt_normals_32k"] != "PASS"
# old gate: global deviation only (limit 0.0018 * L) -> the starved gem passed
lim = 0.0018 * P.state["anatomy"].get("length", 1.1832); dev, _ = deviation("regional_blender_symX_18k", ["SRC"], n=30000)
info["old_gate_dev_p99_mm"] = round(dev["low_to_high"]["p99"] * 1000, 3); info["old_gate_limit_mm"] = round(lim * 1000, 3)
exp["old_gate_missed_it"] = dev["low_to_high"]["p99"] <= lim
out_dir = Project("forge_selftest").gate_dir("s2_improvements_test"); out = os.path.join(out_dir, "s2_improvements_test.json")
json.dump({"expectations": exp, "info": info}, open(out, "w"), indent=2, default=str)
print("S2IMP_TEST " + json.dumps({"all_ok": all(exp.values()), "exp": exp, "info": info}, default=str), flush=True)
if all(exp.values()):
    rec = record_experiment(title="s2: auto symmetry, winding check, per-region normal gate (tool benchmark 2026-10-29)",
        change="forge_mesh: edge_faces counts inconsistent winding, mirror_symmetry(); forge_stages: _decide_symmetry (X-symmetric decimation only for mirror-symmetric meshes) in _decimate_copy/_collapse, s2 checks inconsistent_winding and region_normal_p95_deg (REVIEW > 13, FAIL > 20 deg)",
        hypothesis="no-op/harmful symmetry is avoided, flipped patches are caught, and a low poly with a starved small part (gem 45 deg) stops at s2 while good candidates pass",
        files=["forge_mesh.py", "forge_stages.py"], runs=[{"project": "forge_selftest", "step": "s2_improvements_test", "report": out}],
        before={"starved_gem_caught": False, "flip_detected": False, "symmetry": "always X"}, after={"starved_gem_caught": True, "flip_detected": True, "symmetry": "auto"},
        evidence=[out, r"<studio>\bench\results"], result="better", notes="benchmark data in <studio>\\bench; old code forge/_backup/*." + TS, agent="claude")
    print("RECORD " + json.dumps(rec, default=str)); print("UNTESTED " + json.dumps(check_environment()["untested_files"]))
