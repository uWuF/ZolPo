// ZolPo Alpine component. Depends on window.ZP (i18n, translit, api).
//
// Everything is keyed on the *universal store key* `chain_int:store_id`
// (e.g. "1:11" = Shufersal 11, "2:733" = Rami Levy 733). This is what lets the
// same store number live in two chains without colliding.
(function () {
  const { I18N, LANG_CYCLE, LANG_LABELS, translitHe, translateProductName,
          translatePromo, BRAND_MAP, api } = window.ZP;

  // Deal-type filter chips (order = display order). Colors echo the badge tint.
  const DEAL_KINDS = ['one_plus_one', 'x_for_y', 'percent_off', 'fixed_price', 'club', 'other'];
  const KIND_ICON = { one_plus_one: '🎁', x_for_y: '🧺', percent_off: '％',
                      fixed_price: '🏷️', club: '💳', other: '✨' };

  const CHAIN_COLOR = {
    shufersal: '#e11d48',   // rose
    rami_levy: '#2563eb',   // blue
    carrefour: '#0ea5e9',   // sky
    tiv_taam:  '#16a34a',   // green
    dor_alon:  '#f59e0b',   // amber (AM:PM)
    yellow:    '#eab308',   // yellow (Paz)
    osher_ad:  '#84cc16',   // lime
    fresh_market: '#06b6d4',// cyan
    wolt:       '#00c2e8',  // Wolt blue
    city_market:'#6366f1',  // indigo
    keshet:     '#8b5cf6',  // violet
    king_store: '#7c3aed',  // purple
    good_pharm: '#14b8a6',  // teal
    super_pharm:'#ef4444',  // red
    bareket:    '#f97316',  // orange
  };
  const CHAIN_ORDER = ['shufersal', 'rami_levy', 'carrefour', 'tiv_taam', 'dor_alon',
                       'yellow', 'osher_ad', 'fresh_market', 'wolt', 'city_market',
                       'king_store', 'bareket', 'good_pharm', 'super_pharm', 'keshet'];
  const FORMAT_ORDER = ['Sheli (supermarket)', 'Deal (hypermarket)',
                        'Express (convenience)', 'Be (drugstore)'];
  const STORE_KEY = 'zolpo-stores-v2';   // v2: stores universal keys, not bare store_ids

  // Browse tiles: label key + guess_category() values + an inline SVG path
  // (24×24 outline, stroke-based — same style as the header icons).
  const CATS = [
    { key: 'cat_dairy',   cats: 'milk,cheese,egg',
      d: 'M8 2h8M9 2v3.5L6.5 9v11a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2V9L15 5.5V2M6.5 12h11' },
    { key: 'cat_bread',   cats: 'bread',
      d: 'M4 10a3 3 0 0 1 0-6h16a3 3 0 0 1 0 6v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM9 8v6M15 8v6' },
    { key: 'cat_drinks',  cats: 'drink,water,coffee',
      d: 'M6 3h12l-1.5 18h-9zM6.8 9h10.4' },
    { key: 'cat_snacks',  cats: 'snack',
      d: 'M12 3c5 0 8 3.5 8 8s-3 10-8 10-8-5.5-8-10 3-8 8-8zM9 9h.01M14 8h.01M11 13h.01M15 13h.01M10 17h.01' },
    { key: 'cat_produce', cats: 'fruit,vegetable',
      d: 'M12 8c-4 0-7 3-7 7 0 3 2 6 7 6s7-3 7-6c0-4-3-7-7-7zM12 8c0-2 1-4 3-5M12 8c0-2-1-4-3-5' },
    { key: 'cat_meat',    cats: 'meat,chicken,fish',
      d: 'M15 3c3.5 0 6 2.5 6 6s-4 9-9 9c-2 0-3.5-.7-4.6-1.4L4 20l-1-3 3.4-3.4C5.7 12.5 5 11 5 9c0-3.5 4-6 10-6zM14 8h.01' },
    { key: 'cat_pantry',  cats: 'pasta,rice,oil',
      d: 'M5 8h14M6 8l1 13h10l1-13M9 8V5a3 3 0 0 1 6 0v3' },
    { key: 'cat_home',    cats: 'cleaning,hygiene',
      d: 'M9 3h4v3M8 6h6l1 4v10a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V10zM7 13h8' },
  ];

  function zolpo() {
    return {
      query:          '',
      products:       [],
      stores:         [],
      selectedIds:    [],     // universal store keys; filled in loadStores()
      marketsOpen:    false,
      dealsOnly:      false,  // 🏷️ filter: only products with an active promo
      dealKind:       '',     // '' = all kinds; else one of DEAL_KINDS
      activeCat:      '',     // browse-tile category filter (comma list)
      openPromoCode:  null,   // product whose promo panel is expanded
      radar:          [],     // deals radar: top savings in the selected stores
      radarLoading:   true,
      locating:       false,  // "near me" geolocation in flight
      loading:        true,
      cart:           {},
      lang:           localStorage.getItem('zolpo-lang') || 'en',
      enriching:      false,
      enrichProgress: 0,
      lastUpdate:     null,
      meta:           null,   // /api/meta payload (hero stats)

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
        await Promise.all([this.search(), this.loadRadar()]);
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
        // A huge saved selection (e.g. a former "select all" = 189 stores) makes
        // every card render 189 price rows and every search attach 189 price
        // columns — that's the "everything lags" mode. Cap what we restore;
        // the picker itself still allows any manual set.
        const stored = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
        const restored = Array.isArray(stored) ? stored.filter(k => valid.has(k)) : [];
        this.selectedIds = restored.length && restored.length <= 12 ? restored : def;
      },

      async loadMeta() {
        try {
          this.meta = await api.meta();
          this.lastUpdate = this.meta.last_update || null;
        } catch (_) {}
      },

      // ── home / hero ───────────────────────────────────────────────────────
      // Home = hero + radar + browse tiles; any query/filter switches to results.
      homeMode() { return !this.query && !this.dealsOnly && !this.activeCat; },
      heroStats() {
        const m = this.meta || {};
        const fmt = n => (n >= 1000 ? `${Math.round(n / 1000)}K` : `${n || 0}`);
        return [
          { n: `${this.stores.length}`, label: this.t('statStores') },
          { n: `${new Set(this.stores.map(s => s.chain_key)).size}`, label: this.t('statChains') },
          { n: fmt(m.active_promos), label: this.t('statDeals') },
        ];
      },

      async loadRadar() {
        this.radarLoading = true;
        try {
          const data = await api.deals(this.selectedIds, '', 20);
          this.radar = data.results || [];
        } catch (_) { this.radar = []; }
        finally { this.radarLoading = false; }
      },
      savePctLabel(p) { return `-${Math.round((p.save_pct || 0) * 100)}%`; },
      bestPrice(p) {
        const vals = this.visibleStores().map(s => this.effPrice(p, s.key)).filter(v => v != null);
        return vals.length ? Math.min(...vals) : null;
      },
      bestPriceStore(p) {
        const best = this.bestPrice(p);
        return this.visibleStores().find(s => this.effPrice(p, s.key) === best) || null;
      },
      openDeal(p) {
        // Barcode search shows the single product with its full promo panel.
        this.query = p.item_code;
        this.search().then(() => { this.openPromoCode = p.item_code; });
      },

      // ── browse tiles ─────────────────────────────────────────────────────
      catTiles() { return CATS; },
      setCat(cats) {
        this.activeCat = this.activeCat === cats ? '' : cats;
        this.query = '';
        this.search();
      },
      goHome() {
        this.query = ''; this.activeCat = '';
        this.dealsOnly = false; this.dealKind = '';
        this.search();
      },

      // ── near me ──────────────────────────────────────────────────────────
      nearMe() {
        if (!navigator.geolocation || this.locating) return;
        this.locating = true;
        navigator.geolocation.getCurrentPosition(
          pos => { this._applyNearest(pos.coords.latitude, pos.coords.longitude); this.locating = false; },
          () => { this.locating = false; },
          { timeout: 8000, maximumAge: 300000 }
        );
      },
      _applyNearest(lat, lon) {
        // Nearest branch of each chain (flat-earth distance is fine at city scale),
        // keep the 8 closest chains so cards stay readable.
        const withGeo = this.stores.filter(s => s.lat && s.lon);
        const dist = s => {
          const dx = (s.lon - lon) * Math.cos(lat * Math.PI / 180), dy = s.lat - lat;
          return dx * dx + dy * dy;
        };
        const bestPerChain = {};
        for (const s of withGeo) {
          if (!bestPerChain[s.chain_key] || dist(s) < dist(bestPerChain[s.chain_key])) {
            bestPerChain[s.chain_key] = s;
          }
        }
        const nearest = Object.values(bestPerChain)
          .sort((a, b) => dist(a) - dist(b)).slice(0, 8);
        if (nearest.length) {
          this.selectedIds = nearest.map(s => s.key);
          this._persist();
        }
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
        this.openPromoCode = null;
        try {
          const data = await api.search(this.query, this.selectedIds, this.dealsOnly,
                                        this.dealKind, this.activeCat);
          this.products = data.results || [];
        } catch (e) { console.error('search failed', e); this.products = []; }
        finally { this.loading = false; }
      },
      toggleDeals() {
        this.dealsOnly = !this.dealsOnly;
        if (!this.dealsOnly) this.dealKind = '';
        this.search();
      },

      // ── promos ───────────────────────────────────────────────────────────
      // p.promos = { storeKey: [ {text, qty, price, end, kind}, … best-first ] }
      dealKinds() { return DEAL_KINDS; },
      kindIcon(k) { return KIND_ICON[k] || '🏷️'; },
      kindLabel(k) { return this.t('kind_' + k); },
      setDealKind(k) { this.dealKind = this.dealKind === k ? '' : k; this.search(); },

      promoFor(p, key) { return (p.promos || {})[key] || []; },
      // The one-line teaser on the card: cheapest promo among visible stores.
      cardPromo(p) {
        let best = null;
        for (const s of this.visibleStores()) {
          const pr = this.promoFor(p, s.key)[0];
          if (pr && (!best || (pr.price != null && (best.price == null || pr.price < best.price)))) best = pr;
        }
        return best;
      },
      promoCount(p) {
        return this.visibleStores().reduce((n, s) => n + this.promoFor(p, s.key).length, 0);
      },
      // Stores (among the visible ones) that have promos for this product,
      // with their full deal lists — feeds the expandable panel.
      promoStores(p) {
        return this.visibleStores()
          .map(s => ({ store: s, list: this.promoFor(p, s.key) }))
          .filter(e => e.list.length);
      },
      togglePromoPanel(p) {
        this.openPromoCode = this.openPromoCode === p.item_code ? null : p.item_code;
      },
      promoText(pr) {
        if (!pr) return '';
        return this.lang === 'en' ? translatePromo(pr.text || '') : (pr.text || '');
      },
      promoUntilText(pr) {
        if (!pr || !pr.end) return '';
        return `${this.t('promoUntil')} ${pr.end.slice(5).split('-').reverse().join('.')}`;
      },
      promoLabel(pr) {
        if (!pr) return '';
        let txt = this.promoText(pr);
        if (pr.end) txt += ` · ${this.promoUntilText(pr)}`;
        return txt;
      },
      // Meta line under a deal: min quantity / deal price, when published.
      promoMeta(pr) {
        const bits = [];
        if (pr.qty && pr.qty > 1) bits.push(`${this.t('minQty')} ${Math.round(pr.qty)}`);
        if (pr.price != null) bits.push(`₪${pr.price.toFixed(2)}`);
        return bits.join(' · ');
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
      _persist() {
        localStorage.setItem(STORE_KEY, JSON.stringify(this.selectedIds));
        this.search();
        this.loadRadar();
      },
      toggleStore(key) {
        if (this.selectedIds.includes(key)) {
          if (this.selectedIds.length > 1) this.selectedIds = this.selectedIds.filter(k => k !== key);
        } else {
          this.selectedIds = [...this.selectedIds, key];
        }
        this._persist();
      },
      selectFood() {
        // One representative branch per full-range food chain: "compare the
        // chains" without the 90-store render that made everything lag.
        const seen = new Set();
        this.selectedIds = this.stores
          .filter(s => /supermarket|hypermarket/i.test(s.format_en || ''))
          .filter(s => !seen.has(s.chain_key) && seen.add(s.chain_key))
          .map(s => s.key);
        this._persist();
      },
      resetStores() {
        localStorage.removeItem(STORE_KEY);
        this.selectedIds = [];
        this.loadStores().then(() => this.search());
      },

      // ── product / price helpers ──────────────────────────────────────────
      placeholder(category) { return `/api/placeholder/${encodeURIComponent(category || 'default')}.svg`; },
      fmtP(v) { return v == null ? '—' : v.toFixed(2) + ' ₪'; },

      // Regular (shelf) price a store published; null when it isn't in the feed.
      regPrice(p, key) { const v = p.prices[key]; return v == null ? null : v; },
      // One money-promo's per-unit price: fixed_price → price, x_for_y → price/qty
      // (same convention as the deals ranking). Percentage / club / 1+1 carry no
      // absolute number, so they aren't a unit price and return null.
      promoUnitPrice(pr) {
        if (!pr || pr.price == null || pr.price <= 0) return null;
        return pr.price / Math.max(pr.qty || 1, 1);
      },
      // "מעל 100" / "מעל 200" = "when you spend over ₪X": a threshold loss-leader
      // (item for ₪1 above a big basket), never a real per-unit price. Keep it out
      // of the headline number — it still shows, with its terms, in the panel.
      promoConditional(pr) { return /מעל\s*\d/.test((pr && pr.text) || ''); },
      // Cheapest *believable* money-promo unit price for this product in one store.
      // When a shelf price is known, ignore promos outside a 5–90% discount window
      // (same sanity range as the deals radar) so bad source data can't headline a
      // ₪0.50 "price". When no shelf price exists we show the promo as-is — that's
      // exactly the gov-feed gap this feature surfaces.
      storePromoPrice(p, key) {
        const reg = this.regPrice(p, key);
        let best = null;
        for (const pr of this.promoFor(p, key)) {
          if (this.promoConditional(pr)) continue;
          const u = this.promoUnitPrice(pr);
          if (u == null) continue;
          if (reg != null) {
            const off = 1 - u / reg;
            if (off < 0.005 || off > 0.9) continue;
          }
          if (best == null || u < best) best = u;
        }
        return best;
      },
      // What you'd actually pay: the lower of shelf price and any money-promo.
      effPrice(p, key) {
        const vals = [this.regPrice(p, key), this.storePromoPrice(p, key)].filter(v => v != null);
        return vals.length ? Math.min(...vals) : null;
      },
      // Show the struck-through shelf price next to the promo price.
      hasStrike(p, key) {
        const reg = this.regPrice(p, key), promo = this.storePromoPrice(p, key);
        return reg != null && promo != null && promo < reg - 0.001;
      },
      // A promo exists but the store never published a shelf price (e.g. Rami
      // Levy's PriceFull lists ~2.5k items while its PromoFull advertises more) —
      // show the deal price instead of an empty dash.
      promoOnly(p, key) {
        return this.regPrice(p, key) == null && this.storePromoPrice(p, key) != null;
      },

      isCheapest(p, key) {
        const vals = this.visibleStores().map(s => this.effPrice(p, s.key)).filter(v => v != null);
        if (vals.length < 2) return false;
        const e = this.effPrice(p, key);
        return e != null && e === Math.min(...vals);
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
          const price = this.effPrice(product, key);
          const fallback = this.visibleStores().map(s => this.effPrice(product, s.key)).find(v => v != null);
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
