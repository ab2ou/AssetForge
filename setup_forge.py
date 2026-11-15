"""One-time setup of Sword Forge on a machine.

Run it with Blender's own Python, so the installed libraries match Blender's Python version:

    "<Blender folder>/5.2/python/bin/python.exe" setup_forge.py --projects D:/Forge/projects
    # or inside Blender:
    blender -b --python setup_forge.py -- --projects D:/Forge/projects

It
  1. remembers where this folder is (~/.sword_forge_dir), so forge.py, the CLI and the add-on find the code;
  2. writes paths.local.json (projects folder, ledger, blender executable) - see paths.example.json;
  3. installs the libraries of requirements.txt (pymeshlab) into ./pylibs.

--meshlib also installs MeshLib, an optional voxel engine (high_cleanup.engine = "meshlib"). Sword Forge does not need
it, and its free licence covers non-commercial use only.
"""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ap = argparse.ArgumentParser(description="Sword Forge setup")
ap.add_argument("--projects", help="folder for the projects (default: ~/SwordForge/projects)")
ap.add_argument("--blender", help="blender executable used by the orchestrator")
ap.add_argument("--no-deps", action="store_true", help="do not install Python libraries")
ap.add_argument("--meshlib", action="store_true", help="also install MeshLib (non-commercial licence)")
a = ap.parse_args(argv)

# 1. where the code is
with open(os.path.join(os.path.expanduser("~"), ".sword_forge_dir"), "w", encoding="utf-8") as f:
    f.write(HERE)

# 2. machine paths
lp = os.path.join(HERE, "paths.local.json")
P = json.load(open(lp, encoding="utf-8")) if os.path.exists(lp) else {}
if a.projects: P["projects_root"] = os.path.abspath(os.path.expanduser(a.projects))
P.setdefault("projects_root", os.path.join(os.path.expanduser("~"), "SwordForge", "projects"))
P.setdefault("ledger", os.path.join(os.path.dirname(P["projects_root"]), "forge_ledger.jsonl"))
if a.blender:
    P["blender"] = os.path.abspath(a.blender)
else:
    try:
        import bpy                                    # running inside Blender
        P.setdefault("blender", bpy.app.binary_path)
    except ImportError:
        pass
os.makedirs(P["projects_root"], exist_ok=True)
with open(lp, "w", encoding="utf-8") as f:
    json.dump(P, f, indent=2)
print("paths.local.json:", json.dumps(P, indent=2))

# 3. libraries into ./pylibs (numpy is Blender's own, so no dependencies are pulled in for pymeshlab)
if not a.no_deps:
    py = sys.executable
    print(f"installing with {py} (Python {sys.version.split()[0]}): use Blender's Python so the versions match")
    if subprocess.call([py, "-m", "pip", "--version"]) != 0:
        subprocess.check_call([py, "-m", "ensurepip", "--upgrade"])
    target = os.path.join(HERE, "pylibs")
    req = [l.strip() for l in open(os.path.join(HERE, "requirements.txt"), encoding="utf-8")
           if l.strip() and not l.strip().startswith("#")]
    subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "--no-deps", "--target", target] + req)
    if a.meshlib:
        print("MeshLib: free for non-commercial use only; a commercial licence is needed for commercial work")
        subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "--target", target, "meshlib"])

print("\nSword Forge is set up. Next:")
print("  - Blender: Edit > Preferences > Add-ons > Install from Disk > forge_addon.py (tab 'Sword Forge', N panel)")
print("  - self-test:", f'"{sys.executable}" "{os.path.join(HERE, "tests", "run_selftest.py")}"')
