// ============================================================================
// FinScope add-on (app_include_js):
//   (A) Routing fix (ALL reports, navigation only): sidebar links to a "Custom
//       Report" copy open the real query-report view in-place.
//   (B) Ledger features, SCOPED at runtime to the LedgerX ledger copies only:
//       - persistent column ORDER (drag),
//       - persistent column VISIBILITY (remove a column / multi-select picker),
//       - Summarize-by-any-column + drill-down.
//   Every feature hook re-checks the *current* report name (finscope.on()), so
//   nothing ever activates on the original reports (which share their config).
// ============================================================================
frappe.provide("finscope");

/* ===== (A) sidebar routing fix — navigation only, all reports ===== */
(function () {
	function patchRoute() {
		if (!(frappe.ui && frappe.ui.sidebar_item && frappe.ui.sidebar_item.TypeLink))
			return setTimeout(patchRoute, 200);
		var proto = frappe.ui.sidebar_item.TypeLink.prototype;
		if (proto.__fs_route_patched) return;
		proto.__fs_route_patched = true;
		var orig = proto.get_path;
		proto.get_path = function () {
			try {
				var inEdit = frappe.app && frappe.app.sidebar && frappe.app.sidebar.editor && frappe.app.sidebar.editor.edit_mode;
				if (!inEdit && this.item && this.item.type === "Link" && this.item.link_type === "Report" &&
					this.item.report && this.item.report.report_type === "Custom Report" && this.item.link_to) {
					return frappe.utils.generate_route({ type: "Report", name: this.item.link_to, is_query_report: true, report_ref_doctype: this.item.report.ref_doctype });
				}
			} catch (e) { console.error("FinScope route", e); }
			return orig.apply(this, arguments);
		};
	}
	patchRoute();
	$(document).ready(patchRoute);
})();

/* ===== (B) ledger features — scoped to these report names ONLY ===== */
finscope.FEATURE_REPORTS = {
	"LedgerX - General Ledger": 1,
	"LedgerX - Customer Ledger Summary": 1,
	"LedgerX - Supplier Ledger Summary": 1,
};
finscope.on = function () {
	var r = frappe.query_report;
	return !!(r && r.report_name && finscope.FEATURE_REPORTS[r.report_name]);
};

finscope.rname = () => (frappe.query_report ? frappe.query_report.report_name : "x");
finscope.col_key = () => "finscope_colorder::" + finscope.rname();
finscope.sum_key = () => "finscope_summarize::" + finscope.rname();
finscope.hid_key = () => "finscope_hidden::" + finscope.rname();
finscope.ls_get = (k) => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
finscope.ls_set = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
finscope.get_hidden = () => finscope.ls_get(finscope.hid_key()) || [];
finscope.set_hidden = (a) => finscope.ls_set(finscope.hid_key(), a);
finscope.fields_in_order = (dt) => (dt.getColumns() || []).map((c) => c.fieldname).filter(Boolean);

/* ---- persistent column VISIBILITY: filter report.columns by hidden set ---- */
finscope.apply_hidden = function (report) {
	var full = (report.__fs_cols && report.__fs_cols.length ? report.__fs_cols : report.columns) || [];
	var hidden = finscope.get_hidden();
	report.columns = hidden.length ? full.filter((c) => hidden.indexOf(c.fieldname) < 0) : full.slice();
};

