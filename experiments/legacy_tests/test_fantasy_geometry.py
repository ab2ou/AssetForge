"""fantasy geometry INFO test (headless): blender -b --factory-startup -P forge/test_fantasy_geometry.py"""
import json, os
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
F = r"<forge>"; TS = "20261027_213827"
new_prof = load_profiles(); old_prof = json.load(open(os.path.join(F, "_backup", "weapon_profiles.json." + TS), encoding="utf-8"))
old_ns = {"np": np}; exec(open(os.path.join(F, "_backup", "forge_specs.py." + TS), encoding="utf-8").read(), old_ns)
lt = new_prof["types"]["longsword"]
def mid(k): return (lt[k][0] + lt[k][1]) / 2
base = {"overall_m": mid("overall") * 1.9, "blade_m": lt["blade"][1] * 1.7, "grip_m": mid("grip"), "thickness_m": (lt["thickness"][1] * 3.0 if "thickness" in lt else 0.03),
        "mass_kg": (lt["mass"][1] * 3.0 if "mass" in lt else 6.0), "pob_from_guard_m": None, "watertight": True}
cases = {"exaggerated_fantasy": base, "grip_too_short": dict(base, grip_m=0.05), "wrong_units_x10": dict(base, overall_m=mid("overall") * 10)}
R = {}
for name, m in cases.items():
    for style in ("fantasy", "realistic"):
        o = {c[0]: c[2] for c in old_ns["spec_checks"](m, "longsword", style, old_prof, None, None)}
        n = {c[0]: c[2] for c in spec_checks(m, "longsword", style, new_prof, None, None)}
        R[f"{name}/{style}"] = {"old": o, "new": n}
geo = ("overall_length_m", "blade_length_m", "grip_length_m", "thickness_m")
ef = R["exaggerated_fantasy/fantasy"]; er = R["exaggerated_fantasy/realistic"]
exp = {"old_fantasy_geometry_failed": sum(ef["old"].get(k) == "FAIL" for k in geo) > 0,
       "new_fantasy_geometry_no_fail": all(ef["new"].get(k, "PASS") == "PASS" for k in geo),
       "mass_unchanged": ef["old"].get("mass_kg") == ef["new"].get("mass_kg"),
       "realistic_unchanged": er["old"] == er["new"],
       "grip_still_fails": R["grip_too_short/fantasy"]["new"].get("grip_fits_hands") == "FAIL",
       "units_still_fail": R["wrong_units_x10/fantasy"]["new"].get("scale_plausible") == "FAIL",
       "character_check_kept": "usable_by_character" in ef["new"]}
out_dir = Project("forge_selftest").gate_dir("fantasy_geometry_test"); out = os.path.join(out_dir, "fantasy_geometry_test.json")
before = {"fantasy_geometry_fails": sum(ef["old"].get(k) == "FAIL" for k in geo)}; after = {"fantasy_geometry_fails": sum(ef["new"].get(k) == "FAIL" for k in geo)}
json.dump({"cases": R, "expectations": exp, "before": before, "after": after}, open(out, "w"), indent=2)
print("FANTASY_TEST " + json.dumps({"all_ok": all(exp.values()), "exp": exp, "before": before, "after": after}))
if all(exp.values()):
    rec = record_experiment(title="fantasy: real-world geometry ranges are INFO only (user decision)",
        change="forge_specs.py spec_checks: style.geometry_info_only turns non-PASS length/thickness range checks into INFO PASS; weapon_profiles.json fantasy.geometry_info_only = true",
        hypothesis="exaggerated fantasy designs no longer stop at s0_spec on length/thickness, while units, grip-fits-hands and size-vs-character stay gates and realistic is unchanged",
        files=["forge_specs.py", "weapon_profiles.json"], runs=[{"project": "forge_selftest", "step": "fantasy_geometry_test", "report": out}],
        before=before, after=after, evidence=[out], result="better",
        notes="old code from forge/_backup/*.20261027_213827 vs new code on the same synthetic longsword cases", agent="claude")
    print("RECORD " + json.dumps(rec, default=str)); print("UNTESTED " + json.dumps(check_environment()["untested_files"]))
