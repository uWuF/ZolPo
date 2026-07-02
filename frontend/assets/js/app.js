// ZolPo Alpine component. Depends on window.ZP (i18n, translit, api).
//
// Everything is keyed on the *universal store key* `chain_int:store_id`
// (e.g. "1:11" = Shufersal 11, "2:733" = Rami Levy 733). This is what lets the
// same store number live in two chains without colliding.
(function () {
  const { I18N, LANG_CYCLE, LANG_LABELS, translitHe, translateProductName, BRAND_MAP, api } = window.ZP;

  const CHAIN_COLOR = {
    shufersal: '#e11d48',   // rose
    rami_levy: '#2563eb',   // blue
    carrefour: '#0ea5e9',   // sky
    dor_alon:  '#f59e0b',   // amber (AM:PM)
    yellow:    '#eab308',   // yellow (Paz)
    keshet:     '#8b5cf6',  // violet
    king_store: '#7c3aed',  // purple
    good_pharm: '#14b8a6',  // teal
    bareket:    '#f97316',  // orange
  };
  const CHAIN_ORDER = ['shufersal', 'rami_levy', 'carrefour', 'dor_alon', 'yellow',
                       'king_store', 'bareket', 'good_pharm', 'keshet'];
  const FORMAT_ORDER = ['Sheli (supermarket)', 'Deal (hypermarket)',
                        'Express (convenience)', 'Be (drugstore)'];
  const STORE_KEY = 'zolpo-stores-v2';   // v2: stores universal keys, not bare store_ids

  function zolpo() {
    return {
      query:          '',
      products:       [],
      stores:         [],
      selectedIds:    [],     // universal store keys; filled in loadStores()
      marketsOpen:    false,
      dealsOnly:      false,  // 🏷️ filter: only products with an active promo
      loading:        true,
      cart:           {},
      lang:           localStorage.getItem('zolpo-lang') || 'en',
      enriching:      false,
      enrichProgress: 0,
      lastUpdate:     null,

      // ── i18n ──────────────────────────────────────────────────────────────
      t(key) { return (I18N[this.lang] || I18N.en)[key] || key; },
      langLabel() { return LANG_LABELS[this.lang] || this.lang.toUpperCase(); },
      cycleLang() {
        const i = LANG_CYCLE.indexOf(this.lang);
        this.lang = LANG_CYCLE[(i + 1) % LANG_CYCLE.length];
        localStorage.setItem('zolpo-lang', this.lang);
        document.documentElement.lang = this.lang;
      },
      lastUpdateText() {
        if (!this.lastUpdate) return '';
        const d = new Date(this.lastUpdate.replace(' ', 'T'));
        if (isNaN(d)) return this.lastUpdate;
        return d.toLocaleString(this.lang === 'he' ? 'he-IL' : 'en-GB',
          { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
      },

      // ── product display ──────────────────────────────────────────────────
      productName(p) {
        if (this.lang !== 'en') return p.item_name;
        return p.item_name_en || translateProductName(p.item_name);  // real EN wins; else fallback
      },
      manufacturerName(p) {
        const raw = p.manufacture_name || '';
        if (this.lang !== 'en') return raw;
        const exact = BRAND_MAP[raw.trim()];
        return exact !== undefined ? exact : translitHe(raw);
      },

      // ── lifecycle ─────────────────────────────────────────────────────────
      async init() {
        document.documentElement.lang = this.lang;
        await this.loadStores();
        await this.search();
        this.loadMeta();
        // Open Food Facts auto-enrichment is off: coverage for Israeli barcodes
        // is <1%, so the old loop cost minutes of background requests per visit
        // for almost nothing. Images come from scripts/resolve_images.py and
        // English names from the planned LLM batch; call this._enrichLoop()
        // manually (or POST /api/enrich) if OFF gap-filling is ever wanted.
      },

      async loadStores() {
        try { this.stores = await api.stores(); } catch (_) { this.stores = []; }
        const valid = new Set(this.stores.map(s => s.key));
        // Default = one central branch per chain so the core feature (compare
        // chains) is visible on first load.
        let def = ['1:11', '2:733', '6:085', '3:501'].filter(k => valid.has(k));
        if (def.length < 2) {
          def = this.stores.filter(s => /Sheli|Deal|Rami/.test(s.format_en || ''))
                           .slice(0, 4).map(s => s.key);
        }
        if (def.length === 0) def = this.stores.slice(0, 4).map(s => s.key);

        // Restore a saved selection (dropping stale keys); else use the default.
        const stored = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
        const restored = Array.isArray(stored) ? stored.filter(k => valid.has(k)) : [];
        this.selectedIds = restored.length ? restored : def;
      },

      async loadMeta() {
        try { this.lastUpdate = (await api.meta()).last_update || null; } catch (_) {}
      },

      async _enrichLoop() {
        this.enriching = true; this.enrichProgress = 0;
        let baseline = null;
        for (let i = 0; i < 40; i++) {
          let data;
          try { data = await api.enrich(40); } catch (_) { break; }
          if (baseline === null) baseline = data.remaining + data.checked;
          if (baseline > 0) this.enrichProgress = Math.min(99, Math.round((1 - data.remaining / baseline) * 100));
          if (data.names > 0 || data.images > 0) await this.search();
          if (data.remaining === 0) { this.enrichProgress = 100; break; }
          if (data.rate_limited) await new Promise(r => setTimeout(r, 15000));
        }
        this.enriching = false;
      },

      async search() {
        this.loading = true;
        try {
          const data = await api.search(this.query, this.selectedIds, this.dealsOnly);
          this.products = data.results || [];
        } catch (e) { console.error('search failed', e); this.products = []; }
        finally { this.loading = false; }
      },
      toggleDeals() { this.dealsOnly = !this.dealsOnly; this.search(); },

      // ── promos ───────────────────────────────────────────────────────────
      promoFor(p, key) { return (p.promos || {})[key] || null; },
      // The deal line shown on the card: cheapest active promo among visible stores.
      cardPromo(p) {
        let best = null;
        for (const s of this.visibleStores()) {
          const pr = this.promoFor(p, s.key);
          if (pr && (!best || (pr.price != null && (best.price == null || pr.price < best.price)))) best = pr;
        }
        return best;
      },
      promoLabel(pr) {
        if (!pr) return '';
        let txt = pr.text || '';
        if (pr.end) txt += ` · ${this.t('promoUntil')} ${pr.end.slice(5).split('-').reverse().join('.')}`;
        return txt;
      },

      // ── markets selector ─────────────────────────────────────────────────
      chainColor(s) { return CHAIN_COLOR[s.chain_key] || '#94a3b8'; },
      chainHeader(g) { return this.lang === 'he' ? (g.label_he || g.label_en) : g.label_en; },

      // Grouped by chain, then by format, for the dropdown.
      storeGroups() {
        const byChain = {};
        for (const s of this.stores) (byChain[s.chain_key] = byChain[s.chain_key] || []).push(s);
        return Object.keys(byChain)
          .sort((a, b) => ((CHAIN_ORDER.indexOf(a) + 1) || 99) - ((CHAIN_ORDER.indexOf(b) + 1) || 99))
          .map(ck => {
            const stores = byChain[ck].slice().sort((a, b) =>
              ((FORMAT_ORDER.indexOf(a.format_en) + 1) || 99) - ((FORMAT_ORDER.indexOf(b.format_en) + 1) || 99));
            const sample = stores[0] || {};
            return { chainKey: ck, label_en: sample.chain_en, label_he: sample.chain_he,
                     color: this.chainColor(sample), stores };
          });
      },

      storeLabel(s) {
        return this.lang === 'he' ? (s.label_he || s.store_name) : (s.label_en || s.store_name);
      },

      visibleStores() { return this.stores.filter(s => this.selectedIds.includes(s.key)); },
      isStoreSelected(key) { return this.selectedIds.includes(key); },
      _persist() { localStorage.setItem(STORE_KEY, JSON.stringify(this.selectedIds)); this.search(); },
      toggleStore(key) {
        if (this.selectedIds.includes(key)) {
          if (this.selectedIds.length > 1) this.selectedIds = this.selectedIds.filter(k => k !== key);
        } else {
          this.selectedIds = [...this.selectedIds, key];
        }
        this._persist();
      },
      selectFood() {
        // Full-range food stores only (drops convenience/drugstore formats).
        this.selectedIds = this.stores
          .filter(s => /supermarket|hypermarket/i.test(s.format_en || ''))
          .map(s => s.key);
        this._persist();
      },
      selectAllStores() { this.selectedIds = this.stores.map(s => s.key); this._persist(); },

      // ── product / price helpers ──────────────────────────────────────────
      placeholder(category) { return `/api/placeholder/${encodeURIComponent(category || 'default')}.svg`; },
      isCheapest(p, key) {
        const vals = this.visibleStores().map(s => p.prices[s.key]).filter(v => v != null);
        if (vals.length < 2) return false;
        return p.prices[key] != null && p.prices[key] === Math.min(...vals);
      },

      // ── basket ───────────────────────────────────────────────────────────
      addToCart(p) {
        if (this.cart[p.item_code]) this.cart[p.item_code].qty++;
        else this.cart[p.item_code] = { product: p, qty: 1 };
      },
      qtyOf(code) { return this.cart[code]?.qty || 0; },
      clearCart() { this.cart = {}; },
      get cartCount() { return Object.values(this.cart).reduce((n, e) => n + e.qty, 0); },

      basketTotal(key) {
        let total = 0;
        for (const { product, qty } of Object.values(this.cart)) {
          const price = product.prices[key];
          const fallback = this.visibleStores().map(s => product.prices[s.key]).find(v => v != null);
          total += (price ?? fallback ?? 0) * qty;
        }
        return total;
      },
      cheapestBasket() {
        let best = null, bestTotal = Infinity;
        for (const s of this.visibleStores()) {
          const tot = this.basketTotal(s.key);
          if (tot < bestTotal) { bestTotal = tot; best = s.key; }
        }
        return best;
      },
      cheapestBasketLabel() {
        const s = this.stores.find(s => s.key === this.cheapestBasket());
        return s ? this.storeLabel(s) : '';
      },
      savings() {
        const totals = this.visibleStores().map(s => this.basketTotal(s.key));
        if (totals.length < 2) return 0;
        return Math.max(...totals) - Math.min(...totals);
      },
    };
  }

  window.zolpo = zolpo;
})();
