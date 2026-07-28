"""WhatsApp Cloud API sender — send any document's PDF to any party.

Replaces the old `wa.me` deep-link helper (public/js/vac_pos_print.js), which
rendered the PDF, parked it as a PUBLIC File and handed the user a pre-filled
chat window to send by hand. Two things were wrong with that: the bill sat at a
world-readable /files/ URL forever, and nothing was actually sent — a human had
to press send in WhatsApp.

Here the PDF never becomes a File row at all. It is rendered in memory, uploaded
straight to Meta's /media endpoint, and referenced by the returned media ID. No
public URL exists at any point, so there is nothing to enumerate and nothing to
clean up later. (Meta drops uploaded media after 30 days on its side.)

Business-initiated messages must use a pre-approved TEMPLATE — a free-form
document can only be sent inside a 24h window opened by the customer messaging
us first, which for invoice delivery is never. So every send here goes through
one UTILITY template with a DOCUMENT header. Keep that template strictly
transactional: since Apr 2025 Meta re-categorises at approval time, and the same
template approved as MARKETING costs ~7.5x more per message (India: Rs 0.115 ->
Rs 0.863).

Configuration lives in the **WhatsApp Settings** single, per site: enabled flag,
Phone Number ID, and the access token as a Password field (Frappe encrypts it
into __Auth). It is deliberately a DocType rather than site_config: prod and
staging share one Frappe Cloud bench, bench SSH certificates expire every six
hours, and the owner must be able to paste their own token without anyone else
handling it. The Settings RECORD is per-site data and must never be exported as
a fixture — only the definition is.

site_config still wins where present, for bench-managed overrides:

    vac_whatsapp_enabled            force the feature on for this site
    vac_whatsapp_token              access token
    vac_whatsapp_phone_number_id    the sending number's Phone Number ID
    vac_whatsapp_template           template name
    vac_whatsapp_graph_version      Graph API version, defaults to GRAPH_VERSION

Either way this is the staging-first contract used elsewhere in this app (see
`tools_enabled()` in party.py): shipping the code to the shared bench does not
turn it on for a site until that site is configured.
"""

import re

import frappe
import requests
from frappe import _

GRAPH_VERSION = "v25.0"
DEFAULT_TEMPLATE = "vac_document_utility"
DEFAULT_LANG = "en"
TIMEOUT = 60

# Party master -> the flat field that holds its mobile number. Employee breaks
# the `mobile_no` convention (cell_number), and Shareholder has no flat field at
# all, so it resolves through its linked Contact only.
MOBILE_FIELD = {
	"Customer": "mobile_no",
	"Supplier": "mobile_no",
	"Employee": "cell_number",
	"Shareholder": None,
}

PARTY_MASTERS = tuple(MOBILE_FIELD)

# Transaction field -> party doctype, in resolution order. `party_type`/`party`
# (Payment Entry, Journal Entry) is checked before these because those documents
# also carry a stale `customer` field in some flows.
PARTY_FIELDS = (
	("customer", "Customer"),
	("supplier", "Supplier"),
	("employee", "Employee"),
	("shareholder", "Shareholder"),
)

# Salary Slips carry pay data, so the button is role-gated rather than relying on
# document permissions alone (a user who can read a slip is not automatically
# someone who should be broadcasting it).
PAYROLL_DOCTYPES = ("Salary Slip",)
PAYROLL_ROLES = ("HR Manager", "HR User", "System Manager")


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def _settings():
	"""The WhatsApp Settings single, or None if the DocType isn't installed yet.

	Cached — this is read on every desk boot, so it must not be a query per page.
	"""
	try:
		return frappe.get_cached_doc("WhatsApp Settings")
	except Exception:
		return None


def enabled():
	"""True when this site is configured to send. Cheap — used by the client to
	decide whether to render the button at all.

	site_config wins over the Settings record so an operator can force the
	feature off for a whole site without touching data.
	"""
	if frappe.conf.get("vac_whatsapp_enabled"):
		return True
	settings = _settings()
	return bool(settings and settings.get("enabled"))


