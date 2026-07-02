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
    search: (q, storeKeys, deals) => {
      const stores = encodeURIComponent((storeKeys || []).join(','));
      return getJSON(`/api/search?q=${encodeURIComponent(q || '')}&stores=${stores}&deals=${deals ? 1 : 0}`);
    },
    enrich: (limit = 40) => getJSON(`/api/enrich?limit=${limit}`, { method: 'POST' }),
  };

  window.ZP = Object.assign(window.ZP || {}, { api });
})();
