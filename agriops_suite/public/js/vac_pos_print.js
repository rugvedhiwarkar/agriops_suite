// vac_wa moved. The WhatsApp helper — including the old public-File upload and
// wa.me deep link that used to sit here — now lives in ONE place:
//
//     agriops_suite/public/js/whatsapp_send.bundle.js
//
// It is loaded desk-wide via app_include_js, so window.vac_wa.send_dialog is
// already defined by the time the POS button below calls it. Documents are now
// uploaded straight to Meta and sent for real; no public /files/ URL is created.

// vac_pos_print: extra buttons on the POS order-summary screen (post-checkout
// AND Recent Orders): Invoice A4, Delivery Slip, WhatsApp. Print Receipt stays
// the stock button (POS Profiles point it at "VAC Tax Invoice A5").
(function () {
	const LETTERHEAD = "Blank (VAC Bill Formats)";
	const PRINT_BUTTONS = [
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
				PRINT_BUTTONS.forEach(([label, fmt]) => {
					const $b = $(`<div class="summary-btn btn btn-default vac-extra-print">${__(label)}</div>`);
					$b.on("click", () => frappe.utils.print(this.doc.doctype, this.doc.name, fmt, LETTERHEAD));
					this.$summary_btns.append($b);
				});
				const $wa = $(`<div class="summary-btn btn btn-default vac-extra-print">${__("WhatsApp")}</div>`);
				$wa.on("click", () => window.vac_wa.send_dialog(this.doc));
				this.$summary_btns.append($wa);
			} catch (e) {
				console.warn("vac_pos_print: button injection failed", e);
			}
		};
		return true;
	}
	function arm() {
		if (patch()) return;
		const timer = setInterval(() => { if (patch()) clearInterval(timer); }, 800);
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
