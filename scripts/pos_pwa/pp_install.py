"""POS PWA Phase-1 installer (idempotent, safe to rerun).

Creates on the target site (staging by default — see pp_lib):
  1. Custom Field  Sales Invoice.pwa_client_id  (unique idempotency key)
  2. Role          "POS Cashier" (+ minimal Custom DocPerms via the
                   permission_manager API, which preserves standard perms)
  3. Server Scripts (API type):
       vac_pos_ping            auth/connectivity check
       vac_pos_catalog         one-call catalog bundle (items+prices+customers)
       vac_pos_create_invoice  idempotent create+submit (cash/UPI or udhaar)
       vac_pos_outstanding     customer khata balance
  4. Test user pos.cashier@example.com with API keys (no welcome email);
     keys are appended to .env as STAGING_CASHIER_API_KEY/SECRET.

Run:  python custom_doctypes/pos_pwa/pp_install.py
Then: python custom_doctypes/pos_pwa/pp_test.py
"""
import json
import os

import pp_lib
from pp_lib import call, get_doc, rpc, upsert

# PP_SKIP_JOURNAL=yes -> do NOT create the POS Journal role, its PE/JE perms, or
# assign it. Used for the prod promotion (owner 2026-07-25): the can_journal gate
# already grants Fast Journal via standard Accounts roles, so we leave Payment
# Entry / Journal Entry permissions untouched on production.
SKIP_JOURNAL = os.environ.get("PP_SKIP_JOURNAL") == "yes"

FALLBACK_TAX_TEMPLATE = "Output GST In-state Inclusive - VAC"
TEST_USER = "pos.cashier@example.com"

# Real counter staff (named by the owner 2026-07-24). All three already exist
# as enabled System Users on production, so staging's clone has them too —
# we only APPEND the POS Cashier role, never recreate them (recreating with
# welcome mail on would email real gmail inboxes; see ed_seed_nikita.py).
CASHIERS = [
    "vijaybopche@vijayagrocentre.frappe.cloud",  # Vijay Bopche (never logged in; owner must set a password)
    "hiwarkarnikita75@gmail.com",                # Nikita Hiwarkar
    "hiwarkarvijay@gmail.com",                   # Vijay Hiwarkar (owner)
]

# doctype -> ptypes granted to POS Cashier at permlevel 0.
# GL Entry intentionally NOT granted: vac_pos_outstanding aggregates via
# frappe.get_all inside the server script, so the cashier never gets raw GL read.
PERM_MAP = {
    "Sales Invoice": ["read", "write", "create", "submit", "print"],
    "Customer": ["read", "write", "create"],
    "Item": ["read"],
    "Item Price": ["read"],
    "Item Group": ["read"],
    "Customer Group": ["read"],
    "Territory": ["read"],
    "Mode of Payment": ["read"],
    "POS Profile": ["read"],
    "Warehouse": ["read"],
    "Company": ["read"],
    "UOM": ["read"],
    "Sales Taxes and Charges Template": ["read"],
    # select-only: link validation on SI needs these resolvable, but the
    # cashier gets no list/read access to the ledger masters themselves.
    "Account": ["select"],
    "Cost Center": ["select"],
    "Price List": ["select"],
    "Currency": ["select"],
}

# Separate "POS Journal" role for Fast Journal posting (owner decision
# 2026-07-25: trusted staff only, not every cashier). It grants create+submit
# on the two financial vouchers the hardened fast_voucher_post builds, plus the
# reads/selects PE/JE validation needs. Held ONLY by named trusted users (see
# JOURNAL_USERS); a plain POS Cashier can bill but can never mint a voucher.
PERM_MAP_JOURNAL = {
    "Payment Entry": ["read", "create", "submit"],
    "Journal Entry": ["read", "create", "submit"],
    "Supplier": ["read"],
    "Employee": ["read"],
    "Account": ["read", "select"],
    "Cost Center": ["read", "select"],
    "Party Type": ["read"],
}

# Who may post Fast Journal vouchers. Vijay Hiwarkar (owner) + Nikita, per the
# owner's "trusted staff only" choice. Vijay Bopche (plain counter cashier) is
# deliberately excluded. The staging test user is added in ensure_test_user.
JOURNAL_USERS = [
    "hiwarkarvijay@gmail.com",     # Vijay Hiwarkar (owner)
    "hiwarkarnikita75@gmail.com",  # Nikita Hiwarkar
]

