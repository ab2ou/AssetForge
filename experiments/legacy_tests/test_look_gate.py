"""look gate / target use / keep-awake unit test (headless, factory startup): blender -b --factory-startup -P forge/test_look_gate.py
Integration evidence (run separately): zz_regional_check (s2_auto), zz_s4_check (s4 look), bench look_cal2 (calibration)."""
import json, os
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
exp = {}
exp["keep_awake_windows"] = _keep_awake() is True
th = {"look_excess_p95_max": 0.010, "look_iou_min": 0.988}
look = {"views": {"a": {"dL_p95": 0.020}, "b": {"dL_p95": 0.035}}, "min_iou": ["a", 0.995]}; ref = {"a": {"dL_p95": 0.018}, "b": {"dL_p95": 0.022}}
ok, lim = _look_status(look, th, ref); exp["excess_fails_worst_view"] = (not ok) and lim["worst_excess"][0] == "b" and abs(lim["worst_excess"][1] - 0.013) < 1e-9
look2 = {"views": {"a": {"dL_p95": 0.020}, "b": {"dL_p95": 0.030}}, "min_iou": ["a", 0.995]}; ok2, _ = _look_status(look2, th, ref); exp["excess_passes"] = ok2
look3 = dict(look2, min_iou=["a", 0.98]); ok3, _ = _look_status(look3, th, ref); exp["silhouette_fails"] = not ok3
exp["floor_removed"] = _look_status(look2, th, None)[0] is False      # without the reference the same render floor would fail
# calibration: on 3 swords the excess falls with the budget and the known-bad candidates fail
cal = {}; B = r"<studio>\bench\results"
for m in ("crimson_lava_dagger", "celestial_spiral_sword", "inferno_dragon_v2"):
    R = json.load(open(os.path.join(B, m + "_look_cal2.json"))); d = {r["tag"]: r for r in R["runs"]}
    st = {k: _look_status({"views": v["look_views"], "min_iou": v["min_iou"]}, th, R["ref"])[0] for k, v in d.items()}
    cal[m] = st
    exp[m + "_monotone_8k_to_30k"] = d["u8k"]["worst_excess"][1] > d["u16k"]["worst_excess"][1] > d["u30k"]["worst_excess"][1]
    exp[m + "_meshopt_fails"] = st["bad_meshopt_18k"] is False and st["u8k"] is False
exp["dagger_22k_passes"] = cal["crimson_lava_dagger"]["u22k"]; exp["inferno_22k_passes"] = cal["inferno_dragon_v2"]["u22k"]
P = Project("zz_regional_check"); exp["target_use_written"] = P.state["settings"].get("target_use") == "fab_pc" and P.cfg["budgets"][P.cfg["category"]][:2] == [16000, 30000]
try: set_target_use("zz_regional_check", "nonsense"); exp["bad_use_refused"] = False
except ValueError: exp["bad_use_refused"] = True

rep2 = json.load(open('<projects>\\zz_regional_check\\reports\\s2_lowpoly\\report.json')); rep4 = json.load(open('<projects>\\zz_s4_check\\reports\\s4_bake\\report.json'))
exp["integration_s2_auto_look_checks"] = any(c["id"] == "look_excess_p95" for c in rep2["checks"]) and not any(c["status"] == "FAIL" for c in rep2["checks"])
exp["integration_s4_look_checks"] = any(c["id"] == "look_excess_p95" and c["status"] == "PASS" for c in rep4["checks"])
out_dir = Project("forge_selftest").gate_dir("look_gate_test"); out = os.path.join(out_dir, "look_gate_test.json")
json.dump({"expectations": exp, "calibration_status": cal}, open(out, "w"), indent=2, default=str)
print("LOOK_TEST2 " + json.dumps({"all_ok": all(exp.values()), "n": len(exp), "exp": exp}, default=str), flush=True)
if all(exp.values()):
    ev = [out, '<projects>\\zz_regional_check\\reports\\s2_lowpoly\\report.json', '<projects>\\zz_s4_check\\reports\\s4_bake\\report.json'] + [os.path.join(B, m + "_look_cal2.json") for m in ("crimson_lava_dagger", "celestial_spiral_sword", "inferno_dragon_v2")]
    rec = record_experiment(title="look gate (preview normal bake vs high), s2_auto by target use, keep-awake, clean decimated copies",
        change="forge_stages: USE_PROFILES/set_target_use, look_preview_bake, look_compare, _look_reference/_look_excess/_look_status, s2_auto, look checks in s2_lowpoly and s4_bake_check, _keep_awake in s3/s4, _decimate_copy drops inherited UVs/custom normals/sharp flags",
        hypothesis="judging the low poly WITH its normal map (excess over a dense reference) picks the smallest budget that looks like the high and rejects low/bad candidates that the old deviation-only gate passed",
        files=["forge_stages.py"], runs=[{"project": "zz_regional_check", "step": "s2_auto fab_pc", "report": '<projects>\\zz_regional_check\\reports\\s2_lowpoly\\report.json'}, {"project": "zz_s4_check", "step": "s4_bake_check look", "report": '<projects>\\zz_s4_check\\reports\\s4_bake\\report.json'}],
        before={"gate": "deviation p99 only", "old_18k_pass_on_3_swords": True, "meshopt_18k_pass": True},
        after={"gate": "deviation + region normals + look excess + silhouette", "old_18k_pass_on_3_swords": False, "meshopt_18k_pass": False},
        evidence=ev, result="better", notes="threshold excess 0.010 (16-bit renders, 1K preview); the final 4K bake of an 18k LOD0 passed the s4 look check, so the 1K preview is conservative", agent="claude")
    print("RECORD " + json.dumps(rec, default=str)); print("UNTESTED " + json.dumps(check_environment()["untested_files"]))
