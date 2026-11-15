"""per-project cfg_override test (headless): blender -b --factory-startup -P forge/test_project_override.py"""
import json, os, shutil
exec(open(r"<forge>\forge.py", encoding="utf-8").read())
root = load_config()["projects_root"]; names = ["forge_selftest", "forge_selftest_override"]
d = os.path.join(root, names[1]); os.makedirs(d, exist_ok=True)
json.dump({"name": names[1], "stages": {}, "anatomy": {}, "settings": {"cfg_override": {"budgets": {"hero_sword": [18000, 50000, 0.5, 0.25]}}}},
          open(os.path.join(d, "state.json"), "w"), indent=2)
a = Project(names[0]).cfg; b = Project(names[1]).cfg; base = load_config()
exp = {"override_applied": b["budgets"]["hero_sword"][1] == 50000,
       "other_project_unchanged": a["budgets"]["hero_sword"] == base["budgets"]["hero_sword"],
       "other_categories_unchanged": b["budgets"]["standard_sword"] == base["budgets"]["standard_sword"],
       "rest_of_cfg_unchanged": {k: v for k, v in b.items() if k != "budgets"} == {k: v for k, v in base.items() if k != "budgets"},
       "explicit_cfg_wins": Project(names[1], cfg=load_config()).cfg["budgets"]["hero_sword"][1] == base["budgets"]["hero_sword"][1],
       "defaults_not_mutated": load_config()["budgets"]["hero_sword"][1] == 32000}
shutil.rmtree(d)
out_dir = Project("forge_selftest").gate_dir("project_override_test"); out = os.path.join(out_dir, "project_override_test.json")
json.dump({"expectations": exp}, open(out, "w"), indent=2)
print("OVERRIDE_TEST " + json.dumps({"all_ok": all(exp.values()), "exp": exp}))
if all(exp.values()):
    rec = record_experiment(title="per-project cfg_override in state.settings (user decision)",
        change="forge_core.py Project.__init__: settings.cfg_override (dict) is merged into the project cfg last; explicit cfg argument skips it",
        hypothesis="one project can raise e.g. its LOD0 budget without changing other projects, categories or defaults",
        files=["forge_core.py"], runs=[{"project": "forge_selftest", "step": "project_override_test", "report": out}],
        before={"per_project_override": False}, after={"per_project_override": True}, evidence=[out], result="better",
        notes="test project created and removed; old code backup forge/_backup/forge_core.py.20261028_154831", agent="claude")
    print("RECORD " + json.dumps(rec, default=str)); print("UNTESTED " + json.dumps(check_environment()["untested_files"]))
