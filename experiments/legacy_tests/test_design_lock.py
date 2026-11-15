"""design lock test (headless): blender -b --factory-startup -P forge/test_design_lock.py"""
import json, os, time, traceback
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
PRJ = "forge_selftest"; R = {}; t0 = time.time()
def step(k, fn):
    try: R[k] = fn()
    except Exception as e: R[k] = {"error": repr(e)[:400]}
step("make", lambda: selftest_make(PRJ))
parts = R["make"]["parts"]
step("adopt", lambda: (s0_adopt(PRJ, parts), {"baseline": Project(PRJ).state["settings"].get("design_baseline")})[1])
step("check_initial", lambda: design_check(PRJ))
step("uniform_fit_1.15", lambda: {k: v for k, v in uniform_fit(PRJ, factor=1.15).items() if k != "saved_positions"})
step("check_after_uniform", lambda: design_check(PRJ))
step("thin_zone_locked", lambda: thin_zone(PRJ, 0.3, 0.5, 0.7))
step("extend_grip_locked", lambda: extend_grip(PRJ, add_m=0.03))
step("unlock", lambda: set_settings(PRJ, design_lock=False))
step("thin_zone_unlocked", lambda: thin_zone(PRJ, 0.3, 0.5, 0.7))
step("check_after_thin", lambda: design_check(PRJ))
def _restore():
    rep = json.load(open(os.path.join(Project(PRJ).gate_dir("s0_edits"), "thin.json"))); return restore_positions(PRJ, rep["saved_positions"])
step("restore", _restore)
step("check_after_restore", lambda: design_check(PRJ))
step("relock", lambda: set_settings(PRJ, design_lock=True))
exp = {"baseline_set": bool((R.get("adopt") or {}).get("baseline")),
       "initial_pass": R["check_initial"].get("status") == "PASS",
       "uniform_pass": R["check_after_uniform"].get("status") == "PASS",
       "thin_refused": "design_lock" in str(R["thin_zone_locked"].get("error", "")),
       "grip_refused": "design_lock" in str(R["extend_grip_locked"].get("error", "")),
       "thin_detected": R["check_after_thin"].get("status") == "FAIL",
       "restore_pass": R["check_after_restore"].get("status") == "PASS",
       "relocked": Project(PRJ).state["settings"].get("design_lock") is True}
R["expectations"] = exp; R["all_ok"] = all(exp.values()); R["seconds"] = round(time.time() - t0, 1)
out = os.path.join(Project(PRJ).gate_dir("design_lock_test"), "design_lock_test.json")
json.dump(R, open(out, "w"), indent=2, default=str); R["report"] = out
print("DESIGN_LOCK_TEST " + json.dumps({"all_ok": R["all_ok"], "exp": exp, "report": out}))
