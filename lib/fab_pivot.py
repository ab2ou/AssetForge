"""fab_pivot.py - export with the pivot at the grip (hand position) WITHOUT changing the working scene.

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\fab_export.py").read())
    exec(open(r"<home>\\Blender_AI_Studio\\tools\\fab_pivot.py").read())
    rep = export_with_pivot("SM_DragonSword_B", root, tex_dir, prefix, pivot=(-0.0033, -0.0006, 1.035))

The LOD meshes and their UCX hulls are shifted by -pivot (mesh data, object location stays 0) so the grip sits at
the origin in every exported file, then shifted back - the bake / media / high-poly alignment is untouched.
"""
import bpy, numpy as np


def _shift(objs, d):
    for o in objs:
        me = o.data
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3); co += np.array(d)
        me.vertices.foreach_set("co", co.ravel()); me.update()


def export_with_pivot(base, root, tex_dir, prefix, pivot=(-0.0033, -0.0006, 1.035)):
    objs = [o for o in bpy.data.objects if o.type == "MESH" and
            (o.name.startswith(f"{base}_LOD") or o.name.startswith(f"UCX_{base}_LOD0"))]
    for o in objs:
        assert tuple(round(v, 6) for v in o.location) == (0, 0, 0) and tuple(o.rotation_euler) == (0, 0, 0), o.name
    _shift(objs, [-p for p in pivot])
    try:
        rep = export_all(base, root, tex_dir, prefix)
    finally:
        _shift(objs, pivot)
    return {"pivot": list(pivot), "objects": [o.name for o in objs], "files": rep}
