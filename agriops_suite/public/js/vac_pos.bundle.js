/* VAC POS — let items with NO preset price be billed at the register.
 *
 * ERPNext core POS (erpnext.PointOfSaleController.on_cart_update) HARD-BLOCKS an
 * item whose rate is 0/undefined: it shows "Price is not set for the item.",
 * plays an error sound, and refuses to add the item to the bill. For an agri
 * counter where hundreds of items have no fixed price, that stops the sale.
 *
 * This replaces on_cart_update with a byte-for-byte copy of the core method
 * (ERPNext 16.26.2) EXCEPT that the price block is removed: an unpriced item is
 * instead added at rate 0 and the item panel opens (POS Profile allow_rate_change
 * = 1), so the cashier just types the price on the spot. A server-side
 * before_submit safeguard (agriops_suite.pos.block_zero_rate_pos) blocks
 * completing ANY POS sale that still has a 0-rate line, so nothing bills at zero.
 *
 * Ungated (this is a POS pricing fix, not the theme). Content-hashed .bundle.js
 * so an edit busts the immutable /assets cache.
 * ⚠ RE-DIFF on_cart_update against core on every ERPNext upgrade.
 */
(function () {
	function patch() {
		if (!(window.erpnext && erpnext.PointOfSaleController)) return false;
		var P = erpnext.PointOfSaleController.prototype;
		if (P.__vac_allow_unpriced) return true;

		P.on_cart_update = async function (args) {
			frappe.dom.freeze();
			if (this.frm.doc.set_warehouse !== this.settings.warehouse) {
				this.frm.set_value("set_warehouse", this.settings.warehouse);
			}
			let item_row = undefined;
			try {
				let { field, value, item } = args;
				item_row = this.get_item_from_frm(item);
				const item_row_exists = !$.isEmptyObject(item_row);

				const from_selector = field === "qty" && value === "+1";
				if (from_selector) value = flt(item_row.qty) + flt(value);

				if (item_row_exists) {
					if (field === "qty") value = flt(value);

					if (["qty", "conversion_factor"].includes(field) && value > 0 && !this.allow_negative_stock) {
						const qty_needed =
							field === "qty" ? value * item_row.conversion_factor : item_row.qty * value;
						await this.check_stock_availability(item_row, qty_needed, this.frm.doc.set_warehouse);
					}

					if (this.is_current_item_being_edited(item_row) || from_selector) {
						await frappe.model.set_value(item_row.doctype, item_row.name, field, value);
						if (item.serial_no && from_selector) {
							await frappe.model.set_value(
								item_row.doctype,
								item_row.name,
								"serial_no",
								item_row.serial_no + `\n${item.serial_no}`
							);
						}
						this.update_cart_html(item_row);
					}
				} else {
					if (!this.frm.doc.customer) return this.raise_customer_selection_alert();

					const { item_code, batch_no, serial_no, uom, stock_uom } = item;
					let { rate } = item;

					if (!item_code) return;

					// --- VAC CHANGE (core here blocked + returned when rate was
					// 0/undefined). Let the item in at rate 0 so the cashier can type
					// the price; before_submit safeguard prevents billing at zero. ---
					if (rate == undefined) rate = 0;

					const new_item = { item_code, batch_no, rate, uom, [field]: value, stock_uom };

					if (serial_no) {
						await this.check_serial_no_availablilty(item_code, this.frm.doc.set_warehouse, serial_no);
						new_item["serial_no"] = serial_no;
					}

					new_item["use_serial_batch_fields"] = 1;
					new_item["warehouse"] = this.settings.warehouse;
					if (field === "serial_no") new_item["qty"] = value.split(`\n`).length || 0;

					item_row = this.frm.add_child("items", new_item);

					if (field === "qty" && value !== 0 && !this.allow_negative_stock) {
						const qty_needed = value * item_row.conversion_factor;
						await this.check_stock_availability(item_row, qty_needed, this.frm.doc.set_warehouse);
					}

					await this.trigger_new_item_events(item_row);

					this.update_cart_html(item_row);

					if (this.item_details.$component.is(":visible")) this.edit_item_details_of(item_row);

					if (
						this.check_serial_batch_selection_needed(item_row) &&
						!this.item_details.$component.is(":visible")
					)
						this.edit_item_details_of(item_row);
				}
			} catch (error) {
				console.log(error);
			} finally {
				frappe.dom.unfreeze();
				return item_row; // eslint-disable-line no-unsafe-finally
			}
		};

		P.__vac_allow_unpriced = true;
		// eslint-disable-next-line no-console
		console.log("[VAC] POS: unpriced items can be added — cashier enters the price");
		return true;
	}

	function on_route() {
		var r = (frappe.get_route && frappe.get_route()) || [];
		if (r[0] !== "point-of-sale") return;
		if (patch()) return;
		// POS bundle may still be loading — retry briefly until the class exists.
		var n = 0;
		var iv = setInterval(function () {
			if (patch() || ++n > 60) clearInterval(iv);
		}, 100);
	}

	if (window.frappe && frappe.router && frappe.router.on) frappe.router.on("change", on_route);
	$(document).on("page-change", on_route);
	on_route();
})();
