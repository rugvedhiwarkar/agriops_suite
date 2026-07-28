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
	// Who a document can be sent TO. Same list as PARTY_MASTERS today, but it is
	// a different question — "is this form a party master?" vs "may I address
	// this kind of party?" — so keep them separate. Mirrors MOBILE_FIELD in
	// whatsapp.py, which is what actually authorises the lookup.
	const PARTY_TYPES = PARTY_MASTERS.slice();
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
		// "Send to" options: the document's own party first (the common case, one
		// click), then any other party of any type, then a raw number.
		const doc_option = target.party
			? __("{0} — on this document", [target.party_name || target.party])
			: null;
		const OTHER = __("Another number");
		const options = (doc_option ? [doc_option] : []).concat(PARTY_TYPES, [OTHER]);

		const d = new frappe.ui.Dialog({
			title: __("Send on WhatsApp"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "heading",
					options:
						`<div class="text-muted" style="margin-bottom:8px">${__("Sending")} ` +
						`<b>${frappe.utils.escape_html(doc.name)}</b></div>`,
				},
				{
					fieldname: "to_type",
					label: __("Send to"),
					fieldtype: "Select",
					options: options.join("\n"),
					default: options[0],
					change: () => on_type_change(),
				},
				{
					fieldname: "party",
					label: __("Which one"),
					fieldtype: "Link",
					options: PARTY_TYPES[0],
					// only meaningful once a party TYPE is chosen
					depends_on: `eval:${JSON.stringify(PARTY_TYPES)}.indexOf(doc.to_type) >= 0`,
					change: () => on_party_change(),
				},
				{
					fieldname: "number",
					label: __("Mobile Number"),
					fieldtype: "Data",
					reqd: 1,
					default: target.mobile || "",
					description: target.mobile
						? __("From the {0} record — edit to send elsewhere.", [
								target.party_type || __("document"),
						  ])
						: __("No number on file. Enter one, and add it to the record so it is there next time."),
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
				const chosen = chosen_party();
				try {
					const res = (
						await frappe.call({
							method: "agriops_suite.whatsapp.send",
							args: {
								doctype: doc.doctype,
								name: doc.name,
								print_format: v.print_format || null,
								to_number: v.number,
								to_party_type: chosen ? chosen.party_type : null,
								to_party: chosen ? chosen.party : null,
							},
						})
					).message;
					d.hide();
					frappe.show_alert(
						{
							message: __("Sent to {0} ({1})", [res.party_name || res.to, res.to]),
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

		function chosen_party() {
			const type = d.get_value("to_type");
			const party = d.get_value("party");
			if (PARTY_TYPES.indexOf(type) < 0 || !party) return null;
			return { party_type: type, party: party };
		}

		function set_number_hint(text) {
			const field = d.get_field("number");
			if (field) field.set_description(text);
		}

		function on_type_change() {
			const type = d.get_value("to_type");
			if (type === doc_option) {
				d.set_value("party", "");
				d.set_value("number", target.mobile || "");
				set_number_hint(
					target.mobile
						? __("From the {0} record — edit to send elsewhere.", [
								target.party_type || __("document"),
						  ])
						: __("No number on file. Enter one, and add it to the record so it is there next time.")
				);
				return;
			}
			if (type === OTHER) {
				d.set_value("party", "");
				d.set_value("number", "");
				set_number_hint(__("Type the number to send to — 10 digits, or with 91."));
				return;
			}
			// a party type: repoint the Link field and wait for a pick
			d.set_df_property("party", "options", type);
			d.set_value("party", "");
			d.set_value("number", "");
			// no article — "a Employee" / "a Shareholder" both read wrong
			set_number_hint(__("Choose from {0} records — the number fills in automatically.", [type]));
		}

		async function on_party_change() {
			const chosen = chosen_party();
			if (!chosen) return;
			try {
				const info = (
					await frappe.call({
						method: "agriops_suite.whatsapp.get_party_mobile",
						args: chosen,
					})
				).message;
				d.set_value("number", (info && info.mobile) || "");
				set_number_hint(
					info && info.mobile
						? __("From the {0} record — edit to send elsewhere.", [chosen.party_type])
						: __("No number on file for {0}. Type one, and add it to their record.", [
								(info && info.party_name) || chosen.party,
						  ])
				);
			} catch (e) {
				console.error("vac_wa:", e);
			}
		}

		d.show();
	}

	window.vac_wa = window.vac_wa || {};
	window.vac_wa.send_dialog = send_dialog;

	// --- WhatsApp Settings: let a long API token actually save ----------------
	//
	// `token` is a Password control, and Frappe runs a zxcvbn strength check on
	// Password fields whenever the site password policy is on (it is here:
	// enable_password_policy=1). A ~200-char random Meta token scores so highly
	// that zxcvbn's `guesses` exceeds a 64-bit integer, orjson refuses to
	// serialise the response, and the user gets a "TypeError: Integer exceeds
	// 64-bit range" traceback instead of a saved token.
	//
	// Frappe exposes disable_password_checks() for exactly this. Scoped to this
	// one field, so the password policy still applies everywhere it means
	// something — which is not a machine-generated bearer token.
	function relax_token_field(frm) {
		try {
			const field = frm && frm.get_field ? frm.get_field("token") : null;
			if (field && typeof field.disable_password_checks === "function") {
				field.disable_password_checks();
			}
		} catch (e) {
			console.warn("vac_wa: could not relax token field", e);
		}
	}

	if (window.frappe && frappe.ui && frappe.ui.form && frappe.ui.form.on) {
		frappe.ui.form.on("WhatsApp Settings", {
			onload: relax_token_field,
			refresh: relax_token_field,
		});
	}

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
			const frm = this;
			// Deferred by a tick on purpose. Adding the button synchronously here
			// still lands inside the refresh chain, and a LATER handler (the "VAC
			// Print Buttons" Client Script) then creates its "Print" button group
			// and swallows ours into that dropdown — verified on staging, where
			// the button existed in frm.custom_buttons but rendered inside Print.
			// Once the chain has settled, add_custom_button renders standalone.
			setTimeout(() => {
				try {
					if (!should_show(frm)) return;
					const label = __("Send on WhatsApp");
					if (frm.custom_buttons && frm.custom_buttons[label]) return;
					frm.add_custom_button(label, () => send_dialog(frm.doc));
				} catch (e) {
					console.warn("vac_wa: button injection failed", e);
				}
			}, 0);
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
