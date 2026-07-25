# POS PWA — Assessment & Plan (v2)

Status: PROPOSAL (nothing built, nothing written to any site)
Date: 2026-07-24 · v2 same day: re-scoped after owner clarified the pain is
**platform slowness (Frappe Cloud + heavy desk UI)**, not shop internet.
All facts verified live against production, read-only.

---

## Verdict (TL;DR)

**Yes — and with the real pain named, a local-first PWA is not just a good idea,
it is the architecturally correct answer.**

Measured 2026-07-24: every API round-trip to the site averages **0.6–1.0 s with
spikes to 2.6 s** — and the desk POS fires many such calls per sale (item
search, customer search, tax calc, submit, print render). That is why POS (and
the whole desk) feels terrible. Staging is equally slow, so this is the Frappe
Cloud plan/tier, not one bad site.

Two consequences:

1. **The PWA must be local-first from day one.** Catalog, prices, customers and
   the UI itself live on the device; a sale is composed and printed with **zero
   server calls in the critical path**; submission goes through a background
   queue. The counter becomes instant no matter what Frappe Cloud is doing.
   (In v1 of this plan that queue was Phase 3 "offline" — it is now the core of
   the MVP. Slow-server and no-server are the same architecture.)
2. **The PWA only fixes the counter.** Back-office desk work stays slow until
   the hosting itself is addressed — that is a parallel track (plan tier /
   dedicated server / bench-roll churn), not a PWA feature.

Strategy in one line: **ERPNext stays the engine and ledger (2 years of GST
books, stock, migration investment — it is good at that); humans stop using the
heavy desk for high-frequency work; thin fast frontends do the daily jobs.**
This is already the house pattern (fast_voucher, employee_desk, driver_slip).

---

## Measured latency (2026-07-24, from the shop-side PC, 5 runs each)

| Endpoint | Avg TTFB | Worst | What it tells us |
|---|---|---|---|
| Static asset (nginx only) | 323 ms | 401 ms | Network + TLS baseline — internet is fine |
| `frappe.ping` (minimal Python) | 605 ms | 1,536 ms | ~300 ms pure server overhead per call + queueing spikes |
| Item list ×100 (catalog query) | 879 ms | 2,605 ms | A single catalog page costs up to 2.6 s |
| Customer search | 965 ms | 1,655 ms | Every search keystroke round-trip ≈ 1 s |
| Staging `frappe.ping` | 937 ms | 2,491 ms | Staging equally slow ⇒ platform tier, not site load |

Desk `/app` returned a redirect for token auth (0 bytes) — not measurable this
way, but the desk additionally ships a multi-MB JS bundle on top of these calls.

Interpretation: ~200–300 ms of every call is server-side overhead before any
work happens, with multi-second p95 spikes typical of small shared workers. A
UI that makes N server calls per interaction multiplies this. The fix is fewer
calls, not faster clicking.

---

## Ground truth (verified on production 2026-07-24, read-only)

| Fact | Value |
|---|---|
| ERPNext version | **16.29.0** (drifted again; CLAUDE.md said 16.28.0) |
| POS Profiles | 3 exist: `Cash 1`, `Cash 2`, `Main` — all on `Main Store - VAC`, Standard Selling |
| POS Opening / Closing Entries | 14 / 12 → the desk POS page workflow is in real use |
| POS Invoice docs | 0 (v16 POS creates Sales Invoice directly; POS sales are SI with `is_pos=1`) |
| Sales Invoices all-time | 10,304 — of which **8,171 have `is_pos=1`** |
| July 2026 (24 days) | 364 invoices, **269 is_pos** → ~15/day in season, counter ≈ 74% of billing |
| Live entry pattern | Same-day creation at 11:19, 11:59, 12:14, 13:50, 14:46, 18:05 — real-time billing despite the latency (staff are absorbing the slowness) |
| ⚠️ All recent invoices `owner=Administrator` | Counter runs on the Administrator account — fix regardless (Phase 1) |
| Items enabled | 1,125 · **0 batch-tracked** · 0 serialised → device-side catalog is trivial (a few MB) |
| Items with image on prod | 49 (≈90 optimized images ready in `custom_doctypes/pos_images/optimized/`) |
| Customers | 3,584 — also cacheable on device |
| Modes of Payment | Cash, Cash 2, UPI, Credit, Cheque, Bank Transfer BOI 0025, Bank Draft, Credit Card, Wire Transfer |
| Credit sales today | Regular (non-POS) Sales Invoice through the full desk form (e.g. SI26-00851 ₹51,000 Unpaid) — slowest possible path for the most common sale type |

