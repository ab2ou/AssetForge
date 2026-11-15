"""fab_package.py - Fab pipeline: one zip per file type (Fab allows one file of each type per listing).

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\fab_package.py").read())
    package(root, out_dir, base="InfernoDragonSword")
Each zip contains its mesh files + Textures/4K + Textures/2K + README.txt (so every format is complete on its own).
"""
import os, zipfile


README = """{title}
Formats in this archive: {fmt}
Units: metres in Blender/GLB/OBJ, FBX exported with unit scale (imports at {h} m in Unreal/Unity).
Axes: Z-up in Blender; FBX/GLB/OBJ converted to each format's convention.
Pivot: {pivot}.
LODs: LOD0 {l0} tris, LOD1 {l1} tris, LOD2 {l2} tris. Collision: UCX_* convex hulls in the LOD0 FBX.
Textures: PBR metal/roughness. ORM = R AO, G Roughness, B Metallic. Normal = OpenGL (Blender/Unity),
Normal_DX = DirectX (Unreal). {emissive}
Texture files: {texfiles}
{extra}Created with AI assistance (base sculpt), refined in a dedicated production pipeline.
"""
EXTRA = {"EmissiveMask": "EmissiveMask: R = lava glow intensity, B = lava coverage (G unused) - use it to tune or tint the lava in your engine.\n",
         "Blend": "The .blend opens with LOD0 visible; LOD1/LOD2 and the UCX hulls are in hidden collections; textures are packed.\n"}


EMISSIVE = {True: "Emissive = the glowing parts; suggested emissive intensity 3-4.",
            False: "Emissive = black: this asset has no glowing parts (leave it unconnected)."}


def package(root, out_dir, base="InfernoDragonSword", title="Inferno Dragon Sword", tris=(47561, 22000, 11000), height_m=1.26,
            emissive=True, pivot="grip (hand position)"):
    """emissive: True when the Emissive map has glowing texels (1.4.2: the README always said 'lava and gem')."""
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    for fmt in ("FBX", "GLB", "OBJ", "Blend"):
        z = os.path.join(out_dir, f"{base}_{fmt}.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in os.listdir(os.path.join(root, fmt)):
                zf.write(os.path.join(root, fmt, f), f"{base}/{fmt}/{f}")
            if fmt != "GLB":                                   # GLB already embeds its textures
                for sub in ("Textures/4K", "Textures/2K"):
                    d = os.path.join(root, sub)
                    for f in (sorted(os.listdir(d)) if os.path.isdir(d) else []):     # a missing size is skipped
                        zf.write(os.path.join(d, f), f"{base}/{sub}/{f}")
            tex = sorted(os.listdir(os.path.join(root, "Textures/4K")))
            sizes = [s for s in ("4K", "2K") if os.path.isdir(os.path.join(root, "Textures", s))]
            extra = (EXTRA["EmissiveMask"] if any("EmissiveMask" in f for f in tex) else "") + (EXTRA["Blend"] if fmt == "Blend" else "")
            texfiles = (", ".join(tex) + f" ({' and '.join(sizes)})") if fmt != "GLB" else \
                ("BaseColor, ORM, Normal and Emissive are embedded in the GLB (4K)" if emissive else "BaseColor, ORM and Normal are embedded in the GLB (4K)")
            zf.writestr(f"{base}/README.txt", README.format(title=title, fmt=fmt, h=f"{height_m:.2f}", l0=f"{tris[0]:,}", l1=f"{tris[1]:,}", l2=f"{tris[2]:,}",
                                                            texfiles=texfiles, extra=extra, emissive=EMISSIVE[bool(emissive)], pivot=pivot))
        out[os.path.basename(z)] = round(os.path.getsize(z) / 1e6, 1)
    return out
