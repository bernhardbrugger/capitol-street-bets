import "@fontsource/barlow/400.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow/700.css";
import "@fontsource/teko/500.css";
import "@fontsource/teko/600.css";
import "./styles.css";

type Badge = { id: string; name: string; blurb: string };
type Row = {
  bioguide_id: string;
  name: string;
  initials: string;
  chamber: string;
  party: string;
  state: string;
  district: string | null;
  years_in_service: number;
  rank: number | null;
  previous_rank: number | null;
  rank_change: number | null;
  streak: number;
  on_fire: boolean;
  took_first: boolean;
  elevator: boolean;
  benched: boolean;
  return: number | null;
  alpha: number | null;
  benchmark: number | null;
  copycat_return: number | null;
  copycat_alpha: number | null;
  trades: number;
  avg_hold_days: number | null;
  avg_filing_lag: number | null;
  late_filings: number;
  filings: number;
  excluded_options: number;
  excluded_non_stock: number;
  excluded_unknown: number;
  unmatched_sells: number;
  uncopyable: number;
  badges: Badge[];
};
type WindowBoard = {
  as_of: string;
  previous_date: string | null;
  ranked: Row[];
  benched: Row[];
  beat_market: number;
  field_size: number;
  ticker_tape: string[];
  most_traded?: Stock[];
  chart?: Chart;
};
type Chart = {
  members: { bioguide_id: string; name: string; initials: string; party: string; points: [string, number][] }[];
  congress: [string, number][];
  spy: [string, number][];
};
type Stock = {
  symbol: string;
  name: string;
  trades: number;
  buys: number;
  sells: number;
  members: number;
  est_dollars: number;
  last_trade: string;
  price_change: number | null;
  top_members: { bioguide_id: string; name: string; party: string; trades: number; buys: number; sells: number }[];
};
type League = {
  sample: boolean;
  as_of: string;
  attribution: string;
  disclaimer: string;
  notes: string[];
  min_trades: number;
  price_mode: string;
  late_days: number;
  windows: Record<string, WindowBoard>;
  coverage?: {
    members_loaded: number;
    members_seated: number;
    members_trading?: number;
    tickers_priced?: number;
    tickers_total?: number;
  };
  recent_disclosures?: Disclosure[];
  filings?: Disclosure[];
  filings_7d?: number;
};
type Disclosure = {
  bioguide_id: string;
  name: string;
  chamber: string;
  party: string;
  state: string;
  side: "buy" | "sell";
  symbol: string;
  asset_name: string;
  amount: string;
  transaction_date: string | null;
  filed_date: string;
  lag_days: number | null;
  late: boolean;
};
type TradeRow = {
  transaction_date: string | null;
  filed_date: string | null;
  lag_days: number | null;
  late: boolean;
  side: string;
  symbol: string;
  asset_name: string;
  midpoint: number | null;
  included: boolean;
  exclude_reason: string | null;
  source_url: string | null;
  disclosure_portal: string;
};
type MemberFile = {
  bioguide_id: string;
  name: string;
  initials: string;
  chamber: string;
  party: string;
  state: string;
  district: string | null;
  years_in_service: number;
  curves: Record<string, { date: string; member: number; spy: number }[]>;
  trades: TradeRow[];
  windows: Record<string, Partial<Row>>;
};

const WINDOWS: { id: string; label: string }[] = [
  { id: "30d", label: "30 days" },
  { id: "90d", label: "90 days" },
  { id: "6m", label: "6 months" },
  { id: "12m", label: "1 year" },
  { id: "all", label: "All" },
];
const HUES = [28, 46, 78, 152, 168, 188, 262, 282, 314, 332];
const BASE = import.meta.env.BASE_URL;
const REPO_URL = "https://github.com/bernhardbrugger/capitol-street-bets";
const PROFILE_URL = "https://github.com/bernhardbrugger";

type SortKey = "rank" | "return" | "alpha" | "trades" | "copycat" | "name";
const state: {
  window: string;
  sort: SortKey;
  dir: "asc" | "desc";
  query: string;
  left: string;
  right: string;
  rankBy: "member" | "copycat";
  chamber: string;
  party: string;
  side: string;
  hidden: Set<string>;
} = {
  rankBy: "member",
  chamber: "all",
  party: "all",
  side: "all",
  hidden: new Set<string>(),
  window: "90d",
  sort: "rank",
  dir: "asc",
  query: "",
  left: "",
  right: "",
};
const introduced = new Set<string>();
let league: League | null = null;

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("missing app root");
const app: HTMLElement = root;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  kids: (Node | string)[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const kid of kids) node.append(kid);
  return node;
}

function pct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const points = value * 100;
  const sign = points > 0 ? "+" : "";
  return `${sign}${points.toFixed(1)}%`;
}
function tone(value: number | null | undefined): string {
  if (value == null || Math.abs(value) < 0.00005) return "";
  return value > 0 ? "up" : "down";
}
function money(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}
function place(row: { state: string; district: string | null }): string {
  return row.district ? `${row.state}-${row.district}` : row.state;
}
function hue(id: string): string {
  let hash = 0;
  for (const char of id) hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  return String(HUES[hash % HUES.length]);
}
function httpUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || url.protocol === "http:") return url.toString();
  } catch {
    return null;
  }
  return null;
}
function reduceMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function currentBoard(): WindowBoard {
  if (!league) throw new Error("league not loaded");
  return league.windows[state.window];
}
function allRows(): Row[] {
  const board = currentBoard();
  return [...board.ranked, ...board.benched];
}
function passesFilters(item: { chamber: string; party: string }): boolean {
  if (state.chamber !== "all" && item.chamber !== state.chamber) return false;
  if (state.party !== "all" && (item.party || "").toUpperCase().charAt(0) !== state.party) return false;
  return true;
}
function matches(row: Row): boolean {
  if (!passesFilters(row)) return false;
  const needle = state.query.trim().toLowerCase();
  if (!needle) return true;
  return `${row.name} ${row.state} ${row.chamber}`.toLowerCase().includes(needle);
}

function sorted(rows: Row[]): Row[] {
  const ranked = rows.filter((row) => !row.benched);
  const benched = rows.filter((row) => row.benched);
  const dir = state.dir === "asc" ? 1 : -1;
  const value = (row: Row): number | string => {
    if (state.sort === "name") return row.name;
    if (state.sort === "return") return row.return ?? -999;
    if (state.sort === "alpha") return row.alpha ?? -999;
    if (state.sort === "trades") return row.trades;
    if (state.sort === "copycat") return row.copycat_return ?? -999;
    // "Rank by copy-trading" re-orders the ranked rows by copycat alpha.
    if (state.rankBy === "copycat") return -(row.copycat_alpha ?? -999);
    return row.rank ?? 999;
  };
  ranked.sort((a, b) => {
    const av = value(a);
    const bv = value(b);
    if (typeof av === "string" || typeof bv === "string") return String(av).localeCompare(String(bv)) * dir;
    return (av - bv) * dir || a.name.localeCompare(b.name);
  });
  benched.sort((a, b) => a.name.localeCompare(b.name));
  return [...ranked, ...benched];
}

