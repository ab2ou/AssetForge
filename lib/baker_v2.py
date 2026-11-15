"""baker.py - Fab pipeline F3: bake the high-poly master onto the game mesh (Cycles, selected-to-active).

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\baker.py").read())
    start_bake("SM_DragonSword_B_LOD0", ["dragon_blade_B_pro","B_grip_collar","B_pommel_collar"], out_dir,
               prefix="T_DragonSword_B", size=4096)          # runs on a timer, one map per step, log in bake_log.txt

Maps: BaseColor (diffuse colour only), Normal (OpenGL; DirectX copy with flipped green), Roughness, Metallic
(via a temporary emission re-route of each high material, restored afterwards), AO, Emissive (gem).
Then: ORM packed (R=AO, G=Roughness, B=Metallic), 2K copies, and a game material M_<name> on the LODs.
"""
import bpy, os, time, json
import numpy as np


def _img(name, size, float_buf=False, non_color=False):
    im = bpy.data.images.get(name)
    if im:
        bpy.data.images.remove(im)
    im = bpy.data.images.new(name, size, size, alpha=False, float_buffer=float_buf)
    im.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return im


def _bake_mat(low):
    m = bpy.data.materials.get("BAKE_target") or bpy.data.materials.new("BAKE_target")
    m.use_nodes = True
    low.data.materials.clear(); low.data.materials.append(m)
    return m


def _set_target(m, im):
    nt = m.node_tree
    n = nt.nodes.get("BAKE_img") or nt.nodes.new("ShaderNodeTexImage")
    n.name = "BAKE_img"; n.image = im
    for x in nt.nodes:
        x.select = False
    n.select = True; nt.nodes.active = n


def _reroute(highs, socket):
    """temporarily send <socket> of every Principled BSDF in the high materials into an emission output."""
    saved = []; done = set()                    # a material shared by several objects is rerouted ONCE
    for ob in highs:                            # (bug fixed 2026-10-21: double reroute left it disconnected)
        for slot in ob.material_slots:
            mat = slot.material
            if not mat or not mat.use_nodes or mat.name in done:
                continue
            done.add(mat.name)
            nt = mat.node_tree
            out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
            bs = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if not out or not bs:
                continue
            prev = [(l.from_node, l.from_socket) for l in out.inputs["Surface"].links]
            em = nt.nodes.new("ShaderNodeEmission"); em.name = "BAKE_tmp_em"
            src = bs.inputs[socket]
            if src.is_linked:
                nt.links.new(src.links[0].from_socket, em.inputs["Color"])
            else:
                v = src.default_value
                em.inputs["Color"].default_value = (v, v, v, 1) if isinstance(v, float) else v
            nt.links.new(em.outputs[0], out.inputs["Surface"])
            saved.append((nt, out, prev, em))
    return saved


def _unlink_normal_maps(highs):
    """Normal bake from GEOMETRY only: temporarily cut the links into the Principled 'Normal' inputs of the high
    materials (AI textures carry their own blocky/noisy normal maps; baking them copies their artefacts).
    Returns what to relink."""
    cut = []; done = set()
    for ob in highs:
        for slot in ob.material_slots:
            mat = slot.material
            if not mat or not mat.use_nodes or mat.name in done: continue
            done.add(mat.name); nt = mat.node_tree
            for n in nt.nodes:
                if n.type == "BSDF_PRINCIPLED" and n.inputs["Normal"].is_linked:
                    l = n.inputs["Normal"].links[0]; cut.append((nt, l.from_socket, n.inputs["Normal"])); nt.links.remove(l)
    return cut


def _relink(cut):
    for nt, frm, to in reversed(cut): nt.links.new(frm, to)


def _restore(saved):
    for nt, out, prev, em in reversed(saved):
        for l in list(out.inputs["Surface"].links):
            nt.links.remove(l)
        for fn, fs in prev:
            nt.links.new(fs, out.inputs["Surface"])
        nt.nodes.remove(em)


def _save(im, path, depth="8"):
    """raw buffer save (no view transform): data maps stay linear, colour maps stay sRGB-encoded."""
    im.filepath_raw = path; im.file_format = "PNG"; im.save()


