"""Attach audited product images to Items for POS tiles.

Reads the merged audit verdicts, takes rows with verdict CORRECT, optimizes
each local image (max 512px, JPEG q82, alpha flattened to white), uploads it
as a public /files asset, and sets Item.image. Replaces the old generated
pos_*.png colour placeholders where present. Idempotent: an Item whose image
already points at our pi_*.jpg upload is skipped.

Default target = STAGING (set PI_TARGET=prod for the production pass — only
after user sign-off, per golden rules).
"""
import csv
import os
import re

from PIL import Image

import pi_lib as api

# repo-relative since the 2026-07 folder move (old OneDrive\Projects path is gone)
REPO_ROOT = os.path.normpath(os.path.join(api.script_dir(), "..", ".."))
VERDICTS = os.path.join(REPO_ROOT, "reports", "pos_images", "verdicts_merged.csv")
IMG_DIR = os.path.join(REPO_ROOT, "item-images")
BUILD_DIR = os.path.join(api.script_dir(), "optimized")
LOG = os.path.join(REPO_ROOT, "reports", "pos_images", "upload_log.csv")
MAX_SIDE = 512


def slug(item_code):
    s = re.sub(r"[^a-z0-9]+", "_", item_code.lower()).strip("_")
    return "pi_" + s + ".jpg"


def local_file_for(item_code, files_index):
    norm = item_code.replace(":", "_").replace("/", "_").replace('"', "_").replace("?", "_").lower()
    return files_index.get(norm)


def optimize(src_path, out_path):
    img = Image.open(src_path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=82, optimize=True)
    return os.path.getsize(out_path)


def main():
    os.makedirs(BUILD_DIR, exist_ok=True)
    files_index = {}
    for f in os.listdir(IMG_DIR):
        files_index[os.path.splitext(f)[0].lower()] = f

    rows = [r for r in csv.DictReader(open(VERDICTS, encoding="utf-8-sig"))
            if r["verdict"].strip().upper() == "CORRECT"]
    print("CORRECT verdicts to attach:", len(rows))

    log = []
    done = skipped = failed = 0
    for r in rows:
        item = r["item_code"]
        fname = local_file_for(item, files_index)
        if not fname:
            print("NO LOCAL FILE:", item)
            failed += 1
            log.append({"item_code": item, "status": "no-local-file", "file_url": ""})
            continue
        target_name = slug(item)
        cur = api.get_list("Item", filters={"name": item}, fields=["name", "image"])
        if not cur:
            print("ITEM MISSING on site:", item)
            failed += 1
            log.append({"item_code": item, "status": "item-missing", "file_url": ""})
            continue
        if (cur[0].get("image") or "").endswith("/" + target_name):
            skipped += 1
            log.append({"item_code": item, "status": "already-set", "file_url": cur[0]["image"]})
            continue
        out_path = os.path.join(BUILD_DIR, target_name)
        try:
            size = optimize(os.path.join(IMG_DIR, fname), out_path)
        except Exception as e:
            print("OPTIMIZE FAILED:", item, e)
            failed += 1
            log.append({"item_code": item, "status": "optimize-failed", "file_url": ""})
            continue
        existing = api.get_list("File", filters={"file_url": "/files/" + target_name})
        if existing:
            file_url = "/files/" + target_name
        else:
            file_url = api.upload_file(out_path)
        api.set_value("Item", item, "image", file_url)
        done += 1
        log.append({"item_code": item, "status": "attached", "file_url": file_url})
        print("attached %-45s %s (%d KB)" % (item, file_url, size // 1024))

    with open(LOG, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["item_code", "status", "file_url"])
        w.writeheader()
        w.writerows(log)
    print("DONE attached=%d skipped=%d failed=%d -> log %s" % (done, skipped, failed, LOG))


if __name__ == "__main__":
    print("site user:", api.whoami(), "->", api.SITE_URL)
    main()
