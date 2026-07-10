/* VAC Claude-style Desk theme — gate switch.
 *
 * vac_theme.css is inert until <html> carries data-vac-theme. This snippet
 * sets that attribute only when the site's boot info says the theme is on
 * (boot.py copies `vac_theme_enabled` from site_config.json into boot), so
 * the shared bench can carry the CSS while each site opts in individually:
 *   bench --site <site> set-config vac_theme_enabled 1
 */

(function () {
	function apply() {
		if (window.frappe && frappe.boot && frappe.boot.vac_theme_enabled) {
			document.documentElement.setAttribute("data-vac-theme", "1");
			return true;
		}
		return false;
	}
	// boot is normally available by the time app bundles run; fall back to
	// DOM-ready for safety (worst case: one unthemed first paint)
	if (!apply()) {
		document.addEventListener("DOMContentLoaded", apply);
	}
})();