def _pixels(im):
    a = np.empty(len(im.pixels), np.float32); im.pixels.foreach_get(a)
    return a.reshape(im.size[1], im.size[0], 4)


def _use_gpu():
    """headless bakes only: use the NVIDIA card (OptiX, else CUDA) for this process. The user's saved preferences
    are not changed (background Blender does not save preferences). Returns a description or None (CPU)."""
    try:
        cp = bpy.context.preferences.addons["cycles"].preferences
        for t in ("OPTIX", "CUDA", "HIP"):
            try:
                cp.compute_device_type = t; cp.get_devices()
            except Exception:
                continue
            devs = [d for d in cp.devices if d.type == t]
            if devs:
                for d in cp.devices: d.use = d.type == t
                bpy.context.scene.cycles.device = "GPU"
                return f"GPU {t}: " + ", ".join(d.name for d in devs)
        cp.compute_device_type = "NONE"
    except Exception:
        pass
    return None


def start_bake(low_name, high_names, out_dir, prefix="T_Asset", size=4096, cage=0.004, max_ray=0.012,
               margin=16, ao_samples=48, device="AUTO", normal_from="geometry", color_high_names=None):
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene; low = bpy.data.objects[low_name]; highs = [bpy.data.objects[n] for n in high_names]
    # 1.5.0: colour-type maps can come from another (textured) high, e.g. the original kept by voxel_cleanup
    chighs = [bpy.data.objects[n] for n in (color_high_names or [])]
    COLOR_PASSES = ("BaseColor", "Roughness", "Metallic", "Emissive")
    log = os.path.join(out_dir, "bake_log.txt"); open(log, "w").write("start\n")
    orig_mats = [s.material for s in low.material_slots]
    m = _bake_mat(low)
    prev = {"engine": sc.render.engine, "samples": sc.cycles.samples, "device": sc.cycles.device}
    sc.render.engine = "CYCLES"
    device = os.environ.get("FORGE_BAKE_DEVICE", device)            # CPU forces the CPU (comparisons, low VRAM)
    dev = _use_gpu() if (bpy.app.background and device in ("AUTO", "GPU")) else None
    open(log, "a").write(f"device {dev or 'CPU'}\nnormal from {normal_from}\n")
    for o in highs + chighs + [low]:
        o.hide_render = False; o.hide_set(False)
    bk = sc.render.bake
    bk.use_selected_to_active = True; bk.cage_extrusion = cage; bk.max_ray_distance = max_ray; bk.margin = margin
    try:
        bk.margin_type = 'ADJACENT_FACES'
    except Exception:
        pass
    bk.use_clear = True
    # BaseColor via an emission reroute of the Base Color socket: the DIFFUSE colour pass is BLACK on metallic
    # surfaces (Cycles), which baked metals as black (found by the forge trial renders, 2026-10-21)
    plan = [("BaseColor", "EMIT", None, 1, False, "Base Color"),
            ("Normal", "NORMAL", None, 1, True, None),
            ("Roughness", "ROUGHNESS", None, 1, True, None),
            ("Metallic", "EMIT", None, 1, True, "Metallic"),
            ("AO", "AO", None, ao_samples, True, None),
            ("Emissive", "EMIT", None, 1, False, "__emit__")]
    st = {"i": 0, "t": time.time(), "imgs": {}}

    def select(src):
        bpy.ops.object.select_all(action="DESELECT")
        for o in src:
            o.select_set(True)
        low.select_set(True); bpy.context.view_layer.objects.active = low

    def step():
        try:
            i = st["i"]
            if i < len(plan):
                name, btype, pf, samp, noncol, special = plan[i]
                im = _img(f"{prefix}_{name}", size, float_buf=False, non_color=noncol)
                src = chighs if (chighs and name in COLOR_PASSES) else highs
                _set_target(m, im); select(src)
                sc.cycles.samples = samp
                saved = _reroute(src, special) if special and special != "__emit__" else []
                cut = _unlink_normal_maps(highs) if (btype == "NORMAL" and normal_from == "geometry") else []
                emit_restore = []
                if special == "__emit__":
                    for ob in src:
                        for slot in ob.material_slots:
                            mt = slot.material
                            if mt and mt.use_nodes and "Math.004" in mt.node_tree.nodes:
                                n4 = mt.node_tree.nodes["Math.004"]; emit_restore.append((n4, n4.inputs[1].default_value)); n4.inputs[1].default_value = 1.0
                kw = {"type": btype}
                if pf:
                    kw["pass_filter"] = pf
                if btype == "NORMAL":
                    kw.update(normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y", normal_b="POS_Z")
                try:
                    bpy.ops.object.bake(**kw)
                finally:
                    _relink(cut)
                _restore(saved)
                for n4, v in emit_restore:
                    n4.inputs[1].default_value = v
                path = os.path.join(out_dir, f"{prefix}_{name}.png")
                _save(im, path, "16" if name == "Normal" else "8")
                st["imgs"][name] = im
                open(log, "a").write(f"{name} {round(time.time()-st['t'],1)}s\n"); st["t"] = time.time()
                st["i"] += 1; return 0.2
            # post: DirectX normal, ORM, 2K copies, game material
            N = _pixels(st["imgs"]["Normal"]).copy(); N[..., 1] = 1.0 - N[..., 1]
            dx = _img(f"{prefix}_Normal_DX", size, float_buf=False, non_color=True); dx.pixels.foreach_set(N.ravel())
            _save(dx, os.path.join(out_dir, f"{prefix}_Normal_DX.png"), "16")
            A, R, Mt = (_pixels(st["imgs"][k])[..., 0] for k in ("AO", "Roughness", "Metallic"))
            orm = _img(f"{prefix}_ORM", size, non_color=True)
            O = np.stack([A, R, Mt, np.ones_like(A)], -1); orm.pixels.foreach_set(O.ravel())
            _save(orm, os.path.join(out_dir, f"{prefix}_ORM.png"))
            for k in ("BaseColor", "Normal", "Normal_DX", "ORM", "Emissive"):
                src = os.path.join(out_dir, f"{prefix}_{k}.png")
                im2 = bpy.data.images.load(src, check_existing=False); im2.scale(size // 2, size // 2)
                d = os.path.join(out_dir, "2K"); os.makedirs(d, exist_ok=True)
                _save(im2, os.path.join(d, f"{prefix}_{k}_2K.png"), "16" if "Normal" in k else "8")
                bpy.data.images.remove(im2)
            for o in chighs:
                o.hide_set(True); o.hide_render = True
            open(log, "a").write("post ok\n")
            sc.render.engine = prev["engine"]; sc.cycles.samples = prev["samples"]; sc.cycles.device = prev["device"]
            open(log, "a").write("done\n"); return None
        except Exception as e:
            import traceback
            open(log, "a").write("ERROR " + traceback.format_exc() + "\n")
            sc.cycles.samples = prev["samples"]; return None
    if bpy.app.background:                       # headless: run synchronously
        while step() is not None: pass
    else:
        bpy.app.timers.register(step, first_interval=0.5)
    return [p[0] for p in plan]


def game_material(lod_names, tex_dir, prefix, mat_name):
    """Principled material from the baked maps (BaseColor sRGB, ORM/Normal non-color, Emissive)."""
    m = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bs.outputs[0], out.inputs[0])
    def tex(k, noncol):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(os.path.join(tex_dir, f"{prefix}_{k}.png"), check_existing=True)
        n.image.colorspace_settings.name = "Non-Color" if noncol else "sRGB"; return n
    bc = tex("BaseColor", False); nt.links.new(bc.outputs[0], bs.inputs["Base Color"])
    orm = tex("ORM", True); sep = nt.nodes.new("ShaderNodeSeparateColor"); nt.links.new(orm.outputs[0], sep.inputs[0])
    nt.links.new(sep.outputs[1], bs.inputs["Roughness"]); nt.links.new(sep.outputs[2], bs.inputs["Metallic"])
    nm = tex("Normal", True); nmap = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(nm.outputs[0], nmap.inputs["Color"])
    nt.links.new(nmap.outputs[0], bs.inputs["Normal"])
    em = tex("Emissive", False); nt.links.new(em.outputs[0], bs.inputs["Emission Color"])
    bs.inputs["Emission Strength"].default_value = 4.0
    for n in lod_names:
        o = bpy.data.objects[n]; o.data.materials.clear(); o.data.materials.append(m)
    return m.name
