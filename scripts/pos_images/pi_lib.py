"""Shared REST client for the POS item-images build.

Default target = STAGING. Set env var PI_TARGET=prod to run the same
installer against PRODUCTION (vijayagrocentre) — the switch is explicit and
the URL is hard-asserted per target, so a stray run can never hit the
wrong site. Pattern from custom_doctypes/rebrand/rb_lib.py.
"""
import json
import os
import time

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.normpath(os.path.join(_HERE, "..", "..", ".env"))
if not os.path.exists(ENV_PATH):  # legacy location before the repo moved (2026-07)
    ENV_PATH = r"C:\Users\rugve\OneDrive\Projects\ERPNext Connect\.env"
TARGET = os.environ.get("PI_TARGET", "staging").lower()


def _load_env():
    vals = {}
    with open(ENV_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


_env = _load_env()
if TARGET == "prod":
    SITE_URL = _env["ERPNEXT_SITE_URL"].rstrip("/")
    _key = _env["ERPNEXT_API_KEY"]
    _secret = _env["ERPNEXT_API_SECRET"]
    assert "vijayagrocentre" in SITE_URL, "prod URL sanity check failed - stop"
else:
    SITE_URL = "https://vac-staging.nvi.frappe.cloud"
    _key = _env["STAGING_API_KEY"]
    _secret = _env["STAGING_API_SECRET"]
    assert _env["STAGING_SITE_URL"] == SITE_URL, "staging URL changed - stop"

print("### POS images target:", TARGET.upper(), "->", SITE_URL)

S = requests.Session()
S.headers.update({
    "Authorization": "token {}:{}".format(_key, _secret),
    "Accept": "application/json",
})


def _url(path):
    if TARGET == "prod":
        assert "vijayagrocentre" in SITE_URL
    else:
        assert "vac-staging" in SITE_URL
    return SITE_URL + path


def call(method, path, retries=5, **kw):
    """Retries BOTH gateway status codes and connection-level failures —
    the shared Frappe Cloud proxy intermittently resets TLS handshakes."""
    last_exc = None
    for attempt in range(retries):
        try:
            r = S.request(method, _url(path), timeout=120, **kw)
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code in (429, 502, 503, 504) and attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
            continue
        return r
    if last_exc is not None:
        raise last_exc
    return r


def get(path, params=None):
    return call("GET", path, params=params)


def post(path, payload):
    return call("POST", path, json=payload)


def put(path, payload):
    return call("PUT", path, json=payload)


def whoami():
    r = get("/api/method/frappe.auth.get_logged_user")
    r.raise_for_status()
    return r.json()["message"]


def exists(doctype, name):
    r = get("/api/resource/{}/{}".format(doctype, requests.utils.quote(name)))
    return r.status_code == 200


def insert(payload):
    r = post("/api/method/frappe.client.insert", {"doc": json.dumps(payload)})
    if r.status_code != 200:
        raise RuntimeError("insert {} failed {}: {}".format(
            payload.get("doctype"), r.status_code, r.text[:2000]))
    return r.json()["message"]


def get_list(doctype, filters=None, fields=None, limit=100):
    r = post("/api/method/frappe.client.get_list",
             {"doctype": doctype,
              "filters": json.dumps(filters or {}),
              "fields": json.dumps(fields or ["name"]),
              "limit_page_length": limit})
    r.raise_for_status()
    return r.json()["message"]


def upload_file(local_path, is_private=0):
    """Upload a local file as a public /files asset. Returns file_url."""
    fname = os.path.basename(local_path)
    with open(local_path, "rb") as fh:
        r = S.post(
            _url("/api/method/upload_file"),
            files={"file": (fname, fh)},
            data={"is_private": str(is_private)},
            timeout=120,
        )
    if r.status_code != 200:
        raise RuntimeError("upload {} failed {}: {}".format(
            fname, r.status_code, r.text[:1000]))
    return r.json()["message"]["file_url"]


def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def set_value(doctype, name, fieldname, value):
    r = post("/api/method/frappe.client.set_value",
             {"doctype": doctype, "name": name,
              "fieldname": fieldname, "value": value})
    if r.status_code != 200:
        raise RuntimeError("set_value {} {} {} failed {}: {}".format(
            doctype, name, fieldname, r.status_code, r.text[:1000]))
