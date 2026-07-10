/* Cash Desk POS extension — "Log Payment" button on the Point of Sale screen.
 *
 * Adds a header button (and a menu entry) to the native POS page that opens a
 * dialog for posting drawer money movements without leaving the POS:
 *   - Expense              -> Journal Entry  (Dr expense ledger / Cr till cash)
 *   - Receipt from Customer-> Payment Entry  (customer pays old dues in cash)
 *   - Payment to Party     -> Payment Entry  (supplier paid from the till)
 *
 * Self-gating: the button renders only on sites where the Server Script API
 * `pos_cash_desk_flags` exists and returns enabled=1. Production stays
 * untouched until those scripts are created there (staging-first switch).
 * The cash account is resolved server-side from the POS profile's default
 * payment method, so each counter's entries hit its own till.
 */

(function () {
	const PAGE = "point-of-sale";

	function flags_url() {
		return "/api/method/pos_cash_desk_flags";
	}

	function setup(wrapper) {
		// silent gate: no frappe.call (a missing API would pop an error dialog)
		fetch(flags_url(), { headers: { "X-Frappe-CSRF-Token": frappe.csrf_token } })
			.then((r) => (r.ok ? r.json() : null))
			.then((j) => {
				const flags = j && j.message;
				if (flags && flags.enabled) add_ui(wrapper, flags);
			})
			.catch(() => {});
	}

	function add_ui(wrapper, flags) {
		if (wrapper.__cash_desk_ready) return;
		wrapper.__cash_desk_ready = true;
		// The POS controller rebuilds the header actions when its init finishes
		// (and on later redraws), which removes buttons added before that point.
		// Keep ours present with a re-adding observer instead of a one-shot add.
		const ensure = () => {
			const host =
				wrapper.page &&
				wrapper.page.wrapper &&
				wrapper.page.wrapper.find(".page-actions")[0];
			if (!host || host.querySelector(".cash-desk-log-payment")) return;
			const $btn = wrapper.page.add_button(
				__("Log Payment"),
				() => open_dialog(wrapper, flags),
				{ btn_class: "btn-primary" }
			);
			if ($btn && $btn.addClass) $btn.addClass("cash-desk-log-payment");
		};
		ensure();
		const host = wrapper.page.wrapper.find(".page-actions")[0];
		if (host) {
			const obs = new MutationObserver(ensure);
			obs.observe(host, { childList: true, subtree: true });
			wrapper.__cash_desk_observer = obs;
		}
	}

	function open_dialog(wrapper, flags) {
		const pos_profile =
			(wrapper.pos && wrapper.pos.pos_profile) || null;
		const d = new frappe.ui.Dialog({
			title: __("Log Payment"),
			fields: [
				{
					fieldname: "entry_type",
					fieldtype: "Select",
					label: __("Type"),
					options: ["Expense", "Receipt from Customer", "Payment to Party"],
					default: "Expense",
					reqd: 1,
				},
				{
					fieldname: "expense_type",
					fieldtype: "Select",
					label: __("Expense Type"),
					options: (flags.expense_types || ["Other"]).join("\n"),
					default: "Other",
					depends_on: "eval:doc.entry_type=='Expense'",
				},
				{
					fieldname: "customer",
					fieldtype: "Link",
					label: __("Customer"),
					options: "Customer",
					depends_on: "eval:doc.entry_type=='Receipt from Customer'",
				},
				{
					fieldname: "supplier",
					fieldtype: "Link",
					label: __("Supplier / Party"),
					options: "Supplier",
					depends_on: "eval:doc.entry_type=='Payment to Party'",
				},
				{ fieldname: "cb", fieldtype: "Column Break" },
				{
					fieldname: "amount",
					fieldtype: "Currency",
					label: __("Amount"),
					reqd: 1,
				},
				{ fieldname: "note", fieldtype: "Data", label: __("Note") },
			],
			primary_action_label: __("Post"),
			primary_action(v) {
				if (!v.amount || v.amount <= 0) {
					frappe.msgprint(__("Enter an amount."));
					return;
				}
				let method = "pos_log_expense";
				if (v.entry_type === "Receipt from Customer") {
					if (!v.customer) {
						frappe.msgprint(__("Pick the customer."));
						return;
					}
					method = "pos_receive_payment";
				}
				if (v.entry_type === "Payment to Party") {
					if (!v.supplier) {
						frappe.msgprint(__("Pick the supplier / party."));
						return;
					}
					method = "pos_pay_party";
				}
				frappe.call({
					method: method,
					args: {
						pos_profile: pos_profile,
						expense_type: v.expense_type,
						customer: v.customer,
						supplier: v.supplier,
						amount: v.amount,
						note: v.note || "",
					},
					freeze: true,
					freeze_message: __("Posting..."),
					callback: (r) => {
						d.hide();
						const m = r.message || {};
						frappe.show_alert({
							message: __("Posted {0} into {1}", [
								m.voucher || "",
								m.cash_account || "",
							]),
							indicator: "green",
						});
					},
				});
			},
		});
		d.show();
	}

	// run after ERPNext's own on_page_load builds the POS
	const page_wrapper = frappe.pages[PAGE];
	if (page_wrapper) {
		const orig = page_wrapper.on_page_load;
		page_wrapper.on_page_load = function (wrapper) {
			if (orig) orig.call(this, wrapper);
			setup(wrapper);
		};
	}
})();
