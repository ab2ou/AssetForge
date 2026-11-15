"""listing_writer.py - Fab pipeline F7: listing text from MEASURED data (never invented numbers).

    write_listing(validate_report_json, out_dir, title="My Asset", description="what it is, in your words",
                  tags=["fantasy", "prop"], category="3D Models > Props")

Produces listing.json (field by field, for the publisher) and listing.md (human-readable).
Rules: title <= 30 chars; every technical number comes from the F5 validation report; AI disclosure on.
The description, tags and category are the seller's words: nothing is invented here (1.6.1: the old version had one
sword's description hard-coded).
"""
import json, os


def write_listing(report_path, out_dir, title, description="", price_usd=19.99, tags=(), category="", pivot="grip (hand position)",
                  emissive_note="", author_note="", uv_note="Single UV channel: non-overlapping islands, uniform texel density",
                  extra=()):
    rep = json.load(open(report_path))
    files = rep["files"]
    lods = sorted([(k, v) for k, v in files.items() if k.startswith("FBX/") and "LOD" in k])
    tri = {k.split("_")[-1].replace(".fbx", ""): sum(o["tris"] for o in v["objects"] if not o["name"].startswith("UCX_"))
           for k, v in lods}
    ucx = sum(1 for k, v in lods for o in v["objects"] if o["name"].startswith("UCX_"))
    tex4 = sorted(k.split("/")[-1].replace(".png", "") for k in files if k.startswith("Textures/4K/"))
    pre = os.path.commonprefix(tex4) if len(tex4) > 1 else ""
    pre = pre[:pre.rfind("_") + 1] if "_" in pre else ""
    h = next((v.get("height_m") for k, v in files.items() if k.startswith("GLB/")), None)
    assert len(title) <= 30, "Fab recommends titles of 30 characters or less"
    tech = [
        f"Real-world scale: {h:.2f} m (largest side), Z-up, pivot at the {pivot}" if h else "Real-world scale, Z-up",
        "LODs: " + ", ".join(f"{k} {v:,} tris" for k, v in tri.items()),
        f"Collision: {ucx} convex UCX hulls (Unreal convention)" if ucx else "Collision: none",
        "Textures (4K and 2K, PNG): " + ", ".join(t[len(pre):] for t in tex4),
        "PBR Metal/Roughness; ORM packed (R=AO, G=Roughness, B=Metallic); Normal in OpenGL and DirectX",
    ] + ([emissive_note] if emissive_note else []) + [
        "Formats: FBX (per LOD), GLB (with embedded textures), OBJ, Blender .blend",
        uv_note,
    ] + list(extra)
    desc = ((description.strip() or f"{title} - DESCRIPTION TO WRITE") + "\n\n"
            "Technical details:\n- " + "\n- ".join(tech) + "\n\n"
            "Made with generative AI assistance: the base model was AI-generated, then reworked and refined "
            "through a dedicated production pipeline (surface cleanup, low poly and LODs, UVs, texture baking).")
    listing = {
        "title": title, "price_usd": price_usd, "category": category, "tags": list(tags),
        "description": desc, "technical_details": tech, "ai_disclosure": "Created with AI (base model)",
        "mature_content": False, "lods_included": list(tri.keys()), "source_report": os.path.basename(report_path),
        "author_note": author_note,
    }
    os.makedirs(out_dir, exist_ok=True)
    json.dump(listing, open(os.path.join(out_dir, "listing.json"), "w"), indent=1)
    md = f"# {title}\n\n**Price:** ${price_usd}  \n**Category:** {category or '(to choose)'}  \n**Tags:** {', '.join(tags) or '(to write)'}  \n" \
         f"**AI disclosure:** {listing['ai_disclosure']}\n\n{desc}\n"
    open(os.path.join(out_dir, "listing.md"), "w", encoding="utf-8").write(md)
    return listing
