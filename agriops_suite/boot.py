import frappe


def extend_bootinfo(bootinfo):
	"""Per-site switch for the VAC Claude-style desk theme (staging-first).

	Reads `vac_theme_enabled` from the site's site_config.json, so the theme
	can be piloted on staging and later promoted to production without a
	redeploy: bench --site <site> set-config vac_theme_enabled 1
	"""
	bootinfo.vac_theme_enabled = frappe.conf.get("vac_theme_enabled") or 0
	# which palette: "1"/"claude" (default), "leaf", or "nature" (website-matched)
	bootinfo.vac_theme_variant = frappe.conf.get("vac_theme_variant") or "1"
	# Standard ledger reports augmented IN-PLACE with the ledger features
	# (Summarize / column width+order / hide+rename / dual-role party filter).
	# Now that the features are proven, they default ON for the standard financial
	# ledgers on every site. A site can still override — including disabling with
	# an empty list — via site_config:
	#   bench --site <site> set-config finscope_ledger_reports '[...]' --parse
	_conf_ledgers = frappe.conf.get("finscope_ledger_reports")
	bootinfo.finscope_ledger_reports = _conf_ledgers if _conf_ledgers is not None else [
		# financial ledgers
		"General Ledger",
		"Accounts Receivable",
		"Accounts Payable",
		"Accounts Receivable Summary",
		"Accounts Payable Summary",
		"Customer Ledger Summary",
		"Supplier Ledger Summary",
		"Sales Register",
		"Purchase Register",
		# item-axis registers — the BusyWin Sales/Purchase Analysis (Item-wise)
		# equivalents, and the Invoice Trends period rollups
		"Item-wise Sales Register",
		"Item-wise Purchase Register",
		"Sales Invoice Trends",
		"Purchase Invoice Trends",
		# stock ledgers — the BusyWin Inventory Books / Stock Status / Stock
		# Ageing (FIFO) equivalents (see docs/knowledge/busywin_erpnext_report_map.md)
		"Stock Ledger",
		"Stock Balance",
		"Stock Ageing",
	]