---

## What the PWA delivers, in order of value

1. **Removes Frappe Cloud from the counter's critical path.** App shell cached
   on device (loads instantly), catalog + customers in IndexedDB (search is
   local, 0 ms), sale composed and receipt printed immediately; the invoice
   posts to ERPNext through a background queue with retries. A 2.6 s server
   spike becomes invisible.
2. **One checkout for Cash / UPI / Udhaar.** Credit sales stop being a separate
   trip through the heavy desk form; khata balance shown at checkout.
3. Marathi-first, image tiles (assets already made), big touch targets,
   installable on any cheap Android device; per-counter profiles (Cash 1/2).
4. Insulation from bench auto-rolls: the PWA talks only to our own whitelisted
   endpoints + stable REST, and its UI never changes underneath the staff when
   Frappe Cloud rolls the bench (000006 → 000048 in July alone).

**Out of scope / unchanged from v1:** subsidized fertilizer still legally goes
through the government mFMS/DBT ePOS device *(confirm practice)*; pesticide
batch/expiry printing is a separate compliance decision (no batch tracking
exists today); e-invoicing only matters if B2B turnover crosses ₹5 cr *(confirm)*.

---

## Options compared

| Option | Cost | Fixes counter? | Fixes desk/back-office? |
|---|---|---|---|
| A. Status quo | 0 | No — staff keep absorbing 1–2.6 s per action | No |
| B. Hosting upgrade (bigger FC plan / dedicated) | ₹/month, 0 code | Partially (calls maybe 2–3× faster, still N calls/sale) | **Yes — only option that does** |
| C. Local-first PWA in agriops_suite | ~3 weeks focused | **Yes — fully, regardless of server speed** | No |
| D. Third-party POS app (POS Awesome etc.) | install + learn | Partially (still server-chatty) | No; v16 compat unproven; fragile under auto-rolling bench |
| E. Leave ERPNext | enormous | — | Contradicts the whole project; 2 years of books + migration investment; the ledger itself is not the problem |

**Recommendation: C is the project; B in parallel (cheap to evaluate, helps
everything else); D and E rejected.**

---

## Phased plan

### Phase 0 — Close the remaining unknowns (days, no code)

Latency is now measured (done, above). Remaining:

- **Read the Frappe Cloud plan tier** for both sites from the FC dashboard
  (RAM/workers), and what an upgrade or dedicated server costs. Also check the
  bench group's auto-update setting — every roll means cold caches and restarts.
- Counter hardware today: device, printer model/paper size, who operates it.
- Confirm mFMS ePOS practice for subsidized fertilizer; annual turnover
  (e-invoice threshold); Marathi vs English for staff.

### Phase 1 — Foundations & hygiene (2–4 days; valuable even without the PWA)

> **🚀 PRODUCTION GO-LIVE 2026-07-25 — POS PWA is LIVE at
> `vijayagrocentre.frappe.cloud/pos` (v0.11.0).** Promoted with owner sign-off
> after a fresh backup. `pp_install.py` run with `PP_TARGET=prod
> PP_ALLOW_PROD=yes PP_SKIP_JOURNAL=yes`: created `Sales Invoice.pwa_client_id`,
> the **POS Cashier** role + minimal perms, and the 5 `vac_pos_*` server
> scripts. Perm conversion verified SAFE — Sales Invoice / Customer / Item /
> Account kept every prior standard role + gained POS Cashier; **Payment Entry
> / Journal Entry left UNTOUCHED** (standard perms; owner skipped decision 1 —
> Fast Journal runs on standard Accounts roles via the can_journal allowlist).
> The 4 print formats (Delivery Note A4/A5, Journal Voucher, Money Receipt)
> created on prod earlier and render real PDFs. App deployed (FC) — /pos serves
> v0.11.0, SW/manifest live, guest→login gate, endpoints return real data
> (1123 items / 3576 customers / 88 suppliers / 10 employees).
> **Owner's remaining tasks:** (decision 2) Vijay Bopche has an *Inventory*
> role profile that overrides a directly-added POS Cashier role — grant him
> billing via the profile or a direct assignment; and set his password (he has
> never logged in). Nikita (Accounts profile) + owner already have the access.
> No test invoice was created on prod (would consume a GST number); the create
> path is verified identical on staging with all prod deps confirmed present.

