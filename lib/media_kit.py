"""media_kit.py - Fab pipeline F6: listing media from the GAME asset (what the buyer gets).

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\media_kit.py").read())
    start_media("SM_DragonSword_B_LOD0", out_dir, hide=[...])     # timer; log media_log.txt

Shots (1920x1080, PNG -> converted to JPG < 3 MB afterwards):
  01_hero (3/4, cinematic), 02_front, 03_back, 04_side, 05_guard_gem, 06_grip, 07_blade_detail,
  08_wireframe (Workbench wireframe), plus a 5 s EEVEE turntable MP4 (1920x1080).
"""
import bpy, os, math
from mathutils import Vector


def _cam(name="media_cam"):
    c = bpy.data.objects.get(name)
    if not c:
        c = bpy.data.objects.new(name, bpy.data.cameras.new(name)); bpy.context.scene.collection.objects.link(c)
    return c


def _aim(cam, target, direction, dist=None, ortho=None, lens=60, roll=0.0):
    from mathutils import Quaternion
    t = Vector(target); d = Vector(direction).normalized()
    if ortho:
        cam.data.type = "ORTHO"; cam.data.ortho_scale = ortho; cam.location = t + d * 3.0
    else:
        cam.data.type = "PERSP"; cam.data.lens = lens; cam.location = t + d * dist
    q = (t - cam.location).to_track_quat("-Z", "Y") @ Quaternion((0, 0, 1), math.radians(roll))
    cam.rotation_euler = q.to_euler()


SHOTS = [
    ("01_hero", dict(target=(0, 0, 0.63), direction=(0.55, -0.80, 0.18), dist=1.45, lens=35, roll=-58)),
    ("02_front", dict(target=(0, 0, 0.63), direction=(0, -1, 0), ortho=1.40, roll=90)),
    ("03_back", dict(target=(0, 0, 0.63), direction=(0, 1, 0), ortho=1.40, roll=-90)),
    ("04_side", dict(target=(0, 0, 0.63), direction=(1, 0, 0), ortho=1.40, roll=90)),
    ("05_guard_gem", dict(target=(0, 0, 0.82), direction=(0.35, -1, 0.15), dist=0.75, lens=60)),
    ("06_grip", dict(target=(0, 0, 1.05), direction=(0.5, -1, 0.1), dist=0.55, lens=60)),
    ("07_blade_detail", dict(target=(0.01, 0, 0.42), direction=(0.45, -1, 0.25), dist=0.65, lens=60)),
]


