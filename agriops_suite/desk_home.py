import frappe
from frappe.utils import get_url_to_workspace
from frappe.website.utils import build_response


class WorkspaceHomeRedirect:
	"""Send the bare site root to each user's OWN workspace.

	Why this exists rather than a Website Route Redirect row:

	A redirect row is global — one target for every user. A row `/` -> `/desk/vac`
	is what previously pinned all three of us to the VAC workspace no matter what
	`User.default_workspace`, `sequence_id` or roles said. There is no per-user
	redirect in Frappe's settings, so it has to be code.

	And "just delete the row" is not enough, because bare `/` then 404s:
	`frappe.website.utils.get_home_page()` strips the leading slash at utils.py:127
	and *then* the `default_workspace` branch (utils.py:133-136) overrides the value
	with `get_url_to_workspace()`, which re-adds the slash and returns early — so the
	strip never applies to it. `path_resolver.resolve()` hands that `/desk/director`
	to the renderer list as if it were a TEMPLATE path, and no template lives there
	(the desk is only reachable via the hardcoded shortcut at path_resolver.py:34,
	which was already tested against the pre-resolution path). Every user with a
	default workspace therefore gets NotFoundPage. Verified on 16.27.1:
	`TemplatePage("/desk/admin-desk").can_render()` and the stripped form are both false.

	`page_renderer` hooks are tried BEFORE every built-in renderer
	(path_resolver.py:56-70), so this claims `/` first and issues a real 302.
	`before_request` cannot be used for this: `app.py handle_exception()` has no
	`frappe.Redirect` branch, so raising one there returns a 500, not a redirect.
	"""

	def __init__(self, path=None, http_status_code=None):
		self.path = path
		self.http_status_code = http_status_code
		self._target = None

	def can_render(self):
		request = getattr(frappe.local, "request", None)
		if request is None or (request.path or "").strip("/") != "":
			return False

		# Guests must keep falling through, otherwise they never reach the login page.
		user = getattr(frappe.session, "user", None) if frappe.session else None
		if not user or user == "Guest":
			return False

		self._target = get_landing_url()
		return bool(self._target)

	def render(self):
		target = self._target or get_landing_url()
		frappe.flags.redirect_location = target
		return build_response(self.path, "", 302, {"Location": target})


def get_landing_url():
	"""This user's own workspace URL, falling back to the desk.

	Never returns empty for a logged-in user: falling through would land them on
	the NotFoundPage described above.
	"""
	workspace = None
	try:
		workspace = frappe.get_user().load_user().default_workspace
	except Exception:
		frappe.log_error(title="WorkspaceHomeRedirect: could not read default_workspace")

	if workspace:
		try:
			return get_url_to_workspace(workspace["name"], workspace["public"])
		except Exception:
			frappe.log_error(title="WorkspaceHomeRedirect: could not build workspace URL")

	# No default workspace set — hand them the desk and let it pick.
	return "/desk"
