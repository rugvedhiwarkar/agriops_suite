#!/usr/bin/env python3
"""Sanity-check agriops_suite/fixtures/doctype.json before it reaches a site.

Written after two production incidents in one afternoon, both caused by a
hand-rolled fixture export rather than by anything wrong with the DocTypes:

  1. `WhatsApp Settings` inherited Driver Slip's autoname "DRS-.#####", and
     migrate died on "Series DRS- already used in Driver Slip", aborting the
     whole deploy.
  2. Every field of both new DocTypes lost `options`, so the Link / Dynamic Link
     / Select fields were invalid. That one was worse: it failed SILENTLY at
     runtime — messages still sent, but each audit-log insert raised
     "Options not set for link field reference_doctype" and was swallowed, so
     the trail simply stopped being written.

Both are one grep away. Run this before committing a fixture change:

    python agriops_suite/scripts/check_doctype_fixtures.py
"""
import collections
import json
import os
import sys

PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agriops_suite", "fixtures", "doctype.json",
)
NEEDS_OPTIONS = ("Link", "Dynamic Link", "Select", "Table", "Table MultiSelect")

with open(PATH, encoding="utf-8") as f:
    doctypes = json.load(f)

problems = []

# 1. two DocTypes must never claim the same naming series. "field:x" is not a
#    series — several masters legitimately name themselves off the same field.
series = [
    d["autoname"]
    for d in doctypes
    if d.get("autoname") and not str(d["autoname"]).startswith("field:")
]
for name, count in collections.Counter(series).items():
    if count > 1:
        owners = [d["name"] for d in doctypes if d.get("autoname") == name]
        problems.append(f"naming series {name!r} claimed by {owners}")

# 2. a Link/Select/Table field without options is invalid, and Frappe only
#    complains when something tries to INSERT a row
for d in doctypes:
    for fld in d.get("fields") or []:
        if fld.get("fieldtype") in NEEDS_OPTIONS and not fld.get("options"):
            problems.append(
                f"{d['name']}.{fld.get('fieldname')} is {fld['fieldtype']} with no options"
            )

# 3. a Single with an autoname is contradictory, and that is exactly how the
#    DRS- collision got in
for d in doctypes:
    if d.get("issingle") and d.get("autoname"):
        problems.append(f"{d['name']} is a Single but has autoname {d['autoname']!r}")

# NB: deliberately NOT checking for a shared migration_hash. It looked like a
# good signal — a hash copied from another DocType would tell Frappe the schema
# is already current — but 15 of the existing doctypes here legitimately share
# one, so the check fires on a perfectly healthy file. A guard that cries wolf
# is worse than no guard.

print(f"checked {len(doctypes)} doctypes in {os.path.relpath(PATH)}")
if problems:
    print(f"\n{len(problems)} problem(s):")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
print("OK")