function previousOrder(rows: Row[]): Row[] {
  const ranked = rows.filter((row) => !row.benched);
  const benched = rows.filter((row) => row.benched);
  ranked.sort((a, b) => (a.previous_rank ?? 999) - (b.previous_rank ?? 999) || a.name.localeCompare(b.name));
  return [...ranked, ...benched];
}

function flame(): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "flame");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("fill", "#ffb15a");
  path.setAttribute("d", "M12 2s6 6 6 11a6 6 0 1 1-12 0c0-2 1-3.5 2-5 0 2 2 3 2 3s0-4 2-9z");
  svg.append(path);
  return svg;
}

function changeNode(row: Row): HTMLElement {
  const node = el("div", { class: "chg" });
  if (row.benched || row.rank == null) {
    node.classList.add("flat");
    node.textContent = "BENCH";
    return node;
  }
  if (row.previous_rank == null || row.rank_change == null) {
    node.classList.add("up");
    node.textContent = "NEW";
    return node;
  }
  if (row.rank_change === 0) {
    node.classList.add("flat");
    node.textContent = "—";
    return node;
  }
  if (row.elevator) {
    const shaft = el("span", { class: "shaft", title: "Big drop" });
    shaft.append(el("i"));
    node.append(shaft);
  }
  node.classList.add(row.rank_change > 0 ? "up" : "down");
  node.append(row.rank_change > 0 ? `▲ ${row.rank_change}` : `▼ ${Math.abs(row.rank_change)}`);
  return node;
}

function badgeList(badges: Badge[], onFire: boolean): HTMLElement {
  const wrap = el("div", { class: "badges" });
  if (onFire) {
    const fire = el("span", { class: "fire", title: "Rank improved several snapshots in a row" });
    fire.append(flame(), "ON FIRE");
    wrap.append(fire);
  }
  for (const badge of badges) {
    const hot = badge.id === "beat_the_market" || badge.id === "diamond_hands";
    wrap.append(el("span", { class: hot ? "badge gold" : "badge", title: badge.blurb }, [badge.name]));
  }
  return wrap;
}

function rowView(row: Row, shown?: number): HTMLAnchorElement {
  const link = el("a", {
    class: `row${row.rank === 1 ? " leader" : ""}${row.elevator ? " elevator" : ""}`,
    href: `#/member/${row.bioguide_id}`,
    "data-id": row.bioguide_id,
    "data-elevator": row.elevator ? "true" : "false",
    "data-on-fire": row.on_fire ? "true" : "false",
  });
  const rank = el("div", { class: "rank" }, [row.benched || row.rank == null ? "—" : String(shown ?? row.rank)]);
  const avatar = el("div", { class: "avatar" }, [row.initials]);
  avatar.style.background = `hsl(${hue(row.bioguide_id)} 42% 36%)`;
  const who = el("div", { class: "who" }, [
    avatar,
    el("div", {}, [
      el("div", { class: "name" }, [row.name]),
      el("small", {}, [`${row.chamber} · ${place(row)} · ${row.party || "—"}`]),
    ]),
  ]);
  const chamber = el("div", { class: "desk", title: "Party is a data label" }, [row.chamber]);
  const ret = el("div", { class: `num desk ${tone(row.return)}` }, [pct(row.return)]);
  const alpha = el("div", { class: `num desk ${tone(row.alpha)}` }, [pct(row.alpha)]);
  const trades = el("div", { class: "desk" }, [String(row.trades)]);
  const copy = el("div", { class: `num desk ${tone(row.copycat_return)}` }, [pct(row.copycat_return)]);
  const change = state.rankBy === "copycat" && !row.benched ? el("div", { class: "chg flat" }, ["·"]) : changeNode(row);
  link.append(rank, change, who, chamber, ret, alpha, trades, copy, badgeList(row.badges, row.on_fire));
  // Mobile keeps return and alpha visible under the name via a second line of badges area.
  const mobileNums = el("div", { class: "mobile-stats" });
  mobileNums.append(
    el("span", { class: tone(row.return) }, [`Ret ${pct(row.return)}`]),
    el("span", { class: tone(row.alpha) }, [`Alpha ${pct(row.alpha)}`]),
    el("span", {}, [`${row.trades} trades`]),
    el("span", { class: tone(row.copycat_return) }, [`Copy ${pct(row.copycat_return)}`]),
  );
  link.append(mobileNums);
  return link;
}

function headerCells(): HTMLElement {
  const specs: { key: SortKey | null; label: string }[] = [
    { key: "rank", label: "Rank" },
    { key: null, label: "Chg" },
    { key: "name", label: "Member" },
    { key: null, label: "Chamber" },
    { key: "return", label: "Return" },
    { key: "alpha", label: "Alpha" },
    { key: "trades", label: "Trades" },
    { key: "copycat", label: "Copycat" },
  ];
  const row = el("div", { class: "cols" });
  for (const spec of specs) {
    if (!spec.key) {
      row.append(el("span", {}, [spec.label]));
      continue;
    }
    const key = spec.key;
    const pressed = state.sort === key;
    const button = el("button", {
      type: "button",
      "aria-sort": pressed ? (state.dir === "asc" ? "ascending" : "descending") : "none",
    }, [spec.label]);
    button.addEventListener("click", () => {
      if (state.sort === key) state.dir = state.dir === "asc" ? "desc" : "asc";
      else {
        state.sort = key;
        state.dir = key === "name" ? "asc" : key === "rank" ? "asc" : "desc";
      }
      render();
    });
    row.append(button);
  }
  row.append(el("span", {}, ["Badges"]));
  return row;
}

function flip(host: HTMLElement, draw: () => void): Promise<void> {
  const before = new Map<string, DOMRect>();
  if (!reduceMotion()) {
    host.querySelectorAll<HTMLElement>("[data-id]").forEach((node) => {
      if (node.dataset.id) before.set(node.dataset.id, node.getBoundingClientRect());
    });
  }
  draw();
  if (reduceMotion()) return Promise.resolve();
  const pending: Promise<void>[] = [];
  host.querySelectorAll<HTMLElement>("[data-id]").forEach((node) => {
    const id = node.dataset.id;
    const first = id ? before.get(id) : undefined;
    if (!first) return;
    const last = node.getBoundingClientRect();
    const dy = first.top - last.top;
    if (Math.abs(dy) < 2) return;
    const elevator = node.dataset.elevator === "true" && dy < 0;
    const animation = node.animate(
      [{ transform: `translateY(${dy}px)` }, { transform: "translateY(0)" }],
      {
        duration: elevator ? 1100 : 680,
        easing: elevator ? "cubic-bezier(.5,.05,.9,.45)" : "cubic-bezier(.16,.84,.32,1)",
      },
    );
    pending.push(animation.finished.then(() => undefined, () => undefined));
  });
  return Promise.all(pending).then(() => undefined);
}

