# KP inter-company mirror

Constructs **Krushiyog Plant's own books** inside ERPNext from Vijay Agro
Centre's already-reconciled records — KP is a separate (currently
GST-unregistered) firm whose entire economic history lives on VAC's ledgers.
VAC's books are never modified; the mirror is additive and reversible.

Design doc / decisions / accountant gates: `docs/kp_intercompany_plan.md` in
the ERPNext Connect working folder (owner decisions locked 2026-07-16: separate
firm, own books from 2024-04-01, KP as its own business).

## Files

- **`kp_mirror.py`** — the whole pipeline; runs **bench-side** (needs
  `doc.insert(set_name=...)` for deterministic mirror names). Actions:
  `preview` (read-only), `prereqs` (company shell / internal parties /
  accounts, idempotent), `go [--limit N] [--types ...]`, `reconcile`,
  `held`, `gap`, `gap2` (symmetry debuggers), `wipe [--names a,b]` (reset).
- **`kp_run.py`** — local driver: uploads the script to the site's private
  files over REST (the SSH gateway is PTY-only and mangles large payloads),
  then executes it through `bench-run.sh`.

## Mirror map (all mirrors carry "Mirror of VAC <name>" in remarks)

| VAC source (docstatus=1) | KP mirror | Name |
|---|---|---|
| Purchase Invoice, supplier=KP | Sales Invoice, customer "Vijay Agro Centre" | `PI24-00179 → KPSI24-00179` |
| Sales Invoice, customer=KP | Purchase Invoice (+ unclaimable-GST charge row, `is_paid` for embedded payments) | `SI…→ KPPI…` |
| JE touching the 5 KP ledgers | JE, rows translated (party flips; third parties preserved; suspense for odd legs) | `JE… → KPJE…` |
| Payment Entry, party=KP | JE with Cash - KP leg | `KPJE-<name>` |
| VAC opening (`is_opening`) | Opening JE Dr VAC receivable / Cr Temporary Opening | `KPJE-OPENING-2024` |

Names are the idempotency key — re-runs skip existing mirrors; no naming-series
counters are touched.

## Safety

- **Hard staging guard**: the script refuses any site without "staging" in its
  name. The production run is a deliberate, separately-gated step (plan §4).
- Phase A is accounts-only: `update_stock=0`, KP company forced to periodic
  inventory — no stock ledger, no reposts.
- Full log to `/tmp/kp_mirror.log` bench-side; never pipe through `tail`.

## State (2026-07-16)

Staging run COMPLETE, **reconcile PASS on all 4 gates**: doc parity 168+144
exact; inter-company symmetry diff **0.00** (₹98,577.00 both books — identity
is KP-party net minus the 4 pseudo expense-head claims); KP GL Dr=Cr; revenue
₹66,68,531.17 exact. Three defects were caught by the gates during the build
(dropped GST on mirrored purchases, perpetual-inventory SRBNB routing, one
embedded ₹9,500 cash payment on SI25-01213) — all fixed in this version.

Pending: Phase B inputs (opening stock, BOMs, production vouchers, KP bank
statement), accountant sign-off per plan §5, then the prod run.
