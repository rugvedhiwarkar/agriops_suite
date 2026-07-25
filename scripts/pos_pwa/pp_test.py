"""POS PWA Phase-1 end-to-end test (STAGING ONLY).

Exercises the four server-script endpoints as the POS Cashier test user:
ping -> catalog -> cash sale -> idempotent re-post -> udhaar sale ->
outstanding check -> cancel the two test invoices (as Administrator).

Run after pp_install.py:  python custom_doctypes/pos_pwa/pp_test.py
Leaves only two CANCELLED invoices marked "POS PWA Phase-1 test" behind.
"""
import json
import time
import uuid

import requests

import pp_lib
from pp_lib import call, rpc

assert pp_lib.TARGET == "staging", "pp_test writes documents - staging only"

WAREHOUSE = "Main Store - VAC"
TEST_REMARK = "POS PWA Phase-1 test - safe to ignore"

_env = pp_lib._load_env()
CK, CS = _env.get("STAGING_CASHIER_API_KEY"), _env.get("STAGING_CASHIER_API_SECRET")
assert CK and CS, "run pp_install.py first (cashier keys missing from .env)"

cashier = requests.Session()
cashier.headers.update({
    "Authorization": "token {}:{}".format(CK, CS),
    "Accept": "application/json",
})

RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("  {} {} {}".format("PASS" if ok else "FAIL", label, detail))


def cashier_rpc(method, **params):
    t0 = time.time()
    r = cashier.post(pp_lib.SITE_URL + "/api/method/" + method, data=params, timeout=60)
    ms = int((time.time() - t0) * 1000)
    if r.status_code >= 400:
        raise RuntimeError("{} -> HTTP {}: {}".format(method, r.status_code, r.text[:500]))
    return r.json().get("message"), ms


def pick_sellable_item(prices_by_code):
    """First item with stock > 5 at the POS warehouse AND a selling price."""
    r = call("GET", "/api/resource/Bin?filters="
             + pp_lib._q(json.dumps([["warehouse", "=", WAREHOUSE], ["actual_qty", ">", 5]]))
             + "&fields=" + pp_lib._q(json.dumps(["item_code", "actual_qty"]))
             + "&limit_page_length=50")
    candidates = [
        (row["item_code"], prices_by_code[row["item_code"]])
        for row in r.json().get("data", [])
        if prices_by_code.get(row["item_code"])
    ]
    if not candidates:
        raise RuntimeError("no item found with both stock and a Standard Selling price")
    # prefer whole-rupee prices so paid == rounded total (no false rounding fails)
    for code, rate in candidates:
        if abs(rate - round(rate)) < 1e-6:
            return code, rate
    return candidates[0]


def main():
    print("== 1. ping (server scripts enabled? cashier auth?) ==")
    msg, ms = cashier_rpc("vac_pos_ping")
    check("ping", msg and msg.get("pong") is True, "user={} {}ms".format(msg.get("user"), ms))

    print("== 2. catalog bundle ==")
    cat, ms = cashier_rpc("vac_pos_catalog", profile="Main")
    n_items, n_cust = len(cat["items"]), len(cat["customers"])
    check("catalog counts", n_items > 500 and n_cust > 1000,
          "{} items, {} customers, {}ms".format(n_items, n_cust, ms))
    check("catalog profile", cat["profile"]["warehouse"] == WAREHOUSE,
          str(cat["profile"]["taxes_and_charges"]))

    prices_by_code = {p["item_code"]: p["price_list_rate"] for p in cat["prices"]}
    item_code, rate = pick_sellable_item(prices_by_code)
    print("  test item: {} @ {}".format(item_code, rate))
    walkin = cat["profile"]["customer"] or "Cash Customer"
    udhaar_cust = next((c["name"] for c in cat["customers"] if c["name"] != walkin), walkin)

    print("== 3. cash sale ==")
    cid_cash = "pp-test-" + uuid.uuid4().hex
    inv, ms = cashier_rpc(
        "vac_pos_create_invoice",
        pwa_client_id=cid_cash, pos_profile="Main", customer=walkin,
        items=json.dumps([{"item_code": item_code, "qty": 1, "rate": rate}]),
        payments=json.dumps([{"mode_of_payment": "Cash", "amount": rate}]),
        remarks=TEST_REMARK,
    )
    check("cash sale submitted", inv["docstatus"] == 1 and not inv["duplicate"],
          "{} total={} {}ms".format(inv["name"], inv["grand_total"], ms))
    check("cash sale is_pos", inv["is_pos"] == 1)
    check("tax rows copied", len(inv["taxes"]) == 2,
          json.dumps(inv["taxes"]))
    check("cash sale settled", abs(inv["outstanding_amount"]) < 0.01,
          "outstanding={}".format(inv["outstanding_amount"]))

    print("== 4. idempotent re-post (same pwa_client_id) ==")
    dup, ms = cashier_rpc(
        "vac_pos_create_invoice",
        pwa_client_id=cid_cash, pos_profile="Main", customer=walkin,
        items=json.dumps([{"item_code": item_code, "qty": 1, "rate": rate}]),
        payments=json.dumps([{"mode_of_payment": "Cash", "amount": rate}]),
    )
    check("duplicate detected", dup["duplicate"] is True and dup["name"] == inv["name"],
          "{} {}ms".format(dup["name"], ms))

    print("== 5. udhaar sale (no payments -> regular SI, outstanding) ==")
    before, _ = cashier_rpc("vac_pos_outstanding", customer=udhaar_cust)
    cid_udhaar = "pp-test-" + uuid.uuid4().hex
    ud, ms = cashier_rpc(
        "vac_pos_create_invoice",
        pwa_client_id=cid_udhaar, pos_profile="Main", customer=udhaar_cust,
        items=json.dumps([{"item_code": item_code, "qty": 1, "rate": rate}]),
        remarks=TEST_REMARK,
    )
    check("udhaar submitted", ud["docstatus"] == 1, "{} {}ms".format(ud["name"], ms))
    check("udhaar is_pos=0", ud["is_pos"] == 0)
    check("udhaar outstanding", ud["outstanding_amount"] > 0,
          "outstanding={}".format(ud["outstanding_amount"]))

    print("== 6. outstanding endpoint reflects the sale ==")
    after, ms = cashier_rpc("vac_pos_outstanding", customer=udhaar_cust)
    delta = (after["outstanding"] or 0) - (before["outstanding"] or 0)
    check("khata delta", abs(delta - ud["outstanding_amount"]) < 0.05,
          "delta={} vs {} {}ms".format(round(delta, 2), ud["outstanding_amount"], ms))

    print("== 7. cleanup: cancel test invoices (Administrator) ==")
    for name in (inv["name"], ud["name"]):
        rpc("frappe.client.cancel", doctype="Sales Invoice", name=name)
        print("  cancelled", name)

    failed = [r for r in RESULTS if not r[1]]
    print("\n==== {} passed, {} failed ====".format(
        len(RESULTS) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
