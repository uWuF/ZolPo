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

  // Browse tiles come from GET /api/cats (Wolt-style: tile key + fine
  // categories + product count + a representative product photo). Labels are
  // i18n keys 'cat_<key>'.

  // Leaflet objects live OUTSIDE Alpine's reactive state on purpose: wrapping a
  // Leaflet map in a reactive Proxy breaks its internals. Module scope is fine —
  // there is only ever one zolpo() component.
  let _map = null, _cluster = null, _markers = {};
  const TA_CENTER = [32.0785, 34.7818];   // Tel Aviv-Yafo

  // ── behavioural events ───────────────────────────────────────────────────
  // Buffered and flushed in small batches to POST /api/events (the backend
  // allowlists types and caps sizes). anon_id identifies the device *before*
  // any signup; at sign-in /api/me/link-anon claims its history for the user.
  const ANON_KEY = 'zolpo-anon-id';
  let _anonId = localStorage.getItem(ANON_KEY);
  if (!_anonId) {
    _anonId = (crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    localStorage.setItem(ANON_KEY, _anonId);
  }
  let _evBuf = [], _evTimer = null, _lastSearchSig = '';
  function _flushEvents() {
    if (_evTimer) { clearTimeout(_evTimer); _evTimer = null; }
    if (!_evBuf.length) return;
    api.events(_anonId, _evBuf.splice(0, 25));
  }
  function track(type, fields) {
    _evBuf.push(Object.assign({ type }, fields || {}));
    if (_evBuf.length >= 20) _flushEvents();
    else if (!_evTimer) _evTimer = setTimeout(_flushEvents, 8000);
  }
  // keepalive fetch survives the tab going away — flush on hide, not unload.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') _flushEvents();
  });

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
      tiles:          [],     // /api/cats browse tiles (key, cats, count, image)
      locating:       false,  // "near me" geolocation in flight
      loading:        true,
      cart:           {},
      lang:           localStorage.getItem('zolpo-lang') || 'en',
      enriching:      false,
      enrichProgress: 0,
      lastUpdate:     null,
      meta:           null,   // /api/meta payload (hero stats)
      user:           null,   // /api/me user when signed in
      authOpen:       false,  // sign-in modal
      authEmail:      '',
      authState:      'idle', // idle / sending / sent / error / expired
      authDevLink:    null,   // dev only (no SMTP): the magic link, shown inline

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
        const locale = { he: 'he-IL', ru: 'ru-RU' }[this.lang] || 'en-GB';
        return d.toLocaleString(locale,
          { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
      },

      // ── product display ──────────────────────────────────────────────────
      // Product names exist only in Hebrew (+ partial English). HE shows the
      // original; every other UI language (EN, RU) gets the English/translit
      // form — for RU users Latin beats an alphabet many olim can't read yet.
      productName(p) {
        if (this.lang === 'he') return p.item_name;
        return p.item_name_en || translateProductName(p.item_name);  // real EN wins; else fallback
      },
      manufacturerName(p) {
        const raw = p.manufacture_name || '';
        if (this.lang === 'he') return raw;
        const exact = BRAND_MAP[raw.trim()];
        return exact !== undefined ? exact : translitHe(raw);
      },

      // ── lifecycle ─────────────────────────────────────────────────────────
      async init() {
        document.documentElement.lang = this.lang;
        await this.loadStores();
        await this.loadMe();   // may replace the selection with the synced one
        // The landing is categories + deals radar, not a product pile — no
        // initial catalog query; products load when the user picks/searches.
        this.loading = false;
        await Promise.all([this.loadRadar(), this.loadCats()]);
        this.loadMeta();
        // Map needs the stores (coords) loaded and its container laid out.
        this.$nextTick(() => this.initMap());
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

      // ── account ───────────────────────────────────────────────────────────
      async loadMe() {
        const flag = new URLSearchParams(location.search).get('signed-in');
        if (flag) history.replaceState(null, '', '/');
        if (flag === 'expired') { this.authOpen = true; this.authState = 'expired'; }
        let res;
        try { res = await api.me(); } catch (_) { return; }
        this.user = res.user || null;
        if (!this.user) return;
        if (flag === '1') {
          // Fresh sign-in on this device: claim its pre-signup events, and
          // record the analytics consent named in the sign-in modal text.
          api.linkAnon(_anonId).catch(() => {});
          if (!(res.consents || {}).analytics) api.consent('analytics', true).catch(() => {});
          this.authOpen = false;
        }
        // Store selection: the synced copy wins when it exists; otherwise this
        // device's local selection seeds the account.
        const valid = new Set(this.stores.map(s => s.key));
        const server = (res.stores || []).filter(k => valid.has(k));
        if (server.length) {
          this.selectedIds = server;
          localStorage.setItem(STORE_KEY, JSON.stringify(server));
        } else if (this.selectedIds.length) {
          api.putStores(this.selectedIds).catch(() => {});
        }
      },
      openAuth() {
        this.authOpen = true; this.authState = 'idle'; this.authDevLink = null;
      },
      async signIn() {
        const email = this.authEmail.trim();
        if (!/^\S+@\S+\.\S+$/.test(email)) { this.authState = 'error'; return; }
        this.authState = 'sending';
        try {
          const res = await api.requestLink(email);
          this.authState = 'sent';
          this.authDevLink = res.dev_link || null;   // local dev: no SMTP
        } catch (_) { this.authState = 'error'; }
      },
      async signOut() {
        try { await api.logout(); } catch (_) {}
        this.user = null;
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
        track('promo_click', { item_code: p.item_code });
        // Barcode search shows the single product with its full promo panel.
        this.query = p.item_code;
        this.search().then(() => { this.openPromoCode = p.item_code; });
      },

      // ── browse tiles ─────────────────────────────────────────────────────
      async loadCats() {
        try { this.tiles = (await api.cats(this.selectedIds)).tiles || []; }
        catch (_) { this.tiles = []; }
      },
      catTiles() { return this.tiles; },
      tileLabel(c) { return this.t('cat_' + c.key); },
      tileImage(c) { return c.image || this.placeholder((c.cats || 'default').split(',')[0]); },
      activeCatLabel() {
        const c = this.tiles.find(t => t.cats === this.activeCat);
        return c ? this.tileLabel(c) : '';
      },
      setCat(cats) {
        this.activeCat = this.activeCat === cats ? '' : cats;
        this.query = '';
        if (this.activeCat) { track('category_open', { props: { cat: cats } }); this.search(); }
        else this.products = [];
      },
      goHome() {
        this.query = ''; this.activeCat = '';
        this.dealsOnly = false; this.dealKind = '';
        this.products = [];   // grid is hidden on the landing; nothing to fetch
        // The map div was display:none while browsing — Leaflet must re-measure.
        this.$nextTick(() => { if (_map) _map.invalidateSize(); });
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
        if (_map) _map.setView([lat, lon], 14);
      },

      // ── store map (Leaflet + clustering) ───────────────────────────────────
      initMap() {
        if (_map || typeof L === 'undefined') return;
        const el = document.getElementById('zp-map');
        if (!el) return;
        _map = L.map(el, { scrollWheelZoom: false, attributionControl: false })
                .setView(TA_CENTER, 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                    { maxZoom: 19 }).addTo(_map);
        _cluster = L.markerClusterGroup({
          maxClusterRadius: 48, showCoverageOnHover: false,
          spiderfyOnMaxZoom: true,
        });
        _markers = {};
        for (const s of this.stores) {
          if (!s.lat || !s.lon) continue;
          const m = L.marker([s.lat, s.lon], { icon: this._pin(s), title: this.storeLabel(s) });
          m.on('click', () => this.openStorePin(s, m));
          _markers[s.key] = m;
          _cluster.addLayer(m);
        }
        _map.addLayer(_cluster);
        // Fixed Tel Aviv view — a few stores are mis-geocoded to the Jerusalem
        // area, so fitBounds would zoom the whole country out. The app is
        // TA-scoped; "Near me" recenters on the user.
        _map.setView(TA_CENTER, 12);
      },
      _pin(s) {
        // A coloured teardrop in the chain's colour — matches the price-row dots.
        const c = this.chainColor(s);
        return L.divIcon({
          className: 'zp-pin', iconSize: [22, 22], iconAnchor: [11, 11],
          html: `<span style="--pin:${c}"></span>`,
        });
      },
      async openStorePin(s, marker) {
        track('map_store_open', { store_key: s.key });
        const head = `<div class="font-bold text-sm leading-tight ${this.lang === 'he' ? 'he' : ''}">`
                   + this._esc(this.storeLabel(s)) + '</div>'
                   + `<div class="text-[11px] text-slate-400 he">${this._esc(s.address || '')}</div>`;
        marker.bindPopup(
          `<div class="zp-pop">${head}<div class="py-3 text-center text-slate-400 text-xs">…</div></div>`,
          { minWidth: 208, maxWidth: 232 }
        ).openPopup();
        let data;
        try { data = await api.storeHighlights(s.key); }
        catch (_) { data = { promos: [], drops: [] }; }
        marker.setPopupContent(`<div class="zp-pop">${head}${this._pinBody(data)}</div>`);
      },
      _pinBody(data) {
        const promos = (data.promos || []).slice(0, 3);
        const drops = (data.drops || []).slice(0, 3);
        if (!promos.length && !drops.length)
          return `<div class="py-2 text-center text-slate-400 text-xs">${this.t('mapNothing')}</div>`;
        const row = (it, tone) => {
          const name = this.lang === 'he'
            ? it.item_name : (it.item_name_en || translateProductName(it.item_name));
          const pct = Math.round((it.save_pct || 0) * 100);
          return `<div class="flex items-center gap-1.5 py-0.5">
              <span class="shrink-0 px-1 rounded text-white text-[10px] font-extrabold" style="background:${tone}">-${pct}%</span>
              <span class="flex-1 min-w-0 truncate text-[11px] ${this.lang === 'he' ? 'he' : ''}">${this._esc(name)}</span>
              <span class="shrink-0 text-[11px] font-semibold">₪${it.now.toFixed(2)}</span>
              <span class="shrink-0 text-[10px] text-slate-400 line-through">₪${it.was.toFixed(2)}</span>
            </div>`;
        };
        let html = '';
        if (promos.length)
          html += `<div class="mt-1.5 mb-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-600">${this.t('mapDeals')}</div>`
                + promos.map(p => row(p, '#009465')).join('');
        if (drops.length)
          html += `<div class="mt-1.5 mb-0.5 text-[10px] font-bold uppercase tracking-wide text-rose-500">${this.t('mapDrops')}</div>`
                + drops.map(d => row(d, '#e11d48')).join('');
        return html;
      },
      _esc(s) {
        return (s || '').replace(/[&<>"]/g, c =>
          ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
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
        // On the landing the grid is hidden — clearing the query/filters just
        // returns home, no catalog fetch needed.
        if (this.homeMode()) { this.products = []; this.openPromoCode = null; this.loading = false; return; }
        this.loading = true;
        this.openPromoCode = null;
        try {
          const data = await api.search(this.query, this.selectedIds, this.dealsOnly,
                                        this.dealKind, this.activeCat);
          this.products = data.results || [];
          // Demand signal: log each distinct query/filter combination once.
          const sig = `${this.query}|${this.activeCat}|${this.dealsOnly}|${this.dealKind}`;
          if (sig !== _lastSearchSig && (this.query.length >= 2 || this.activeCat || this.dealsOnly)) {
            _lastSearchSig = sig;
            track('search', {
              query: this.query || undefined,
              props: { results: this.products.length, cat: this.activeCat || undefined,
                       deals: this.dealsOnly || undefined, kind: this.dealKind || undefined },
            });
          }
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
      // Deal-kind accent dot (chips + expanded panel) — colour, not emoji.
      kindColor(k) {
        return { one_plus_one: '#8b5cf6', x_for_y: '#2563eb', percent_off: '#e11d48',
                 fixed_price: '#00aa76', club: '#d97706', other: '#64748b' }[k] || '#64748b';
      },
      kindLabel(k) { return this.t('kind_' + k); },
      setDealKind(k) { this.dealKind = this.dealKind === k ? '' : k; this.search(); },

      promoFor(p, key) { return (p.promos || {})[key] || []; },
      // Promos only count in stores that actually carry (price) the item — a
      // store advertising a deal it never lists a shelf price for is treated as
      // not stocking it, so it shows neither a deal badge nor a price.
      promoForCarried(p, key) { return this.carries(p, key) ? this.promoFor(p, key) : []; },
      // The one-line teaser on the card: cheapest promo among carrying stores.
      cardPromo(p) {
        let best = null;
        for (const s of this.visibleStores()) {
          const pr = this.promoForCarried(p, s.key)[0];
          if (pr && (!best || (pr.price != null && (best.price == null || pr.price < best.price)))) best = pr;
        }
        return best;
      },
      promoCount(p) {
        return this.visibleStores().reduce((n, s) => n + this.promoForCarried(p, s.key).length, 0);
      },
      // Stores (among the visible ones) that carry the item and have promos,
      // with their full deal lists — feeds the expandable panel.
      promoStores(p) {
        return this.visibleStores()
          .map(s => ({ store: s, list: this.promoForCarried(p, s.key) }))
          .filter(e => e.list.length);
      },
      togglePromoPanel(p) {
        this.openPromoCode = this.openPromoCode === p.item_code ? null : p.item_code;
        if (this.openPromoCode) track('promo_open', { item_code: p.item_code });
      },
      promoText(pr) {
        if (!pr) return '';
        return this.lang === 'he' ? (pr.text || '') : translatePromo(pr.text || '');
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
        if (this.user) api.putStores(this.selectedIds).catch(() => {});   // account sync
        this.search();
        this.loadRadar();
        this.loadCats();
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
        this.loadStores().then(() => { this.search(); this.loadRadar(); this.loadCats(); });
      },

      // ── product / price helpers ──────────────────────────────────────────
      placeholder(category) { return `/api/placeholder/${encodeURIComponent(category || 'default')}.svg`; },
      fmtP(v) { return v == null ? '—' : v.toFixed(2) + ' ₪'; },

      // Regular (shelf) price a store published; null when it isn't in the feed.
      regPrice(p, key) { const v = p.prices[key]; return v == null ? null : v; },
      // A store "carries" the product only if it published a shelf price. A promo
      // with no matching PriceFull row (Rami Levy lists ~2.5k items per store but
      // advertises more promos) can't be verified as stocked/priced, so we treat
      // that store as simply not having the item — no promo price, no badge.
      carries(p, key) { return this.regPrice(p, key) != null; },
      // One money-promo's per-unit price: fixed_price → price, x_for_y → price/qty
      // (this reproduces the feed's own DiscountedPricePerMida). Percentage / club
      // / 1+1 carry no absolute number, so they aren't a unit price → null.
      promoUnitPrice(pr) {
        if (!pr || pr.price == null || pr.price <= 0) return null;
        return pr.price / Math.max(pr.qty || 1, 1);
      },
      // "מעל 100" = "when you spend over ₪X": a threshold loss-leader (item for ₪1
      // above a big basket), never a real per-unit price — keep it off the headline.
      promoConditional(pr) { return /מעל\s*\d/.test((pr && pr.text) || ''); },
      // The best (cheapest, believable) money-promo for this product in a store —
      // only where the store actually carries it. Ignores promos outside a 5–90%
      // discount window (same sanity range as the deals radar) so bad source data
      // can't headline a ₪0.50 "price".
      storeBestPromo(p, key) {
        const reg = this.regPrice(p, key);
        if (reg == null) return null;                 // not carried → no promo price
        let best = null, bestU = null;
        for (const pr of this.promoFor(p, key)) {
          if (this.promoConditional(pr)) continue;
          const u = this.promoUnitPrice(pr);
          if (u == null) continue;
          const off = 1 - u / reg;
          if (off < 0.005 || off > 0.9) continue;
          if (bestU == null || u < bestU) { bestU = u; best = pr; }
        }
        return best;
      },
      storePromoPrice(p, key) {
        const pr = this.storeBestPromo(p, key);
        return pr ? this.promoUnitPrice(pr) : null;
      },
      // A short condition tag shown next to the deal price: multi-buy quantity, or
      // a credit-card / club requirement. Full terms live in the expandable panel.
      promoNote(p, key) {
        const pr = this.storeBestPromo(p, key);
        if (!pr) return '';
        const q = Math.round(pr.qty || 1);
        if (q > 1) return '×' + q;
        const t = pr.text || '';
        if (/אשראי/.test(t)) return this.t('condCredit');
        if (/מועדון|לחברי|מצטרפים/.test(t)) return this.t('condClub');
        return '';
      },
      // What you'd actually pay: the lower of shelf price and any money-promo.
      effPrice(p, key) {
        const vals = [this.regPrice(p, key), this.storePromoPrice(p, key)].filter(v => v != null);
        return vals.length ? Math.min(...vals) : null;
      },

      isCheapest(p, key) {
        const vals = this.visibleStores().map(s => this.effPrice(p, s.key)).filter(v => v != null);
        if (vals.length < 2) return false;
        const e = this.effPrice(p, key);
        return e != null && e === Math.min(...vals);
      },

      // ── basket ───────────────────────────────────────────────────────────
      addToCart(p) {
        track('add_to_cart', { item_code: p.item_code });
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
