"""Sales Invoice submit guard for the POS.

Deliberately a SEPARATE module from pos.py, and deliberately importing nothing
but frappe.

pos.py is a pinned copy of an ERPNext core function and reaches into non-API
internals (``erpnext.accounts.doctype.pos_invoice.pos_invoice``,
``erpnext.selling.page.point_of_sale.point_of_sale``). Frappe resolves
``doc_events`` handlers through ``frappe.get_attr()`` with no exception
handling, so while this guard lived in pos.py an ImportError from any of those
internals propagated out of ``run_method("before_submit")`` for EVERY Sales
Invoice submit — desk, /pos and /slip alike — and the failure looked nothing
like a POS problem. The bench auto-updates (ERPNext rolled 16.25.0 -> 16.28.0
here with no action on our part), so that was a live upgrade hazard, and
nothing would have caught it until the first invoice of the morning.

Keeping the hook here means a broken pinned copy degrades only the desk item
grid, which is what the pinned copy is actually for.
"""

import frappe
from frappe.utils import flt


def block_zero_rate_pos(doc, method=None):
    """Safeguard for the "cashier types the price at the register" POS change
    (public/js/vac_pos.bundle.js): never let a POS sale be completed with a
    zero-rate line. The JS lets an unpriced item into the cart at rate 0 so the
    cashier can type the price on the spot; this catches the case where they
    forgot. Scoped to POS invoices (is_pos) — regular Sales Invoices, which may
    legitimately carry a zero-rate line (a free sample, a 100%-discount item),
    are untouched. Wired via before_submit on Sales Invoice in hooks.py."""
    if not getattr(doc, "is_pos", 0):
        return
    # Only the "forgot to price it" case: qty>0, net rate 0, AND no list price.
    # An intentional 100%-discount on a PRICED item keeps price_list_rate>0, so
    # it is allowed through.
    zero = [
        d.item_code
        for d in (doc.items or [])
        if flt(d.qty) and flt(d.rate) <= 0 and flt(d.price_list_rate) <= 0
    ]
    if zero:
        frappe.throw(
            frappe._("Set a price for these items before completing the sale: {0}").format(
                ", ".join(frappe.bold(x) for x in zero)
            ),
            title=frappe._("Price not set"),
        )
