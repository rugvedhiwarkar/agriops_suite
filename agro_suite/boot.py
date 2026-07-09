import frappe


def extend_bootinfo(bootinfo):
	"""Per-site switch for the VAC Claude-style desk theme (staging-first).

	Reads `vac_theme_enabled` from the site's site_config.json, so the theme
	can be piloted on staging and later promoted to production without a
	redeploy: bench --site <site> set-config vac_theme_enabled 1
	"""
	bootinfo.vac_theme_enabled = frappe.conf.get("vac_theme_enabled") or 0