function stopConfetti(): void {
  const canvas = document.querySelector<HTMLCanvasElement>("#confetti");
  const ctx = canvas?.getContext("2d");
  if (!canvas || !ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function celebrate(): void {
  if (reduceMotion()) return;
  const canvas = document.querySelector<HTMLCanvasElement>("#confetti");
  const ctx = canvas?.getContext("2d");
  if (!canvas || !ctx) return;
  const width = window.innerWidth;
  const height = window.innerHeight;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const colors = ["#f0c14a", "#3ee0a2", "#8fd4ff", "#ffe3a3", "#ffb15a"];
  const bits = Array.from({ length: 140 }, () => ({
    x: Math.random() * width,
    y: -20 - Math.random() * 120,
    w: 3 + Math.random() * 5,
    h: 2 + Math.random() * 3,
    vy: 2.2 + Math.random() * 3.2,
    vx: -1.4 + Math.random() * 2.8,
    rot: Math.random() * 6,
    vr: -0.18 + Math.random() * 0.36,
    color: colors[Math.floor(Math.random() * colors.length)],
  }));
  const started = performance.now();
  const frame = (now: number) => {
    ctx.clearRect(0, 0, width, height);
    for (const bit of bits) {
      bit.vy += 0.035;
      bit.x += bit.vx;
      bit.y += bit.vy;
      bit.rot += bit.vr;
      ctx.save();
      ctx.translate(bit.x, bit.y);
      ctx.rotate(bit.rot);
      ctx.fillStyle = bit.color;
      ctx.fillRect(-bit.w / 2, -bit.h / 2, bit.w, bit.h);
      ctx.restore();
    }
    if (now - started < 2000) requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, width, height);
  };
  requestAnimationFrame(frame);
  canvas.dataset.state = "fired";
}

function shell(body: HTMLElement): void {
  app.replaceChildren();
  const top = el("header", { class: "wrap top" });
  const brand = el("div", { class: "brand" });
  brand.append(
    el("p", { class: "kicker" }, ["PUBLIC DISCLOSURES"]),
    el("h1", { class: "wordmark" }, ["CAPITOL STREET BETS"]),
    el("p", { class: "tagline" }, ["The only league where everyone files late."]),
  );
  const nav = el("nav", { class: "nav" });
  const method = el("a", { href: `${BASE}methodology.html` }, ["Methodology"]);
  const repo = el("a", { href: REPO_URL, target: "_blank", rel: "noopener" }, ["GitHub ★"]);
  nav.append(method, repo);
  top.append(brand, nav);
  const routeName = parseRoute().name;
  // Outside the page body: some pages rebuild their body after loading.
  app.append(top, el("div", { class: "wrap" }, [tabs(routeName)]), body, footer());
}

function tabs(current: string): HTMLElement {
  const bar = el("nav", { class: "tabs", "aria-label": "Sections" });
  const items: [string, string, string, string?][] = [
    ["home", "#/", "Leaderboard"],
    ["filings", "#/filings", "Filings", league?.filings_7d != null ? `${league.filings_7d} in last 7d` : undefined],
    ["stocks", "#/stocks", "Stocks"],
    ["versus", "#/versus", "Head to head"],
  ];
  for (const [id, href, label, note] of items) {
    const link = el("a", { href }, [label, note ? el("small", {}, [note]) : ""]);
    if (id === current) link.setAttribute("aria-current", "page");
    bar.append(link);
  }
  return bar;
}

function select(label: string, value: string, options: [string, string][], onChange: (v: string) => void): HTMLElement {
  const node = el("select", { class: "filter", "aria-label": label }) as HTMLSelectElement;
  for (const [v, text] of options) {
    const option = el("option", { value: v }, [text]) as HTMLOptionElement;
    if (v === value) option.selected = true;
    node.append(option);
  }
  node.addEventListener("change", () => onChange(node.value));
  return node;
}

function segmented(label: string, value: string, options: [string, string][], onChange: (v: string) => void): HTMLElement {
  const wrap = el("div", { class: "seg", role: "group", "aria-label": label }, [el("span", { class: "seg-label" }, [label])]);
  for (const [v, text] of options) {
    const button = el("button", { type: "button", "aria-pressed": v === value ? "true" : "false" }, [text]);
    button.addEventListener("click", () => onChange(v));
    wrap.append(button);
  }
  return wrap;
}

function filterSelects(): HTMLElement[] {
  return [
    select("Chamber", state.chamber, [["all", "House and Senate"], ["House", "House"], ["Senate", "Senate"]], (v) => {
      state.chamber = v;
      render();
    }),
    select("Party", state.party, [["all", "All parties"], ["D", "Democrats"], ["R", "Republicans"], ["I", "Independents"]], (v) => {
      state.party = v;
      render();
    }),
  ];
}

function footer(): HTMLElement {
  const node = el("footer", { class: "wrap footer" });
  if (!league) return node;
  node.append(
    el("p", {}, [league.disclaimer]),
    el("p", {}, [el("strong", {}, [league.attribution]), ` · Price mode: ${league.price_mode}`]),
    el("p", {}, [
      el("a", { href: `${BASE}methodology.html` }, ["How the score is kept"]),
      " · Humor is about the stats. Party is only a label.",
    ]),
    el("p", {}, [
      "Built by ",
      el("a", { href: PROFILE_URL, target: "_blank", rel: "noopener" }, ["Bernhard Brugger"]),
      " · ",
      el("a", { href: REPO_URL, target: "_blank", rel: "noopener" }, ["Source on GitHub"]),
    ]),
  );
  return node;
}

function windowBar(): HTMLElement {
  const bar = segmented("Period", state.window, WINDOWS.map((w) => [w.id, w.label] as [string, string]), (v) => {
    state.window = v;
    render();
  });
  bar.classList.add("windows");
  return bar;
}

function paintBoard(host: HTMLElement, rows: Row[]): void {
  host.replaceChildren(headerCells());
  const ranked = rows.filter((row) => !row.benched);
  const benched = rows.filter((row) => row.benched);
  const searching = state.query.trim().length > 0;
  // Only members who traded in the period are on this page; the rest of the
  // roster shows up when you search for them.
  const active = benched.filter((row) => row.filings > 0);
  const quiet = searching ? benched.filter((row) => row.filings <= 0) : [];
  if (!ranked.length && !active.length && !quiet.length) {
    host.append(el("p", { class: "empty" }, [searching ? "No one on the roster matches that." : "Nobody matching these filters has enough priced trades in this period. Try a longer period."]));
    return;
  }
  ranked.forEach((row, index) => host.append(rowView(row, index + 1)));
  if (active.length) {
    const details = el("details", { class: "bench" });
    details.open = searching || ranked.length < 8;
    details.append(el("summary", {}, [`Traded, not ranked yet · ${active.length} with fewer than ${league?.min_trades ?? 3} priced stock trades`]));
    const stack = el("div", { class: "board" });
    for (const row of active) stack.append(rowView(row));
    details.append(stack);
    host.append(details);
  }
  if (quiet.length) {
    const stack = el("div", { class: "board" });
    for (const row of quiet) stack.append(rowView(row));
    host.append(el("p", { class: "meta-line" }, ["No trades in this period:"]), stack);
  }
}

function compactMoney(value: number): string {
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `$${Math.round(value / 1e3)}K`;
  return `$${Math.round(value)}`;
}

function splitBar(stock: Stock): HTMLElement {
  const total = Math.max(1, stock.buys + stock.sells);
  return el("div", { class: "split", title: `${stock.buys} buys · ${stock.sells} sells` }, [
    el("span", { class: "buy", style: `width:${((stock.buys / total) * 100).toFixed(1)}%` }),
    el("span", { class: "sell", style: `width:${((stock.sells / total) * 100).toFixed(1)}%` }),
  ]);
}

function windowLabel(id: string): string {
  return { "30d": "last 30 days", "90d": "last 90 days", "6m": "last 6 months", "12m": "last 12 months", all: "all time" }[id] ?? id;
}

function stockStrip(): HTMLElement | null {
  const items = currentBoard().most_traded ?? [];
  if (!items.length) return null;
  const section = el("section", { class: "stocks-strip", "aria-label": "Most traded stocks" });
  section.append(
    el("div", { class: "strip-head" }, [
      el("h2", { class: "feed-title" }, [`Most traded stocks · ${windowLabel(state.window)}`]),
      el("a", { class: "more", href: "#/stocks" }, ["All stocks →"]),
    ]),
  );
  const grid = el("div", { class: "stock-grid" });
  items.slice(0, 8).forEach((stock, index) => {
    grid.append(
      el("a", { class: "stock-card", href: `#/stocks?s=${encodeURIComponent(stock.symbol)}` }, [
        el("div", { class: "stock-top" }, [
          el("span", { class: "stock-rank" }, [String(index + 1)]),
          el("strong", { class: "sym" }, [stock.symbol]),
          el("span", { class: `move ${tone(stock.price_change)}` }, [pct(stock.price_change)]),
        ]),
        el("div", { class: "stock-name" }, [stock.name || "\u00a0"]),
        splitBar(stock),
        el("div", { class: "stock-meta" }, [
          `${stock.trades} trades · ${stock.members} member${stock.members === 1 ? "" : "s"} · ~${compactMoney(stock.est_dollars)}`,
        ]),
      ]),
    );
  });
  section.append(grid);
  return section;
}

function renderFilings(): void {
  stopConfetti();
  const page = el("main", { class: "wrap" });
  const all = (league?.filings ?? []).filter(passesFilters);
  const needle = state.query.trim().toLowerCase();
  const items = all.filter(
    (item) =>
      (state.side === "all" || item.side === state.side) &&
      (!needle || `${item.name} ${item.symbol} ${item.asset_name}`.toLowerCase().includes(needle)),
  );
  const search = el("input", { class: "search", type: "search", placeholder: "Search members or stocks", value: state.query, "aria-label": "Search filings" }) as HTMLInputElement;
  search.addEventListener("input", () => {
    state.query = search.value;
    render();
    const next = document.querySelector<HTMLInputElement>(".search");
    next?.focus();
    const pos = next?.value.length ?? 0;
    next?.setSelectionRange(pos, pos);
  });
  page.append(
    el("h2", { class: "section-title" }, ["Filings"]),
    el("p", { class: "muted" }, [
      `Stock trades disclosed in the last 60 days, newest filing first. "Filed after" is the gap between the trade and the disclosure; over ${league?.late_days ?? 45} days counts as late.`,
    ]),
    el("div", { class: "controls" }, [
      segmented("Show", state.side, [["all", "All"], ["buy", "Buys"], ["sell", "Sells"]], (v) => {
        state.side = v;
        render();
      }),
      ...filterSelects(),
      search,
    ]),
    el("p", { class: "status" }, [el("i", { class: "dot" }), `${items.length} filing${items.length === 1 ? "" : "s"} shown · ${league?.filings_7d ?? 0} filed in the last 7 days.`]),
  );
  if (!items.length) {
    page.append(el("div", { class: "callout" }, ["No filings match these filters yet."]));
    shell(page);
    return;
  }
  const table = el("div", { class: "filings", role: "table" });
  table.append(
    el("div", { class: "filing head", role: "row" }, [
      el("span", {}, ["Filed"]),
      el("span", {}, ["Member"]),
      el("span", {}, [""]),
      el("span", {}, ["Stock"]),
      el("span", {}, ["Amount"]),
      el("span", {}, ["Traded"]),
      el("span", {}, ["Filed after"]),
    ]),
  );
  for (const item of items.slice(0, 300)) {
    table.append(
      el("div", { class: "filing", role: "row" }, [
        el("span", { class: "date" }, [item.filed_date]),
        el("span", { class: "member" }, [
          el("a", { href: `#/member/${item.bioguide_id}` }, [item.name]),
          el("small", {}, [`${item.chamber} · ${item.state} · ${item.party}`]),
        ]),
        el("span", {}, [el("span", { class: `side ${item.side}` }, [item.side === "buy" ? "BUY" : "SELL"])]),
        el("span", { class: "stock" }, [
          el("a", { href: `#/stocks?s=${encodeURIComponent(item.symbol)}`, class: "sym" }, [item.symbol]),
          el("small", {}, [item.asset_name.replace(/\s*\[[A-Z]+\]\s*$/, "").slice(0, 48)]),
        ]),
        el("span", {}, [item.amount]),
        el("span", { class: "date" }, [item.transaction_date ?? "—"]),
        el("span", { class: item.late ? "late" : "" }, [item.lag_days == null ? "—" : `${item.lag_days} days${item.late ? " · late" : ""}`]),
      ]),
    );
  }
  page.append(table);
  shell(page);
}

function renderStocks(): void {
  stopConfetti();
  const focus = decodeURIComponent((location.hash.split("?s=")[1] || "").toUpperCase());
  const items = currentBoard().most_traded ?? [];
  const page = el("main", { class: "wrap" });
  page.append(
    el("h2", { class: "section-title" }, ["Most traded stocks"]),
    el("p", { class: "muted" }, [
      "Stock trades disclosed by members of Congress, by number of trades in the window. Buy/sell split in green and red, dollar volume estimated from the disclosed ranges, move is the stock's price change over the window.",
    ]),
    el("div", { class: "toolbar" }, [windowBar()]),
  );
  if (!items.length) {
    page.append(el("div", { class: "callout" }, ["No stock trades in this window yet. Try YTD or ALL."]));
    shell(page);
    return;
  }
  const table = el("div", { class: "stock-table", role: "table" });
  table.append(
    el("div", { class: "stock-row head", role: "row" }, [
      el("span", {}, ["#"]),
      el("span", {}, ["Stock"]),
      el("span", {}, ["Trades"]),
      el("span", {}, ["Buy / sell"]),
      el("span", {}, ["Est. volume"]),
      el("span", {}, ["Move"]),
      el("span", {}, ["Who traded it"]),
    ]),
  );
  items.forEach((stock, index) => {
    const who = el("span", { class: "traders" });
    for (const m of stock.top_members.slice(0, 3)) {
      who.append(el("span", {}, [el("a", { href: `#/member/${m.bioguide_id}` }, [m.name]), el("small", {}, [`${m.trades}×`])]));
    }
    if (stock.members > 3) who.append(el("small", {}, [`+${stock.members - 3} more`]));
    const row = el("div", { class: `stock-row${stock.symbol === focus ? " focus" : ""}`, role: "row", id: `stock-${stock.symbol}` }, [
      el("span", { class: "stock-rank" }, [String(index + 1)]),
      el("span", { class: "stock-id" }, [el("strong", { class: "sym" }, [stock.symbol]), el("small", {}, [stock.name])]),
      el("span", {}, [`${stock.trades}`, el("small", {}, [` · ${stock.members} member${stock.members === 1 ? "" : "s"}`])]),
      el("span", { class: "split-cell" }, [splitBar(stock), el("small", {}, [`${stock.buys} / ${stock.sells}`])]),
      el("span", {}, [`~${compactMoney(stock.est_dollars)}`]),
      el("span", { class: `move ${tone(stock.price_change)}` }, [pct(stock.price_change)]),
      who,
    ]);
    table.append(row);
  });
  page.append(table);
  shell(page);
  if (focus) document.getElementById(`stock-${focus}`)?.scrollIntoView({ block: "center" });
}

function windowPhrase(id: string): string {
  return { "30d": "in the last 30 days", "90d": "in the last 90 days", "6m": "in the last 6 months", "12m": "in the last 12 months", all: "on record" }[id] ?? "";
}

function hero(board: WindowBoard): HTMLElement {
  const box = el("section", { class: "hero" });
  const ranked = board.ranked.filter((row) => row.copycat_alpha != null);
  const star = [...ranked].sort((a, b) => (b.copycat_alpha ?? -9) - (a.copycat_alpha ?? -9))[0];
  if (star) {
    const ahead = (star.copycat_alpha ?? 0) >= 0;
    box.append(
      el("h2", {}, [
        el("a", { href: `#/member/${star.bioguide_id}`, class: "hl" }, [star.name]),
        " made ",
        el("span", { class: "hl" }, [`${star.trades} stock trades`]),
        ` ${windowPhrase(state.window)}.`,
        el("br"),
        "Copying them when the filings went public would have ",
        el("span", { class: ahead ? "hl" : "hl down" }, [ahead ? "beaten" : "trailed"]),
        " the S&P 500 by ",
        el("span", { class: ahead ? "hl" : "hl down" }, [`${Math.abs((star.copycat_alpha ?? 0) * 100).toFixed(1)} points`]),
        ".",
      ]),
    );
  } else {
    box.append(el("h2", {}, ["Who in Congress beats the S&P 500 with their own stock trades?"]));
  }
  box.append(
    el("p", { class: "muted" }, [
      `Members of Congress must disclose stock trades over $1,000 within 45 days. This board prices every disclosed stock trade and compares it with the S&P 500 over the same holding period.`,
    ]),
  );
  return box;
}

function statusLine(board: WindowBoard): HTMLElement {
  const rows = [...board.ranked, ...board.benched].filter(passesFilters);
  const traded = rows.filter((row) => row.filings > 0).length;
  const ranked = board.ranked.filter(passesFilters).length;
  const cov = league?.coverage;
  const parts = [
    `Updated ${league?.as_of ?? board.as_of}.`,
    ` ${traded} member${traded === 1 ? "" : "s"} traded in this period; ${ranked} ${ranked === 1 ? "has" : "have"} enough priced trades to rank.`,
  ];
  if (cov && cov.members_loaded < cov.members_seated) {
    parts.push(` Trade history loaded for ${cov.members_loaded} of ${cov.members_seated} seated members so far, more every day, busiest traders first.`);
  }
  return el("p", { class: "status" }, [el("i", { class: "dot" }), parts.join("")]);
}

const LINE_COLORS = ["#5aa9ff", "#3ee0a2", "#ff8a5c", "#c792ea", "#ffd166", "#ff6b9a"];

function perfChart(chart: Chart | undefined): HTMLElement | null {
  if (!chart || (!chart.members.length && !chart.spy.length)) return null;
  const card = el("section", { class: "perf" });
  card.append(
    el("h2", {}, ["Performance over time"]),
    el("p", { class: "muted small" }, [
      state.rankBy === "copycat"
        ? "Lines show each member's own disclosed trades from their trade dates. Dashed line: S&P 500."
        : "How each member's disclosed stock trades performed from their trade dates, larger trades counting more. Dashed line: S&P 500.",
    ]),
  );
  type Series = { id: string; label: string; initials: string; color: string; points: [string, number][]; dashed?: boolean; bold?: boolean };
  const series: Series[] = [
    { id: "spy", label: "S&P 500", initials: "S&P", color: "#9fb0c5", points: chart.spy, dashed: true },
  ];
  if (chart.congress.length) series.push({ id: "congress", label: "All Congress", initials: "ALL", color: "#f0c14a", points: chart.congress, bold: true });
  chart.members.forEach((m, i) =>
    series.push({ id: m.bioguide_id, label: m.name.split(" ").slice(-1)[0], initials: m.initials, color: LINE_COLORS[i % LINE_COLORS.length], points: m.points }),
  );
  const chips = el("div", { class: "chips" });
  for (const item of series) {
    const off = state.hidden.has(item.id);
    const chip = el("button", { type: "button", class: `chip${off ? " off" : ""}`, "aria-pressed": off ? "false" : "true", title: off ? `Show ${item.label}` : `Hide ${item.label}` }, [
      el("span", { class: "ring", style: `border-color:${item.color};${item.dashed ? "border-style:dashed;" : ""}` }, [item.initials]),
      el("small", {}, [item.label]),
    ]);
    chip.addEventListener("click", () => {
      if (state.hidden.has(item.id)) state.hidden.delete(item.id);
      else state.hidden.add(item.id);
      render();
    });
    chips.append(chip);
  }
  card.append(chips);
  const visible = series.filter((item) => !state.hidden.has(item.id) && item.points.length >= 2);
  if (!visible.length) {
    card.append(el("p", { class: "empty" }, ["Pick a line above."]));
    return card;
  }
  // Narrow screens get a taller, tighter canvas so labels stay readable.
  const narrow = window.innerWidth < 640;
  const W = narrow ? 560 : 1100;
  const H = narrow ? 380 : 320;
  const L = 12;
  const R = 70;
  const T = 14;
  const B = 30;
  const toTime = (d: string) => new Date(`${d}T00:00:00Z`).getTime();
  const all = visible.flatMap((item) => item.points);
  const t0 = Math.min(...all.map((p) => toTime(p[0])));
  const t1 = Math.max(...all.map((p) => toTime(p[0])));
  const vals = all.map((p) => p[1] - 100);
  let lo = Math.min(0, ...vals);
  let hi = Math.max(0, ...vals);
  const padV = (hi - lo) * 0.08 || 2;
  lo -= padV;
  hi += padV;
  const x = (d: string) => L + ((toTime(d) - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const y = (v: number) => T + ((hi - (v - 100)) / (hi - lo)) * (H - T - B);
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "perf-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Indexed performance of the top members, all ranked members and the S&P 500");
  const step = [1, 2, 5, 10, 20, 25, 50, 100].find((s) => (hi - lo) / s <= 6) ?? 100;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    const g = document.createElementNS(NS, "line");
    g.setAttribute("x1", String(L));
    g.setAttribute("x2", String(W - R));
    g.setAttribute("y1", String(y(v + 100)));
    g.setAttribute("y2", String(y(v + 100)));
    g.setAttribute("class", v === 0 ? "zero" : "grid");
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", String(W - R + 6));
    t.setAttribute("y", String(y(v + 100) + 4));
    t.setAttribute("class", "tick");
    t.textContent = `${v > 0 ? "+" : ""}${v}%`;
    svg.append(g, t);
  }
  // Month ticks along the bottom.
  const months = new Set<string>();
  for (const p of all) months.add(p[0].slice(0, 7));
  const monthList = [...months].sort();
  const every = Math.max(1, Math.ceil(monthList.length / 8));
  monthList.forEach((m, i) => {
    if (i % every) return;
    const d = `${m}-01`;
    if (toTime(d) < t0) return;
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", String(x(d)));
    t.setAttribute("y", String(H - 8));
    t.setAttribute("class", "tick");
    t.textContent = new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", year: monthList.length > 12 ? "2-digit" : undefined, timeZone: "UTC" });
    svg.append(t);
  });
  const labels: { y: number; text: string; color: string }[] = [];
  for (const item of visible) {
    const line = document.createElementNS(NS, "polyline");
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", item.color);
    line.setAttribute("stroke-width", item.bold ? "3.2" : "2");
    line.setAttribute("stroke-linejoin", "round");
    if (item.dashed) line.setAttribute("stroke-dasharray", "5 5");
    line.setAttribute("points", item.points.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" "));
    const title = document.createElementNS(NS, "title");
    title.textContent = item.label;
    line.append(title);
    svg.append(line);
    const last = item.points[item.points.length - 1];
    labels.push({ y: y(last[1]), text: `${last[1] - 100 >= 0 ? "+" : ""}${(last[1] - 100).toFixed(1)}%`, color: item.color });
  }
  // End labels, nudged apart so they do not overlap.
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 15) labels[i].y = labels[i - 1].y + 15;
  for (const label of labels) {
    const r = document.createElementNS(NS, "rect");
    r.setAttribute("x", String(W - R + 2));
    r.setAttribute("y", String(label.y - 8));
    r.setAttribute("width", "58");
    r.setAttribute("height", "15");
    r.setAttribute("rx", "3");
    r.setAttribute("fill", label.color);
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", String(W - R + 31));
    t.setAttribute("y", String(label.y + 3.5));
    t.setAttribute("class", "endlabel");
    t.textContent = label.text;
    svg.append(r, t);
  }
  card.append(svg);
  return card;
}

