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
  { id: "30d", label: "30D" },
  { id: "ytd", label: "YTD" },
  { id: "12m", label: "1Y" },
  { id: "all", label: "ALL" },
];
const HUES = [28, 46, 78, 152, 168, 188, 262, 282, 314, 332];
const BASE = import.meta.env.BASE_URL;
const REPO_URL = "https://github.com/bernhardbrugger/capitol-street-bets";
const PROFILE_URL = "https://github.com/bernhardbrugger";

type SortKey = "rank" | "return" | "alpha" | "trades" | "copycat" | "name";
const state: { window: string; sort: SortKey; dir: "asc" | "desc"; query: string; left: string; right: string } = {
  window: "30d",
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
function matches(row: Row): boolean {
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

function rowView(row: Row): HTMLAnchorElement {
  const link = el("a", {
    class: `row${row.rank === 1 ? " leader" : ""}${row.elevator ? " elevator" : ""}`,
    href: `#/member/${row.bioguide_id}`,
    "data-id": row.bioguide_id,
    "data-elevator": row.elevator ? "true" : "false",
    "data-on-fire": row.on_fire ? "true" : "false",
  });
  const rank = el("div", { class: "rank" }, [row.benched || row.rank == null ? "—" : String(row.rank)]);
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
  link.append(rank, changeNode(row), who, chamber, ret, alpha, trades, copy, badgeList(row.badges, row.on_fire));
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
  const home = el("a", { href: "#/" }, ["League"]);
  const versus = el("a", { href: "#/versus" }, ["Head to head"]);
  const method = el("a", { href: `${BASE}methodology.html` }, ["Methodology"]);
  const routeName = parseRoute().name;
  if (routeName === "home") home.setAttribute("aria-current", "page");
  if (routeName === "versus") versus.setAttribute("aria-current", "page");
  const repo = el("a", { href: REPO_URL, target: "_blank", rel: "noopener" }, ["GitHub ★"]);
  nav.append(home, versus, method, repo);
  top.append(brand, nav);
  app.append(top, body, footer());
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
  const bar = el("div", { class: "windows" });
  for (const item of WINDOWS) {
    const button = el("button", { type: "button", "aria-pressed": state.window === item.id ? "true" : "false" }, [item.label]);
    button.addEventListener("click", () => {
      state.window = item.id;
      render();
    });
    bar.append(button);
  }
  return bar;
}

function paintBoard(host: HTMLElement, rows: Row[]): void {
  host.replaceChildren(headerCells());
  const ranked = rows.filter((row) => !row.benched);
  const benched = rows.filter((row) => row.benched);
  if (!ranked.length && !benched.length) {
    host.append(el("p", { class: "empty" }, ["No one on the roster matches that."]));
    return;
  }
  for (const row of ranked) host.append(rowView(row));
  if (benched.length) {
    const details = el("details", { class: "bench" });
    details.open = true;
    details.append(el("summary", {}, [`Benched · ${benched.length} under ${league?.min_trades ?? 3} priced equity trades`]));
    const stack = el("div", { class: "board" });
    for (const row of benched) stack.append(rowView(row));
    details.append(stack);
    host.append(details);
  }
}

function renderHome(): void {
  const board = currentBoard();
  const page = el("main", { class: "wrap" });
  if (league?.sample) {
    page.append(
      el("div", { class: "banner", "data-sample": "true" }, [
        "Sample league. These members and prices are fictional, so you can click around before a real ingestion. Live disclosures replace this board once an Alpha Vantage key is configured.",
      ]),
    );
  }
  const tapeText = board.ticker_tape.length ? board.ticker_tape : ["The tape is quiet. Check back after the next snapshot."];
  const doubled = [...tapeText, ...tapeText];
  const track = el("div", { class: "tape-track" });
  for (const line of doubled) track.append(el("span", {}, [line]));
  page.append(el("div", { class: "tape", "aria-label": "Daily ticker tape" }, [track]));

  const behind = board.ranked.filter((row) => (row.alpha ?? 0) < -0.0001).length;
  const score = el("section", { class: "scorebug", "data-scorebug": "true" });
  score.append(
    el("div", { class: "team ahead" }, [
      el("div", { class: "label" }, ["CONGRESS"]),
      el("strong", { "data-beat": String(board.beat_market) }, [String(board.beat_market)]),
      el("em", {}, ["members ahead of SPY"]),
    ]),
    el("div", { class: "versus" }, ["VS"]),
    el("div", { class: "team behind" }, [
      el("div", { class: "label" }, ["THE MARKET"]),
      el("strong", {}, [String(behind)]),
      el("em", {}, ["members the S&P is ahead of"]),
    ]),
  );
  page.append(score);

  const tools = el("div", { class: "toolbar" });
  const search = el("input", { class: "search", type: "search", placeholder: "Find a member", value: state.query, "aria-label": "Find a member" }) as HTMLInputElement;
  search.addEventListener("input", () => {
    state.query = search.value;
    render();
    const next = document.querySelector<HTMLInputElement>(".search");
    next?.focus();
    const pos = next?.value.length ?? 0;
    next?.setSelectionRange(pos, pos);
  });
  tools.append(windowBar(), search);
  page.append(tools);
  page.append(
    el("p", { class: "meta-line" }, [
      `Scored ${board.as_of}. Arrows versus ${board.previous_date ?? "no prior snapshot"}. Ranked on alpha. Minimum ${league?.min_trades ?? 3} trades.`,
    ]),
  );

  const host = el("section", { class: "board", id: "board" });
  page.append(host);
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

function renderVersus(): void {
  stopConfetti();
  const rows = allRows();
  if (!state.left) state.left = rows[0]?.bioguide_id || "";
  if (!state.right) state.right = rows[1]?.bioguide_id || state.left;
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
  for (const row of rows) {
    const option = el("option", { value: row.bioguide_id }, [`${row.name} · ${row.chamber}`]) as HTMLOptionElement;
    if (row.bioguide_id === selected?.bioguide_id) option.selected = true;
    select.append(option);
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
    box.textContent = "Neither left a copyable position in this window.";
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

function parseRoute(): { name: "home" } | { name: "member"; id: string } | { name: "versus" } {
  const hash = location.hash.replace(/^#/, "") || "/";
  const member = hash.match(/^\/member\/([A-Za-z0-9]+)$/);
  if (member) return { name: "member", id: member[1] };
  if (hash.startsWith("/versus")) return { name: "versus" };
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
  render();
}

window.addEventListener("hashchange", () => render());
void boot();
