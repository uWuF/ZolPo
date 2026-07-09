// Thin wrappers around the ZolPo JSON API. Exposes window.ZP.api.
(function () {
  async function getJSON(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    return res.json();
  }

  const api = {
    stores: () => getJSON('/api/stores'),
    meta: () => getJSON('/api/meta'),
    compat: () => getJSON('/api/compat'),
    search: (q, storeKeys, deals, kind, cat) => {
      const stores = encodeURIComponent((storeKeys || []).join(','));
      const k = deals && kind ? `&kind=${encodeURIComponent(kind)}` : '';
      const c = cat ? `&cat=${encodeURIComponent(cat)}` : '';
      return getJSON(`/api/search?q=${encodeURIComponent(q || '')}&stores=${stores}&deals=${deals ? 1 : 0}${k}${c}`);
    },
    deals: (storeKeys, kind, limit = 24) => {
      const stores = encodeURIComponent((storeKeys || []).join(','));
      const k = kind ? `&kind=${encodeURIComponent(kind)}` : '';
      return getJSON(`/api/deals?stores=${stores}&limit=${limit}${k}`);
    },
    cats: (storeKeys) =>
      getJSON(`/api/cats?stores=${encodeURIComponent((storeKeys || []).join(','))}`),
    storeHighlights: (storeKey) =>
      getJSON(`/api/store-highlights?store=${encodeURIComponent(storeKey)}`),
    enrich: (limit = 40) => getJSON(`/api/enrich?limit=${limit}`, { method: 'POST' }),

    // ── accounts (users.db) ──────────────────────────────────────────────
    me: () => getJSON('/api/me'),
    requestLink: (email) => postJSON('/api/auth/request-link', { email }),
    logout: () => getJSON('/api/auth/logout', { method: 'POST' }),
    putStores: (keys) => postJSON('/api/me/stores', { stores: keys }, 'PUT'),
    consent: (kind, granted) => postJSON('/api/me/consents', { kind, granted }),
    linkAnon: (anonId) => postJSON('/api/me/link-anon', { anon_id: anonId }),
    // Fire-and-forget: keepalive lets a batch survive tab close/navigation.
    events: (anonId, events) =>
      fetch('/api/events', {
        method: 'POST', keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anon_id: anonId, events }),
      }).catch(() => {}),
  };

  function postJSON(url, body, method = 'POST') {
    return getJSON(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  window.ZP = Object.assign(window.ZP || {}, { api });
})();