function renderHome(): void {
  const board = currentBoard();
  const page = el("main", { class: "wrap" });
  if (league?.sample) {
    page.append(
      el("div", { class: "banner", "data-sample": "true" }, [
        "Sample league. These members and prices are fictional, so you can click around before a real ingestion.",
      ]),
    );
  }
  page.append(hero(board));
  const search = el("input", { class: "search", type: "search", placeholder: "Search members", value: state.query, "aria-label": "Find a member" }) as HTMLInputElement;
  search.addEventListener("input", () => {
    state.query = search.value;
    render();
    const next = document.querySelector<HTMLInputElement>(".search");
    next?.focus();
    const pos = next?.value.length ?? 0;
    next?.setSelectionRange(pos, pos);
  });
  page.append(
    el("div", { class: "controls" }, [
      segmented("Rank by", state.rankBy, [["member", "Member's return"], ["copycat", "Copy-trading"]], (v) => {
        state.rankBy = v as "member" | "copycat";
        render();
      }),
      ...filterSelects(),
    ]),
    el("div", { class: "controls" }, [windowBar(), search]),
    statusLine(board),
  );
  const chart = perfChart(board.chart);
  if (chart) page.append(chart);
  const host = el("section", { class: "board", id: "board" });
  page.append(
    el("p", { class: "meta-line" }, [
      state.rankBy === "copycat"
        ? `Ranked by copy-trading: buying on the day each trade was disclosed, versus the S&P 500. Minimum ${league?.min_trades ?? 3} priced stock trades.`
        : `Ranked by alpha: the member's own trade-date returns versus the S&P 500 over the same days. Minimum ${league?.min_trades ?? 3} priced stock trades. Arrows versus ${board.previous_date ?? "the first snapshot"}.`,
    ]),
    host,
  );
  const hot = stockStrip();
  if (hot) page.append(hot);
  shell(page);

  const visible = sorted(allRows().filter(matches));
  const playIntro = state.sort === "rank" && state.dir === "asc" && !state.query && !introduced.has(state.window) && visible.some((row) => row.previous_rank != null);
  const settle = (done: Promise<void>) => {
    void done.then(() => {
      if (host.isConnected) host.dataset.settled = "true";
    });
  };
  if (playIntro) {
    introduced.add(state.window);
    paintBoard(host, previousOrder(visible));
    window.setTimeout(() => {
      settle(flip(host, () => paintBoard(host, visible)));
      if (visible.some((row) => row.took_first)) celebrate();
    }, reduceMotion() ? 0 : 40);
  } else {
    settle(flip(host, () => paintBoard(host, visible)));
  }
}