# ---------------------------------------------------------------- server scripts
# Bodies run inside Frappe's safe_exec sandbox: no imports; frappe.get_all
# bypasses perms (fine for catalog/outstanding), doc.insert/submit respect them.

SCRIPT_PING = r"""
# can_journal shows/hides the Fast Journal ⚡ (the real gate is at post time —
# fast_voucher_post's insert/submit enforce actual perms). frappe.has_permission
# is not exposed in safe_exec, so we approximate via the roles that grant PE/JE
# create: the standalone POS Journal role OR a standard Accounts profile (so
# Nikita, on the Accounts profile, sees it) — never a billing-only cashier.
journal_roles = ["POS Journal", "Accounts User", "Accounts Manager", "System Manager", "Administrator"]
role_rows = frappe.get_all("Has Role",
    filters={"parenttype": "User", "parent": frappe.session.user},
    fields=["role"], limit_page_length=0, ignore_permissions=True)
user_roles = []
for rr in role_rows:
    user_roles.append(rr["role"])
can_journal = 0
for rname in journal_roles:
    if rname in user_roles:
        can_journal = 1
        break
frappe.response["message"] = {
    "pong": True,
    "user": frappe.session.user,
    "can_journal": can_journal,
    "ts": frappe.utils.now(),
}
"""

SCRIPT_CATALOG = r"""
profile_name = frappe.form_dict.get("profile") or "Main"
profile = frappe.get_doc("POS Profile", profile_name)
price_list = profile.selling_price_list or "Standard Selling"

items = frappe.get_all(
    "Item",
    filters={"disabled": 0, "is_sales_item": 1},
    fields=["name", "item_name", "item_group", "stock_uom", "image", "gst_hsn_code"],
    limit_page_length=0,
)
prices = frappe.get_all(
    "Item Price",
    filters={"price_list": price_list, "selling": 1},
    fields=["item_code", "price_list_rate"],
    limit_page_length=0,
)
customers = frappe.get_all(
    "Customer",
    filters={"disabled": 0},
    fields=["name", "customer_name", "mobile_no", "customer_group",
            "custom_village", "custom_alias"],
    limit_page_length=0,
)
modes = frappe.get_all(
    "Mode of Payment", filters={"enabled": 1}, fields=["name", "type"],
    limit_page_length=0,
)
# Parties for the Fast Journal (receipt=Customer above; payment=Supplier,
# employee advance=Employee). Small lists — bundled so the FJ pickers work
# offline like the customer picker. ignore_permissions: a POS Cashier has no
# read on Supplier/Employee master, so a plain get_all would 403 the whole
# catalog; the endpoint itself is the access gate and we return only the
# display name (never salary/personal fields), so this exposes nothing extra.
suppliers = frappe.get_all(
    "Supplier", filters={"disabled": 0},
    fields=["name", "supplier_name"], limit_page_length=0,
    ignore_permissions=True,
)
employees = frappe.get_all(
    "Employee", filters={"status": "Active"},
    fields=["name", "employee_name"], limit_page_length=0,
    ignore_permissions=True,
)

latest = {}
for dt in ["Item", "Item Price", "Customer"]:
    rows = frappe.get_all(dt, fields=["modified"], order_by="modified desc", limit_page_length=1)
    latest[dt] = str(rows[0].modified) if rows else None

frappe.response["message"] = {
    "profile": {
        "name": profile.name,
        "company": profile.company,
        "customer": profile.customer,
        "warehouse": profile.warehouse,
        "selling_price_list": price_list,
        "taxes_and_charges": profile.taxes_and_charges,
        "payments": [
            {"mode_of_payment": p.mode_of_payment, "default": p.default}
            for p in profile.payments
        ],
    },
    "items": items,
    "prices": prices,
    "customers": customers,
    "suppliers": suppliers,
    "employees": employees,
    "modes_of_payment": modes,
    "version": latest,
}
"""