def start_media(obj_name, out_dir, hide=(), samples=96, res=(1920, 1080), turntable_frames=120):
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene; r = sc.render; ob = bpy.data.objects[obj_name]
    log = os.path.join(out_dir, "media_log.txt"); open(log, "w").write("start\n")
    prev = dict(cam=sc.camera, engine=r.engine, rx=r.resolution_x, ry=r.resolution_y, s=sc.cycles.samples,
                fp=r.filepath, fmt=r.image_settings.file_format, f0=sc.frame_start, f1=sc.frame_end,
                shade=sc.display.shading.type if hasattr(sc.display, "shading") else None)
    hidden = []
    for o in sc.objects:
        if o.type == "MESH" and o is not ob and not o.hide_render and not o.name.startswith(("cine_floor", "cine_back")):
            if o.name in hide or o.name.startswith(("dragon_blade", "B_", "SM_", "UCX_")):
                o.hide_render = True; hidden.append(o)
    ob.hide_render = False
    cine = bpy.data.collections.get("cine")
    walls = []
    if cine:
        cine.hide_render = False
        for o in cine.all_objects:
            if o.type == "MESH" and not o.hide_render:
                o.hide_render = True; walls.append(o)
            if o.type == "LIGHT" and o.light_linking.receiver_collection:
                rc = o.light_linking.receiver_collection
                if ob.name not in rc.all_objects:
                    rc.objects.link(ob)
    cam = _cam(); r.resolution_x, r.resolution_y = res
    st = {"i": 0}

    def restore():
        for o in hidden + walls:
            o.hide_render = False
        ob.hide_render = True
        sc.camera = prev["cam"]; r.engine = prev["engine"]; r.resolution_x = prev["rx"]; r.resolution_y = prev["ry"]
        sc.cycles.samples = prev["s"]; r.filepath = prev["fp"]; r.image_settings.file_format = prev["fmt"]
        sc.frame_start, sc.frame_end = prev["f0"], prev["f1"]

    def step():
        try:
            i = st["i"]
            if i < len(SHOTS):
                n, kw = SHOTS[i]
                _aim(cam, **kw); sc.camera = cam; r.engine = "CYCLES"; sc.cycles.samples = samples
                r.image_settings.file_format = "PNG"; r.filepath = os.path.join(out_dir, n + ".png")
                bpy.ops.render.render(write_still=True)
            elif i == len(SHOTS):
                _aim(cam, target=(0, 0, 0.63), direction=(0.55, -0.80, 0.18), dist=1.45, lens=35, roll=-58)
                r.engine = "BLENDER_WORKBENCH"; sc.display.shading.type = "WIREFRAME"
                r.filepath = os.path.join(out_dir, "08_wireframe.png"); bpy.ops.render.render(write_still=True)
                sc.display.shading.type = "SOLID"
            elif i == len(SHOTS) + 1:
                # turntable: rotate the asset around Z on a temporary empty
                piv = bpy.data.objects.get("media_pivot") or bpy.data.objects.new("media_pivot", None)
                if piv.name not in sc.collection.objects:
                    sc.collection.objects.link(piv)
                old_parent = ob.parent; ob.parent = piv
                piv.rotation_euler = (0, 0, 0); piv.keyframe_insert("rotation_euler", index=2, frame=1)
                piv.rotation_euler = (0, 0, 2 * math.pi); piv.keyframe_insert("rotation_euler", index=2, frame=turntable_frames + 1)
                for fc in piv.animation_data.action.fcurves:
                    for k in fc.keyframe_points:
                        k.interpolation = "LINEAR"
                _aim(cam, target=(0, 0, 0.63), direction=(0, -1, 0.10), dist=1.75, lens=35, roll=90)
                r.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in r.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
                sc.frame_start, sc.frame_end = 1, turntable_frames
                r.image_settings.file_format = "FFMPEG"; r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
                r.ffmpeg.constant_rate_factor = "HIGH"; r.filepath = os.path.join(out_dir, "09_turntable_")
                bpy.ops.render.render(animation=True)
                ob.parent = old_parent; piv.animation_data_clear()
            else:
                restore(); open(log, "a").write("done\n"); return None
            open(log, "a").write(f"{i}\n"); st["i"] += 1; return 0.3
        except Exception:
            import traceback
            open(log, "a").write("ERROR " + traceback.format_exc()); restore(); return None
    if bpy.app.background:
        while step() is not None: pass
    else:
        bpy.app.timers.register(step, first_interval=0.3)
    return [s[0] for s in SHOTS] + ["08_wireframe", "09_turntable"]


def _wire_mat():
    m = bpy.data.materials.get("M_media_wire") or bpy.data.materials.new("M_media_wire")
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); mix = nt.nodes.new("ShaderNodeMixShader")
    base = nt.nodes.new("ShaderNodeBsdfPrincipled"); base.inputs["Base Color"].default_value = (0.05, 0.05, 0.06, 1)
    base.inputs["Roughness"].default_value = 0.6
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Color"].default_value = (0.95, 0.55, 0.25, 1); em.inputs["Strength"].default_value = 2.0
    wf = nt.nodes.new("ShaderNodeWireframe"); wf.use_pixel_size = True; wf.inputs["Size"].default_value = 1.0
    nt.links.new(wf.outputs[0], mix.inputs[0]); nt.links.new(base.outputs[0], mix.inputs[1]); nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    return m