function stat(label: string, value: string, className = ""): HTMLElement {
  return el("div", { class: "stat" }, [el("span", {}, [label]), el("strong", { class: className }, [value])]);
}

function curve(points: { date: string; member: number; spy: number }[]): HTMLElement {
  const card = el("section", { class: "chart-card" });
  card.append(el("h2", { class: "section-title" }, ["Equity curve vs SPY"]));
  if (points.length < 2) {
    card.append(el("p", { class: "empty" }, ["Not enough overlapping sessions to draw a curve in this window."]));
    return card;
  }
  const width = 680;
  const height = 240;
  const pad = 28;
  const values = points.flatMap((point) => [point.member, point.spy]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (index: number) => pad + (index / (points.length - 1)) * (width - pad * 2);
  const y = (value: number) => height - pad - ((value - min) / span) * (height - pad * 2);
  const line = (key: "member" | "spy") => points.map((point, index) => `${x(index)},${y(point[key])}`).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "curve");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Indexed member return and matched SPY return, starting at 100");
  const axis = document.createElementNS("http://www.w3.org/2000/svg", "line");
  axis.setAttribute("x1", String(pad));
  axis.setAttribute("x2", String(width - pad));
  axis.setAttribute("y1", String(height - pad));
  axis.setAttribute("y2", String(height - pad));
  axis.setAttribute("stroke", "rgba(214,226,242,0.2)");
  const member = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  member.setAttribute("fill", "none");
  member.setAttribute("stroke", "#f0c14a");
  member.setAttribute("stroke-width", "3");
  member.setAttribute("points", line("member"));
  const spy = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  spy.setAttribute("fill", "none");
  spy.setAttribute("stroke", "#8fd4ff");
  spy.setAttribute("stroke-width", "2");
  spy.setAttribute("points", line("spy"));
  svg.append(axis, spy, member);
  const memberSwatch = el("i", { class: "swatch" });
  memberSwatch.style.background = "#f0c14a";
  const spySwatch = el("i", { class: "swatch" });
  spySwatch.style.background = "#8fd4ff";
  const legend = el("div", { class: "legend" });
  legend.append(
    el("span", {}, [memberSwatch, " Their holding periods"]),
    el("span", {}, [spySwatch, " SPY, same dates"]),
  );
  card.append(svg, legend, el("p", { class: "muted" }, ["Both lines start at 100. Flat stretches mean no open position."]));
  return card;
}

