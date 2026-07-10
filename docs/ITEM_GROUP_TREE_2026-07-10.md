# Item Group tree migration — 2026-07-10

The legacy BusyWin-era item groups were merged into the restructured tree on
BOTH sites, and staging's tree was aligned to production's shape. The tree is
master DATA (deliberately outside this app's fixture policy), so this document
is the durable record; the executable scripts live in
`custom_doctypes/rebrand/ig_*.py` in the project folder.

## What happened

1. **Legacy merge (both sites)** — every child of "Legacy Item Groups"
   (38 staging / 39 prod) was merged into its new-tree home via
   `frappe.rename_doc(..., merge=True)`, repointing ~35k Sales Invoice lines
   and ~1k Purchase Invoice lines. The "Legacy Item Groups" node was deleted
   and the nested set rebuilt. Zero orphaned group references after; GL
   untouched (107,149 entries). Prod backup first: `20260710_190742`.

2. **Mapping method** — majority vote of each legacy group's historical
   invoice lines over the CURRENT groups of those items (33/35 groups were
   100% unanimous). User rulings: WS Bio Stimulant → Biostimulants
   (name-faithful over the 53% PGR vote); empty groups to semantic homes
   (Bulk Fertilizers → Single Nutrient, Construction Materiel → General
   Hardware, Soil Application → Micronutrients, Water Soluble →
   Water-Soluble Fertilizers, Spreader → General Hardware).

3. **Staging→prod tree alignment** — staging had diverged (combined
   "Bio-Fertilizers & Biostimulants", parents named Bagged Fertilizers /
   Crop Protection / Hardware & Equipment / Seeds). Fixed: 4 parent renames,
   "VAC Krishi Kendra" recreated as the second ROOT (insert ignores an empty
   parent — detach via `db.set_value` + `rebuild_tree`), the combined bio
   group split by PROD ITEM MEMBERSHIP (9 → Bio-Fertilizers, 56 →
   Biostimulants, 0 unmatched) and then merged into Biostimulants.
   Final check: staging and prod trees byte-identical, 30 groups each.

## Final tree (both sites)

```
All Item Groups
├── Consumable / Products / Raw Material / Services / Sub Assemblies
└── VAC Hardware ── General Hardware · Irrigation · Solar & Fencing · Spray Equipment
VAC Krishi Kendra          (second root — the retail catalogue)
├── Fertilizer Bags ─── Bio-Fertilizers · NPK Complex & Mixtures · Single Nutrient
├── Plant Nutrition ─── Biostimulants · Micronutrients · Water-Soluble Fertilizers
├── Plant Protection ── Bio-Pesticides · Fungicides · Herbicides · Insecticides · Plant Growth Regulators
└── Seed ────────────── Field-Crop Seeds · Paddy Seeds · Vegetable Seeds
```

## Gotchas learned (for the next tree surgery)

- NestedSet merge is **leaf-to-leaf only** — flip empty group nodes to
  `is_group=0` first, and never target a group node.
- **Commit per merge**: a mid-loop rollback otherwise undoes prior
  uncommitted merges.
- `frappe.delete_doc(force=1)` on a DocType leaves its table behind; the
  same class of half-state applies to interrupted renames — verify tables
  after any bulk rename session.
- Report filters that referenced the legacy subtree
  (`parent_item_group != "Legacy Item Groups"` get_query in the StockPilot
  reports) are now inert no-ops; left in place as protection.