SCRIPT_CREATE_INVOICE = r"""
body = frappe.form_dict

client_id = body.get("pwa_client_id")
if not client_id:
    frappe.throw("pwa_client_id is required")

existing = frappe.db.exists("Sales Invoice", {"pwa_client_id": client_id})
if existing:
    doc = frappe.get_doc("Sales Invoice", existing)
    frappe.response["message"] = {
        "duplicate": True,
        "name": doc.name,
        "docstatus": doc.docstatus,
        "grand_total": doc.grand_total,
        "outstanding_amount": doc.outstanding_amount,
    }
else:
    items_in = body.get("items")
    if isinstance(items_in, str):
        items_in = json.loads(items_in)
    if not items_in:
        frappe.throw("items is required")

    pays = body.get("payments") or []
    if isinstance(pays, str):
        pays = json.loads(pays)

    profile = frappe.get_doc("POS Profile", body.get("pos_profile") or "Main")
    customer = body.get("customer") or profile.customer
    if not customer:
        frappe.throw("customer is required")

    posting_date = body.get("posting_date") or frappe.utils.nowdate()
    is_pos = 1 if pays else 0  # no payments -> udhaar as regular SI (house pattern)

    si = {
        "doctype": "Sales Invoice",
        "company": profile.company,
        "customer": customer,
        "is_pos": is_pos,
        "update_stock": 1,
        "set_warehouse": profile.warehouse,
        "selling_price_list": profile.selling_price_list,
        "taxes_and_charges": profile.taxes_and_charges or "__FALLBACK_TAX_TEMPLATE__",
        "posting_date": posting_date,
        "due_date": posting_date,
        "pwa_client_id": client_id,
        "remarks": body.get("remarks"),
        "items": [
            {"item_code": i["item_code"], "qty": i["qty"], "rate": i.get("rate")}
            for i in items_in
        ],
    }
    if is_pos:
        si["pos_profile"] = profile.name
    if body.get("posting_date"):
        si["set_posting_time"] = 1

    doc = frappe.get_doc(si)

    if doc.taxes_and_charges:
        tmpl = frappe.get_doc("Sales Taxes and Charges Template", doc.taxes_and_charges)
        for t in tmpl.taxes:
            doc.append("taxes", {
                "charge_type": t.charge_type,
                "account_head": t.account_head,
                "description": t.description,
                "rate": t.rate,
                "included_in_print_rate": t.included_in_print_rate,
                "cost_center": t.cost_center,
            })

    for p in pays:
        acc = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": p["mode_of_payment"], "company": profile.company},
            "default_account",
        )
        doc.append("payments", {
            "mode_of_payment": p["mode_of_payment"],
            "amount": p["amount"],
            "account": acc,
        })

    doc.insert()
    doc.submit()

    frappe.response["message"] = {
        "duplicate": False,
        "name": doc.name,
        "docstatus": doc.docstatus,
        "customer": doc.customer,
        "net_total": doc.net_total,
        "grand_total": doc.grand_total,
        "rounded_total": doc.rounded_total,
        "outstanding_amount": doc.outstanding_amount,
        "is_pos": doc.is_pos,
        "taxes": [
            {"account_head": t.account_head, "tax_amount": t.tax_amount}
            for t in doc.taxes
        ],
    }
"""

SCRIPT_OUTSTANDING = r"""
customer = frappe.form_dict.get("customer")
if not customer:
    frappe.throw("customer is required")

# v16 blocks SQL-function strings in get_all fields; sum in Python instead
rows = frappe.get_all(
    "GL Entry",
    filters={"party_type": "Customer", "party": customer, "is_cancelled": 0},
    fields=["debit", "credit"],
    limit_page_length=0,
)
debit = 0.0
credit = 0.0
for r in rows:
    debit += r.debit or 0
    credit += r.credit or 0
frappe.response["message"] = {
    "customer": customer,
    "outstanding": debit - credit,
}
"""