async function renderMember(id: string): Promise<void> {
  stopConfetti();
  const page = el("main", { class: "wrap" });
  page.append(el("p", { class: "loading" }, ["Pulling the card…"]));
  shell(page);
  let file: MemberFile;
  try {
    file = await fetchJson<MemberFile>(`data/members/${id}.json`);
  } catch {
    page.replaceChildren(el("div", { class: "error" }, ["That member card is not on this board."]));
    return;
  }
  const stats = (file.windows[state.window] || {}) as Partial<Row>;
  const head = el("div", { class: "member-head" });
  const avatar = el("div", { class: "avatar" }, [file.initials]);
  avatar.style.background = `hsl(${hue(file.bioguide_id)} 42% 36%)`;
  avatar.style.width = "72px";
  avatar.style.height = "72px";
  avatar.style.fontSize = "36px";
  head.append(
    avatar,
    el("div", {}, [
      el("h2", { class: "wordmark", style: "font-size:64px" }, [file.name]),
      el("p", { class: "tagline" }, [
        `${file.chamber} · ${place(file)} · ${file.party || "—"} · ${file.years_in_service} years in service`,
      ]),
    ]),
  );
  const onTime = (stats.filings || 0) - (stats.late_filings || 0);
  const ratio = stats.filings ? Math.max(0, onTime) / stats.filings : 0;
  const meter = el("div", { class: "meter", "aria-hidden": "true" });
  const fill = el("span");
  fill.style.width = `${Math.round(ratio * 100)}%`;
  meter.append(fill);
  page.replaceChildren(
    head,
    el("div", { class: "toolbar" }, [windowBar()]),
    el("div", { class: "stats" }, [
      stat("Rank", stats.benched || stats.rank == null ? "Bench" : `#${stats.rank}`),
      stat("Their return", pct(stats.return ?? null), tone(stats.return)),
      stat("Alpha vs S&P", pct(stats.alpha ?? null), tone(stats.alpha)),
      stat("Copycat return", pct(stats.copycat_return ?? null), tone(stats.copycat_return)),
    ]),
    badgeList((stats.badges as Badge[]) || [], Boolean(stats.on_fire)),
    curve(file.curves[state.window] || []),
    el("section", { class: "chart-card" }, [
      el("h2", { class: "section-title" }, ["Filing punctuality"]),
      el("p", {}, [
        stats.filings
          ? `${onTime} of ${stats.filings} filings in this window landed within ${league?.late_days ?? 45} days. Average lag ${stats.avg_filing_lag ?? "—"} days.`
          : "No disclosure date falls in this window.",
      ]),
      meter,
      el("p", { class: "muted" }, [
        `Excluded here or on the card: ${stats.excluded_options ?? 0} options, ${stats.excluded_non_stock ?? 0} other assets, ${stats.excluded_unknown ?? 0} unknown prices, ${stats.unmatched_sells ?? 0} unmatched sales, ${stats.uncopyable ?? 0} too late to copy.`,
      ]),
    ]),
    tradeTable(file.trades),
  );
}

