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
	return context
