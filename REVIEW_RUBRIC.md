# Visual review rubric (100 points)

This rubric is for whoever approves a `REVIEW` item: a person, or a vision model (Claude, ChatGPT, Gemini…) shown the images in `reports/<stage>/comparison/` and `reports/<stage>/diagnostics/`.

A vision model **scores and points at defects**. It does not have the final word. Measured checks are decided by the numbers. A critical or contradictory case stays `REVIEW` for the user.

| criterion | points | look at |
|---|---|---|
| Silhouette and blade shape (outline, notches, tip, V shapes) | 25 | `sheet_silhouette.png`, `full_front` / `full_back` |
| Sharp edges and cross-section (bevels, ridges, fuller, edge thickness) | 25 | `junction`, `blade_mid`, `tip` |
| Ornaments and key details kept (gem roundness, guard reliefs, pommel) | 20 | `guard_center`, `guard_left` / `guard_right`, `pommel` |
| Triangle distribution and shading (no crumples, folds, fans across flat areas) | 15 | `low_flat_*`, `diagnostics/issues_*` |
| Bake readiness / bake result (no seam lines, dark wedges or lost detail) | 15 | `diagnostics/edges_*`, s4 `sheet_high_vs_low_*` |

**Decision:**
- ≥ 85 with no criterion below 60 % of its points: approve.
- 70–84: approve only with a written note of what is accepted.
- < 70: FAIL. Re-run the stage with another method or budget.

**Answer format for a vision model.** Reply with this JSON:
```json
{"stage": "s2_lowpoly", "variant": "A_18k",
 "scores": {"silhouette": 0, "edges": 0, "ornaments": 0, "shading": 0, "bake": 0},
 "total": 0,
 "defects": [{"image": "guard_left", "where": "upper wing edge, left third", "what": "serrated outline", "severity": "high"}],
 "recommendation": "approve | approve_with_note | fail"}
```