function tradeTable(trades: TradeRow[]): HTMLElement {
  const card = el("section", { class: "table-card" });
  card.append(el("h2", { class: "section-title" }, ["Disclosed trades"]));
  const table = el("table", { class: "trades" });
  const head = el("tr");
  for (const label of ["Trade", "Filed", "Side", "Ticker", "Midpoint", "Lag", "Filing"]) head.append(el("th", {}, [label]));
  table.append(el("thead", {}, [head]));
  const body = el("tbody");
  for (const trade of trades) {
    const row = el("tr");
    const linkCell = el("td");
    const href = httpUrl(trade.source_url) || httpUrl(trade.disclosure_portal);
    if (href) {
      const anchor = el("a", { href, rel: "noreferrer", target: "_blank" }, [
        trade.source_url ? "Original filing" : "Official search",
      ]);
      linkCell.append(anchor);
    } else linkCell.textContent = "—";
    const lag = el("td", { class: trade.late ? "late" : "" }, [
      trade.lag_days == null ? "—" : `${trade.lag_days}d${trade.late ? " late" : ""}`,
    ]);
    row.append(
      el("td", {}, [trade.transaction_date ?? "—"]),
      el("td", {}, [trade.filed_date ?? "—"]),
      el("td", {}, [trade.side || "—"]),
      el("td", {}, [trade.included ? trade.symbol || "—" : `${trade.symbol || "—"} (${trade.exclude_reason || "out"})`]),
      el("td", {}, [money(trade.midpoint)]),
      lag,
      linkCell,
    );
    body.append(row);
  }
  table.append(body);
  card.append(table);
  return card;
}

// Disclosed filings over the whole record: a stable "how much is there to
// look at" score that does not depend on prices.
function activity(id: string): number {
  const all = league?.windows?.all;
  const row = all ? [...all.ranked, ...all.benched].find((item) => item.bioguide_id === id) : undefined;
  return row?.filings ?? 0;
}

