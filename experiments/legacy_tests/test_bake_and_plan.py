"""s2 plan + 4K bake guard test (headless): blender -b --factory-startup -P forge/test_bake_and_plan.py"""
import json, os, time, copy, inspect
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
P = Project("forge_selftest"); S0 = copy.deepcopy(P.state); R = {}
def fresh():
    P.state = copy.deepcopy(S0); P.state["settings"].pop("s2_plan", None); P.state["settings"].pop("bake_1k_check", None)
    P.state["settings"].pop("allow_direct_highres_bake", None); P.state.setdefault("stages", {})
    P.state["stages"]["s3_uv"] = {"status": "PASS", "time": "2026-10-27 12:00:00"}; P.state["stages"].pop("s4_bake", None)
    P.state["settings"]["last_bake"] = {"size": 1024, "dir": "x"}
fresh(); R["s2_default_n"] = len(_s2_plan(P))
P.state["settings"]["s2_plan"] = [["A", 18000]]; R["s2_setting"] = _s2_plan(P)
R["s2_call_overrides"] = _s2_plan(P, (("C", 9000),))
fresh(); R["g_no_check"] = _bake_highres_guard(P, 4096)
R["g_1k_allowed"] = _bake_highres_guard(P, 1024)
P.state["settings"]["bake_1k_check"] = {"time": "2026-10-27 11:00:00", "ok": True}; R["g_uv_newer"] = _bake_highres_guard(P, 4096)
P.state["settings"]["bake_1k_check"] = {"time": "2026-10-27 13:00:00", "ok": False}; R["g_1k_failed"] = _bake_highres_guard(P, 4096)
P.state["settings"]["bake_1k_check"]["ok"] = True; P.state["stages"]["s4_bake"] = {"status": "REVIEW"}; R["g_not_approved"] = _bake_highres_guard(P, 4096)
P.state["stages"]["s4_bake"]["approved"] = {"by": "user"}; R["g_approved"] = _bake_highres_guard(P, 4096)
P.state["settings"]["last_bake"] = {"size": 4096}; P.state["stages"]["s4_bake"] = {"status": "REVIEW"}; R["g_rebake_4k"] = _bake_highres_guard(P, 4096)
fresh(); P.state["settings"]["allow_direct_highres_bake"] = True; R["g_override"] = _bake_highres_guard(P, 4096)
src4 = inspect.getsource(s4_bake) if False else open(r"<forge>\forge_stages.py", encoding="utf-8").read()
R["s4_calls_guard"] = "why = _bake_highres_guard(P, size)" in src4 and "bake_1k_check\"] = {" in src4
exp = {"s2_default_5": R["s2_default_n"] == 5, "s2_setting_1": R["s2_setting"] == (("A", 18000),), "s2_call_wins": R["s2_call_overrides"] == (("C", 9000),),
       "no_check_refused": bool(R["g_no_check"]), "1k_free": R["g_1k_allowed"] is None, "uv_newer_refused": "UV changed" in (R["g_uv_newer"] or ""),
       "1k_fail_refused": bool(R["g_1k_failed"]), "unapproved_refused": "not approved" in (R["g_not_approved"] or ""),
       "approved_allowed": R["g_approved"] is None, "rebake_4k_allowed": R["g_rebake_4k"] is None, "override_allowed": R["g_override"] is None,
       "s4_wired": R["s4_calls_guard"]}
R["expectations"] = exp; R["all_ok"] = all(exp.values())
out = os.path.join(Project("forge_selftest").gate_dir("bake_plan_test"), "bake_plan_test.json")
json.dump(R, open(out, "w"), indent=2, default=str)
print("BAKE_PLAN_TEST " + json.dumps({"all_ok": R["all_ok"], "exp": exp, "report": out}))
