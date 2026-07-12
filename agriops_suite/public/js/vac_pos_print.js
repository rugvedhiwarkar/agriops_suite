// vac_pos_print: extra print buttons on the POS order-summary screen —
// "Invoice A4" and "Delivery Slip" next to the stock Print Receipt (which the
// POS Profiles point at "VAC Tax Invoice A5"). The summary component is shared
// by the post-checkout screen and Recent Orders, so one patch covers both.
// Self-gating: no-op anywhere but the point-of-sale page, and degrades to
// stock behaviour if the component ever changes shape.
(function () {
	const LETTERHEAD = "Blank (VAC Bill Formats)";
	const BUTTONS = [
		["Invoice A4", "VAC Tax Invoice A4"],
		["Delivery Slip", "VAC Delivery Slip"],
	];

	function patch() {
		const cls = window.erpnext?.PointOfSale?.PastOrderSummary;
		if (!cls) return false;
		if (cls.__vac_print_patched) return true;
		cls.__vac_print_patched = true;
		const orig = cls.prototype.load_summary_of;
		cls.prototype.load_summary_of = function (...args) {
			orig.apply(this, args);
			try {
				if (!this.$summary_btns || !this.doc || this.doc.docstatus !== 1) return;
				this.$summary_btns.find(".vac-extra-print").remove();
				BUTTONS.forEach(([label, fmt]) => {
					const $b = $(
						`<div class="summary-btn btn btn-default vac-extra-print">${__(label)}</div>`
					);
					$b.on("click", () =>
						frappe.utils.print(this.doc.doctype, this.doc.name, fmt, LETTERHEAD)
					);
					this.$summary_btns.append($b);
				});
			} catch (e) {
				console.warn("vac_pos_print: button injection failed", e);
			}
		};
		return true;
	}

	function arm() {
		if (patch()) return;
		const timer = setInterval(() => {
			if (patch()) clearInterval(timer);
		}, 800);
		setTimeout(() => clearInterval(timer), 30000);
	}

	$(function () {
		if (!window.frappe) return;
		frappe.router?.on("change", () => {
			if ((frappe.get_route?.() || [])[0] === "point-of-sale") arm();
		});
		if ((frappe.get_route?.() || [])[0] === "point-of-sale") arm();
	});
})();
