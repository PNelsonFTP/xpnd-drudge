/* XPND DRUDGE — client UI (live FastAPI + static GitHub Pages) */
(() => {
  "use strict";

  const CFG = Object.assign(
    {
      mode: "live",
      basePath: "/",
      dataUrl: "/api/dashboard",
      csvUrl: "/api/alerts.csv",
      workflowUrl: "",
    },
    window.XPND_CONFIG || {}
  );
  const IS_STATIC = CFG.mode === "static";

  const KEYS = {
    theme: "xpnd-drudge:theme-ft",
    density: "xpnd-drudge:density",
    bookmarks: "xpnd-drudge:bookmarks",
    queue: "xpnd-drudge:queue",
    read: "xpnd-drudge:read",
    mutedSources: "xpnd-drudge:muted:sources",
    mutedTickers: "xpnd-drudge:muted:tickers",
    snapshots: "xpnd-drudge:snapshots",
    lastVisit: "xpnd-drudge:last-visit",
  };

  const NEW_HOURS = 6;
  const STALE_HOURS = 72;
  const STALE_DATA_HOURS = IS_STATIC ? 3 : 6;
  const AUTO_REFRESH_MS = IS_STATIC ? 15 * 60 * 1000 : 10 * 60 * 1000;
  const COLLAPSED_PER_COMPANY = 5;
  const READ_CAP = 3000;

  const state = {
    data: null,
    view: "home",
    search: "",
    sort: "weight",
    sector: "",
    filters: new Set(),
    expanded: new Set(),
    prevVisit: null,
    hoverTimer: null,
    nextRefresh: Date.now() + AUTO_REFRESH_MS,
    loading: false,
  };

  const $ = (id) => document.getElementById(id);
  const el = {
    tagline: $("tagline"),
    search: $("search"),
    sort: $("sort"),
    sector: $("sector"),
    ticker: $("ticker"),
    summary: $("summary"),
    index: $("index-strip"),
    banners: $("banners"),
    status: $("status"),
    skeleton: $("skeleton"),
    home: $("home-view"),
    list: $("list-view"),
    brief: $("daily-brief"),
    trending: $("trending"),
    lead: $("lead-story"),
    latest: $("latest"),
    columns: $("columns"),
    hover: $("hover-card"),
    toasts: $("toasts"),
    mutesModal: $("mutes-modal"),
    mutesBody: $("mutes-body"),
    helpModal: $("help-modal"),
    footerRight: $("footer-right"),
    themeBtn: $("btn-theme"),
    densityBtn: $("btn-density"),
    countdown: $("refresh-countdown"),
    btnBookmarks: $("btn-bookmarks"),
    btnQueue: $("btn-queue"),
  };

  // ---------- storage ----------
  const loadSet = (key) => {
    try {
      const arr = JSON.parse(localStorage.getItem(key) || "[]");
      return new Set(Array.isArray(arr) ? arr : []);
    } catch {
      return new Set();
    }
  };
  const saveSet = (key, set) => {
    try {
      localStorage.setItem(key, JSON.stringify([...set]));
    } catch {
      /* quota */
    }
  };
  const loadObj = (key) => {
    try {
      return JSON.parse(localStorage.getItem(key) || "{}") || {};
    } catch {
      return {};
    }
  };
  const saveObj = (key, obj) => {
    try {
      localStorage.setItem(key, JSON.stringify(obj));
    } catch {
      /* quota */
    }
  };

  const bookmarks = loadSet(KEYS.bookmarks);
  const queue = loadSet(KEYS.queue);
  const readIds = loadSet(KEYS.read);
  const mutedSources = loadSet(KEYS.mutedSources);
  const mutedTickers = loadSet(KEYS.mutedTickers);
  const snapshots = loadObj(KEYS.snapshots);

  function toggleInSet(set, key, storageKey) {
    if (set.has(key)) set.delete(key);
    else set.add(key);
    saveSet(storageKey, set);
  }

  function markRead(id) {
    if (!id || readIds.has(id)) return;
    readIds.add(id);
    if (readIds.size > READ_CAP) {
      const trimmed = [...readIds].slice(-READ_CAP);
      readIds.clear();
      trimmed.forEach((x) => readIds.add(x));
    }
    saveSet(KEYS.read, readIds);
  }

  // ---------- theme / density ----------
  function applyTheme(theme) {
    const t = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    el.themeBtn.textContent = t.toUpperCase();
    localStorage.setItem(KEYS.theme, t);
  }

  function applyDensity(d) {
    const v = d === "compact" ? "compact" : "comfortable";
    document.documentElement.setAttribute("data-density", v);
    el.densityBtn.textContent = v === "compact" ? "comfortable" : "compact";
    el.densityBtn.classList.toggle("on", v === "compact");
    localStorage.setItem(KEYS.density, v);
  }

  applyTheme(localStorage.getItem(KEYS.theme) || "light");
  applyDensity(localStorage.getItem(KEYS.density) || "comfortable");

  // ---------- helpers ----------
  function ageHours(iso) {
    if (!iso) return Infinity;
    const t = new Date(iso).getTime();
    return Number.isNaN(t) ? Infinity : Math.max(0, (Date.now() - t) / 3_600_000);
  }

  function timeAgo(iso) {
    if (!iso) return "";
    const h = ageHours(iso);
    if (h < 1 / 60) return "just now";
    if (h < 1) return `${Math.max(1, Math.floor(h * 60))}m ago`;
    if (h < 24) return `${Math.floor(h)}h ago`;
    if (h < 168) return `${Math.floor(h / 24)}d ago`;
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  const isNew = (iso) => ageHours(iso) <= NEW_HOURS;
  const isStale = (iso) => ageHours(iso) > STALE_HOURS;

  function holdingsSync(data) {
    return (data && data.holdingsSync) || {};
  }

  function holdingsAsOfLabel(data) {
    const sync = holdingsSync(data);
    const raw = sync.asOf || sync.syncedAt;
    if (!raw) return "";
    const d = new Date(raw.length <= 10 ? `${raw}T12:00:00Z` : raw);
    if (Number.isNaN(d.getTime())) return String(raw);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  function formatTickerList(tickers, limit = 8) {
    const list = (tickers || []).filter(Boolean);
    if (!list.length) return "";
    if (list.length <= limit) return list.join(", ");
    return `${list.slice(0, limit).join(", ")} +${list.length - limit} more`;
  }

  function isQuoteOutlier(q) {
    return Boolean(q && (q.outlier || Math.abs(Number(q.changePct) || 0) >= 15));
  }

  function quoteMove(q) {
    if (!q || isQuoteOutlier(q)) return 0;
    return Math.abs(Number(q.changePct) || 0);
  }

  function quotePctHTML(q, kind) {
    if (!q) return "";
    if (isQuoteOutlier(q)) {
      return kind === "ticker"
        ? `<span class="ticker-flat" title="Split or bad prior close — excluded from day move">quote check</span>`
        : `<span title="Split or bad prior close — excluded from day move">quote check</span>`;
    }
    const up = q.changePct >= 0;
    const cls = kind === "ticker" ? (up ? "ticker-up" : "ticker-down") : "";
    const body = `${up ? "▲" : "▼"}${Math.abs(q.changePct).toFixed(2)}%`;
    return cls ? `<span class="${cls}">${body}</span>` : body;
  }

  function taglineText(data) {
    const asOf = holdingsAsOfLabel(data);
    const asOfBit = asOf ? ` · holdings ${asOf}` : "";
    return `expanded technology etf · ${data.company_count} holdings${asOfBit} · updated ${timeAgo(data.generatedAt)}`;
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

  function toast(msg) {
    const node = document.createElement("div");
    node.className = "toast";
    node.textContent = msg;
    el.toasts.appendChild(node);
    setTimeout(() => node.remove(), 2600);
  }

  function severityClass(a) {
    if (a.severity === "severe") return "severe";
    if (a.severity === "elevated") return "elevated";
    if (a.severity === "watch") return "watch";
    return "";
  }

  // ---------- article index ----------
  function allArticles(data) {
    const out = [];
    for (const c of data?.companies || []) {
      for (const a of c.articles || []) {
        out.push({
          ...a,
          ticker: a.ticker || c.ticker,
          company_name: c.company_name,
          classification: c.classification,
          weighting: c.weighting,
        });
      }
    }
    return out;
  }

  function syncSnapshots() {
    const keep = new Set([...bookmarks, ...queue]);
    const byId = new Map(allArticles(state.data).map((a) => [a.id, a]));
    for (const id of keep) {
      const live = byId.get(id);
      if (live) snapshots[id] = live;
    }
    for (const id of Object.keys(snapshots)) {
      if (!keep.has(id)) delete snapshots[id];
    }
    saveObj(KEYS.snapshots, snapshots);
  }

  function savedArticles(ids) {
    const live = new Map(allArticles(state.data).map((a) => [a.id, a]));
    const out = [];
    for (const id of ids) {
      const a = live.get(id) || snapshots[id];
      if (a) out.push(a);
    }
    out.sort((a, b) => (b.published || "").localeCompare(a.published || ""));
    return out;
  }

  // ---------- URL state ----------
  function writeHash() {
    const p = new URLSearchParams();
    if (state.view !== "home") p.set("v", state.view);
    if (state.search.trim()) p.set("q", state.search.trim());
    if (state.sort !== "weight") p.set("sort", state.sort);
    if (state.sector) p.set("sec", state.sector);
    if (state.filters.size) p.set("f", [...state.filters].join(","));
    const hash = p.toString();
    const next = hash ? `#${hash}` : "";
    if (next !== window.location.hash) {
      history.replaceState(null, "", window.location.pathname + next);
    }
  }

  function readHash() {
    const raw = window.location.hash.replace(/^#/, "");
    if (!raw) return;
    const p = new URLSearchParams(raw);
    const v = p.get("v");
    if (v === "bookmarks" || v === "queue") state.view = v;
    state.search = p.get("q") || "";
    const sort = p.get("sort");
    if (sort) state.sort = sort;
    state.sector = p.get("sec") || "";
    const f = p.get("f");
    if (f) f.split(",").filter(Boolean).forEach((x) => state.filters.add(x));
  }

  function syncControls() {
    el.search.value = state.search;
    el.sort.value = state.sort;
    el.sector.value = state.sector;
    document.querySelectorAll(".chip[data-filter]").forEach((chip) => {
      chip.classList.toggle("on", state.filters.has(chip.dataset.filter));
      chip.setAttribute("aria-pressed", state.filters.has(chip.dataset.filter));
    });
  }

  // ---------- filtering ----------
  function matchesSearch(a, company) {
    const q = state.search.trim().toLowerCase();
    if (!q) return true;
    return [a.title, a.source, a.ticker || company?.ticker, company?.company_name, company?.classification]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q);
  }

  function passesFilters(a) {
    if (state.filters.has("neg") && !a.negative) return false;
    if (state.filters.has("24h") && ageHours(a.published) > 24) return false;
    if (state.filters.has("unread") && readIds.has(a.id)) return false;
    return true;
  }

  function filteredCompanies(data) {
    const list = (data.companies || [])
      .filter((c) => !mutedTickers.has(c.ticker))
      .filter((c) => !state.sector || c.classification === state.sector)
      .map((c) => ({
        ...c,
        articles: (c.articles || []).filter(
          (a) => !mutedSources.has(a.source || "") && matchesSearch(a, c) && passesFilters(a)
        ),
      }));

    const narrowing = state.search.trim() || state.filters.size > 0;
    const visible = narrowing ? list.filter((c) => c.articles.length > 0) : list;

    const quotes = data.stocks || {};
    const sorters = {
      weight: (a, b) => b.weighting - a.weighting,
      alpha: (a, b) => a.ticker.localeCompare(b.ticker),
      recent: (a, b) => (b.articles[0]?.published || "").localeCompare(a.articles[0]?.published || ""),
      negative: (a, b) =>
        b.negative_count - a.negative_count ||
        Math.max(0, ...b.articles.map((x) => x.negative_score || 0)) -
          Math.max(0, ...a.articles.map((x) => x.negative_score || 0)) ||
        b.weighting - a.weighting,
      move: (a, b) =>
        quoteMove(quotes[b.ticker]) - quoteMove(quotes[a.ticker]),
    };
    return [...visible].sort(sorters[state.sort] || sorters.weight);
  }

  // ---------- render ----------
  function updateCounts() {
    document.querySelector('[data-count="bookmarks"]').textContent = bookmarks.size;
    document.querySelector('[data-count="queue"]').textContent = queue.size;
    document.querySelector('[data-count="mutes"]').textContent =
      mutedSources.size + mutedTickers.size;
    el.btnBookmarks.classList.toggle("active", state.view === "bookmarks");
    el.btnQueue.classList.toggle("active", state.view === "queue");
  }

  function renderTicker(data) {
    const entries = Object.entries(data.stocks || {});
    if (!entries.length) {
      el.ticker.hidden = true;
      return;
    }
    const negByTicker = new Map(
      (data.companies || []).map((c) => [c.ticker, c.negative_count])
    );
    el.ticker.hidden = false;
    el.ticker.innerHTML = entries
      .map(([sym, q]) => {
        const neg = (negByTicker.get(sym) || 0) > 0;
        return `<a class="ticker-item${neg ? " has-neg" : ""}" href="#${esc(sym)}" data-jump="${esc(sym)}" title="${neg ? "has negative headlines" : ""}">
          <span class="ticker-sym">${esc(sym)}</span>
          <span>$${Number(q.price).toFixed(2)}</span>
          ${quotePctHTML(q, "ticker")}
        </a>`;
      })
      .join("");
  }

  function renderSummary(data) {
    const p = data.portfolio || {};
    const wc = Number(p.weightedChangePct || 0);
    el.summary.hidden = false;
    el.summary.innerHTML = `
      <span class="summary-item ${wc >= 0 ? "up" : "down"}">weighted day move <strong>${wc >= 0 ? "+" : ""}${wc.toFixed(2)}%</strong></span>
      <span class="summary-item up">gainers <strong>${p.gainers ?? 0}</strong></span>
      <span class="summary-item down">losers <strong>${p.losers ?? 0}</strong></span>
      ${p.quoteOutliers ? `<span class="summary-item">quote check <strong>${p.quoteOutliers}</strong></span>` : ""}
      <span class="summary-item risk">negative headlines <strong>${data.negative_total}</strong></span>
      ${data.severe_total ? `<span class="summary-item risk">severe <strong>${data.severe_total}</strong></span>` : ""}
      <span class="summary-item">headlines <strong>${data.headline_count}</strong> across <strong>${data.company_count}</strong> holdings</span>
      ${holdingsAsOfLabel(data) ? `<span class="summary-item">holdings as of <strong>${esc(holdingsAsOfLabel(data))}</strong></span>` : ""}`;
  }

  function renderIndex(companies, data) {
    if (!companies.length) {
      el.index.hidden = true;
      return;
    }
    el.index.hidden = false;
    el.index.innerHTML = companies
      .map((c) => {
        const sev = c.max_severity === "severe" ? "severe" : c.negative_count ? "neg" : "";
        return `<a class="index-chip ${sev}" href="#${esc(c.ticker)}" data-jump="${esc(c.ticker)}">${esc(c.ticker)}${c.negative_count ? ` ${c.negative_count}` : ""}</a>`;
      })
      .join("");
  }

  function renderBanners(data) {
    const parts = [];
    if (data.generatedAt && ageHours(data.generatedAt) > STALE_DATA_HOURS) {
      const action = IS_STATIC
        ? CFG.workflowUrl
          ? `<a class="tool-btn" href="${esc(CFG.workflowUrl)}" target="_blank" rel="noopener">Run hourly refresh</a>`
          : ""
        : `<button type="button" data-action="refresh">Refresh now</button>`;
      parts.push(
        `<div class="banner">Headlines may be delayed — last ${IS_STATIC ? "published snapshot" : "refresh"} was over ${STALE_DATA_HOURS} hours ago.
          ${action}</div>`
      );
    }
    const sync = holdingsSync(data);
    if (sync.rebalanceDetected && ((sync.added || []).length || (sync.removed || []).length)) {
      const added = formatTickerList(sync.added);
      const removed = formatTickerList(sync.removed);
      const asOf = holdingsAsOfLabel(data);
      parts.push(
        `<div class="banner holdings">
          <span>XPND reconstitution detected${asOf ? ` · official holdings as of <strong>${esc(asOf)}</strong>` : ""}.
          ${added ? ` Added <strong>${esc(added)}</strong>.` : ""}
          ${removed ? ` Dropped <strong>${esc(removed)}</strong>.` : ""}
          News now follows the official First Trust universe.</span>
        </div>`
      );
    }
    if (state.prevVisit != null) {
      const fresh = allArticles(data).filter(
        (a) => a.published && new Date(a.published).getTime() > state.prevVisit
      );
      if (fresh.length) {
        const neg = fresh.filter((a) => a.negative).length;
        parts.push(
          `<div class="banner info" id="new-banner">
            <span><strong>${fresh.length}</strong> new ${fresh.length === 1 ? "story" : "stories"} since your last visit${neg ? ` · <strong class="siren">${neg} negative</strong>` : ""}.</span>
            <button type="button" data-action="dismiss-new" aria-label="Dismiss">✕</button>
          </div>`
        );
      }
    }
    el.banners.innerHTML = parts.join("");
  }

  function badgesHTML(a) {
    const sev = a.severity === "severe";
    return `${isNew(a.published) && !a.low_value ? '<span class="new-badge">NEW</span>' : ""}
      ${a.negative && !a.low_value ? `<span class="neg-badge${sev ? " severe" : ""}">${sev ? "SEVERE" : "NEG"}</span>` : ""}
      ${a.low_value ? '<span class="filing-badge">FILING</span>' : ""}
      ${a.related_count ? `<span class="src-badge">+${a.related_count} src</span>` : ""}`;
  }

  function headlineHTML(a, opts = {}) {
    const cls = a.low_value ? "" : severityClass(a);
    const read = readIds.has(a.id) ? " read" : "";
    return `<article class="headline${isStale(a.published) ? " stale" : ""}${read}${a.low_value ? " lowval" : ""}" data-id="${esc(a.id)}" data-ticker="${esc(a.ticker || "")}" data-source="${esc(a.source || "")}">
      <div class="hl-actions">
        <button type="button" class="${bookmarks.has(a.id) ? "on-star" : ""}" data-action="bookmark" aria-label="Bookmark">${bookmarks.has(a.id) ? "★" : "☆"}</button>
        <button type="button" class="${queue.has(a.id) ? "on-queue" : ""}" data-action="queue" aria-label="Read later">⏷</button>
      </div>
      <div class="hl-body">
        <a class="hl-title ${cls}" href="${esc(safeUrl(a.link))}" target="_blank" rel="noopener noreferrer nofollow" data-action="open">${esc(a.title)}</a>
        ${badgesHTML(a)}
        ${opts.tickerChip ? `<span class="source-badge tickerchip">${esc(a.ticker)}</span>` : ""}
        <div class="hl-meta">
          ${a.source ? `<span class="source-badge">${esc(a.source)}</span>` : ""}
          <span>${esc(timeAgo(a.published))}</span>
          ${a.source ? '<button type="button" class="mute-btn" data-action="mute-source">mute source</button>' : ""}
        </div>
      </div>
    </article>`;
  }

  function renderBrief(brief) {
    if (!brief) {
      el.brief.hidden = true;
      return;
    }
    el.brief.hidden = false;
    el.brief.innerHTML = `
      <header class="section-head">
        <h2 class="section-title">Daily Brief</h2>
        <span class="section-meta">${esc(brief.source === "llm" ? "AI summary" : "curated")}</span>
      </header>
      <div class="brief-headline">${esc(brief.headline)}</div>
      <ul class="brief-bullets">${(brief.bullets || []).map((b) => `<li>${esc(b)}</li>`).join("")}</ul>`;
  }

  function renderTrending(items) {
    const q = state.search.trim().toLowerCase();
    const list = (items || []).filter((t) => {
      if (mutedTickers.has(t.ticker)) return false;
      if (state.filters.has("24h") && ageHours(t.published) > 24) return false;
      if (!q) return true;
      return `${t.title} ${t.ticker}`.toLowerCase().includes(q);
    });
    if (!list.length) {
      el.trending.hidden = true;
      return;
    }
    el.trending.hidden = false;
    el.trending.innerHTML = `
      <header class="section-head">
        <h2 class="section-title">Risk Radar</h2>
        <span class="section-meta">${list.length} negative headlines · newest first</span>
      </header>
      <ol class="trending-list">
        ${list
          .map(
            (t, i) => `<li>
            <span class="trending-num">${i + 1}</span>
            <div>
              <a class="hl-title ${t.severity === "severe" ? "severe" : "elevated"}" href="${esc(safeUrl(t.primaryUrl))}" target="_blank" rel="noopener noreferrer">${esc(t.title)}</a>
              <span class="neg-badge${t.severity === "severe" ? " severe" : ""}">${t.severity === "severe" ? "SEVERE" : "NEG"}</span>
              <a class="source-badge tickerchip" href="#${esc(t.ticker)}" data-jump="${esc(t.ticker)}">${esc(t.ticker)}</a>
              <span class="section-meta">${esc(timeAgo(t.published))}</span>
            </div>
          </li>`
          )
          .join("")}
      </ol>`;
  }

  function renderLead(lead) {
    if (!lead || mutedTickers.has(lead.ticker) || !matchesSearch(lead, lead) || !passesFilters(lead)) {
      el.lead.hidden = true;
      return;
    }
    el.lead.hidden = false;
    const related = lead.related || [];
    el.lead.innerHTML = `
      <header class="section-head">
        <h2 class="section-title">Lead Story</h2>
        <span class="section-meta">highest-impact recent headline</span>
      </header>
      <h3 class="lead-title${lead.negative ? " neg" : ""}"><a href="${esc(safeUrl(lead.link))}" target="_blank" rel="noopener noreferrer">${esc(lead.title)}</a></h3>
      <div class="hl-meta">
        <a class="source-badge tickerchip" href="#${esc(lead.ticker)}" data-jump="${esc(lead.ticker)}">${esc(lead.ticker)}</a>
        ${lead.source ? `<span class="source-badge">${esc(lead.source)}</span>` : ""}
        <span>${esc(timeAgo(lead.published))}</span>
        ${lead.negative ? `<span class="neg-badge${lead.severity === "severe" ? " severe" : ""}">${lead.severity === "severe" ? "SEVERE" : "NEG"}</span>` : ""}
      </div>
      ${lead.snippet ? `<p class="lead-snippet">${esc(lead.snippet)}</p>` : ""}
      ${
        related.length
          ? `<div class="also-covered">Also covered by: ${related
              .slice(0, 5)
              .map((r) => `<a href="${esc(safeUrl(r.link))}" target="_blank" rel="noopener noreferrer">${esc(r.source)}</a>`)
              .join(", ")}</div>`
          : ""
      }`;
  }

  function dayLabel(iso) {
    if (!iso) return "EARLIER";
    const d = new Date(iso);
    const today = new Date();
    const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    if (d >= startOfToday) return "TODAY";
    const yest = new Date(startOfToday.getTime() - 86400000);
    if (d >= yest) return "YESTERDAY";
    return d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }).toUpperCase();
  }

  function renderLatest(items) {
    const q = state.search.trim().toLowerCase();
    const list = (items || [])
      .filter((a) => !mutedTickers.has(a.ticker) && !mutedSources.has(a.source || ""))
      .filter((a) => passesFilters(a))
      .filter((a) => (!q ? true : `${a.title} ${a.source} ${a.ticker}`.toLowerCase().includes(q)))
      .slice(0, 14);
    if (!list.length) {
      el.latest.hidden = true;
      return;
    }
    el.latest.hidden = false;
    let lastDay = null;
    const rows = list
      .map((a) => {
        const day = dayLabel(a.published);
        const divider = day !== lastDay ? `<li class="day-divider">${esc(day)}</li>` : "";
        lastDay = day;
        return `${divider}<li>
          <span class="latest-ago">${esc(timeAgo(a.published))}</span>
          <span>
            <a href="${esc(safeUrl(a.link))}" target="_blank" rel="noopener noreferrer" class="hl-title ${severityClass(a)}${readIds.has(a.id) ? " read" : ""}" data-id="${esc(a.id)}" data-action="open-latest">${esc(a.title)}</a>
            ${isNew(a.published) ? '<span class="new-badge">NEW</span>' : ""}
            <a class="source-badge tickerchip" href="#${esc(a.ticker)}" data-jump="${esc(a.ticker)}">${esc(a.ticker)}</a>
          </span>
        </li>`;
      })
      .join("");
    el.latest.innerHTML = `
      <header class="section-head">
        <h2 class="section-title">Latest</h2>
        <span class="section-meta">reverse-chronological across the book</span>
      </header>
      <ul class="latest-list">${rows}</ul>`;
  }

  function renderColumns(companies, data) {
    const quotes = data.stocks || {};
    const cols = [[], [], []];
    companies.forEach((c, i) => cols[i % 3].push(c));
    el.columns.innerHTML = cols
      .map(
        (col) => `<div class="col">${col
          .map((c) => {
            const arts = c.articles || [];
            const expanded = state.expanded.has(c.ticker);
            const shown = expanded ? arts : arts.slice(0, COLLAPSED_PER_COMPANY);
            const hiddenCount = arts.length - shown.length;
            const q = quotes[c.ticker];
            const sev = c.max_severity === "severe";
            return `<section class="company${c.negative_count ? " has-neg" : ""}" id="${esc(c.ticker)}" data-ticker="${esc(c.ticker)}">
              <div class="company-head">
                <span class="company-ticker">${esc(c.ticker)}</span>
                ${
                  q
                    ? `<span class="company-quote ${isQuoteOutlier(q) ? "" : q.changePct >= 0 ? "up" : "down"}">${quotePctHTML(q)} $${Number(q.price).toFixed(2)}</span>`
                    : ""
                }
                ${c.negative_count ? `<span class="badge-neg${sev ? " severe" : ""}">${c.negative_count} ${sev ? "SEVERE" : "NEG"}</span>` : ""}
                <button type="button" class="mute-btn" data-action="mute-ticker" data-ticker="${esc(c.ticker)}">hide</button>
                <span class="company-weight">${Number(c.weighting).toFixed(2)}%</span>
              </div>
              <p class="company-sector">${esc(c.company_name)} · ${esc(c.classification || "")}</p>
              ${
                shown.length
                  ? shown.map((a) => headlineHTML({ ...a, ticker: c.ticker })).join("")
                  : '<p class="empty">No headlines match the current filters.</p>'
              }
              ${
                hiddenCount > 0
                  ? `<button type="button" class="show-more" data-action="expand" data-ticker="${esc(c.ticker)}">+ ${hiddenCount} more</button>`
                  : expanded && arts.length > COLLAPSED_PER_COMPANY
                    ? `<button type="button" class="show-more" data-action="collapse" data-ticker="${esc(c.ticker)}">− show less</button>`
                    : ""
              }
            </section>`;
          })
          .join("")}</div>`
      )
      .join("");
  }

  function renderListView() {
    const isBookmarks = state.view === "bookmarks";
    const articles = savedArticles(isBookmarks ? bookmarks : queue).filter(
      (a) => !mutedSources.has(a.source || "") && !mutedTickers.has(a.ticker || "")
    );
    el.list.innerHTML = `
      <div class="list-view-wrap">
        <header class="section-head">
          <h2 class="section-title">${isBookmarks ? "Bookmarks" : "Read Later"} (${articles.length})</h2>
          <span class="section-meta">saved locally in this browser</span>
        </header>
        <p class="list-sub">${
          isBookmarks
            ? "Saved permanently. Click ★ again to remove."
            : "Opening a headline clears it from the queue."
        }</p>
        ${
          articles.length
            ? articles.map((a) => headlineHTML(a, { tickerChip: true })).join("")
            : `<p class="empty">${
                isBookmarks
                  ? "No bookmarks yet — click ☆ next to any headline."
                  : "Queue empty — click ⏷ next to any headline."
              }</p>`
        }
      </div>`;
  }

  function render() {
    updateCounts();
    syncControls();
    writeHash();
    const data = state.data;
    if (!data) return;

    el.tagline.textContent = taglineText(data);
    el.footerRight.textContent = IS_STATIC
      ? `static snapshot ${new Date(data.generatedAt).toLocaleString()} · hourly GitHub Actions`
      : `built ${new Date(data.generatedAt).toLocaleString()} · news cached 15m · quotes 10m`;

    renderTicker(data);
    renderSummary(data);
    renderBanners(data);

    if (state.view === "home") {
      el.home.hidden = false;
      el.list.hidden = true;
      const companies = filteredCompanies(data);
      renderIndex(companies, data);
      renderBrief(data.brief);
      renderLead(data.lead);
      renderLatest(data.latest);
      renderTrending(data.trending);
      if (!companies.length) {
        el.columns.innerHTML = `<p class="empty" style="grid-column:1/-1;text-align:center;padding:40px">
          ${
            state.search || state.filters.size || state.sector
              ? "Nothing matches the current search or filters."
              : "All sections hidden — open ✕ to restore mutes."
          }</p>`;
      } else {
        renderColumns(companies, data);
      }
    } else {
      el.home.hidden = true;
      el.list.hidden = false;
      el.index.hidden = true;
      renderListView();
    }
  }

  // ---------- hover card ----------
  const hideHover = () => {
    el.hover.hidden = true;
    el.hover.innerHTML = "";
  };
  const scheduleHideHover = () => {
    clearTimeout(state.hoverTimer);
    state.hoverTimer = setTimeout(hideHover, 250);
  };
  const cancelHideHover = () => clearTimeout(state.hoverTimer);

  function showHover(a, rect) {
    cancelHideHover();
    el.hover.hidden = false;
    el.hover.style.top = `${Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 230))}px`;
    el.hover.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 360))}px`;
    const related = a.related || [];
    el.hover.innerHTML = `
      <div class="hl-meta">
        ${a.ticker ? `<span class="source-badge tickerchip">${esc(a.ticker)}</span>` : ""}
        ${a.source ? `<span class="source-badge">${esc(a.source)}</span>` : ""}
        <span>${esc(timeAgo(a.published))}</span>
        ${a.negative ? `<span class="neg-badge${a.severity === "severe" ? " severe" : ""}">${a.severity === "severe" ? "SEVERE" : "NEG"}</span>` : ""}
      </div>
      <h4>${esc(a.title)}</h4>
      <p>${esc(a.company_name || "")}${a.weighting != null ? ` · ${Number(a.weighting).toFixed(2)}% of XPND` : ""}</p>
      ${related.length ? `<p class="also-covered">Also: ${related.slice(0, 4).map((r) => esc(r.source)).join(", ")}</p>` : ""}
      <a class="read-link" href="${esc(safeUrl(a.link))}" target="_blank" rel="noopener noreferrer">Read article →</a>`;
  }

  function articleFromRow(row) {
    const id = row.dataset.id;
    return (
      allArticles(state.data).find((a) => a.id === id) ||
      snapshots[id] || {
        id,
        title: row.querySelector(".hl-title")?.textContent || "",
        link: row.querySelector("a.hl-title")?.href || "#",
        source: row.dataset.source || "",
        ticker: row.dataset.ticker || "",
        published: null,
      }
    );
  }

  // ---------- digest / export ----------
  function buildDigest() {
    const data = state.data;
    if (!data) return "";
    const lines = [
      `XPND RISK DIGEST — ${new Date().toLocaleString()}`,
      `${data.negative_total} negative headlines across ${data.company_count} holdings · weighted day move ${(data.portfolio?.weightedChangePct ?? 0).toFixed(2)}%`,
      "",
    ];
    const byTicker = new Map();
    for (const a of data.alerts || []) {
      if (!byTicker.has(a.ticker)) byTicker.set(a.ticker, []);
      byTicker.get(a.ticker).push(a);
    }
    if (!byTicker.size) lines.push("No negative headlines in the latest pull.");
    for (const [ticker, items] of byTicker) {
      lines.push(`${ticker} — ${items[0].company_name}`);
      for (const a of items) {
        lines.push(`  • [${(a.severity || "watch").toUpperCase()}] ${a.title} (${a.source || "unknown"}, ${timeAgo(a.published)})`);
        lines.push(`    ${a.link}`);
      }
      lines.push("");
    }
    return lines.join("\n");
  }

  async function copyDigest() {
    const text = buildDigest();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast("Risk digest copied to clipboard");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast("Risk digest copied");
    }
  }

  // ---------- mutes modal ----------
  function openMutes() {
    const src = [...mutedSources].sort();
    const tickers = [...mutedTickers].sort();
    const group = (title, items, attr) => `
      <div class="mute-group">
        <h3>${title} (${items.length})</h3>
        ${
          items.length
            ? items
                .map(
                  (v) => `<div class="mute-row"><span>${esc(v)}</span>
                  <button type="button" class="tool-btn" data-${attr}="${esc(v)}">restore</button></div>`
                )
                .join("")
            : '<p class="empty">None</p>'
        }
      </div>`;
    el.mutesBody.innerHTML =
      group("Companies", tickers, "restore-ticker") + group("Sources", src, "restore-source");
    el.mutesModal.hidden = false;
  }

  function closeModals() {
    el.mutesModal.hidden = true;
    el.helpModal.hidden = true;
    hideHover();
  }

  // ---------- events ----------
  $("btn-home").addEventListener("click", () => {
    state.view = "home";
    render();
  });
  el.btnBookmarks.addEventListener("click", () => {
    state.view = state.view === "bookmarks" ? "home" : "bookmarks";
    render();
  });
  el.btnQueue.addEventListener("click", () => {
    state.view = state.view === "queue" ? "home" : "queue";
    render();
  });
  $("btn-mutes").addEventListener("click", openMutes);
  $("btn-close-mutes").addEventListener("click", closeModals);
  $("btn-help").addEventListener("click", () => {
    el.helpModal.hidden = false;
  });
  $("btn-close-help").addEventListener("click", closeModals);
  $("btn-digest").addEventListener("click", copyDigest);
  $("btn-csv").addEventListener("click", () => {
    const url = CFG.csvUrl || "/api/alerts.csv";
    window.open(url, "_blank");
  });
  $("btn-restore-all").addEventListener("click", () => {
    mutedSources.clear();
    mutedTickers.clear();
    saveSet(KEYS.mutedSources, mutedSources);
    saveSet(KEYS.mutedTickers, mutedTickers);
    openMutes();
    render();
    toast("All mutes restored");
  });

  el.mutesBody.addEventListener("click", (e) => {
    const t = e.target.closest("[data-restore-ticker]");
    const s = e.target.closest("[data-restore-source]");
    if (t) mutedTickers.delete(t.dataset.restoreTicker);
    if (s) mutedSources.delete(s.dataset.restoreSource);
    if (t || s) {
      saveSet(KEYS.mutedTickers, mutedTickers);
      saveSet(KEYS.mutedSources, mutedSources);
      openMutes();
      render();
    }
  });

  [el.mutesModal, el.helpModal].forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModals();
    });
  });

  el.themeBtn.addEventListener("click", () => {
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
  el.densityBtn.addEventListener("click", () => {
    applyDensity(
      document.documentElement.getAttribute("data-density") === "compact" ? "comfortable" : "compact"
    );
  });

  $("btn-refresh").addEventListener("click", () => load(true));

  let searchTimer = null;
  el.search.addEventListener("input", (e) => {
    state.search = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(render, 120);
  });

  el.sort.addEventListener("change", (e) => {
    state.sort = e.target.value;
    render();
  });
  el.sector.addEventListener("change", (e) => {
    state.sector = e.target.value;
    render();
  });

  document.querySelectorAll(".chip[data-filter]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const f = chip.dataset.filter;
      if (state.filters.has(f)) state.filters.delete(f);
      else state.filters.add(f);
      render();
    });
  });

  el.banners.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    if (btn.dataset.action === "refresh") load(true);
    if (btn.dataset.action === "dismiss-new") $("new-banner")?.remove();
  });

  document.body.addEventListener("click", (e) => {
    const jump = e.target.closest("[data-jump]");
    if (jump) {
      const ticker = jump.dataset.jump;
      const target = document.getElementById(ticker);
      if (target) {
        e.preventDefault();
        if (state.view !== "home") {
          state.view = "home";
          render();
        }
        document.getElementById(ticker)?.scrollIntoView({ block: "start" });
        target.classList.remove("flash");
        void target.offsetWidth;
        target.classList.add("flash");
        return;
      }
    }

    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const row = btn.closest(".headline");

    if (action === "bookmark" && row) {
      toggleInSet(bookmarks, row.dataset.id, KEYS.bookmarks);
      syncSnapshots();
      render();
      return;
    }
    if (action === "queue" && row) {
      toggleInSet(queue, row.dataset.id, KEYS.queue);
      syncSnapshots();
      render();
      return;
    }
    if (action === "mute-source" && row) {
      const src = row.dataset.source;
      if (src) {
        mutedSources.add(src);
        saveSet(KEYS.mutedSources, mutedSources);
        render();
        toast(`Muted ${src}`);
      }
      return;
    }
    if (action === "mute-ticker") {
      const t = btn.dataset.ticker;
      if (t) {
        mutedTickers.add(t);
        saveSet(KEYS.mutedTickers, mutedTickers);
        render();
        toast(`Hid ${t} — restore via ✕`);
      }
      return;
    }
    if (action === "expand" || action === "collapse") {
      const t = btn.dataset.ticker;
      if (action === "expand") state.expanded.add(t);
      else state.expanded.delete(t);
      render();
      return;
    }
    if (action === "open" && row) {
      markRead(row.dataset.id);
      if (state.view === "queue") {
        queue.delete(row.dataset.id);
        saveSet(KEYS.queue, queue);
        syncSnapshots();
      }
      setTimeout(render, 0);
      return;
    }
    if (action === "open-latest") {
      markRead(btn.dataset.id);
      setTimeout(render, 0);
    }
  });

  document.body.addEventListener("mouseover", (e) => {
    const row = e.target.closest(".headline");
    if (!row) return;
    if (e.target.closest(".hl-actions")) return;
    showHover(articleFromRow(row), row.getBoundingClientRect());
  });
  document.body.addEventListener("mouseout", (e) => {
    const row = e.target.closest(".headline");
    if (row && !row.contains(e.relatedTarget)) scheduleHideHover();
  });
  el.hover.addEventListener("mouseenter", cancelHideHover);
  el.hover.addEventListener("mouseleave", scheduleHideHover);
  document.addEventListener("pointerdown", (e) => {
    if (!el.hover.hidden && !el.hover.contains(e.target) && !e.target.closest(".headline")) {
      hideHover();
    }
  });

  // keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
    if (e.key === "Escape") {
      if (!el.mutesModal.hidden || !el.helpModal.hidden) closeModals();
      else if (typing) e.target.blur();
      else if (state.search) {
        state.search = "";
        render();
      }
      return;
    }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;

    const toggleFilter = (f) => {
      if (state.filters.has(f)) state.filters.delete(f);
      else state.filters.add(f);
      render();
    };

    switch (e.key) {
      case "/":
        e.preventDefault();
        el.search.focus();
        el.search.select();
        break;
      case "r":
        load(true);
        break;
      case "t":
        el.themeBtn.click();
        break;
      case "c":
        el.densityBtn.click();
        break;
      case "n":
        toggleFilter("neg");
        break;
      case "h":
        toggleFilter("24h");
        break;
      case "u":
        toggleFilter("unread");
        break;
      case "b":
        el.btnBookmarks.click();
        break;
      case "l":
        el.btnQueue.click();
        break;
      case "d":
        copyDigest();
        break;
      case "g":
        state.view = "home";
        render();
        break;
      case "?":
        el.helpModal.hidden = false;
        break;
      default:
        break;
    }
  });

  window.addEventListener("hashchange", () => {
    const before = JSON.stringify([state.view, state.search, state.sort, state.sector, [...state.filters]]);
    readHash();
    const after = JSON.stringify([state.view, state.search, state.sort, state.sector, [...state.filters]]);
    if (before !== after) render();
  });

  // ---------- auto refresh ----------
  function tickCountdown() {
    if (state.loading) {
      el.countdown.textContent = "…";
      return;
    }
    const left = Math.max(0, state.nextRefresh - Date.now());
    const mins = Math.floor(left / 60000);
    const secs = Math.floor((left % 60000) / 1000);
    el.countdown.textContent = `${mins}:${String(secs).padStart(2, "0")}`;
    if (left <= 0 && document.visibilityState === "visible") load(true, true);
  }

  setInterval(tickCountdown, 1000);
  setInterval(() => {
    if (state.data) el.tagline.textContent = taglineText(state.data);
  }, 60000);

  // ---------- load ----------
  function dataFetchUrl(refresh) {
    if (IS_STATIC) {
      const base = CFG.dataUrl || "data/dashboard.json";
      return refresh ? `${base}${base.includes("?") ? "&" : "?"}t=${Date.now()}` : base;
    }
    return `${CFG.dataUrl || "/api/dashboard"}?per_company=10${refresh ? "&refresh=true" : ""}`;
  }

  async function load(refresh = false, silent = false) {
    state.loading = true;
    state.nextRefresh = Date.now() + AUTO_REFRESH_MS;
    if (!silent) {
      el.status.hidden = false;
      el.status.textContent = refresh
        ? IS_STATIC
          ? "Reloading published snapshot…"
          : "Refreshing headlines…"
        : "Loading headlines…";
      if (!state.data) el.skeleton.hidden = false;
    }
    try {
      const res = await fetch(dataFetchUrl(refresh), { cache: refresh ? "no-store" : "default" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.data = data;

      // Populate sector filter once per payload.
      const opts = ['<option value="">all sectors</option>']
        .concat((data.sectors || []).map((s) => `<option value="${esc(s)}">${esc(s)}</option>`))
        .join("");
      if (el.sector.innerHTML !== opts) el.sector.innerHTML = opts;
      el.sector.value = state.sector;

      syncSnapshots();
      el.skeleton.hidden = true;
      el.status.hidden = true;
      render();
      if (refresh && !silent) {
        toast(IS_STATIC ? "Loaded latest published snapshot" : "Headlines refreshed");
      }
      try {
        localStorage.setItem(KEYS.lastVisit, new Date().toISOString());
      } catch {
        /* ignore */
      }
    } catch (err) {
      el.skeleton.hidden = true;
      el.status.hidden = false;
      el.status.textContent = `Failed to load headlines: ${err.message}. Retrying on next refresh.`;
    } finally {
      state.loading = false;
    }
  }

  try {
    const raw = localStorage.getItem(KEYS.lastVisit);
    const t = raw ? new Date(raw).getTime() : NaN;
    state.prevVisit = Number.isNaN(t) ? null : t;
  } catch {
    state.prevVisit = null;
  }

  readHash();
  syncControls();
  load(false);
})();
