import frappe


def get_context(context):
	"""Driver Slip PWA shell (/slip).

	The page is a self-contained single-file app (inline CSS+JS, Marathi-first)
	for the delivery driver's phone. It is deliberately guest-viewable: without
	a stored pairing token it only shows the pairing screen, and every API call
	it makes is authenticated with the driver's own token. Served no_cache so
	edits reach phones on their next online open (the service worker uses
	stale-while-revalidate on top of this).
	"""
	context.no_cache = 1
	# standalone page — no website header/footer wrapper
	context.show_sidebar = 0
	# CSRF token for an already-signed-in session (email+password login). The
	# app also fetches it from agriops_suite.slip.csrf after login, since the SW
	# caches this shell; this seeds it on a fresh server-rendered open. Parity
	# with www/count.py / www/pos.py.
	context.csrf_token = ""
	if frappe.session.user and frappe.session.user != "Guest":
		try:
			context.csrf_token = frappe.sessions.get_csrf_token()
		except Exception:
			context.csrf_token = ""
	return context
