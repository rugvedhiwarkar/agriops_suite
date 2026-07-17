"""Local driver for kp_mirror.py: pushes the script to the bench and runs it.

Push channel: staging's /api/method/upload_file (private File) — the SSH
gateway is PTY-only and mangles large base64 payloads, so the file rides the
REST API instead and the bench copies it out of private/files.

Usage:
  python kp_run.py preview
  python kp_run.py prereqs
  python kp_run.py go --limit 5
  python kp_run.py go
  python kp_run.py reconcile
Every call re-uploads the current kp_mirror.py (cheap), then executes it
bench-side against STAGING and prints the full output.
"""
import argparse
import json
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STAGING_SITE = "vac-staging.nvi.frappe.cloud"


def env():
    out = {}
    for line in open(ROOT / ".env", encoding="utf-8-sig"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


E = env()


def upload_script():
    """Upload kp_mirror.py to staging as a private file; return its disk filename."""
    body = (HERE / "kp_mirror.py").read_bytes()
    boundary = uuid.uuid4().hex
    fname = f"kp_mirror_{uuid.uuid4().hex[:8]}.py"
    parts = []
    for k, v in [("is_private", "1"), ("folder", "Home")]:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                  f"filename=\"{fname}\"\r\nContent-Type: text/x-python\r\n\r\n").encode())
    parts.append(body)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    payload = b"".join(parts)
    req = urllib.request.Request(
        E["STAGING_SITE_URL"].rstrip("/") + "/api/method/upload_file",
        data=payload, method="POST",
        headers={"Authorization": f"token {E['STAGING_API_KEY']}:{E['STAGING_API_SECRET']}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    file_url = resp["message"]["file_url"]        # /private/files/<name>
    return file_url.split("/files/")[-1]


def bench(cmd, timeout=560):
    r = subprocess.run(["bash", str(ROOT / "bench-run.sh").replace("\\", "/"), cmd],
                       capture_output=True, text=True, timeout=timeout,
                       cwd=str(ROOT))
    if not r.stdout.strip():
        print("bench stderr:", (r.stderr or "")[-800:], file=sys.stderr)
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["preview", "prereqs", "go", "reconcile"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--types")
    args = ap.parse_args()

    disk_name = upload_script()
    print(f"uploaded -> private/files/{disk_name}")
    extra = ""
    if args.limit:
        extra += f" --limit {args.limit}"
    if args.types:
        extra += f" --types {args.types}"
    marker = uuid.uuid4().hex[:8]
    # run from the sites dir (frappe.init cwd rule); full output to a file, then cat
    cmd = (f"cp ~/frappe-bench/sites/{STAGING_SITE}/private/files/{disk_name} /tmp/kp_mirror.py"
           f" && cd ~/frappe-bench/sites"
           f" && ../env/bin/python /tmp/kp_mirror.py --site {STAGING_SITE} {args.action}{extra}"
           f" > /tmp/kp_out_{marker}.txt 2>&1; echo EXIT=$?"
           f"; cat /tmp/kp_out_{marker}.txt")
    out = bench(cmd)
    # strip the PTY echo of the command itself
    lines = out.splitlines()
    started = False
    for ln in lines:
        if not started and ln.startswith("EXIT="):
            started = True
            print(ln)
            continue
        if started:
            print(ln)
    if not started:
        print(out[-4000:])


if __name__ == "__main__":
    sys.exit(main())
