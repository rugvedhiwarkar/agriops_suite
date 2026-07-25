# POS PWA — operator scripts

Server-side tooling for the counter **POS PWA** (the app itself is
`agriops_suite/www/pos.html`, served at `/pos`). These are run from an
operator's working copy, **staging-first** and target-guarded — production
needs `PP_TARGET=prod` + `PP_ALLOW_PROD=yes` **and** the owner's in-session
confirmation, per the golden rules.

They read the site keys from a `.env` two levels up (repo root), same
convention as `scripts/kp_interco/`:
`ERPNEXT_SITE_URL/API_KEY/API_SECRET` (prod) and
`STAGING_SITE_URL/STAGING_API_KEY/STAGING_API_SECRET` (staging). `.env` is
git-ignored and never committed.

## Files

- **`pp_lib.py`** — shared REST client; picks staging by default, prod only
  behind the two explicit switches above.
- **`pp_install.py`** — idempotent installer: the unique
  `Sales Invoice.pwa_client_id` idempotency field; the **POS Cashier**
  (billing-only) and **POS Journal** (Fast Journal posting) roles + minimal
  perms; the `vac_pos_*` server scripts (ping / catalog / create_invoice /
  outstanding / recent); role assignment to the named cashiers; a staging
  test user with API keys.
- **`pp_test.py`** — end-to-end test (cash sale → idempotent re-post → udhaar
  → khata delta → cancels its test docs). Staging only.
- **`pp_files_pilot.py`** — uploads `www/pos.html` to staging `/files/pos.html`
  so the app can be exercised before a bench deploy reaches `/pos`.
- **`pp_print_formats.py`** — creates the VAC print formats the POS prompts
  for: Delivery Note A4/A5, Journal Voucher, Money Receipt (house style).

## Related

- `scripts/pos_images/` — product-image upload for the POS tiles.
- `docs/pos_pwa_plan.md` — phased plan + running status.
- `demo/pos_demo.html` — standalone offline demo (mock server, sample data);
  regenerated from `www/pos.html`.
