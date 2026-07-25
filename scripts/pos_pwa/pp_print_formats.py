"""Create the print formats the POS prompts for (staging by default).

  VAC Delivery Note A4 / A5   (Sales Invoice)  — goods-only delivery note,
                              cloned from the existing "VAC Delivery Slip"
                              HTML with A4 vs A5 page geometry.
  VAC Journal Voucher         (Journal Entry)  — accounts / debit / credit
                              voucher in the house slate-&-cream skin.
  VAC Money Receipt           (Payment Entry)  — RECEIPT / PAYMENT VOUCHER
                              with amount-in-words, mode, signatures.

All reuse the .vac-bill CSS lifted from "VAC Tax Invoice A4" so they match the
bills exactly. Idempotent: updates in place. Run: python pp_print_formats.py
"""
import json

import pp_lib
from pp_lib import call, get_doc


def base_css():
    """The full .vac-bill component CSS from the A4 invoice, minus its @page."""
    d = get_doc("Print Format", "VAC Tax Invoice A4")
    css = d.get("css") or ""
    # drop any @page rule; each format sets its own page size below
    out, depth, i = [], 0, 0
    while i < len(css):
        if css[i:i + 5] == "@page":
            j = css.find("{", i)
            k = css.find("}", j)
            i = k + 1
            continue
        out.append(css[i])
        i += 1
    return "".join(out)


HDR = """
    <div class="hdr">
      <div class="hdr-title"><span class="doc-title">{TITLE}</span></div>
      <table class="hdr-tbl"><tr>
        <td class="hdr-left">
          <div class="co-name">VIJAY AGRO CENTRE</div>
          <div>NEAR BANK OF INDIA, SIHORA 441915</div>
          <div>TAL- TUMSAR, DIST- BHANDARA</div>
          <div class="bold">9881527395, 9422833565</div>
          <div class="bold">GSTIN : {{ frappe.db.get_value("Company", doc.company, "gstin") or "" }}</div>
        </td>
        <td class="hdr-logo"><img src="/files/vac-logo.png" alt=""></td>
        <td class="hdr-lic">
          <table class="lic-tbl">
            <tr><td class="lic-key">PEST. LIC.</td><td class="lic-val">LCID0820221786BHA</td></tr>
            <tr><td class="lic-key">SEED LIC.</td><td class="lic-val">LCSD0420221004BHA</td></tr>
            <tr><td class="lic-key">FERT. LIC.</td><td class="lic-val">LCRFD0520220248BHA</td></tr>
          </table>
        </td>
      </tr></table>
    </div>
"""

SIGN = """
    <table class="sign-tbl"><tr>
      <td class="sign-left"><br><br><b>{LEFT}</b></td>
      <td class="sign-right"><b>FOR, VIJAY AGRO CENTRE</b><br><br><br><b>AUTHORIZED SIGNATURE</b></td>
    </tr></table>
"""

JOURNAL_HTML = """{%- set dr = doc.total_debit or 0 -%}
<div class="vac-bill"><div class="bill-border">
""" + HDR.replace("{TITLE}", "JOURNAL VOUCHER") + """
    <table class="party-tbl"><tr>
      <td class="party-left">
        <div class="bold">Voucher Type</div>
        <div class="party-name">{{ doc.voucher_type or "Journal Entry" }}</div>
      </td>
      <td class="party-right">
        <div class="meta-line"><span>Voucher No. :</span><b>{{ doc.name }}</b></div>
        <div class="meta-line"><span>Dated :</span><b>{{ frappe.utils.formatdate(doc.posting_date, "dd/MM/yyyy") }}</b></div>
      </td>
    </tr></table>
    <table class="items-tbl">
      <thead><tr>
        <th class="c-sr"></th>
        <th class="dn-prod">ACCOUNT</th>
        <th class="dn-mfg">PARTY</th>
        <th class="c-qty c-num">DEBIT</th>
        <th class="c-amt">CREDIT</th>
      </tr></thead>
      <tbody>
        {%- for a in doc.accounts %}
        <tr>
          <td class="c-sr">{{ loop.index }}</td>
          <td class="dn-prod bold">{{ a.account }}</td>
          <td class="dn-mfg">{{ (a.party_type ~ ": " ~ a.party) if a.party else "" }}</td>
          <td class="c-num">{{ "%.2f"|format(a.debit_in_account_currency) if a.debit_in_account_currency else "" }}</td>
          <td class="c-amt">{{ "%.2f"|format(a.credit_in_account_currency) if a.credit_in_account_currency else "" }}</td>
        </tr>
        {%- endfor %}
        <tr class="filler-row f-mid"><td colspan="5"></td></tr>
      </tbody>
      <tfoot><tr class="totals-row">
        <td colspan="3" class="no-right-border" style="text-align:right"><b>Total</b></td>
        <td class="c-num bold">{{ "%.2f"|format(doc.total_debit) }}</td>
        <td class="c-amt">{{ "%.2f"|format(doc.total_credit) }}</td>
      </tr></tfoot>
    </table>
    <div class="tax-words">
      <div class="words-line"><span class="words-label">Rupees</span> <b>{{ frappe.utils.money_in_words(dr).replace("INR ", "").replace(" only.", " Only") }}</b></div>
      {%- if doc.user_remark %}<div class="words-line"><span class="words-label">Narration</span> {{ doc.user_remark }}</div>{% endif %}
    </div>
""" + SIGN.replace("{LEFT}", "PREPARED BY") + """
</div></div>
"""

