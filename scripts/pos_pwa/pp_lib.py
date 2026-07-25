"""Shared REST client for the POS PWA Phase-1 build.

Default target = STAGING. Set env var PP_TARGET=prod to run against
PRODUCTION — additionally requires PP_ALLOW_PROD=yes so a stray run can
never hit production without two explicit switches (golden rule 1: prod
writes only with the owner's confirmation in-session).
Pattern from custom_doctypes/pos_images/pi_lib.py, with the .env path made
repo-relative so it survives folder moves.
"""
import json
import os
import time

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.normpath(os.path.join(_HERE, "..", "..", ".env"))
TARGET = os.environ.get("PP_TARGET", "staging").lower()


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
    assert os.environ.get("PP_ALLOW_PROD") == "yes", (
        "Refusing to touch production: set PP_ALLOW_PROD=yes only after the "
        "owner has confirmed promotion in this session."
    )
    SITE_URL = _env["ERPNEXT_SITE_URL"].rstrip("/")
    _key = _env["ERPNEXT_API_KEY"]
    _secret = _env["ERPNEXT_API_SECRET"]
    assert "vijayagrocentre" in SITE_URL, "prod URL sanity check failed - stop"
else:
    SITE_URL = _env["STAGING_SITE_URL"].rstrip("/")
    _key = _env["STAGING_API_KEY"]
    _secret = _env["STAGING_API_SECRET"]
    assert "vac-staging" in SITE_URL, "staging URL sanity check failed - stop"

print("### POS PWA target:", TARGET.upper(), "->", SITE_URL)

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


def call(method, path, retries=4, **kw):
    """Retries gateway status codes and connection-level failures."""
    for attempt in range(retries):
        try:
            r = S.request(method, _url(path), timeout=60, **kw)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == retries - 1:
                raise
            print("  .. connection issue ({}), retry {}".format(exc.__class__.__name__, attempt + 1))
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (502, 503, 504) and attempt < retries - 1:
            print("  .. HTTP {} from gateway, retry {}".format(r.status_code, attempt + 1))
            time.sleep(3 * (attempt + 1))
            continue
        return r
    return r


def get_doc(doctype, name):
    r = call("GET", "/api/resource/{}/{}".format(_q(doctype), _q(name)))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()["data"]


def upsert(doctype, name, payload):
    """Create doc if absent, else update with payload. Returns (action, data)."""
    if get_doc(doctype, name) is None:
        r = call("POST", "/api/resource/{}".format(_q(doctype)), json=payload)
        r.raise_for_status()
        return "created", r.json()["data"]
    r = call("PUT", "/api/resource/{}/{}".format(_q(doctype), _q(name)), json=payload)
    r.raise_for_status()
    return "updated", r.json()["data"]


def rpc(method, **params):
    """POST /api/method/<method> with form params; raises on API error."""
    r = call("POST", "/api/method/{}".format(method), data=params)
    if r.status_code >= 400:
        raise RuntimeError("{} -> HTTP {}: {}".format(method, r.status_code, r.text[:400]))
    return r.json().get("message")


def _q(s):
    return requests.utils.quote(str(s), safe="")
