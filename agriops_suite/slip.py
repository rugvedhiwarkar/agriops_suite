"""Driver Slip PWA (/slip) — static endpoints.

The PWA's page lives at www/slip.html and its dynamic API surface is the
Driver Slip* Server Script fixtures (submit / bootstrap / make-invoice /
validate — DB records, same pattern as the LedgerLift endpoints). Only two
things genuinely need app code, because they must be served as raw
non-HTML responses from stable URLs:

- the service worker:  Frappe's StaticPage renderer refuses .js under www/,
  and /assets is proxy-cached immutable (an edit would never reach phones).
  Serving it from a whitelisted method gives a stable, never-cached URL; the
  `Service-Worker-Allowed: /slip` header widens its scope to the page even
  though the script URL sits under /api/method/.
- the web-app manifest: same .json-under-www restriction.

Both are allow_guest: the browser fetches them without auth headers (SW
registration and manifest fetches can't carry our token), and they contain
nothing site-specific beyond public branding.
"""

import json

import frappe
from werkzeug.wrappers import Response

SCOPE = "/slip"


@frappe.whitelist(methods=["GET"])
def csrf():
	"""CSRF token + identity for the CURRENT logged-in session.

	The /slip app signs in with the driver's own email + password (frappe's
	/api/method/login sets the session cookie). Every subsequent POST to a Driver
	Slip / delivery endpoint then needs an X-Frappe-CSRF-Token header — a cookie
	session without it is rejected. The token is fetched here right after login
	because the app shell is service-worker cached and a baked-in token would go
	stale. (Same pattern as count.py / pos_pwa.py.)

	Not allow_guest: a caller with no valid session gets 403, which is exactly how
	the app decides whether to show the login screen. Same-origin means a
	cross-site page cannot read this response, so returning the token is safe.
	"""
	user = frappe.session.user
	roles = frappe.get_roles(user)
	return {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") or user,
		"is_driver": "Driver" in roles,
		"is_office": frappe.db.get_value("User", user, "user_type") == "System User",
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def sw():
	"""Serve public/js/slip_sw.js with the scope-widening header."""
	path = frappe.get_app_path("agriops_suite", "public", "js", "slip_sw.js")
	with open(path, encoding="utf-8") as f:
		body = f.read()
	resp = Response(body, mimetype="text/javascript")
	resp.headers["Service-Worker-Allowed"] = SCOPE
	# no-cache (not immutable): the browser revalidates on each visit, so a
	# shipped SW change reaches phones on their next online open.
	resp.headers["Cache-Control"] = "no-cache"
	return resp


@frappe.whitelist(allow_guest=True, methods=["GET"])
def manifest():
	"""Web-app manifest so the page installs to the driver's home screen."""
	m = {
		"name": "VAC स्लिप",
		"short_name": "VAC स्लिप",
		"start_url": SCOPE,
		"scope": SCOPE,
		"display": "standalone",
		"background_color": "#f6f5f0",
		"theme_color": "#166b41",
		"icons": [
			{
				"src": "/assets/agriops_suite/images/slip-icon-192.png",
				"sizes": "192x192",
				"type": "image/png",
			},
			{
				"src": "/assets/agriops_suite/images/slip-icon-512.png",
				"sizes": "512x512",
				"type": "image/png",
			},
		],
	}
	resp = Response(json.dumps(m, ensure_ascii=False), mimetype="application/manifest+json")
	resp.headers["Cache-Control"] = "no-cache"
	return resp
