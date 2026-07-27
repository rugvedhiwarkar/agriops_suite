/* Financial Cockpit service worker — offline = last snapshot.
 *
 * Strategy: network-first for both the shell (/fin) and the read-only data
 * GETs, falling back to the last cached copy when the shop wifi drops. The
 * page stamps "as of" from the payload itself, so a stale-served snapshot is
 * visibly stale, never silently wrong. Bump VERSION to invalidate.
 */
var VERSION = "fin-v3";  // bumped: no caching at all where the user cannot be identified
var DATA_PREFIX = "/api/method/agriops_suite.fin_api.";
var CACHEABLE = ["snapshot", "acct", "tree", "bootstrap", "outstanding", "stock_balance"];

// Cache name for THIS user, or null meaning "do not cache, do not serve".
//
// cookieStore is Chromium-only inside a service worker. Where it is absent
// (Safari, Firefox) we cannot tell one principal from another, and the previous
// version fell back to a single shared "anon" bucket — so on a shared counter
// machine the next person to open /fin, logged in or not, could switch on
// airplane mode and be served the complete company snapshot: P&L, balance sheet,
// party-by-party receivables and stock valuation. fin_api._guard() never runs on
// that path because nothing is fetched, and the cache survived logout.
//
// Refusing to cache is the only safe answer where the principal is unknown:
// /fin then simply reports no offline data. An unauthenticated or Guest session
// is likewise never cached.
function userCache() {
	if (!(self.cookieStore && self.cookieStore.get)) return Promise.resolve(null);
	return self.cookieStore.get("user_id").then(function (c) {
		var u = (c && c.value) ? decodeURIComponent(c.value) : "";
		if (!u || u === "Guest") return null;
		return VERSION + ":" + u;
	}).catch(function () { return null; });
}

function offlineResponse() {
	return new Response(
		JSON.stringify({ offline: true }),
		{ status: 503, headers: { "Content-Type": "application/json" } }
	);
}

self.addEventListener("install", function (e) {
	self.skipWaiting();
});

self.addEventListener("activate", function (e) {
	e.waitUntil(
		caches.keys().then(function (keys) {
			return Promise.all(keys.filter(function (k) {
				// drops every fin-v2 bucket too, including the shared "anon" one
				return k.indexOf(VERSION + ":") !== 0;
			}).map(function (k) { return caches.delete(k); }));
		}).then(function () { return self.clients.claim(); })
	);
});

function cacheable(url) {
	var u = new URL(url);
	if (u.pathname === "/fin") return true;
	if (u.pathname.indexOf(DATA_PREFIX) === 0) {
		var method = u.pathname.slice(DATA_PREFIX.length);
		return CACHEABLE.some(function (m) { return method.indexOf(m) === 0; });
	}
	return false;
}

self.addEventListener("fetch", function (e) {
	if (e.request.method !== "GET" || !cacheable(e.request.url)) return;
	e.respondWith(
		fetch(e.request).then(function (resp) {
			if (resp && resp.ok) {
				var copy = resp.clone();
				// tie the write to the event lifetime (was fire-and-forget) and store
				// it ONLY in the current user's cache
				e.waitUntil(userCache().then(function (name) {
					if (!name) return;   // unidentifiable principal -> store nothing
					return caches.open(name).then(function (c) { return c.put(e.request, copy); });
				}));
			}
			return resp;
		}).catch(function () {
			// offline: serve only from THIS user's cache, never a shared one
			return userCache().then(function (name) {
				if (!name) return offlineResponse();
				return caches.open(name).then(function (c) {
					return c.match(e.request).then(function (hit) {
						return hit || offlineResponse();
					});
				});
			});
		})
	);
});