# Recent entries for the POS "Recent" tab: POS sales for everyone; the money
# vouchers (Payment Entry / Journal Entry from Fast Journal) only for staff who
# may post them. Read-only, ignore_permissions so a billing cashier's lack of
# PE/JE read doesn't 403 the sales list — the money section is role-gated below.
SCRIPT_RECENT = r"""
sales = frappe.get_all(
    "Sales Invoice",
    filters={"is_pos": 1, "docstatus": 1},
    fields=["name", "customer", "customer_name", "grand_total", "rounded_total",
            "outstanding_amount", "status", "posting_date"],
    order_by="creation desc", limit_page_length=20, ignore_permissions=True,
)
journal_roles = ["POS Journal", "Accounts User", "Accounts Manager", "System Manager", "Administrator"]
role_rows = frappe.get_all("Has Role",
    filters={"parenttype": "User", "parent": frappe.session.user},
    fields=["role"], limit_page_length=0, ignore_permissions=True)
user_roles = []
for rr in role_rows:
    user_roles.append(rr["role"])
can_journal = 0
for rname in journal_roles:
    if rname in user_roles:
        can_journal = 1
        break
payments = []
journals = []
if can_journal:
    pes = frappe.get_all(
        "Payment Entry", filters={"docstatus": 1},
        fields=["name", "payment_type", "party_type", "party", "party_name",
                "paid_amount", "posting_date", "remarks"],
        order_by="creation desc", limit_page_length=15, ignore_permissions=True)
    for p in pes:
        payments.append({
            "name": p.name, "kind": p.payment_type,
            "party": p.party_name or p.party or "",
            "amount": p.paid_amount, "date": str(p.posting_date),
            "remark": (p.remarks or "")[:80],
        })
    jes = frappe.get_all(
        "Journal Entry", filters={"docstatus": 1},
        fields=["name", "voucher_type", "total_debit", "posting_date", "user_remark"],
        order_by="creation desc", limit_page_length=15, ignore_permissions=True)
    for j in jes:
        journals.append({
            "name": j.name, "kind": j.voucher_type or "Journal",
            "amount": j.total_debit, "date": str(j.posting_date),
            "remark": (j.user_remark or "")[:80],
        })
frappe.response["message"] = {
    "sales": sales,
    "payments": payments,
    "journals": journals,
    "can_journal": can_journal,
}
"""

SERVER_SCRIPTS = {
    "vac_pos_ping": SCRIPT_PING,
    "vac_pos_catalog": SCRIPT_CATALOG,
    "vac_pos_create_invoice": SCRIPT_CREATE_INVOICE.replace(
        "__FALLBACK_TAX_TEMPLATE__", FALLBACK_TAX_TEMPLATE
    ),
    "vac_pos_outstanding": SCRIPT_OUTSTANDING,
    "vac_pos_recent": SCRIPT_RECENT,
}


def ensure_custom_field():
    name = "Sales Invoice-pwa_client_id"
    payload = {
        "dt": "Sales Invoice",
        "fieldname": "pwa_client_id",
        "label": "PWA Client ID",
        "fieldtype": "Data",
        "insert_after": "remarks",
        "unique": 1,
        "hidden": 1,
        "no_copy": 1,
        "print_hide": 1,
        "description": "Idempotency key set by the POS PWA; one per device sale.",
    }
    action, _ = upsert("Custom Field", name, payload)
    print("[1] Custom Field pwa_client_id:", action)


def ensure_role_named(role, desk_access=1):
    if get_doc("Role", role) is None:
        r = call("POST", "/api/resource/Role", json={"role_name": role, "desk_access": desk_access})
        r.raise_for_status()
        print("[2] Role {}: created".format(role))
    else:
        print("[2] Role {}: exists".format(role))


def ensure_perms(role, perm_map, tag="3"):
    for dt, ptypes in perm_map.items():
        existing = call(
            "GET",
            "/api/resource/Custom%20DocPerm?filters="
            + pp_lib._q(json.dumps([["role", "=", role], ["parent", "=", dt]]))
            + "&fields=" + pp_lib._q(json.dumps(["name"])),
        ).json().get("data", [])
        if not existing:
            rpc("frappe.core.page.permission_manager.permission_manager.add",
                parent=dt, role=role, permlevel=0)
        for ptype in ptypes:
            rpc("frappe.core.page.permission_manager.permission_manager.update",
                doctype=dt, role=role, permlevel=0, ptype=ptype, value=1)
        print("[{}] {} perms {} -> {}".format(tag, role, dt, ",".join(ptypes)))


def ensure_journal_users():
    for email in JOURNAL_USERS:
        user = get_doc("User", email)
        if user is None:
            print("[8] {}: MISSING — POS Journal not assigned".format(email))
            continue
        roles = [r["role"] for r in user.get("roles", [])]
        if "POS Journal" in roles:
            print("[8] {}: already has POS Journal".format(email))
            continue
        merged = [{"role": r} for r in roles] + [{"role": "POS Journal"}]
        r = call("PUT", "/api/resource/User/" + pp_lib._q(email), json={"roles": merged})
        r.raise_for_status()
        print("[8] {}: POS Journal role added".format(email))