def _config():
	"""(token, phone_number_id) for this site, or throw with a useful message.

	Credentials live in the WhatsApp Settings single (token is a Password field,
	so Frappe keeps it encrypted in __Auth). site_config is honoured first for
	bench-managed deployments; neither ever appears in code or a fixture.
	"""
	if not enabled():
		frappe.throw(_("WhatsApp sending is not enabled on this site."))
	settings = _settings()
	token = frappe.conf.get("vac_whatsapp_token")
	if not token and settings:
		token = settings.get_password("token", raise_exception=False)
	pnid = frappe.conf.get("vac_whatsapp_phone_number_id") or (
		settings.get("phone_number_id") if settings else None
	)
	if not token or not pnid:
		frappe.throw(
			_("WhatsApp is not configured. Set the Phone Number ID and access "
			  "token in WhatsApp Settings.")
		)
	return token, pnid


def _graph(path):
	version = frappe.conf.get("vac_whatsapp_graph_version") or GRAPH_VERSION
	return f"https://graph.facebook.com/{version}/{path}"


# ---------------------------------------------------------------------------
# party + number resolution
# ---------------------------------------------------------------------------


def normalise(raw):
	"""Return a Meta-ready 91XXXXXXXXXX, or None if this isn't a valid Indian
	mobile.

	Deliberately strict: Meta bills per message and silently accepts a
	well-formed-but-wrong number, so a junk value must fail here rather than
	quietly send someone else's invoice. Landlines and the 8-digit values that
	came across in the Busy import are rejected (they cannot receive WhatsApp).
	"""
	digits = re.sub(r"\D", "", raw or "")
	digits = digits.lstrip("0")
	if len(digits) == 12 and digits.startswith("91"):
		digits = digits[2:]
	if len(digits) == 10 and digits[0] in "6789":
		return "91" + digits
	return None


def resolve_party(doc):
	"""(party_type, party_name) for any document, or (None, None).

	Handles three shapes: a party master opened directly, the generic
	party_type/party pair (Payment Entry, Journal Entry), and the named link
	fields on sales/purchase/payroll documents.
	"""
	if doc.doctype in PARTY_MASTERS:
		return doc.doctype, doc.name
	party_type = doc.get("party_type")
	if party_type in MOBILE_FIELD and doc.get("party"):
		return party_type, doc.get("party")
	for field, party_type in PARTY_FIELDS:
		if doc.get(field):
			return party_type, doc.get(field)
	return None, None


def _contact_mobile(party_type, party):
	"""Mobile from the party's linked Contact, via the standard Dynamic Link
	pattern (same shape as share_addresses_and_contacts in party.py)."""
	names = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Contact", "link_doctype": party_type, "link_name": party},
		pluck="parent",
	)
	if not names:
		return None
	for row in frappe.get_all(
		"Contact",
		filters={"name": ["in", list(set(names))]},
		fields=["mobile_no", "phone"],
		order_by="is_primary_contact desc, modified desc",
	):
		number = normalise(row.get("mobile_no")) or normalise(row.get("phone"))
		if number:
			return number
	return None


def resolve_mobile(party_type, party, doc=None):
	"""Best known mobile for this party: the document's own contact_mobile (the
	one a user may have overridden per-transaction) beats the master, which beats
	the linked Contact."""
	if doc is not None:
		number = normalise(doc.get("contact_mobile"))
		if number:
			return number
	if not party_type or not party:
		return None
	field = MOBILE_FIELD.get(party_type)
	if field:
		number = normalise(frappe.db.get_value(party_type, party, field))
		if number:
			return number
	return _contact_mobile(party_type, party)


def _party_label(party_type, party):
	"""Human name for the party, for the message body and the log."""
	if not party_type or not party:
		return ""
	meta_field = {
		"Customer": "customer_name",
		"Supplier": "supplier_name",
		"Employee": "employee_name",
		"Shareholder": "title",
	}.get(party_type)
	if meta_field:
		return frappe.db.get_value(party_type, party, meta_field) or party
	return party


# ---------------------------------------------------------------------------
# permissions
# ---------------------------------------------------------------------------


