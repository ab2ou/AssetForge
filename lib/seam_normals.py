"""seam_normals.py - smooth shading everywhere except along UV seams with a real crease.
Hard edges inside a UV chart make the normal map wrong across the edge (visible lines), so:
sharp = (UV seam) and (dihedral > max_deg); everything else smooth. Then weighted normals keep_sharp."""
import bpy, bmesh, math


def seam_sharp(name, uv_name="UV_game", max_deg=45.0):
    ob = bpy.data.objects[name]; me = ob.data
    bm = bmesh.new(); bm.from_mesh(me)
    uvl = bm.loops.layers.uv[uv_name]
    nseam = nsharp = 0
    for e in bm.edges:
        if len(e.link_faces) != 2:
            e.smooth = False; nsharp += 1; continue
        f1, f2 = e.link_faces
        def uvs(f):
            d = {}
            for l in f.loops:
                if l.vert in e.verts: d[l.vert.index] = l[uvl].uv.copy()
            return d
        a, b = uvs(f1), uvs(f2)
        seam = any((a[k] - b[k]).length > 1e-6 for k in a)
        e.seam = seam; nseam += seam
        ang = math.degrees(f1.normal.angle(f2.normal, 0.0))
        hard = seam and ang > max_deg
        e.smooth = not hard; nsharp += hard
    for f in bm.faces: f.smooth = True
    bm.to_mesh(me); bm.free(); me.update()
    for m in ob.modifiers:
        if m.type == 'WEIGHTED_NORMAL': m.keep_sharp = True
    return {'obj': name, 'seam_edges': nseam, 'sharp_edges': nsharp, 'edges': len(me.edges)}