function versusRows(): Row[] {
  const board = currentBoard();
  const benched = [...board.benched].sort(
    (a, b) => activity(b.bioguide_id) - activity(a.bioguide_id) || a.name.localeCompare(b.name),
  );
  return [...board.ranked, ...benched];
}

function renderVersus(): void {
  stopConfetti();
  const rows = versusRows();
  const lively = rows.filter((row) => row.rank != null || activity(row.bioguide_id) > 0);
  const pool = lively.length >= 2 ? lively : rows;
  if (!state.left) state.left = pool[0]?.bioguide_id || "";
  if (!state.right) state.right = pool.find((row) => row.bioguide_id !== state.left)?.bioguide_id || state.left;
  const page = el("main", { class: "wrap" });
  page.append(el("h2", { class: "section-title" }, ["Head to head"]), el("div", { class: "toolbar" }, [windowBar()]));
  const grid = el("div", { class: "versus-grid" });
  grid.append(versusCard("left", rows), el("div", { class: "versus" }, ["VS"]), versusCard("right", rows));
  page.append(grid, verdict(rows));
  shell(page);
}

function versusCard(side: "left" | "right", rows: Row[]): HTMLElement {
  const selected = rows.find((row) => row.bioguide_id === state[side]) || rows[0];
  const card = el("section", { class: "versus-card" });
  const select = el("select", { class: "pick", "aria-label": side === "left" ? "First member" : "Second member" }) as HTMLSelectElement;
  const groups: [string, Row[]][] = [
    ["Ranked", rows.filter((row) => row.rank != null)],
    ["Filed trades, not ranked yet", rows.filter((row) => row.rank == null && activity(row.bioguide_id) > 0)],
    ["No disclosed trades loaded yet", rows.filter((row) => row.rank == null && activity(row.bioguide_id) <= 0)],
  ];
  for (const [label, members] of groups) {
    if (!members.length) continue;
    const group = el("optgroup", { label }) as HTMLOptGroupElement;
    for (const row of members) {
      const option = el("option", { value: row.bioguide_id }, [`${row.name} · ${row.chamber}`]) as HTMLOptionElement;
      if (row.bioguide_id === selected?.bioguide_id) option.selected = true;
      group.append(option);
    }
    select.append(group);
  }
  select.addEventListener("change", () => {
    state[side] = select.value;
    render();
  });
  if (!selected) {
    card.append(el("p", {}, ["No members in this window."]));
    return card;
  }
  const avatar = el("div", { class: "avatar" }, [selected.initials]);
  avatar.style.background = `hsl(${hue(selected.bioguide_id)} 42% 36%)`;
  card.append(
    avatar,
    el("h3", {}, [selected.name]),
    el("p", { class: "muted" }, [`${selected.chamber} · ${place(selected)} · ${selected.party || "—"}`]),
    select,
    el("div", { class: "stats" }, [
      stat("Return", pct(selected.return), tone(selected.return)),
      stat("Alpha", pct(selected.alpha), tone(selected.alpha)),
      stat("Copycat", pct(selected.copycat_return), tone(selected.copycat_return)),
      stat("Trades", String(selected.trades)),
    ]),
    el("p", { class: "muted versus-note" }, [
      `${selected.filings} disclosed in this window · ${selected.trades} with a price so far · ${activity(selected.bioguide_id)} on record`,
    ]),
    badgeList(selected.badges, selected.on_fire),
  );
  return card;
}

function verdict(rows: Row[]): HTMLElement {
  const left = rows.find((row) => row.bioguide_id === state.left);
  const right = rows.find((row) => row.bioguide_id === state.right);
  const box = el("div", { class: "callout" });
  if (!left || !right) return box;
  if (left.bioguide_id === right.bioguide_id) {
    box.textContent = "Pick two different members. Mirrors are undefeated.";
    return box;
  }
  const a = left.copycat_return;
  const b = right.copycat_return;
  if (a == null && b == null) {
    const filed = left.filings + right.filings;
    box.textContent =
      left.trades + right.trades === 0 && filed > 0
        ? `${filed} filings between them, but no prices loaded yet. The matchup scores itself once prices land; they are pulled a few tickers a day.`
        : "Neither left a copyable position in this window. Try YTD or ALL.";
    return box;
  }
  if (a == null || b == null) {
    const winner = a == null ? right : left;
    box.textContent = `You'd rather copy ${winner.name}. The other side was already closed, or never got a price, by the time it was disclosed.`;
    return box;
  }
  if (Math.abs(a - b) < 0.0005) {
    box.textContent = "Too close to call. The disclosures shrug.";
    return box;
  }
  const winner = a > b ? left : right;
  box.textContent = `You'd rather copy ${winner.name}. Copycat return ${pct(winner.copycat_return)} if you waited for the filing.`;
  return box;
}

function parseRoute(): { name: "home" } | { name: "member"; id: string } | { name: "versus" } | { name: "stocks" } | { name: "filings" } {
  const hash = location.hash.replace(/^#/, "") || "/";
  const member = hash.match(/^\/member\/([A-Za-z0-9]+)$/);
  if (member) return { name: "member", id: member[1] };
  if (hash.startsWith("/versus")) return { name: "versus" };
  if (hash.startsWith("/stocks")) return { name: "stocks" };
  if (hash.startsWith("/filings")) return { name: "filings" };
  return { name: "home" };
}

function render(): void {
  const route = parseRoute();
  if (!league) return;
  if (route.name === "member") {
    void renderMember(route.id);
    return;
  }
  if (route.name === "versus") {
    renderVersus();
    return;
  }
  if (route.name === "stocks") {
    renderStocks();
    return;
  }
  if (route.name === "filings") {
    renderFilings();
    return;
  }
  renderHome();
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(String(response.status));
  return response.json() as Promise<T>;
}

async function boot(): Promise<void> {
  app.replaceChildren(el("main", { class: "wrap" }, [el("p", { class: "loading" }, ["Lighting the board…"])]));
  try {
    league = await fetchJson<League>("data/league.json");
  } catch {
    app.replaceChildren(
      el("main", { class: "wrap" }, [
        el("div", { class: "error" }, ["The league file did not load. Refresh, or rebuild the sample JSON."]),
      ]),
    );
    return;
  }
  // Open on the window with the most ranked members, so an early board
  // does not look empty just because the last 30 days are quiet.
  const counts = (["90d", "6m", "12m", "30d", "all"] as const).map((id) => [id, league?.windows?.[id]?.ranked?.length ?? 0] as const);
  const best = counts.reduce((a, b) => (b[1] > a[1] ? b : a));
  if ((league?.windows?.[state.window]?.ranked?.length ?? 0) === 0 && best[1] > 0) state.window = best[0];
  render();
}

window.addEventListener("hashchange", () => render());
void boot();