def reshoot(obj_name, out_dir, shots, samples=96, res=(1920, 1080)):
    """re-render selected shots; each shot may rotate the ASSET (spin_deg around Z) instead of moving the
    camera behind it, so the studio lighting stays the same. shots: [(name, aim_kwargs, spin_deg)]"""
    sc = bpy.context.scene; r = sc.render; ob = bpy.data.objects[obj_name]
    log = os.path.join(out_dir, "reshoot_log.txt"); open(log, "w").write("start\n")
    hidden = [o for o in sc.objects if o.type == "MESH" and o is not ob and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    ob.hide_render = False
    prev = dict(cam=sc.camera, rot=ob.rotation_euler.copy(), rx=r.resolution_x, ry=r.resolution_y, s=sc.cycles.samples)
    cam = _cam(); st = {"i": 0}

    def restore():
        for o in hidden:
            o.hide_render = False
        ob.hide_render = True; ob.rotation_euler = prev["rot"]; sc.camera = prev["cam"]
        r.resolution_x, r.resolution_y = prev["rx"], prev["ry"]; sc.cycles.samples = prev["s"]

    def step():
        try:
            i = st["i"]
            if i >= len(shots):
                restore(); open(log, "a").write("done\n"); return None
            n, kw, spin = shots[i][:3]
            use_wire = len(shots[i]) > 3 and shots[i][3] == "wire"
            mats = [sl.material for sl in ob.material_slots]
            if use_wire:
                wm = _wire_mat()
                for sl in ob.material_slots:
                    sl.material = wm
            ob.rotation_euler = (prev["rot"][0], prev["rot"][1], prev["rot"][2] + math.radians(spin))
            _aim(cam, **kw); sc.camera = cam; r.engine = "CYCLES"; sc.cycles.samples = samples
            r.resolution_x, r.resolution_y = res; r.image_settings.file_format = "PNG"
            r.filepath = os.path.join(out_dir, n + ".png"); bpy.ops.render.render(write_still=True)
            if use_wire:
                for sl, m in zip(ob.material_slots, mats):
                    sl.material = m
            open(log, "a").write(n + "\n"); st["i"] += 1; return 0.3
        except Exception:
            import traceback
            open(log, "a").write("ERROR " + traceback.format_exc()); restore(); return None
    if bpy.app.background:
        while step() is not None: pass
    else:
        bpy.app.timers.register(step, first_interval=0.3)
    return [s[0] for s in shots]


def turntable(obj_name, out_dir, frames=120, aim=None, engine=None):
    """rotate the asset 360 deg around world Z (linear), render MP4 1920x1080. Blender 5-safe (no fcurve access)."""
    sc = bpy.context.scene; r = sc.render; ob = bpy.data.objects[obj_name]
    log = os.path.join(out_dir, "turntable_log.txt"); open(log, "w").write("start\n")
    hidden = [o for o in sc.objects if o.type == "MESH" and o is not ob and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    ob.hide_render = False
    prefs = bpy.context.preferences.edit; old_interp = prefs.keyframe_new_interpolation_type
    prev = dict(cam=sc.camera, f0=sc.frame_start, f1=sc.frame_end, eng=r.engine, fmt=r.image_settings.file_format, fp=r.filepath)
    rot0 = ob.rotation_euler.copy()

    def run():
        try:
            prefs.keyframe_new_interpolation_type = "LINEAR"
            ob.rotation_euler = rot0; ob.keyframe_insert("rotation_euler", index=2, frame=1)
            ob.rotation_euler = (rot0[0], rot0[1], rot0[2] + 2 * math.pi); ob.keyframe_insert("rotation_euler", index=2, frame=frames + 1)
            cam = _cam(); _aim(cam, **(aim or dict(target=(0, 0, 0.63), direction=(0, -1, 0.10), dist=1.75, lens=35, roll=90)))
            sc.camera = cam
            engines = [e.identifier for e in r.bl_rna.properties["engine"].enum_items]
            r.engine = engine or ("BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE")
            sc.frame_start, sc.frame_end = 1, frames
            r.resolution_x, r.resolution_y = 1920, 1080
            ims = r.image_settings
            if hasattr(ims, "media_type"):              # Blender 5: video output is a separate media type
                ims.media_type = "VIDEO"
            ims.file_format = "FFMPEG"; r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
            r.ffmpeg.constant_rate_factor = "HIGH"; r.filepath = os.path.join(out_dir, "09_turntable_")
            bpy.ops.render.render(animation=True)
            open(log, "a").write("done\n")
        except Exception:
            import traceback
            open(log, "a").write("ERROR " + traceback.format_exc())
        finally:
            prefs.keyframe_new_interpolation_type = old_interp
            ob.animation_data_clear(); ob.rotation_euler = rot0
            for o in hidden:
                o.hide_render = False
            ob.hide_render = True
            sc.camera = prev["cam"]; sc.frame_start, sc.frame_end = prev["f0"], prev["f1"]; r.engine = prev["eng"]
            if hasattr(r.image_settings, "media_type"):
                r.image_settings.media_type = "IMAGE"
            r.image_settings.file_format = prev["fmt"]; r.filepath = prev["fp"]
        return None
    if bpy.app.background:
        while run() is not None: pass
    else:
        bpy.app.timers.register(run, first_interval=0.3)
    return True