> **Status 2026-07-24 evening — Phase 1 EXECUTED on staging, 12/12 E2E green.**
> Kit lives in `custom_doctypes/pos_pwa/` (`pp_install.py` idempotent installer,
> `pp_test.py` E2E; staging default, prod requires `PP_TARGET=prod` +
> `PP_ALLOW_PROD=yes` + owner confirmation). Delivered on staging: unique
> `Sales Invoice.pwa_client_id`; `POS Cashier` role (minimal perms via
> permission_manager, standard roles preserved); server scripts
> `vac_pos_ping` / `vac_pos_catalog` / `vac_pos_create_invoice` /
> `vac_pos_outstanding`; role assigned to the three real cashiers (Vijay
> Bopche `vijaybopche@vijayagrocentre.frappe.cloud` — never logged in, owner
> must set password; Nikita `hiwarkarnikita75@gmail.com`; Vijay Hiwarkar
> `hiwarkarvijay@gmail.com`); **87/87 item images** attached (was 49).
> Test evidence: cash sale SI with inclusive CGST/SGST computed correctly and
> outstanding 0; same-UUID re-post deduped in 230 ms; udhaar sale as
> `is_pos=0` SI with correct khata delta; all test invoices cancelled after.
> **v16 gotchas encoded in the scripts:** cashier needs `select` perm on
> Account / Cost Center / Price List / Currency or SI insert 403s;
> `get_all` rejects SQL-function strings (`sum(x) as y`) — aggregate in
> Python. **Latency reality:** catalog ~1.0 s, submit ~7 s server-side,
> dup-check 230 ms — reinforces the Phase-2 optimistic-queue design.
> Endpoint shapes mirror prod exactly: default customer **Cash Customer**,
> template **Output GST In-state Inclusive - VAC** (rate-0 CGST/SGST rows,
> `included_in_print_rate=1`, item tax templates drive rates), MoP accounts
> Cash → CASH 1 - VAC, UPI → UPI Payment - VAC; udhaar = regular SI.
> Also fixed: `pi_lib.py` / `pi_upload.py` legacy pre-move paths (now
> repo-relative). Staging keys in `.env` belong to `claude-agent@…`
> (regenerated by owner 2026-07-24 after a re-clone killed the old pair).
> **Not done (needs explicit owner go + fresh backup): promotion to
> production, and porting these artifacts into agriops_suite as fixtures.**

All on **staging first**, exported as **fixtures in agriops_suite**, promoted to
production only with explicit confirmation + fresh backup, per golden rules.

1. **Stop billing as Administrator**: named user per staff member, `POS Cashier`
   role with minimal perms.
2. Finish the **item image upload** to production (`pi_upload.py`, ~40 remaining).
3. **Server API** `agriops_suite/pos_api.py` — built for a chatty-free client:
   - `get_catalog_bundle(profile, since_version)` — items, prices, images,
     tax rates, customers **in one call**, delta-updatable. One call replaces
     the desk's hundreds.
   - `create_pos_invoice(payload)` — creates + submits SI (`is_pos`,
     `update_stock=1`, payment rows or none ⇒ udhaar), **idempotent** on new
     unique field `pwa_client_id` (device UUID) so queue retries can never
     double-bill. Server recomputes taxes; client numbers are display-only.
   - `get_customer_outstanding(customer)`.
4. Custom field `Sales Invoice.pwa_client_id` (unique) via fixture.

### Phase 2 — PWA MVP, local-first (2–3 weeks focused)