def _check_permission(doc):
	"""Server-side gate. The client hides the button, but that is cosmetic — this
	is what actually stops a send."""
	if not frappe.has_permission(doc.doctype, ptype="print", doc=doc):
		frappe.throw(
			_("You are not permitted to send {0} {1}.").format(doc.doctype, doc.name),
			frappe.PermissionError,
		)
	if doc.doctype in PAYROLL_DOCTYPES:
		roles = set(frappe.get_roles())
		if not roles.intersection(PAYROLL_ROLES):
			frappe.throw(
				_("Only HR users can send {0} documents on WhatsApp.").format(doc.doctype),
				frappe.PermissionError,
			)


# ---------------------------------------------------------------------------
# Meta Cloud API
# ---------------------------------------------------------------------------


def _meta_error(response):
	"""Meta returns its real reason in a nested error object; surface it instead
	of a bare status code, because the useful ones (131047 re-engagement, 132001
	template missing, 131053 media) are only distinguishable by message."""
	try:
		err = (response.json() or {}).get("error") or {}
	except ValueError:
		err = {}
	parts = [p for p in (err.get("message"), err.get("error_user_msg")) if p]
	detail = " — ".join(parts) or (response.text or "")[:300]
	code = err.get("code")
	return f"[{response.status_code}{'/' + str(code) if code else ''}] {detail}"


def upload_media(pdf_bytes, filename, token, pnid):
	"""Upload the PDF to Meta and return its media ID.

	This is the whole reason no public URL is needed: the alternative Cloud API
	path takes a link and has Meta fetch it, which both exposes the document and
	makes delivery depend on our render latency.
	"""
	response = requests.post(
		_graph(f"{pnid}/media"),
		headers={"Authorization": f"Bearer {token}"},
		files={
			"file": (filename, pdf_bytes, "application/pdf"),
			"messaging_product": (None, "whatsapp"),
			"type": (None, "application/pdf"),
		},
		timeout=TIMEOUT,
	)
	if not response.ok:
		frappe.throw(_("WhatsApp upload failed: {0}").format(_meta_error(response)))
	media_id = (response.json() or {}).get("id")
	if not media_id:
		frappe.throw(_("WhatsApp upload returned no media id."))
	return media_id


def send_template(to, media_id, filename, body_params, token, pnid):
	"""Send the document template. Returns Meta's message ID."""
	settings = _settings()
	template = (
		frappe.conf.get("vac_whatsapp_template")
		or (settings.get("template_name") if settings else None)
		or DEFAULT_TEMPLATE
	)
	language = (
		frappe.conf.get("vac_whatsapp_template_lang")
		or (settings.get("template_language") if settings else None)
		or DEFAULT_LANG
	)
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": to,
		"type": "template",
		"template": {
			"name": template,
			"language": {"code": language},
			"components": [
				{
					"type": "header",
					"parameters": [
						{
							"type": "document",
							"document": {"id": media_id, "filename": filename},
						}
					],
				},
				{
					"type": "body",
					"parameters": [{"type": "text", "text": p} for p in body_params],
				},
			],
		},
	}
	response = requests.post(
		_graph(f"{pnid}/messages"),
		headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
		json=payload,
		timeout=TIMEOUT,
	)
	if not response.ok:
		frappe.throw(_("WhatsApp send failed: {0}").format(_meta_error(response)))
	messages = (response.json() or {}).get("messages") or [{}]
	return messages[0].get("id"), template


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------


def _log(**kwargs):
	"""Write a WhatsApp Send Log row. These are GST documents leaving the
	building, so every attempt — including failures — is recorded.

	Never raises: a logging problem must not turn a delivered message into an
	error the user retries (and pays for twice).
	"""
	try:
		doc = frappe.get_doc({"doctype": "WhatsApp Send Log", **kwargs})
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "WhatsApp Send Log write failed")
		return None


def _recent_duplicate(doctype, name, to_number):
	"""True if the same document went to the same number in the last 60s.

	Guards the double-click / double-submit case. Each send costs money and
	arrives as a real notification, so a resend has to be deliberate.
	"""
	return bool(
		frappe.get_all(
			"WhatsApp Send Log",
			filters={
				"reference_doctype": doctype,
				"reference_name": name,
				"to_number": to_number,
				"status": "Sent",
				"creation": [">", frappe.utils.add_to_date(None, seconds=-60)],
			},
			limit=1,
		)
	)


