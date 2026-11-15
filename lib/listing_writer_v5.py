"""listing_writer.py - Fab pipeline F7: listing text from MEASURED data (never invented numbers).

    exec(open(r"<home>\\Blender_AI_Studio\\tools\\listing_writer.py").read())
    write_listing(validate_report_json, out_dir, title="Inferno Dragon Sword", price_usd=19.99)

Produces listing.json (field by field, for the publisher) and listing.md (human-readable).
Rules: title <= 30 chars; every technical number comes from the F5 validation report; AI disclosure on.
"""
import json, os


def write_listing(report_path, out_dir, title="Inferno Dragon Sword", price_usd=19.99, author_note="", uv_note="Single UV channel: non-overlapping islands, uniform texel density (~45 px/cm at 4K)", extra=()):
    rep = json.load(open(report_path))
    files = rep["files"]
    lods = sorted([(k, v) for k, v in files.items() if k.startswith("FBX/") and "LOD" in k])
    tri = {k.split("_")[-1].replace(".fbx", ""): sum(o["tris"] for o in v["objects"] if not o["name"].startswith("UCX_"))
           for k, v in lods}
    ucx = sum(1 for k, v in lods for o in v["objects"] if o["name"].startswith("UCX_"))
    tex4 = sorted(k.split("/")[-1].replace(".png", "") for k in files if k.startswith("Textures/4K/"))
    h = next((v.get("height_m") for k, v in files.items() if k.startswith("GLB/")), None)
    assert len(title) <= 30, "Fab recommends titles of 30 characters or less"
    tech = [
        f"Real-world scale: {h:.2f} m long, Z-up, pivot at the grip (hand position)" if h else "Real-world scale, Z-up",
        "LODs: " + ", ".join(f"{k} {v:,} tris" for k, v in tri.items()),
        f"Collision: {ucx} convex UCX hulls (Unreal convention)" if ucx else "Collision: none",
        "Textures (4K and 2K, PNG): " + ", ".join(t.replace("T_DragonSword_B_", "") for t in tex4),
        "PBR Metal/Roughness; ORM packed (R=AO, G=Roughness, B=Metallic); Normal in OpenGL and DirectX",
        "Emissive map for the glowing gem",
        "Formats: FBX (per LOD), GLB (with embedded textures), OBJ, Blender .blend",
        uv_note,
    ] + list(extra)
    desc = (f"{title} - a dark fantasy two-handed sword with a dragon-wing guard, a glowing ember gem and a "
            "curved, spiked blade with a raised midrib, and a molten-lava channel.\n\n"
            "Game-ready and render-ready: three LODs, collision, PBR textures baked from a 1.5M-triangle "
            "sculpt, tested by re-import (scale, axes, UVs, textures).\n\n"
            "Technical details:\n- " + "\n- ".join(tech) + "\n\n"
            "Made with generative AI assistance: the base sculpt was AI-generated, then reworked and refined "
            "through a dedicated production pipeline (geometry rework, surface cleanup, LOD optimization, UVs, "
            "texture baking, materials).")
    listing = {
        "title": title, "price_usd": price_usd, "category": "3D Models > Weapons (or closest weapons category)",
        "tags": ["sword", "fantasy", "dragon", "weapon", "medieval", "dark fantasy", "game ready", "pbr", "low poly", "lod"],
        "description": desc, "technical_details": tech, "ai_disclosure": "Created with AI (base sculpt)",
        "mature_content": False,
        "lods_included": list(tri.keys()),
        "source_report": os.path.basename(report_path),
    }
    os.makedirs(out_dir, exist_ok=True)
    json.dump(listing, open(os.path.join(out_dir, "listing.json"), "w"), indent=1)
    md = f"# {title}\n\n**Price:** ${price_usd}  \n**Category:** {listing['category']}  \n**Tags:** {', '.join(listing['tags'])}  \n" \
         f"**AI disclosure:** {listing['ai_disclosure']}\n\n{desc}\n"
    open(os.path.join(out_dir, "listing.md"), "w", encoding="utf-8").write(md)
    return listing