> **Status 2026-07-24 late night — v0.1.1 LIVE at /pos on staging and
> browser-verified end-to-end; v0.2.0 (`a9d27ad`, numpad sheet for rate/qty
> — owner request) pushed and awaiting the next deploy.**
> **Update — same night — v0.3.0 (`9989a52`) pushed: held bills + Fast
> Journal.** *Held bills* (fix for "more than one customer, we get confused"):
> park cart+customer+mode with one tap, amber chip strip above the grid,
> resume-swaps the in-progress bill onto the shelf instead of losing it,
> persists in localStorage. *Fast Journal* (⚡ header button): receive a
> khata payment in-screen via the existing fast_voucher Server Scripts —
> both button and sheet self-gate on `fast_voucher_config.enabled`, inert
> where absent (prod until promotion). Verified: held-bills logic 9/9
> headless unit tests (park/resume/**swap**/persist/drop/empty-guard); FJ
> **posted a real Payment Entry** with the app's exact payload
> (PE26-00488, cancelled+deleted, staging clean). Numpad (v0.2.0) confirmed
> live on /pos earlier: unpriced "Wal Fobera 9 Sardar 100 GM" → pad → ₹85
> line, qty edit → 3, total ₹255.
> ⚠️ **Deploy-gate reminder:** the `/pos` ROUTE is bench-rendered, so each
> version only reaches /pos after an FC deploy; the SW cache can't be forced
> ahead of it (background revalidation re-pulls the route). v0.2.0 numpad IS
> live; v0.3.0 awaits the next deploy. The `/files/pos.html` pilot copy is
> always current for token-mode preview.
>
> **Update — same night — v0.4.0 (`39fbe7d`) pushed: split payment.** Fourth
> checkout mode "Split" (बाँटें / विभागून): cashier types Cash + UPI amounts
> on the numpad, a live "Khata (balance)" row shows the remainder, which
> posts as the invoice's outstanding. **Server unchanged** — it already
> accepts multiple payment rows + partial pay (proven: 25/25/50 → Partly
> Paid ₹309.50 khata; 40/60 → Paid, outstanding 0, both rows on
> SI26-00861). Guards: overpay blocked; any credit remainder requires a
> named customer; empty split falls back to udhaar. Receipt prints each
> tendered mode + khata balance; held bills carry their split amounts.
> Verified: 13-case checkout money-math unit test (paid+credit==total always)
> + 2 live E2E posts, all cancelled/clean.
>
> **Update — v0.4.0 split VERIFIED LIVE on /pos + v0.5.0 visual port pushed
> (`b9f35a1`).** Owner deployed v0.4.0; browser E2E through the deployed app
> UI posted **SI26-00863** — ₹1,600, ₹800 paid (₹400 cash + ₹400 UPI), ₹800
> khata, **Partly Paid**, bill number surfaced back in the app's Sent list,
> cancelled after. Then built a polished mockup (published artifact) and
> **ported its look into the real app** as v0.5.0: green-biased neutrals,
> layered shadows, green-gradient primary actions, brand-green header logo,
> and category-tinted product cards (item_group → seed green / pesticide
> amber / fertilizer teal / other, gradient thumb with photo-or-monogram +
> quick-add). v0.5.0 shell verified rendering on /pos via SW-cache preview
> (60 tiles categorised, all greens computing). **Awaits the owner's next FC
> deploy to reach /pos.** Caught + fixed a mismatched-quote bug in the new
> tileHtml with node --check before shipping.
>
> **Update — v0.6.1 (`8193863`): Fast Journal expanded + party-picker bug
> fixed.** FJ went from receipt-only to the full desk set — receipt (Customer),
> payment (Supplier), expense (drawer→head), employee advance (Employee) —
> each posting a native Payment Entry / Journal Entry via the existing
> `fast_voucher_post` (all four verified: create + cancel clean). Fixed the
> reported "customer window opens behind the FJ form": overlay z-index tiers
> (FJ 60 / party picker 70 / numpad 80 — browser-verified custAboveFj). Party
> picker generalised over Customer/Supplier/Employee; `vac_pos_catalog` now
> returns suppliers (88) + employees (10) via `ignore_permissions` (a
> cashier's lack of master read would otherwise 403 the whole catalog).
> **Posting gated to trusted staff (owner's choice):** a separate **POS
> Journal** role grants create+submit on the two vouchers, assigned to
> owner + Nikita only (NOT Vijay Bopche); ⚡ button shows only when the
> identity endpoint reports `can_journal` (POS Journal role OR a standard
> Accounts profile). Also: installer no longer rotates the test API key each
> run.
> **⚠️ Open item — POS Journal grant not yet activated on staging.** DocPerms
> + role + assignment are correct and accounts-privileged users post fine, but
> a POS-Journal-only user still 403s: `has_permission` reads a *cached* role
> list that Frappe Cloud didn't invalidate across workers when the role was
> added. Fix = `bench clear-cache` (or any deploy — bench migrate restarts
> workers). Couldn't run it: **SSH cert expired 2026-07-25 00:59.** Activates
> on the owner's next FC deploy of agriops_suite; re-verify FJ posting then.
> gotcha logged: `frappe.has_permission` / `frappe.get_roles` are NOT exposed
> in safe_exec, and underscore-prefixed var names are rejected — the ping
> gate reads `Has Role` via `get_all(ignore_permissions=True)` instead.
>
> **Update — v0.8.0 + v0.9.0.** v0.8.0: fixed the **missing Fertilizer
> category** (fine-grained groups → keyword-bucketed high-level chips: Seeds /
> Fertilizer / Pesticide / Growth / Irrigation / Hardware; fertilizer shows all
> 71 items) + 5 UX upgrades (in-app confirm sheet replacing browser
> `confirm()`; loading skeleton; why-disabled hint on Confirm; inline PC
> qty/rate edit; "+1" tile-tap flourish). v0.9.0: **Recent tab** — pulls what
> landed in ERPNext (bills for all; Fast Journal PE/JE for journal staff,
> role-gated) each with **VAC print formats** (SI → A4/A5 Bill, Delivery Slip;
> PE → Deposit Slip / RTGS-NEFT / Voucher; JE → Voucher). PDF fetched with the
> app's own auth so it prints on kiosk devices. New `vac_pos_recent` server
> script. All browser-verified. **Print-format gaps flagged to owner:** no
> A4/A5 *Delivery Note* variant for a POS bill (only "VAC Delivery Slip"), and
> no dedicated VAC *Journal Entry* / money-*receipt* format (uses Standard) —
> creating those is real template work, pending owner go-ahead.
>
> Browser E2E on /pos (token kiosk mode, real UI state): catalog in memory
> (1,123/3,574/677), 60 tiles + 9 chips, white native header, **service
> worker controlling the page**, desktop two-pane verified at 1280px
> (sticky bill panel, रोख/UPI/उधार, black confirm), and a real sale driven
> through the app: POS-TEST-0001 → **SI26-00858** ₹1,600 Paid (18% GST
> 122.03+122.03 inclusive), bill number surfaced back in the app's Sent
> list, invoice cancelled afterwards. Numpad logic unit-tested (6 cases).
> Post-deploy verification: /pos serves the rendered shell (Jinja gone,
> guest CSRF empty), SW carries `Service-Worker-Allowed: /pos` + no-cache,
> manifest/icons 200, guest csrf → 403 (login contract). Prod: /pos is 404 —
> **the deploy did not reach the prod bench** (same split as the Stock Count
> deploys, see bench-run.sh notes); also learned an absent Server Script
> answers **HTTP 417** "Failed to get method", not 404 → client's
> "not enabled" detection now keys on both (`5b60028`).
> v0.1.1 additions (owner requests mid-session): **Hindi** as third language;
> **native-ERPNext restyle** (light gray page, white cards/header, dark
> primary buttons; green/amber kept only as paid/udhaar accents);
> **desktop two-pane layout** ≥1000px (item grid left, bill panel fixed
> right — the native POS split) for the counter PC; **Enter-to-add** in
> search (one exact match ⇒ added + cleared — USB barcode scanner ready).
> New UI previewable now at `<staging>/files/pos.html`; reaches /pos on the
> owner's next FC deploy.
> *(Original build status below.)*
> Built as the third www/ PWA sibling (pattern of /count and /slip): single
> file `www/pos.html` (~1,300 lines, Marathi-first), `www/pos.py`,
> `pos_pwa.py` (csrf/sw/manifest endpoints, `Service-Worker-Allowed: /pos`),
> `public/js/pos_sw.js` (shell SWR + item-image cache), icons. Features:
> IndexedDB catalog (823 KB bundle: 1,123 items, 3,574 customers — 3,199
> with village), instant local search + group chips + image tiles,
> tap-for-rate when unpriced (677/1,123 items have Standard Selling prices),
> cart with qty/rate edit, customer picker with khata badge + quick-create,
> Cash/UPI/**Udhaar** checkout, offline outbox with client-UUID idempotency,
> provisional 80 mm receipt printed immediately (final GST number shown after
> sync; never faked), pending/failed review screen, session login
> (email+password, /count contract) or device-token kiosk mode.
> **Verified without a browser** (pane approval for the staging origin did
> not arrive in the autonomous session): Node syntax-check of the deployed
> shell; pilot copy live at `<staging>/files/pos.html`; the app's exact wire
> format replayed E2E as the test cashier — SI26-00856 submitted (inclusive
> CGST/SGST ₹14.74 each, outstanding 0, ~10.5 s server-side ⇒ queue design
> vindicated), same-UUID re-post deduped, invoice cancelled after.
> **To go live on staging:** owner deploys agriops_suite on the FC bench
> group → open `/pos`, sign in, install to home screen. On production the
> same deploy renders only a "not enabled" notice until Phase-1 promotion.

- **Stack:** Vite + Vue 3 + frappe-ui (doppio pattern) inside `agriops_suite`,
  served at `/pos`; `vite-plugin-pwa`. App shell fully cached on device.
- **Local data:** catalog + customers in IndexedDB (Dexie), background-refreshed
  via `get_catalog_bundle` version stamps. Search and browsing never touch the
  network.
- **Optimistic submit queue (core, not add-on):** sale → queued with UUID →
  receipt prints immediately → background sync posts to ERPNext with retries.
  Receipt carries queue reference `POS-C1-0042`; the GST invoice number is the
  SI name assigned at sync (receipt states this — never fake an invoice number
  client-side). Sync status strip always visible (n pending / last sync OK);
  failures land on a review screen, never silently dropped.
- **Screens:** item grid (images, Marathi search) → cart → customer (Walk-in
  default, search by name/mobile/village, quick-add, shows outstanding) →
  checkout Cash / UPI / **Udhaar** / split → print (browser print CSS for
  existing printer).
- **Pilot:** 1 week on staging; then production **in parallel** with the desk
  POS as fallback; daily tie-out of PWA invoices for the first week.

### Phase 3 — Extended offline & multi-device (1–2 weeks, after MVP soak)

The MVP queue already survives short outages by design. This phase hardens it:
multi-hour/day offline windows, catalog staleness policy, price-change and
negative-stock conflict handling, two counters + a phone simultaneously,
device-level kill switch. Gets its own plan-mode review.

### Phase 4 — Polish (ongoing, optional)

Barcode (USB wedge first) · WhatsApp receipt share · day-end Z-report tied to
the cash_update_voucher habit · udhaar ledger view + credit-limit warning.

### Parallel track — Hosting (independent of all phases)

The PWA does nothing for back-office desk speed. Evaluate: FC plan upgrade or
dedicated server (get quotes from dashboard), region check, and whether the
bench group's auto-deploy cadence can be calmed. Re-run the latency benchmark
in this doc after any change (script lives in the session log; 5×TTFB on ping /
item list / customer search).

---

## Key risks & mitigations

| Risk | Mitigation |
|---|---|
| Queued sale fails server validation later (price/stock/customer) | Review screen with the exact error; sale is never lost (queue is durable in IndexedDB); daily tie-out during pilot |
| Duplicate invoices on retry | `pwa_client_id` unique + server-side idempotency |
| Receipt total ≠ final SI total (server recompute) | GST-inclusive standard pricing keeps parity; deltas surfaced on review screen, tolerated only within paisa rounding |
| Bench auto-updates break the client | Only own endpoints + stable REST; contract-test script after each bench roll |
| Staff adoption | Must beat the desk on taps-per-sale and seconds-per-sale — measure both in pilot; desk POS stays as fallback |
| Accounting integrity (golden rule 7) | Server recomputes everything; submit path identical to desk; staging-first; fixtures; backup before prod install |
| Scope creep into "custom ERP" | PWA does counter billing only; everything else stays in desk |

## Effort estimate (with Claude assistance)

Phase 1: ~2–4 focused days · Phase 2: ~10–15 focused days · Phase 3: ~5–10
focused days + soak. Hardware: ₹0 (reuse PC) to ~₹15k (Android tablet + thermal
printer). Hosting track: whatever the FC plan delta costs — evaluate in Phase 0.

## Open questions (answer before Phase 1)

1. Frappe Cloud plan tier for prod & staging, and upgrade/dedicated pricing?
2. Counter device + printer today, and who operates it?
3. Subsidized fertilizer: mFMS ePOS used? Are those sales re-entered in ERPNext?
4. Annual turnover above ₹5 cr (e-invoice relevance)?
5. Marathi UI required, or English fine?
6. Udhaar: enforce credit-limit warning at checkout?