# ---------------------------------------------------------------------------
# whitelisted API
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_target(doctype, name):
	"""Who this document would go to, for the dialog's default.

	Read-only and cheap. Returning the resolved name alongside the number is
	deliberate: it lets the user see *who* they are about to message before they
	send, which is the only practical guard against a wrong linked contact.
	"""
	doc = frappe.get_doc(doctype, name)
	_check_permission(doc)
	party_type, party = resolve_party(doc)
	return {
		"party_type": party_type,
		"party": party,
		"party_name": _party_label(party_type, party),
		"mobile": resolve_mobile(party_type, party, doc),
		"print_formats": _print_formats(doctype),
	}


def _print_formats(doctype):
	"""Print formats available for this doctype, our own ones first."""
	rows = frappe.get_all(
		"Print Format",
		filters={"doc_type": doctype, "disabled": 0},
		fields=["name"],
		order_by="name",
		pluck="name",
	)
	preferred = [r for r in rows if r.startswith("VAC ")]
	return preferred + [r for r in rows if r not in preferred]


@frappe.whitelist(methods=["POST"])
def send(doctype, name, print_format=None, to_number=None):
	"""Render this document and WhatsApp it to the party. Returns the log row.

	`to_number` is optional — omitted, it resolves from the document/party. When
	supplied (the user typed a different number) it is validated the same way; a
	caller cannot bypass normalise() by passing something exotic.
	"""
	token, pnid = _config()
	doc = frappe.get_doc(doctype, name)
	_check_permission(doc)

	party_type, party = resolve_party(doc)
	number = normalise(to_number) if to_number else resolve_mobile(party_type, party, doc)
	if not number:
		frappe.throw(
			_("No valid mobile number for {0}. Add one on the {1} record first.").format(
				_party_label(party_type, party) or name, party_type or doctype
			)
		)

	if _recent_duplicate(doctype, name, number):
		frappe.throw(_("This document was just sent to {0}. Wait a moment before resending.").format(number))

	print_format = print_format or None
	filename = _filename(doc, print_format)
	party_name = _party_label(party_type, party) or (doc.get("title") or name)

	log_args = {
		"reference_doctype": doctype,
		"reference_name": name,
		"party_type": party_type,
		"party": party,
		"party_name": party_name,
		"to_number": number,
		"print_format": print_format or "",
	}

	try:
		pdf = frappe.get_print(doctype, name, print_format=print_format, as_pdf=True)
		media_id = upload_media(pdf, filename, token, pnid)
		message_id, template = send_template(
			number,
			media_id,
			filename,
			[party_name, _doc_label(doc), name, frappe.utils.format_date(_doc_date(doc))],
			token,
			pnid,
		)
	except Exception as exc:
		_log(status="Failed", error=str(exc)[:2000], **log_args)
		raise

	log_name = _log(status="Sent", message_id=message_id, template=template, **log_args)
	return {"ok": True, "to": number, "party_name": party_name, "log": log_name}


def _doc_label(doc):
	"""What to call this document to the recipient. The internal doctype name is
	right often enough ("Sales Invoice"), but a customer should read "Tax
	Invoice", and a Delivery Note that is really a slip should say so."""
	overrides = {
		"Sales Invoice": "Tax Invoice",
		"Purchase Invoice": "Purchase Bill",
		"Payment Entry": "Payment Receipt",
		"Salary Slip": "Salary Slip",
	}
	return overrides.get(doc.doctype, doc.doctype)


def _doc_date(doc):
	for field in ("posting_date", "transaction_date", "date", "start_date"):
		if doc.get(field):
			return doc.get(field)
	return frappe.utils.nowdate()


def _filename(doc, print_format=None):
	"""Recipient-visible filename. Meta shows this in the chat, so it carries the
	document number rather than a random token — unlike the old public-file path,
	an unguessable name buys nothing here because the file is never at a URL."""
	base = f"{doc.name} {_doc_label(doc)}".strip()
	base = re.sub(r"[^\w\- .]", "", base) or doc.name
	return f"{base}.pdf"[:120]
