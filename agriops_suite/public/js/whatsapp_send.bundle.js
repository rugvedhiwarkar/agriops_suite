// ============================================================================
// "Send on WhatsApp" — one button on every document that has a party.
//
// Replaces the old wa.me deep-link helper that used to live in
// vac_pos_print.js. That one rendered the PDF, uploaded it as a PUBLIC File and
// opened a pre-filled chat the user still had to send by hand. Everything now
// goes through agriops_suite.whatsapp.send: the PDF is uploaded straight to
// Meta and never becomes a File row, and the message is actually sent.
//
// window.vac_wa.send_dialog(doc) is kept as the entry point because two callers
// depend on it — the POS order-summary button (vac_pos_print.js) and the "VAC
// Print Buttons - Sales Invoice" Client Script fixture. Both keep working
// unchanged; they just reach the real sender now.
//
// The button renders only where frappe.boot.vac_whatsapp_enabled is set (see
// boot.py), so this ships to the shared bench without appearing on a site that
// has no token configured.
// ============================================================================
(function () {
	const PARTY_MASTERS = ["Customer", "Supplier", "Employee", "Shareholder"];
	// mirrors PARTY_FIELDS/party_type in whatsapp.py — keep the two in step
	const PARTY_FIELDS = ["customer", "supplier", "employee", "shareholder", "party"];
	const PAYROLL_DOCTYPES = ["Salary Slip"];
	const PAYROLL_ROLES = ["HR Manager", "HR User", "System Manager"];

	function enabled() {
		return !!(window.frappe && frappe.boot && frappe.boot.vac_whatsapp_enabled);
	}

	function has_party(frm) {
		if (PARTY_MASTERS.indexOf(frm.doctype) >= 0) return true;
		return PARTY_FIELDS.some((f) => frm.doc && frm.doc[f]);
	}

	function allowed(frm) {
		if (PAYROLL_DOCTYPES.indexOf(frm.doctype) < 0) return true;
		// Cosmetic only — whatsapp.py enforces the same rule server-side. Hiding
		// it here just avoids offering an action that would be refused.
		const roles = (window.frappe && frappe.user_roles) || [];
		return PAYROLL_ROLES.some((r) => roles.indexOf(r) >= 0);
	}

	function should_show(frm) {
		if (!enabled() || !frm || !frm.doc) return false;
		if (frm.is_new && frm.is_new()) return false;
		if (frm.doc.docstatus === 2) return false; // cancelled — nothing to send
		if (frm.meta && frm.meta.issingle) return false;
		return has_party(frm) && allowed(frm);
	}

	// --- the dialog ---------------------------------------------------------

	async function send_dialog(doc) {
		if (!doc || !doc.doctype || !doc.name) return;
		let target;
		try {
			target = (
				await frappe.call({
					method: "agriops_suite.whatsapp.get_target",
					args: { doctype: doc.doctype, name: doc.name },
				})
			).message;
		} catch (e) {
			console.error("vac_wa:", e);
			return; // frappe already showed the server error
		}
		if (!target) return;

		const formats = target.print_formats || [];
		const who = target.party_name || target.party || __("this document");
		const d = new frappe.ui.Dialog({
			title: __("Send on WhatsApp"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "who",
					options:
						`<div class="text-muted" style="margin-bottom:8px">${__("Sending")} ` +
						`<b>${frappe.utils.escape_html(doc.name)}</b> ${__("to")} ` +
						`<b>${frappe.utils.escape_html(who)}</b></div>`,
				},
				{
					fieldname: "number",
					label: __("Mobile Number"),
					fieldtype: "Data",
					reqd: 1,
					default: target.mobile || "",
					description: target.mobile
						? __("From the {0} record — edit to send elsewhere.", [target.party_type || __("document")])
						: __("No number on file for this party. Enter one, and add it to the record so it is there next time."),
				},
				formats.length
					? {
							fieldname: "print_format",
							label: __("Document"),
							fieldtype: "Select",
							options: formats.join("\n"),
							default: formats[0],
					  }
					: { fieldtype: "HTML", options: "" },
			],
			primary_action_label: __("Send"),
			primary_action: async (v) => {
				const btn = d.get_primary_btn();
				btn.prop("disabled", true).text(__("Sending..."));
				try {
					const res = (
						await frappe.call({
							method: "agriops_suite.whatsapp.send",
							args: {
								doctype: doc.doctype,
								name: doc.name,
								print_format: v.print_format || null,
								to_number: v.number,
							},
						})
					).message;
					d.hide();
					frappe.show_alert(
						{
							message: __("Sent to {0} ({1})", [res.party_name || who, res.to]),
							indicator: "green",
						},
						7
					);
				} catch (e) {
					console.error("vac_wa:", e);
					// the server's throw() is already on screen; just re-arm the button
					btn.prop("disabled", false).text(__("Send"));
				}
			},
		});
		d.show();
	}

	window.vac_wa = window.vac_wa || {};
	window.vac_wa.send_dialog = send_dialog;

	// --- desk-wide button ----------------------------------------------------
	//
	// Frappe has no "on every doctype" form event, so refresh is wrapped the same
	// way core_fixes.js wraps upstream functions: defer to the original, then do
	// our bit inside a try so a failure here can never break a form.

	function arm() {
		const Form = window.frappe && frappe.ui && frappe.ui.form && frappe.ui.form.Form;
		if (!Form || Form.prototype.__vac_wa_patched) return !!Form;
		Form.prototype.__vac_wa_patched = true;
		const orig = Form.prototype.refresh;
		Form.prototype.refresh = function (...args) {
			const out = orig.apply(this, args);
			try {
				if (should_show(this)) {
					this.add_custom_button(__("Send on WhatsApp"), () => send_dialog(this.doc));
				}
			} catch (e) {
				console.warn("vac_wa: button injection failed", e);
			}
			return out;
		};
		return true;
	}

	if (!arm()) {
		$(function () {
			arm();
		});
	}
})();