/* ---- persistent column ORDER ---- */
finscope.save_order = function () {
	var r = frappe.query_report;
	if (r && r.datatable) finscope.ls_set(finscope.col_key(), finscope.fields_in_order(r.datatable));
};
finscope.apply_order = async function (report) {
	var dt = report.datatable; if (!dt) return;
	var saved = finscope.ls_get(finscope.col_key()); if (!saved || !saved.length) return;
	var cm = dt.columnmanager; if (!cm || !cm.switchColumn) return;
	var existing = finscope.fields_in_order(dt);
	var target = saved.filter((f) => existing.indexOf(f) >= 0);
	existing.forEach((f) => { if (target.indexOf(f) < 0) target.push(f); });
	if (existing.join(",") === target.join(",")) return;
	report.__fs_applying = true;
	try {
		for (var pos = 0; pos < target.length; pos++) {
			var cur = dt.getColumns().map((c) => c.fieldname);
			var from = cur.indexOf(target[pos]); var to = pos + 1;
			if (from > 0 && from !== to) { cm.switchColumn(to, from); await new Promise((r) => setTimeout(r, 70)); }
		}
	} catch (e) { console.error("FinScope order", e); }
	report.__fs_applying = false;
};
finscope.decorate_options = function (options) {
	try {
		var saved = finscope.ls_get(finscope.col_key());
		if (saved && saved.length && options.columns) {
			var map = {}; options.columns.forEach((c) => (map[c.fieldname] = c));
			var re = [];
			saved.forEach((f) => { if (map[f]) { re.push(map[f]); delete map[f]; } });
			options.columns.forEach((c) => { if (map[c.fieldname]) { re.push(c); delete map[c.fieldname]; } });
			if (re.length === options.columns.length) options.columns = re;
		}
	} catch (e) {}
	options.events = options.events || {};
	var prevSw = options.events.onSwitchColumn;
	options.events.onSwitchColumn = function () {
		if (prevSw) { try { prevSw.apply(this, arguments); } catch (e) {} }
		var r = frappe.query_report; if (r && r.__fs_applying) return;
		setTimeout(finscope.save_order, 80);
	};
	var prevRm = options.events.onRemoveColumn;
	options.events.onRemoveColumn = function (col) {
		if (prevRm) { try { prevRm.apply(this, arguments); } catch (e) {} }
		try {
			var fn = col && col.fieldname;
			if (fn) { var h = finscope.get_hidden(); if (h.indexOf(fn) < 0) { h.push(fn); finscope.set_hidden(h); } }
		} catch (e) {}
	};
	return options;
};

