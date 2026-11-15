# AssetForge — status of each part (keep this honest)

> 2026-11-15: s0 → s9 ran end to end on a real AI sword (silver_fang, 2026-11-04). Rows below not updated since are older.

| part | state |
|---|---|
| core: state, gates, 4 gate outputs + html, checkpoints, CLI, ledger, lessons | built, tested |
| orchestrator (headless, queue, fingerprints, retries, resume, disk check) | built; resume + injected failure **tested** |
| add-on control panel | built; not yet installed (needs your OK to install an add-on) |
| s0 intake (adopt / import + anatomy detection) | adopt tested on Inferno Dragon Sword; import of AI GLB/FBX/OBJ written, **not yet tested on a real AI file** |
| s1 high-poly checks | tested |
| s2 low-poly (decimate + fold repair + budget search + comparisons + diagnostics) | tested headless (self-test); dragon s2_select running |
| s2 variants A/B/C + budget comparison | **built and run** on the dragon sword (A wins); ranking weights provisional |
| s3 UV: forge recipe (class charts + LSCM + FFT packing, numpy only) + full audit (overlaps, exact gap, both coverage definitions, distortion, texel density, regions, applied = packed) | built; container-tested on the old dragon low poly; Blender test running (self-test, then A_18K) |
| s3 old smart-project recipe | kept as `method="smart"` for comparison only |
| s0_spec: weapon fit (type, length, blade/grip, mass, balance, hands, character) | built; container-tested (volume exact on a box, 0.1 % on a sphere); Blender test pending |
| evidence-first rule (record_experiment, manifest.json, untested code refused on real projects) | built; container-tested; to deploy after the dragon UV run |
| s4 bake 1K → compare → 4K | written (uses the proven baker), not yet tested through forge |
| s5 look: lava generator | exists as a container script (numpy+scipy+PIL); **to port** to Blender-only numpy |
| PBR material rebuild by part (blade / guard / gem) | **to build** |
| s6 LODs + collision, s7 export + re-import, s8 media, s9 package | wrappers of the proven tools; not yet run through forge |
| s10 rights / Fab checklist | written |
| generic assets (any model) | 1.6.0: runs s0 → s9 with bounding-box cameras and a size gate; **to do**: real AI non-weapons, part detection, generic look/listing text |
| other weapon types (axe, spear, dagger) | anatomy is sword-specific; **to generalise** (or run them as generic) |
| calibration on 4–5 swords | **to do** after the dragon sword |
