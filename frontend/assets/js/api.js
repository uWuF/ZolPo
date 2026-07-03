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
    enrich: (limit = 40) => getJSON(`/api/enrich?limit=${limit}`, { method: 'POST' }),
  };

  window.ZP = Object.assign(window.ZP || {}, { api });
})();
