"""fab_export.py - Fab pipeline F4 (exporter) + F5 (export validator).

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\fab_export.py").read())
    rep = make_collision("SM_DragonSword_B_LOD0", parts=((-1, 0.69), (0.69, 0.935), (0.935, 2)))
    rep = export_all("SM_DragonSword_B", out_root, tex_dir, prefix="T_DragonSword_B", high=["dragon_blade_B_pro", ...])
    rep = validate(out_root, base="SM_DragonSword_B", expect_height_m=1.259)     # F5 gate

Layout (English, alphanumeric + underscore, short paths):
  <root>/FBX/SM_..._LOD0.fbx (+UCX collision), _LOD1.fbx, _LOD2.fbx
  <root>/GLB/SM_....glb              (LOD0 + embedded textures; also used for the Fab 3D preview)
  <root>/OBJ/SM_..._LOD0.obj + .mtl
  <root>/Textures/4K, <root>/Textures/2K
  <root>/Blend/<base>.blend          (game meshes + material, packed textures)
"""
import bpy, bmesh, os, re, json, shutil
import numpy as np


def make_collision(lod0, parts=((-1, 0.69), (0.69, 0.935), (0.935, 2.0))):
    """Unreal convention: UCX_<mesh>_NN convex hulls (one per part, split by height)."""
    src = bpy.data.objects[lod0]; M = np.array(src.matrix_world)
    co = np.array([v.co for v in src.data.vertices]); W = co @ M[:3, :3].T + M[:3, 3]
    made = []
    for i, (z0, z1) in enumerate(parts):
        name = f"UCX_{lod0}_{i:02d}"
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        pts = W[(W[:, 2] >= z0) & (W[:, 2] < z1)]
        if len(pts) < 4:
            continue
        bm = bmesh.new()
        for p in pts[:: max(1, len(pts) // 4000)]:
            bm.verts.new(p)
        res = bmesh.ops.convex_hull(bm, input=bm.verts)
        bmesh.ops.delete(bm, geom=[v for v in res["geom_interior"] if isinstance(v, bmesh.types.BMVert)], context="VERTS")
        me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(ob)
        ob.display_type = "WIRE"; ob.hide_render = True
        made.append({"name": name, "tris": sum(len(p.vertices) - 2 for p in me.polygons)})
    return made


def _select(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.hide_set(False); o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def export_all(base, root, tex_dir, prefix, high=None):
    os.makedirs(root, exist_ok=True)
    for d in ("FBX", "GLB", "OBJ", "Textures/4K", "Textures/2K", "Blend"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    out = {}
    lods = [bpy.data.objects[f"{base}_LOD{i}"] for i in range(3) if bpy.data.objects.get(f"{base}_LOD{i}")]
    ucx = [o for o in bpy.data.objects if o.name.startswith(f"UCX_{base}_LOD0")]
    # textures
    for f in os.listdir(tex_dir):
        if f.startswith(prefix) and f.endswith(".png"):
            shutil.copy(os.path.join(tex_dir, f), os.path.join(root, "Textures/4K", f))
    d2 = os.path.join(tex_dir, "2K")
    if os.path.isdir(d2):
        for f in os.listdir(d2):        # 1.4.2: one name per map in both sizes (the baker writes *_2K.png; s9 checks
            shutil.copy(os.path.join(d2, f), os.path.join(root, "Textures/2K", f.replace("_2K.png", ".png")))   # 2K == 4K names)
    # FBX per LOD (LOD0 carries the UCX collision)
    for i, o in enumerate(lods):
        _select([o] + (ucx if i == 0 else []))
        p = os.path.join(root, "FBX", f"{o.name}.fbx")
        bpy.ops.export_scene.fbx(filepath=p, use_selection=True, apply_scale_options="FBX_SCALE_ALL",
                                 mesh_smooth_type="FACE", use_tspace=True, path_mode="STRIP",
                                 bake_space_transform=False, object_types={"MESH"}, use_mesh_modifiers=True)
        out[p] = os.path.getsize(p)
    # GLB (LOD0, embedded textures)
    _select([lods[0]])
    p = os.path.join(root, "GLB", f"{base}.glb")
    bpy.ops.export_scene.gltf(filepath=p, export_format="GLB", use_selection=True, export_apply=True,
                              export_yup=True, export_image_format="AUTO")
    out[p] = os.path.getsize(p)
    # OBJ
    _select([lods[0]])
    p = os.path.join(root, "OBJ", f"{lods[0].name}.obj")
    bpy.ops.wm.obj_export(filepath=p, export_selected_objects=True, export_materials=True, path_mode="STRIP",
                          export_triangulated_mesh=True, forward_axis="NEGATIVE_Z", up_axis="Y")
    out[p] = os.path.getsize(p)
    # clean .blend with the game assets only (library write keeps the master file untouched)
    p = os.path.join(root, "Blend", f"{base}.blend")
    blocks = set(lods + ucx)
    for o in lods:
        for s in o.material_slots:
            if s.material:
                blocks.add(s.material)
                for n in s.material.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image:
                        n.image.pack(); blocks.add(n.image)
    bpy.data.libraries.write(p, blocks, fake_user=True, compress=True)
    out[p] = os.path.getsize(p)
    return {k.replace(root, ""): round(v / 1e6, 2) for k, v in out.items()}


NAME_OK = re.compile(r"^[A-Za-z0-9_.\-]+$")


def validate(root, base, expect_height_m=1.259, tol=0.003, max_img_mb=None, pivot_frac=None, pivot_tol=0.03):
    """F5 gate: re-import every export into a scratch scene and check it; also names, paths, textures."""
    rep = {"files": {}, "problems": [], "warnings": []}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            if not NAME_OK.match(f):
                rep["problems"].append(f"non-alphanumeric name: {rel}")
            if len(f"{os.path.basename(root)}/{rel}") > 140:
                rep["problems"].append(f"path > 140 chars: {rel}")
    # textures: power of two, <= 8K
    for sub in ("Textures/4K", "Textures/2K"):
        d = os.path.join(root, sub)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            im = bpy.data.images.load(os.path.join(d, f), check_existing=False)
            w, h = im.size
            if w & (w - 1) or h & (h - 1) or max(w, h) > 8192:
                rep["problems"].append(f"texture size {w}x{h}: {sub}/{f}")
            rep["files"][f"{sub}/{f}"] = {"px": [w, h], "mb": round(os.path.getsize(os.path.join(d, f)) / 1e6, 2)}
            bpy.data.images.remove(im)
    # re-import meshes
    def reimport(path, kind):
        before = set(bpy.data.objects)
        if kind == "fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        elif kind == "glb":
            bpy.ops.import_scene.gltf(filepath=path)
        elif kind == "obj":
            bpy.ops.wm.obj_import(filepath=path)
        new = [o for o in bpy.data.objects if o not in before]
        info = {"objects": [], "height_m": None}
        mins, maxs = [], []
        for o in new:
            if o.type != "MESH":
                continue
            me = o.data; tris = sum(len(p.vertices) - 2 for p in me.polygons)
            bb = np.array([o.matrix_world @ __import__("mathutils").Vector(c) for c in o.bound_box])
            mins.append(bb.min(0)); maxs.append(bb.max(0))
            mats = [s.material.name for s in o.material_slots if s.material]
            imgs = sorted({n.image.name for s in o.material_slots if s.material and s.material.use_nodes
                           for n in s.material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image})
            info["objects"].append({"name": o.name, "tris": tris, "uv": len(me.uv_layers), "materials": mats, "images": imgs})
        if mins:
            ext = np.max(maxs, 0) - np.min(mins, 0)
            info["extent_m"] = [round(float(e), 4) for e in ext]
            info["height_m"] = round(float(ext.max()), 4)
            ax = int(np.argmax(ext)); lo = float(np.min(mins, 0)[ax])
            info["pivot_frac"] = round(-lo / float(ext[ax]), 4)     # where the origin sits along the length (0..1)
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)
        return info
    for sub, kind in (("FBX", "fbx"), ("GLB", "glb"), ("OBJ", "obj")):
        d = os.path.join(root, sub)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not f.lower().endswith("." + kind):
                continue
            p = os.path.join(d, f)
            try:
                info = reimport(p, kind)
            except Exception as e:
                rep["problems"].append(f"import failed {sub}/{f}: {e!r}"); continue
            info["mb"] = round(os.path.getsize(p) / 1e6, 2)
            rep["files"][f"{sub}/{f}"] = info
            h = info.get("height_m")
            if h is None or abs(h - expect_height_m) > tol:
                rep["problems"].append(f"{sub}/{f}: longest extent {h} m (expected {expect_height_m})")
            pf = info.get("pivot_frac")
            if pivot_frac is not None and (pf is None or min(abs(pf - pivot_frac), abs(1 - pf - pivot_frac)) > pivot_tol):
                rep["problems"].append(f"{sub}/{f}: pivot at {pf} of the length (expected {pivot_frac})")
            for ob in info["objects"]:
                if ob["name"].startswith("UCX_"):
                    continue
                if ob["uv"] < 1:
                    rep["problems"].append(f"{sub}/{f}: {ob['name']} has no UVs")
                if kind != "obj" and not ob["images"]:
                    rep["warnings"].append(f"{sub}/{f}: {ob['name']} imported without textures (normal for FBX path_mode=STRIP)")
            if kind == "glb" and info["mb"] > 500:
                rep["problems"].append("GLB > 500 MB (Fab 3D preview limit)")
    rep["passed"] = not rep["problems"]
    return rep