RECEIPT_HTML = """{%- set rcv = doc.payment_type == "Receive" -%}
{%- set amt = doc.paid_amount or doc.received_amount or 0 -%}
{%- set party = doc.party_name or doc.party or "" -%}
{%- set mode = doc.mode_of_payment or (doc.paid_to if rcv else doc.paid_from) or "" -%}
<div class="vac-bill"><div class="bill-border">
""" + HDR.replace("{TITLE}", '{{ "RECEIPT" if rcv else "PAYMENT VOUCHER" }}') + """
    <table class="party-tbl"><tr>
      <td class="party-left">
        <div class="bold">{{ "Received with thanks from :" if rcv else "Paid to :" }}</div>
        <div class="party-name">{{ party }}</div>
        {%- if doc.party_type %}<div class="party-gstin">{{ doc.party_type }}</div>{% endif %}
      </td>
      <td class="party-right">
        <div class="meta-line"><span>Voucher No. :</span><b>{{ doc.name }}</b></div>
        <div class="meta-line"><span>Dated :</span><b>{{ frappe.utils.formatdate(doc.posting_date, "dd/MM/yyyy") }}</b></div>
        <div class="meta-line"><span>Mode :</span><b>{{ mode }}</b></div>
        {%- if doc.reference_no %}<div class="meta-line"><span>Ref. No. :</span><b>{{ doc.reference_no }}</b></div>{% endif %}
      </td>
    </tr></table>
    <table class="grand-tbl"><tr>
      <td class="gt-label"><b>{{ "Amount Received" if rcv else "Amount Paid" }}</b> &#8377;</td>
      <td class="gt-amt">{{ frappe.utils.fmt_money(amt) }}</td>
    </tr></table>
    <div class="tax-words">
      <div class="words-line"><span class="words-label">Rupees</span> <b>{{ frappe.utils.money_in_words(amt).replace("INR ", "").replace(" only.", " Only") }}</b></div>
      {%- if doc.remarks %}<div class="words-line"><span class="words-label">Towards</span> {{ doc.remarks }}</div>{% endif %}
    </div>
""" + SIGN.replace("{LEFT}", '{{ "RECEIVER" if rcv else "PAID BY" }}') + """
</div></div>
"""


def upsert_pf(name, doc_type, html, css, page):
    payload = {
        "doctype": "Print Format", "name": name, "module": "Agriops Suite",
        "doc_type": doc_type, "standard": "No", "print_format_type": "Jinja",
        "custom_format": 1, "raw_printing": 0, "html": html,
        "css": "@page { size: %s; }\n%s" % (page, css),
        "font_size": 14, "margin_top": 5, "margin_bottom": 5, "margin_left": 5, "margin_right": 5,
        "disabled": 0,
    }
    if get_doc("Print Format", name) is None:
        r = call("POST", "/api/resource/Print%20Format", json=payload)
    else:
        r = call("PUT", "/api/resource/Print%20Format/" + pp_lib._q(name), json=payload)
    r.raise_for_status()
    print("  %-26s %s" % (name, "created" if r.status_code in (200, 201) else "ok"))


def main():
    css = base_css()
    print("base .vac-bill css:", len(css), "chars")
    # delivery notes: reuse the existing delivery HTML at two page sizes
    dslip = get_doc("Print Format", "VAC Delivery Slip")
    dn_html = dslip.get("html")
    upsert_pf("VAC Delivery Note A4", "Sales Invoice", dn_html, css, "210mm 297mm")
    upsert_pf("VAC Delivery Note A5", "Sales Invoice", dn_html, css, "148mm 210mm")
    # money vouchers, house style
    upsert_pf("VAC Journal Voucher", "Journal Entry", JOURNAL_HTML, css, "210mm 148mm")
    upsert_pf("VAC Money Receipt", "Payment Entry", RECEIPT_HTML, css, "210mm 148mm")
    print("DONE")


if __name__ == "__main__":
    main()