/* ---- summarize + drill-down ---- */
finscope.is_sum_col = function (col) {
	var ft = (col.fieldtype || "").toLowerCase();
	if (["currency", "float", "int", "percent"].indexOf(ft) < 0) return false;
	return !/balance|closing|opening/.test((col.fieldname || "").toLowerCase());
};
finscope.cell = function (row, fn) { var v = row[fn]; return v === undefined || v === null || v === "" ? "(Blank)" : v; };
finscope.pin_kind = function (row, columns) {
	for (var i = 0; i < columns.length; i++) {
		var v = row[columns[i].fieldname];
		if (typeof v !== "string") continue;
		var s = v.trim().replace(/^['"]+/, "").replace(/['"]+$/, "").toLowerCase();
		if (!s) continue;
		if (/^opening\b/.test(s)) return "top";
		if (/^(total|closing|grand total|net total|difference)\b/.test(s)) return "bottom";
		return false;
	}
	return false;
};
finscope.build_groups = function (flat, columns, by1, by2) {
	var c1 = columns.find((c) => c.fieldname === by1);
	if (!c1) return { rows: flat, tree: false };
	var c2 = by2 ? columns.find((c) => c.fieldname === by2) : null;
	var sumCols = columns.filter(finscope.is_sum_col);
	var top = [], bottom = [], mid = [];
	flat.forEach((r) => { var k = finscope.pin_kind(r, columns); if (k === "top") top.push(r); else if (k === "bottom") bottom.push(r); else mid.push(r); });
	function grp(rows, col) { var order = [], map = {}; rows.forEach((r) => { var k = String(finscope.cell(r, col.fieldname)); if (!(k in map)) { map[k] = []; order.push(k); } map[k].push(r); }); return { order, map }; }
	function header(node, parent, indent, lf, key, members) { var h = { _fs_node: node, _fs_parent: parent, indent: indent, __fs_group: 1 }; h[lf] = String(key) + "  (" + members.length + ")"; sumCols.forEach((c) => { h[c.fieldname] = members.reduce((s, m) => s + (parseFloat(m[c.fieldname]) || 0), 0); }); return h; }
	function leaf(m, node, parent, indent) { var d = Object.assign({}, m); d._fs_node = node; d._fs_parent = parent; d.indent = indent; return d; }
	var out = [], pi = 0;
	top.forEach((r) => out.push(leaf(r, "fstop" + pi++, "", 0)));
	var gi = 0, g1 = grp(mid, c1);
	g1.order.forEach((k1) => {
		var members = g1.map[k1]; var gid = "fsg" + gi++;
		out.push(header(gid, "", 0, c1.fieldname, k1, members));
		if (c2) {
			var g2 = grp(members, c2), si = 0;
			g2.order.forEach((k2) => { var subs = g2.map[k2]; var sid = gid + "s" + si++; out.push(header(sid, gid, 1, c2.fieldname, k2, subs)); subs.forEach((m, j) => out.push(leaf(m, sid + "d" + j, sid, 2))); });
		} else { members.forEach((m, j) => out.push(leaf(m, gid + "d" + j, gid, 1))); }
	});
	bottom.forEach((r) => out.push(leaf(r, "fsbot" + pi++, "", 0)));
	return { rows: out, tree: true };
};
finscope.apply_summarize = function (report) {
	var flat = report.__fs_flat; if (!flat) return;
	var sel = finscope.ls_get(finscope.sum_key()) || { by1: "", by2: "" };
	var treeNow = !!sel.by1;
	if (treeNow) {
		var res = finscope.build_groups(flat, report.columns, sel.by1, sel.by2);
		report.data = res.rows; report.tree_report = true;
		report.report_settings.tree = true; report.report_settings.name_field = "_fs_node"; report.report_settings.parent_field = "_fs_parent";
		if (typeof report.report_settings.initial_depth !== "number") report.report_settings.initial_depth = 0;
	} else {
		report.data = flat; report.tree_report = false; report.report_settings.tree = false;
	}
	if (report.__fs_tree_state !== treeNow || treeNow) {
		report.__fs_tree_state = treeNow;
		if (report.datatable) { try { report.$report.empty(); } catch (e) {} report.datatable = null; }
	}
};

/* ---- control bar: Summarize By + Columns multi-select ---- */
finscope.add_control = function (report) {
	if (report.__fs_ctrl || !report.$report) return;
	var visCols = (report.columns || []).filter((c) => c.fieldname && c.label);
	if (!visCols.length) return;
	report.__fs_ctrl = true;
	var sel = finscope.ls_get(finscope.sum_key()) || { by1: "", by2: "" };
	var opts = '<option value="">— none —</option>' + visCols.map((c) => '<option value="' + c.fieldname + '">' + frappe.utils.escape_html(c.label) + "</option>").join("");
	var $bar = $('<div class="finscope-summarize-bar" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:2px 0 10px;">' +
		'<span style="font-weight:600;">Summarize By</span>' +
		'<select class="fs-by1 form-control input-xs" style="width:200px">' + opts + "</select>" +
		'<span class="text-muted">then</span>' +
		'<select class="fs-by2 form-control input-xs" style="width:200px">' + opts + "</select></div>");
	$bar.find(".fs-by1").val(sel.by1 || ""); $bar.find(".fs-by2").val(sel.by2 || "");
	$bar.find("select").on("change", function () {
		finscope.ls_set(finscope.sum_key(), { by1: $bar.find(".fs-by1").val(), by2: $bar.find(".fs-by2").val() });
		report.render_datatable();
	});

	// --- Columns multi-select (show/hide, persisted) ---
	var allCols = (report.__fs_cols && report.__fs_cols.length ? report.__fs_cols : report.columns).filter((c) => c.fieldname && c.label);
	var $colWrap = $('<div style="position:relative;display:inline-block;margin-left:6px;">');
	var $colBtn = $('<button class="btn btn-default btn-xs">Columns ▾</button>');
	var $colMenu = $('<div style="display:none;position:absolute;z-index:1010;top:100%;left:0;background:var(--fg-color,#fff);border:1px solid var(--border-color,#d1d8dd);border-radius:6px;padding:6px;max-height:320px;overflow:auto;min-width:240px;box-shadow:0 4px 14px rgba(0,0,0,.18);"></div>');
	function rebuildMenu() {
		var hidden = finscope.get_hidden();
		$colMenu.empty();
		allCols.forEach(function (c) {
			var $row = $('<label style="display:flex;align-items:center;gap:7px;padding:4px 6px;cursor:pointer;white-space:nowrap;border-radius:4px;"><input type="checkbox" ' + (hidden.indexOf(c.fieldname) < 0 ? "checked" : "") + '><span>' + frappe.utils.escape_html(c.label) + "</span></label>");
			$row.find("input").on("change", function () {
				var h = finscope.get_hidden();
				if (this.checked) h = h.filter((x) => x !== c.fieldname);
				else if (h.indexOf(c.fieldname) < 0) h.push(c.fieldname);
				finscope.set_hidden(h);
				report.render_datatable();
			});
			$colMenu.append($row);
		});
	}
	$colBtn.on("click", function (e) { e.preventDefault(); rebuildMenu(); $colMenu.toggle(); });
	$(document).off("click.fscols").on("click.fscols", function (e) {
		if ($colWrap[0] && !$colWrap[0].contains(e.target)) $colMenu.hide();
	});
	$colWrap.append($colBtn).append($colMenu);
	$bar.append($colWrap);

	$bar.insertBefore(report.$report);
};

finscope.wrap_settings = function (report) {
	var rs = report.report_settings;
	if (!rs || rs.__fs_wrapped) return;
	rs.__fs_wrapped = true;
	var prevGDO = rs.get_datatable_options;
	rs.get_datatable_options = function (options) {
		if (prevGDO) { try { options = prevGDO.call(rs, options) || options; } catch (e) {} }
		return finscope.on() ? finscope.decorate_options(options) : options;
	};
	var prevADR = rs.after_datatable_render;
	rs.after_datatable_render = function (d) {
		if (prevADR) { try { prevADR.call(rs, d); } catch (e) {} }
		if (!finscope.on()) return;
		try { finscope.apply_order(frappe.query_report); } catch (e) {}
		try { finscope.add_control(frappe.query_report); } catch (e) {}
	};
	var prevFmt = rs.formatter;
	rs.formatter = function (value, row, column, data, df) {
		if (finscope.on() && data && data.__fs_group) return "<b>" + df(value, row, column, data) + "</b>";
		if (prevFmt) { try { return prevFmt(value, row, column, data, df); } catch (e) {} }
		return df(value, row, column, data);
	};
};

finscope.init = function () {
	if (finscope.__inited) return;
	if (!(frappe.views && frappe.views.QueryReport)) return setTimeout(finscope.init, 200);
	finscope.__inited = true;
	var proto = frappe.views.QueryReport.prototype;
	var origPrep = proto.prepare_report_data;
	proto.prepare_report_data = function () {
		var ret = origPrep.apply(this, arguments);
		if (this.report_name && finscope.FEATURE_REPORTS[this.report_name]) {
			try { this.__fs_flat = (this.data || []).slice(); this.__fs_cols = (this.columns || []).slice(); } catch (e) {}
		}
		return ret;
	};
	var origRender = proto.render_datatable;
	proto.render_datatable = function () {
		if (this.report_name && finscope.FEATURE_REPORTS[this.report_name]) {
			try { finscope.wrap_settings(this); } catch (e) {}
			try { finscope.apply_hidden(this); } catch (e) {}
			try { finscope.apply_summarize(this); } catch (e) {}
		}
		return origRender.apply(this, arguments);
	};
	console.log("FinScope: routing fix + scoped ledger features (order/visibility/summarize) active");
};
finscope.init();
$(document).ready(finscope.init);
