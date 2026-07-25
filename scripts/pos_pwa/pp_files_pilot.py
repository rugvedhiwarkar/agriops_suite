"""Deploy the POS PWA shell to STAGING's /files for the pre-deploy pilot.

The real serving path is agriops_suite www/pos.html at /pos (needs a bench
deploy the owner triggers from the FC dashboard). This script lets the app be
exercised on staging TODAY: it strips the Jinja bits from the same source file
and uploads it as a public file, reachable at  <staging>/files/pos.html.
Same origin as the vac_pos_* endpoints, so everything works except the
service worker + manifest (which register only on the /pos route anyway).

Idempotent: deletes any previous /files/pos.html File doc first so the name
never collides into pos-1.html. STAGING ONLY.
"""
import json
import os

import pp_lib
from pp_lib import call

assert pp_lib.TARGET == "staging", "files pilot is staging-only"

SRC = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "agriops_suite", "agriops_suite", "www", "pos.html"))


def transform(html):
    html = html.replace("{{ csrf_token }}", "")
    html = html.replace("{% raw %}", "").replace("{% endraw %}", "")
    return html


def main():
    with open(SRC, encoding="utf-8") as fh:
        body = transform(fh.read())

    existing = call(
        "GET",
        "/api/resource/File?filters=" + pp_lib._q(json.dumps([["file_url", "=", "/files/pos.html"]]))
        + "&fields=" + pp_lib._q(json.dumps(["name"])),
    ).json().get("data", [])
    for f in existing:
        r = call("DELETE", "/api/resource/File/" + pp_lib._q(f["name"]))
        # 404 = a timed-out first attempt actually landed; already gone is fine
        if r.status_code not in (200, 202, 404):
            r.raise_for_status()
        print("deleted old File", f["name"], "(HTTP {})".format(r.status_code))

    r = call(
        "POST", "/api/method/upload_file",
        files={"file": ("pos.html", body.encode("utf-8"), "text/html")},
        data={"is_private": "0", "optimize": "false"},
    )
    r.raise_for_status()
    url = r.json()["message"]["file_url"]
    print("uploaded ->", pp_lib.SITE_URL + url, "({} KB)".format(len(body) // 1024))
    assert url == "/files/pos.html", "unexpected file_url: " + url


if __name__ == "__main__":
    main()