def ensure_server_scripts():
    for name, script in SERVER_SCRIPTS.items():
        payload = {
            "script_type": "API",
            "api_method": name,
            "allow_guest": 0,
            "disabled": 0,
            "script": script.strip() + "\n",
        }
        if get_doc("Server Script", name) is None:
            payload["name"] = name
            r = call("POST", "/api/resource/Server%20Script", json=payload)
            r.raise_for_status()
            print("[4] Server Script {}: created".format(name))
        else:
            r = call("PUT", "/api/resource/Server%20Script/" + pp_lib._q(name), json=payload)
            r.raise_for_status()
            print("[4] Server Script {}: updated".format(name))


def ensure_test_user():
    # test user holds BOTH roles so the FJ happy-path is testable; a plain
    # POS Cashier (no POS Journal) is already known to 403 on posting.
    if pp_lib.TARGET == "prod":
        print("[5] test user: skipped on production")
        return
    existing = get_doc("User", TEST_USER)
    if existing is None:
        r = call("POST", "/api/resource/User", json={
            "email": TEST_USER,
            "first_name": "POS Test Cashier",
            "send_welcome_email": 0,
            "user_type": "System User",
            "roles": [{"role": "POS Cashier"}, {"role": "POS Journal"}],
        })
        r.raise_for_status()
        print("[5] test user: created")
        existing = get_doc("User", TEST_USER)
    else:
        roles = [x["role"] for x in existing.get("roles", [])]
        need = [rl for rl in ["POS Cashier", "POS Journal"] if rl not in roles]
        if need:
            merged = [{"role": rl} for rl in roles] + [{"role": rl} for rl in need]
            call("PUT", "/api/resource/User/" + pp_lib._q(TEST_USER),
                 json={"roles": merged}).raise_for_status()
            print("[5] test user: added " + ",".join(need))
        else:
            print("[5] test user: exists (roles ok)")

    # Mint keys ONLY if the user has none or .env lacks the pair. Regenerating on
    # every run rotated the secret and broke the kiosk token mid-test — don't.
    env = pp_lib._load_env()
    if existing.get("api_key") and env.get("STAGING_CASHIER_API_KEY") and env.get("STAGING_CASHIER_API_SECRET"):
        print("[5] cashier API keys: kept (already set)")
        return
    secret = rpc("frappe.core.doctype.user.user.generate_keys", user=TEST_USER)
    api_secret = secret["api_secret"] if isinstance(secret, dict) else secret
    r = call("GET", "/api/resource/User/" + pp_lib._q(TEST_USER) + "?fields="
             + pp_lib._q(json.dumps(["api_key"])))
    api_key = r.json()["data"].get("api_key")

    lines = []
    with open(pp_lib.ENV_PATH, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith(("STAGING_CASHIER_API_KEY=", "STAGING_CASHIER_API_SECRET=")):
                lines.append(line.rstrip("\n"))
    lines += [
        "STAGING_CASHIER_API_KEY=" + (api_key or ""),
        "STAGING_CASHIER_API_SECRET=" + (api_secret or ""),
    ]
    with open(pp_lib.ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("[5] cashier API keys: generated and written to .env")


def ensure_cashier_roles():
    for email in CASHIERS:
        user = get_doc("User", email)
        if user is None:
            print("[6] {}: MISSING on this site — create manually, NOT auto-created".format(email))
            continue
        roles = [r["role"] for r in user.get("roles", [])]
        if "POS Cashier" in roles:
            print("[6] {}: already has POS Cashier".format(email))
            continue
        merged = [{"role": r} for r in roles] + [{"role": "POS Cashier"}]
        r = call("PUT", "/api/resource/User/" + pp_lib._q(email), json={"roles": merged})
        r.raise_for_status()
        print("[6] {}: POS Cashier role added ({} existing roles kept)".format(email, len(roles)))


def smoke():
    msg = rpc("vac_pos_ping")
    print("[7] ping:", msg)


if __name__ == "__main__":
    ensure_custom_field()
    ensure_role_named("POS Cashier")
    ensure_perms("POS Cashier", PERM_MAP, tag="3")
    if SKIP_JOURNAL:
        print("[*] PP_SKIP_JOURNAL=yes -> POS Journal role/perms/assignment SKIPPED "
              "(Fast Journal runs on standard Accounts roles; PE/JE perms untouched)")
    else:
        ensure_role_named("POS Journal")
        ensure_perms("POS Journal", PERM_MAP_JOURNAL, tag="3J")
    ensure_server_scripts()
    ensure_test_user()
    ensure_cashier_roles()
    if not SKIP_JOURNAL:
        ensure_journal_users()
    smoke()
    print("DONE — now run pp_test.py")
