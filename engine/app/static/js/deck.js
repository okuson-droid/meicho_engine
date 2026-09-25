// デッキメーカー（M6・APP-014）。アーティファクト版「鳴潮：対決 デッキメーカー」を、仕様と画面そのままでアプリに取り込んだもの。
// 違いは 4 つだけ:
//  1. カードの一覧はサーバの /api/cards（エンジンが遊べる番号・数値・言い換えの文）から取る。読み込みは要らない。
//     手元の cards_structured.json（または CSV）を読むと、属性・武器・所属・レアリティ・公式のテキストを重ねる（このブラウザにだけ保管）
//  2. 画像はアプリの保管領域（art.js・APP-013）を使う。対局の盤面と同じものが出る
//  3. デッキはアプリのロビーと同じ置き場（localStorage の meichosim.decks）に入る。組んだデッキがそのまま部屋で選べる
//  4. 保存は、ブラウザの普通のダウンロードで行う
// 準拠: rules_draft §3 デッキ構築ルール（判定は engine の GameConfig.validate と同じ条件。部屋に入るときはサーバがもう一度確かめる）
// 公式のテキストも画像もアプリには入っていない（要件 R-ASSET-1）。どれもこの端末のブラウザの中だけにあり、どこにも送らない。
import * as art from "./art.js";
import { api } from "./net.js";
import { encodeDeck, decodeDeck, DeckCodeError } from "./deckcode.js";

const LS_CARDS = "meichosim.deckmaker.cards";     // 手元のファイルから重ねた公式の欄（番号ごと）
const LS_DECKS = "meichosim.decks";               // ロビーと同じ置き場。1 件 = {name, chara_deck, action_deck, id, description, art}
const LS_CUR   = "meichosim.deckmaker.current";
const LS_UI    = "meichosim.deckmaker.ui";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, txt) => { const n = document.createElement(tag); if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };
const esc = (s) => String(s ?? "");
const isNone = (v) => v == null || v === "" || v === "-";
const num = (v) => { const n = parseInt(v, 10); return Number.isFinite(n) ? n : null; };

/* ------------------------------- state ------------------------------- */
const S = {
  cards: [],           // deduped by code
  byCode: new Map(),
  images: art.allSlots(),   // 番号 → {base?, R?, SP?, PR?}（art.js の表をそのまま見る）
  base: [],            // /api/cards から作ったカード（FIELDS の形）
  decks: [],           // [{id,name,description,chara:[[code,n]],action:[[code,n]]}]
  deckId: null,
  filters: { q:"", type:new Set(), color:new Set(), cost:new Set(), level:new Set(),
             attribute:new Set(), weapon:new Set(), affiliation:new Set(), set:new Set(),
             ded:"", legal:false, indeck:false, hasimg:false },
  sort: "code",
  big: false,
  tab: "pool",
};

const deck = () => S.decks.find(d => d.id === S.deckId);
const entries = (arr) => Array.isArray(arr) ? arr : [];
const countOf = (list, code) => { const e = entries(list).find(x => x[0] === code); return e ? e[1] : 0; };
const totalOf = (list) => entries(list).reduce((a, x) => a + x[1], 0);

/* ---------------------------- storage utils --------------------------- */
function lsGet(k, fallback) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback; } catch { return fallback; } }
function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } }

/* ---------------------------- card DB loading ------------------------- */
const FIELDS = ["code","rarity","name","cost","type","color","level","speed","affiliation","damage","attribute","weapon","trait","effect","set","dedicated_to"];

function parseCSV(text) {
  const rows = []; let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i+1] === '"') { cell += '"'; i++; } else q = false; }
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
    else if (c !== "\r") cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  if (!rows.length) return [];
  const head = rows[0].map(h => h.trim());
  return rows.slice(1).filter(r => r.length > 1).map(r => {
    const o = {}; head.forEach((h, i) => o[h] = (r[i] ?? "").trim()); return o;
  });
}

const COLOR_JA = { red: "赤", blue: "青", green: "緑" };
// サーバの 1 枚を、アーティファクト版の行の形（FIELDS）にする。無い欄は "-"
function fromApi(code, c) {
  const o = {}; FIELDS.forEach(f => o[f] = "-");
  o.code = code; o.name = c.name || code;
  o.type = c.kind === "chara" ? "キャラカード" : "アクションカード";
  o.color = c.kind === "chara" ? "-" : (COLOR_JA[c.color] || "-");
  for (const f of ["cost", "speed", "damage", "level"]) if (c[f] != null) o[f] = String(c[f]);
  if (c.dedicated_to) o.dedicated_to = c.dedicated_to;
  if (Array.isArray(c.tags) && c.tags.length) o.trait = c.tags.join("、");
  if (Array.isArray(c.skills) && c.skills.length) o.effect = c.skills.join("\n");
  o.set = code.split("-")[0];
  o._src = "engine";
  return o;
}
function toCard(r) {
  const c = {}; for (const f of FIELDS) c[f] = r[f] == null ? "-" : String(r[f]).trim();
  c.kind = c.type.includes("キャラ") ? "chara" : "action";
  c.nCost = num(c.cost); c.nSpeed = num(c.speed); c.nDamage = num(c.damage); c.nLevel = num(c.level);
  c.traits = isNone(c.trait) ? [] : c.trait.split(/[、,]/).map(s => s.trim()).filter(Boolean);
  c.rarities = new Set(Array.isArray(r._r) ? r._r : (isNone(c.rarity) ? [] : [c.rarity]));
  c.src = r._src || "engine";
  return c;
}
// 公式の行（同じ番号が複数行あればレアリティを束ねる）→ 番号ごとの重ねる欄
const OVERLAY = ["rarity", "attribute", "weapon", "affiliation", "trait", "effect", "set"];
function overlayFrom(raw) {
  const out = {};
  for (const r of raw) {
    const code = String(r.code ?? "").trim().toUpperCase(); if (!code) continue;
    const o = out[code] || (out[code] = { _r: [] });
    for (const f of OVERLAY) if (o[f] == null && r[f] != null) o[f] = String(r[f]).trim();
    const rr = String(r.rarity ?? "").trim(); if (!isNone(rr) && !o._r.includes(rr)) o._r.push(rr);
  }
  return out;
}
// 遊べるカードはエンジンが持つ番号だけ（重ねる側にしか無い番号は入れない）
function buildCards() {
  const ov = lsGet(LS_CARDS, null) || {};
  const byCode = new Map();
  for (const b of S.base) {
    const o = ov[b.code];
    const row = { ...b };
    if (o) {                        // 重ねるのは文字の欄だけ。数値と種類はエンジンのものを正とする
      for (const f of OVERLAY) if (f !== "effect" && f !== "trait" && !isNone(o[f])) row[f] = o[f];
      row.effect = isNone(o.effect) ? "-" : o.effect;      // 特徴と効果は丸ごと入れ替える（エンジンのタグは属性・武器・所属を混ぜて持つので、残すと重なる）
      row.trait = isNone(o.trait) ? "-" : o.trait;
      row._src = "official";
      row._r = o._r;
    }
    byCode.set(row.code, toCard(row));
  }
  S.cards = [...byCode.values()];
  S.byCode = byCode;
}
function ingestCards(raw) {
  if (!Array.isArray(raw)) throw new Error("カードデータは配列である必要があります");
  const ov = overlayFrom(raw);
  const hit = S.base.filter(b => ov[b.code]).length;
  if (!hit) throw new Error("このアプリのカードと一致する番号が 0 件だった");
  lsSet(LS_CARDS, ov);
  buildCards(); buildFilterOptions(); render();
  toast(`公式のデータを重ねた（${raw.length} 行・このアプリのカードと一致 ${hit} 種）`);
}
function clearOverlay() { try { localStorage.removeItem(LS_CARDS); } catch {} buildCards(); buildFilterOptions(); render(); }
async function loadBaseCards() {
  const data = await api("/api/cards");
  S.base = Object.entries(data.cards || {}).map(([code, c]) => fromApi(code, c)).sort((a, b) => a.code.localeCompare(b.code));
  buildCards();
}

/* ------------------------------ images -------------------------------- */
/* 版（イラスト違い）はファイル名の接尾辞で決まる。cards/ 直下は接尾辞なし、
   cards/parallel/ に -R（別イラスト）・-SP（署名）・-PR（プロモ）が入る。
   Lv2 キャラでは 接尾辞なし=★3 / -R=★4 / -SP=★5 に対応する（cards/MANUAL_SHOTS_20260913.md）。 */
const IMG_RE = /^([A-Za-z]{2}\d{2}-\d{2,3})_[\s\S]*?(?:-(R|SP|PR))?\.(png|jpe?g|webp)$/i;
const VARIANTS = ["base", "R", "SP", "PR"];

function variantLabel(card, v) {
  const lv2 = card && card.kind === "chara" && card.nLevel === 2;
  if (v === "base") return lv2 ? "★3" : "通常";
  if (v === "R") return lv2 ? "★4" : "別イラスト";
  if (v === "SP") return lv2 ? "★5" : "署名";
  if (v === "PR") return "プロモ";
  return v;
}

async function ingestImages(fileList) {
  const r = await art.ingest(fileList);          // 盤面と同じ保管領域（APP-013）
  if (!r.added) { toast("カード画像として認識できるファイルがなかった（例: BP01-001_ツバキ_LV2.png）"); return; }
  render();
  toast(`画像 ${r.added} 枚を読み込んだ` + (r.saved ? "" : "。保存できなかったので、このタブを閉じるまで有効"));
}
const variantsOf = (code) => { const s = S.images.get(code); return s ? VARIANTS.filter(v => s[v]) : []; };
const imgOf = (code) => art.urlOf(code);

/* ------------------------------ deck model ---------------------------- */
function newDeck(name) {
  return { id: "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
           name: name || "新しいデッキ", description: "", chara: [], action: [] };
}
// ロビーと同じ置き場に、engine の decklists と同じ形（1 枚ずつ並べた番号）で入れる。id・説明・版は見た目のための追加の欄
function saveDecks() {
  lsSet(LS_DECKS, S.decks.map(deckToJSON).map((x, i) => ({ ...x, id: S.decks[i].id })));
  lsSet(LS_CUR, S.deckId);
}
function restoreDecks() {
  const saved = lsGet(LS_DECKS, null);
  S.decks = Array.isArray(saved) ? saved.filter(x => x && typeof x === "object").map(x => { const d = jsonToDeck(x); if (x.id) d.id = String(x.id); return d; }) : [];
  if (!S.decks.length) S.decks = [newDeck("新しいデッキ")];
  const cur = lsGet(LS_CUR, null);
  S.deckId = cur && S.decks.some(d => d.id === cur) ? cur : S.decks[0].id;
}
function limitFor(card) { return card.kind === "chara" ? 1 : 3; }   // §3.1-4 / §3.2-4
function listFor(d, card) { return card.kind === "chara" ? d.chara : d.action; }

/* 1 枚ごとのイラストの版。d.art[code] = ["base","base","R"] のように、その番号の枚数ぶん並ぶ。
   構築ルールは番号だけを数えるので、版は見た目の情報であり検証には関わらない。 */
function syncArt(d, code, n) {
  if (!d.art) d.art = {};
  if (n <= 0) { delete d.art[code]; return []; }
  const avail = variantsOf(code);
  const def = avail[0] || "base";
  const a = d.art[code] || (d.art[code] = []);
  while (a.length < n) a.push(def);
  a.length = n;
  // 画像がまだ読み込まれていない間は avail が空になるので、そのときは触らない
  if (avail.length) for (let i = 0; i < a.length; i++) if (!avail.includes(a[i])) a[i] = def;
  return a;
}

function setCount(code, n) {
  const d = deck(); const card = S.byCode.get(code); if (!d || !card) return;
  const list = listFor(d, card);
  n = Math.max(0, Math.min(limitFor(card), n));
  const i = list.findIndex(x => x[0] === code);
  if (n === 0) { if (i >= 0) list.splice(i, 1); }
  else if (i >= 0) list[i][1] = n;
  else list.push([code, n]);
  syncArt(d, code, n);
  saveDecks(); render();
}
const addCard = (code, delta) => { const c = S.byCode.get(code); if (!c) return; setCount(code, countOf(listFor(deck(), c), code) + delta); };

/* ---------------------- 構築ルール検証 (rules v0.9 §3) ------------------ */
function validateDeck() {
  const d = deck(); const out = [];
  const chara = d.chara.map(([code, n]) => ({ c: S.byCode.get(code), n, code })).filter(x => x.c);
  const action = d.action.map(([code, n]) => ({ c: S.byCode.get(code), n, code })).filter(x => x.c);
  const charaN = chara.reduce((a, x) => a + x.n, 0);
  const actionN = action.reduce((a, x) => a + x.n, 0);

  // --- 3.1 キャラデッキ ---
  const wrongKind1 = chara.filter(x => x.c.kind !== "chara");
  if (wrongKind1.length) out.push(["err", "キャラデッキにキャラカード以外が入っている", "3.1-1"]);

  const species = new Map();
  for (const x of chara) {
    const s = species.get(x.c.name) || { total: 0, lv0: 0 };
    s.total += x.n; if (x.c.nLevel === 0) s.lv0 += x.n;
    species.set(x.c.name, s);
  }
  const names = [...species.keys()];
  if (names.length < 3) out.push(["err", `キャラが ${names.length} 種類。ちょうど 3 種類にする`, "3.1-2"]);
  else if (names.length > 3) out.push(["err", `キャラが ${names.length} 種類（${names.join("・")}）。ちょうど 3 種類にする`, "3.1-2"]);
  else out.push(["ok", `キャラ 3 種類（${names.join("・")}）`, "3.1-2"]);

  const noLv0 = names.filter(n => species.get(n).lv0 < 1);
  if (noLv0.length) out.push(["err", `Lv0 が入っていないキャラ: ${noLv0.join("・")}`, "3.1-2"]);
  else if (names.length) out.push(["ok", "各キャラの Lv0 を投入済み", "3.1-2"]);

  if (charaN < 3) out.push(["err", `キャラデッキ ${charaN} 枚。3 枚以上必要`, "3.1-3"]);
  else if (charaN > 15) out.push(["err", `キャラデッキ ${charaN} 枚。15 枚以下にする`, "3.1-3"]);
  else out.push(["ok", `キャラデッキ ${charaN} 枚（3–15）`, "3.1-3"]);

  const over1 = chara.filter(x => x.n > 1);
  if (over1.length) out.push(["err", `同じ番号が 2 枚以上: ${over1.map(x => x.code).join(" ")}`, "3.1-4"]);

  // --- 3.2 アクションデッキ ---
  const wrongKind2 = action.filter(x => x.c.kind !== "action");
  if (wrongKind2.length) out.push(["err", "アクションデッキにアクションカード以外が入っている", "3.2-1"]);

  if (actionN !== 40) out.push([actionN > 40 ? "err" : "warn", `アクションデッキ ${actionN} 枚。ちょうど 40 枚にする（残り ${40 - actionN} 枚）`, "3.2-2"]);
  else out.push(["ok", "アクションデッキ 40 枚", "3.2-2"]);

  const allowed = new Set(names);
  const illegal = action.filter(x => !isNone(x.c.dedicated_to) && !allowed.has(x.c.dedicated_to));
  if (illegal.length) {
    const who = [...new Set(illegal.map(x => x.c.dedicated_to))].join("・");
    out.push(["err", `キャラデッキにいない ${who} の専用カードが ${illegal.reduce((a, x) => a + x.n, 0)} 枚`, "3.2-3"]);
  } else if (actionN) out.push(["ok", "専用カードの所属はすべて一致", "3.2-3"]);

  const over3 = action.filter(x => x.n > 3);
  if (over3.length) out.push(["err", `同じ番号が 4 枚以上: ${over3.map(x => x.code).join(" ")}`, "3.2-4"]);

  const illegalCodes = new Set(illegal.map(x => x.code));
  return { items: out, charaN, actionN, names, illegalCodes,
           legal: !out.some(i => i[0] === "err") && actionN === 40 };
}

/* ------------------------------ filtering ----------------------------- */
function poolCards() {
  const f = S.filters;
  const d = deck();
  const charaNames = new Set(d.chara.map(([c]) => S.byCode.get(c)).filter(Boolean).map(c => c.name));
  const q = f.q.trim().toLowerCase();
  let list = S.cards.filter(c => {
    if (f.type.size && !f.type.has(c.kind)) return false;
    if (f.color.size && !f.color.has(c.color)) return false;
    if (f.cost.size && !f.cost.has(c.cost)) return false;
    if (f.level.size && !f.level.has(c.level)) return false;
    if (f.attribute.size && !f.attribute.has(c.attribute)) return false;
    if (f.weapon.size && !f.weapon.has(c.weapon)) return false;
    if (f.affiliation.size && !f.affiliation.has(c.affiliation)) return false;
    if (f.set.size && ![...f.set].some(s => c.set.includes(s))) return false;
    if (f.ded) { if (f.ded === "__common__") { if (!isNone(c.dedicated_to)) return false; } else if (c.dedicated_to !== f.ded) return false; }
    if (f.hasimg && !imgOf(c.code)) return false;
    if (f.indeck && countOf(listFor(d, c), c.code) === 0) return false;
    if (f.legal && c.kind === "action" && !isNone(c.dedicated_to) && !charaNames.has(c.dedicated_to)) return false;
    if (q) {
      const hay = (c.name + " " + c.code + " " + c.effect + " " + c.trait + " " + c.dedicated_to).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const by = S.sort;
  const key = { cost: "nCost", speed: "nSpeed", damage: "nDamage", level: "nLevel" }[by];
  list.sort((a, b) => {
    if (by === "name") return a.name.localeCompare(b.name, "ja") || a.code.localeCompare(b.code);
    if (key) { const av = a[key], bv = b[key];
      if (av == null && bv == null) return a.code.localeCompare(b.code);
      if (av == null) return 1; if (bv == null) return -1;
      return av - bv || a.code.localeCompare(b.code); }
    return a.code.localeCompare(b.code);
  });
  return list;
}

/* ------------------------------ rendering ----------------------------- */
function render() { renderPool(); renderDeck(); updateStatus(); }

function updateStatus() {
  const n = S.cards.length;
  $("dot-cards").className = "dot " + (n ? "on" : "off");
  $("lbl-cards").textContent = n ? `カード ${n} 種` : "カード未読込";
  const withImg = S.cards.filter(c => imgOf(c.code)).length;
  const imgs = S.images.size;
  $("dot-imgs").className = "dot " + (imgs ? "on" : "off");
  $("lbl-imgs").textContent = imgs ? (n ? `画像 ${withImg}/${n}` : `画像 ${imgs} 種`) : "画像なし";
  const sets = [...new Set(S.cards.map(c => c.set).flatMap(s => s.split(/[、,]/)).map(s => s.trim()).filter(s => !isNone(s)))].sort();
  $("setline").textContent = sets.length ? sets.join(" / ") : "BP01 / SD01 / SD02";
}

function renderPool() {
  const body = $("pool-body");
  body.textContent = "";
  if (!S.cards.length) { $("pool-n").textContent = "0"; $("pool-of").textContent = ""; body.append(onboarding()); return; }
  const list = poolCards();
  $("pool-n").textContent = String(list.length);
  $("pool-of").textContent = list.length === S.cards.length ? "" : `/ ${S.cards.length}`;
  const grid = el("div", "grid" + (S.big ? " lg" : ""));
  const d = deck();
  for (const c of list) grid.append(tile(c, countOf(listFor(d, c), c.code)));
  body.append(grid);
}

function tile(c, n) {
  const t = el("div", "tile" + (n ? " in-deck" : ""));
  const art = el("div", "tile-art");
  const url = imgOf(c.code);
  if (url) { const im = el("img"); im.src = url; im.alt = c.name; im.loading = "lazy"; art.append(im); }
  else art.append(textCard(c));
  if (n) art.append(el("span", "badge-n", "×" + n));
  const add = el("div", "tile-add");
  if (n) { const m = el("button", "minus", "−"); m.title = "1 枚減らす"; m.onclick = (e) => { e.stopPropagation(); addCard(c.code, -1); }; add.append(m); }
  const p = el("button", null, "＋"); p.title = "1 枚入れる"; p.onclick = (e) => { e.stopPropagation(); addCard(c.code, 1); };
  add.append(p); art.append(add);
  t.append(art);
  const foot = el("div", "tile-foot");
  foot.append(el("span", "nm", c.name), el("span", "cd", c.code));
  t.append(foot);
  t.tabIndex = 0;
  t.onclick = () => openDetail(c.code);
  t.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(c.code); } };
  return t;
}

function textCard(c) {
  const w = el("div", "tc");
  w.dataset.color = c.color; w.dataset.kind = c.kind;
  const top = el("div", "tc-top");
  top.append(el("span", "tc-code", c.code));
  if (!isNone(c.cost)) top.append(el("span", "tc-cost", "◈" + c.cost));
  else if (!isNone(c.level)) top.append(el("span", "tc-cost", "Lv" + c.level));
  w.append(top, el("div", "tc-name", c.name));
  const sub = [c.attribute, c.weapon, c.affiliation].filter(x => !isNone(x)).join(" · ");
  if (sub) w.append(el("div", "tc-sub", sub));
  w.append(el("div", "tc-eff", isNone(c.effect) ? "（効果なし）" : c.effect));
  const foot = el("div", "tc-foot");
  if (!isNone(c.speed)) foot.append(el("span", null, "速 " + c.speed));
  if (!isNone(c.damage)) foot.append(el("span", null, "打 " + c.damage));
  if (!isNone(c.dedicated_to)) foot.append(el("span", null, c.dedicated_to));
  if (foot.childNodes.length) w.append(foot);
  return w;
}

function onboarding() {
  const w = el("div", "empty");
  w.append(el("h2", null, "カードの一覧を取れなかった"));
  w.append(el("p", null, "アプリのサーバに届かなかった。サーバが動いているか確かめて、ページを読み込み直してほしい。"));
  return w;
}

function renderDeck() {
  const d = deck();
  $("deck-name").value = d.name;
  $("deck-desc").value = d.description || "";
  const sel = $("deck-select");
  sel.textContent = "";
  for (const x of S.decks) { const o = el("option", null, x.name || "(無題)"); o.value = x.id; if (x.id === S.deckId) o.selected = true; sel.append(o); }
  $("deck-del").disabled = S.decks.length <= 1;

  const v = validateDeck();

  const cc = $("cnt-chara"), ca = $("cnt-action");
  cc.className = "counter" + (v.charaN === 0 ? "" : (v.charaN >= 3 && v.charaN <= 15 ? " ok" : " bad"));
  cc.querySelector(".v").innerHTML = v.charaN + '<small>/3–15</small>';
  ca.className = "counter" + (v.actionN === 0 ? "" : (v.actionN === 40 ? " ok" : " bad"));
  ca.querySelector(".v").innerHTML = v.actionN + '<small>/40</small>';

  const ck = $("checks"); ck.textContent = "";
  const order = { err: 0, warn: 1, ok: 2 };
  const items = [...v.items].sort((a, b) => order[a[0]] - order[b[0]]);
  if (!items.length) ck.append(el("div", "check ok", "—"));
  for (const [lvl, text, rule] of items) {
    const r = el("div", "check " + lvl);
    r.append(el("span", "ic", lvl === "err" ? "×" : lvl === "warn" ? "!" : "✓"));
    const t = el("span", null, text);
    t.append(el("span", "rule", "§" + rule));
    r.append(t); ck.append(r);
  }

  renderDeckList($("list-chara"), d.chara, v, "キャラカードがまだない。Lv0 を含めて 3 キャラ分を入れる。");
  renderDeckList($("list-action"), d.action, v, "アクションカードがまだない。ちょうど 40 枚にする。");
}

/* 並び順はデッキ欄と書き出す画像で共通にする。キャラは名前→レベル、アクションは色→コスト→番号。 */
function deckRows(list) {
  const rows = list.map(([code, n]) => ({ code, n, c: S.byCode.get(code) }));
  rows.sort((a, b) => {
    if (!a.c || !b.c) return 0;
    const co = { "赤": 0, "青": 1, "緑": 2 };
    const ac = co[a.c.color] ?? -1, bc = co[b.c.color] ?? -1;
    if (a.c.kind === "chara") return (a.c.name.localeCompare(b.c.name, "ja")) || ((a.c.nLevel ?? 0) - (b.c.nLevel ?? 0));
    return ac - bc || (a.c.nCost ?? 0) - (b.c.nCost ?? 0) || a.code.localeCompare(b.code);
  });
  return rows;
}

function renderDeckList(host, list, v, emptyText) {
  host.textContent = "";
  if (!list.length) { host.append(el("div", "dempty", emptyText)); return; }
  const rows = deckRows(list);
  for (const r of rows) {
    const row = el("div", "drow" + (v.illegalCodes.has(r.code) ? " illegal" : ""));
    if (r.c) { row.dataset.color = r.c.color; row.dataset.kind = r.c.kind; }
    row.append(el("span", "n", "×" + r.n));
    const info = el("div", "info");
    const nm = el("div", "nm", r.c ? r.c.name : r.code + "（不明なカード）");
    nm.title = r.c ? r.c.effect : "";
    nm.onclick = () => r.c && openDetail(r.code);
    info.append(nm);
    const meta = el("div", "meta");
    meta.append(el("span", null, r.code));
    if (r.c && !isNone(r.c.cost)) meta.append(el("span", null, "◈" + r.c.cost));
    if (r.c && !isNone(r.c.speed)) meta.append(el("span", null, "速" + r.c.speed));
    if (r.c && !isNone(r.c.damage)) meta.append(el("span", null, "打" + r.c.damage));
    if (r.c && !isNone(r.c.level)) meta.append(el("span", null, "Lv" + r.c.level));
    info.append(meta);
    if (r.c) {
      const avail = variantsOf(r.code);
      const art = syncArt(deck(), r.code, r.n);
      if (avail.length > 1) {
        const chips = el("div", "vchips");
        for (let i = 0; i < r.n; i++) {
          const b = el("button", "vchip", variantLabel(r.c, art[i]));
          b.title = (i + 1) + " 枚目の版を切り替える";
          b.onclick = () => {
            const cur = avail.indexOf(art[i]);
            art[i] = avail[(cur + 1) % avail.length];
            saveDecks(); renderDeck();
          };
          chips.append(b);
        }
        info.append(chips);
      }
    }
    row.append(info);
    const ctl = el("div", "ctl");
    const minus = el("button", null, "−"); minus.title = "減らす"; minus.onclick = () => addCard(r.code, -1);
    const plus = el("button", null, "＋"); plus.title = "増やす"; plus.onclick = () => addCard(r.code, 1);
    ctl.append(minus, plus); row.append(ctl);
    host.append(row);
  }
}

/* ------------------------------- detail ------------------------------- */
let detailCode = null;
function openDetail(code) {
  const c = S.byCode.get(code); if (!c) return;
  detailCode = code;
  closeScrim();
  const scrim = el("div", "scrim"); scrim.id = "scrim-detail";
  const panel = el("div", "panel detail");

  const art = el("div", "detail-art");
  const frame = el("div", "frame");
  const slot = S.images.get(code) || {};
  const avail = variantsOf(code);           // base → R → SP → PR の順。既定は先頭（Lv2 キャラなら ★3）
  let variant = avail[0] || null;
  const im = el("img");
  const paint = () => {
    frame.textContent = "";
    if (variant) { im.src = slot[variant]; im.alt = c.name + "（" + variantLabel(c, variant) + "）"; frame.append(im); }
    else { const tc = textCard(c); tc.style.position = "absolute"; frame.append(tc); }
  };
  paint();
  art.append(frame);
  if (avail.length > 1) {
    const seg = el("div", "seg");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "版を選ぶ");
    const btns = avail.map(v => {
      const b = el("button", null, variantLabel(c, v));
      b.onclick = () => { variant = v; sync(); };
      return b;
    });
    const sync = () => { btns.forEach((b, i) => b.setAttribute("aria-pressed", avail[i] === variant)); paint(); };
    sync(); seg.append(...btns); art.append(seg);
  } else if (!variant) {
    const nn = el("div", null, "画像未登録");
    nn.style.cssText = "font-size:11px;color:var(--faint);text-align:center";
    art.append(nn);
  }

  const body = el("div", "detail-body");
  body.append(el("h2", null, c.name), el("div", "detail-code", c.code));
  const tags = el("div", "tags");
  const push = (txt, cls) => { if (!isNone(txt)) tags.append(el("span", "tag " + (cls || ""), txt)); };
  push(c.type);
  if (!isNone(c.color)) tags.append(el("span", "tag k-" + ({ "赤": "red", "青": "blue", "緑": "green" }[c.color] || ""), c.color));
  if (!isNone(c.level)) push("Lv" + c.level, "k-em");
  push(c.attribute); push(c.weapon); push(c.affiliation);
  if (!isNone(c.dedicated_to)) push("専用: " + c.dedicated_to, "k-em");
  c.traits.forEach(t => push(t));
  body.append(tags);

  const stats = el("div", "stats");
  const stat = (k, val) => { const s = el("div", "stat"); s.append(el("div", "k", k), el("div", "v", isNone(val) ? "—" : val)); stats.append(s); };
  stat("コスト", c.cost); stat("速度", c.speed); stat("ダメージ", c.damage); stat("レベル", c.level);
  body.append(stats);
  body.append(el("div", "eff", isNone(c.effect) ? "（テキストなし）" : c.effect));
  const src = el("div", null, c.src === "official" ? "公式のテキスト（手元のファイルから。このブラウザの中だけ）" : "エンジンの処理の言い換えで、公式のテキストではない。「データ」から公式のカードデータを重ねられる");
  src.style.cssText = "font-size:10.5px;color:var(--faint);margin-top:6px";
  body.append(src);

  const dl = el("dl", "dl");
  const kv = (k, v2) => { dl.append(el("dt", null, k), el("dd", null, v2)); };
  kv("収録", c.set);
  kv("レアリティ", [...c.rarities].sort().join(" / ") || "—");
  kv("投入上限", limitFor(c) + " 枚");
  body.append(dl);

  const acts = el("div", "detail-actions");
  const n = countOf(listFor(deck(), c), code);
  const st = el("div", "stepper");
  const minus = el("button", null, "−"), cnt = el("div", "n", String(n)), plus = el("button", null, "＋");
  minus.onclick = () => { addCard(code, -1); cnt.textContent = String(countOf(listFor(deck(), c), code)); };
  plus.onclick = () => { addCard(code, 1); cnt.textContent = String(countOf(listFor(deck(), c), code)); };
  st.append(minus, cnt, plus);
  acts.append(st);
  const hint = el("span", null, (c.kind === "chara" ? "キャラデッキへ" : "アクションデッキへ") + "（上限 " + limitFor(c) + " 枚）");
  hint.style.cssText = "font-size:11.5px;color:var(--muted)";
  acts.append(hint);
  const close = el("button", "btn", "閉じる"); close.style.marginLeft = "auto"; close.onclick = closeScrim;
  acts.append(close);
  body.append(acts);

  panel.append(art, body);
  scrim.append(panel);
  scrim.onclick = (e) => { if (e.target === scrim) closeScrim(); };
  document.body.append(scrim);
  close.focus();
}
function closeScrim() { document.querySelectorAll(".scrim").forEach(n => n.remove()); detailCode = null; }

/* ------------------------------ data sheet ---------------------------- */
function openDataSheet() {
  closeScrim();
  const scrim = el("div", "scrim");
  const panel = el("div", "panel sheet");
  const head = el("div", "sheet-head");
  head.append(el("h2", null, "データ"));
  const x = el("button", "btn ghost", "閉じる"); x.onclick = closeScrim; head.append(x);
  const body = el("div", "sheet-body");

  const r1 = el("div", "srow");
  r1.append(el("h3", null, "公式のカードデータ（任意）"));
  r1.append(el("p", null, lsGet(LS_CARDS, null) ? `重ねてある。カードは ${S.cards.length} 種（アプリが遊べるもの）。別のファイルを選ぶと置き換わる。` : `カードの一覧（${S.cards.length} 種）はアプリが持っている。手元の cards/cards_structured.json（または CSV）を選ぶと、属性・武器・所属・レアリティ・公式のテキストを重ねる。このブラウザにだけ保管される。`));
  const b1 = el("div", "btns");
  const l1 = el("label", "filelabel", "ファイルを選ぶ"); l1.setAttribute("for", "in-cards"); b1.append(l1);
  if (lsGet(LS_CARDS, null)) { const c1 = el("button", "btn ghost", "消す"); c1.onclick = () => { clearOverlay(); closeScrim(); toast("重ねた公式のデータを消した（カードの一覧はそのまま）"); }; b1.append(c1); }
  r1.append(b1); body.append(r1);

  const r2 = el("div", "srow");
  r2.append(el("h3", null, "カード画像"));
  const withImg = S.cards.filter(c => imgOf(c.code)).length;
  r2.append(el("p", null, S.images.size ? `${S.images.size} 種の画像を保存済み（うちカードと一致 ${withImg} 種）。追加で選べば継ぎ足される。` : "未登録。フォルダごと選ぶのが早い。"));
  const b2 = el("div", "btns");
  const l2 = el("label", "filelabel", "フォルダを選ぶ"); l2.setAttribute("for", "in-imgdir");
  const l3 = el("label", "filelabel", "画像を選ぶ"); l3.setAttribute("for", "in-imgs");
  b2.append(l2, l3);
  if (S.images.size) { const c2 = el("button", "btn ghost", "すべて消す"); c2.onclick = async () => { await art.clear(); render(); closeScrim(); toast("画像を消した"); }; b2.append(c2); }
  r2.append(b2); body.append(r2);

  const r3 = el("div", "srow");
  r3.append(el("h3", null, "保存先について"));
  r3.append(el("p", null, "重ねた公式のデータ・デッキ・画像はすべてこのブラウザの中だけに保存され、外部には送信されない（部屋でデッキを選んだときだけ、そのデッキの番号の並びがサーバに送られる）。別の端末やブラウザで開いたときは、もう一度読み込む必要がある。"));
  body.append(r3);

  panel.append(head, body); scrim.append(panel);
  scrim.onclick = (e) => { if (e.target === scrim) closeScrim(); };
  document.body.append(scrim); x.focus();
}

/* ---------------------------- import / export ------------------------- */
function deckToJSON(d) {
  const expand = (list) => list.flatMap(([code, n]) => Array(n).fill(code));
  const arts = (list) => list.flatMap(([code, n]) => {
    const a = (d.art && d.art[code]) || [];
    return Array.from({ length: n }, (_, i) => a[i] || "base");
  });
  // art は見た目だけの情報。engine は chara_deck / action_deck しか読まないので無視される。
  return { name: d.name || "deck", description: d.description || "",
           chara_deck: expand(d.chara), action_deck: expand(d.action),
           art: { chara: arts(d.chara), action: arts(d.action) } };
}
function jsonToDeck(obj) {
  const collapse = (arr) => {
    const out = [];
    for (const code of (Array.isArray(arr) ? arr : [])) {
      const c = String(code).trim(); if (!c) continue;
      const e = out.find(x => x[0] === c); if (e) e[1]++; else out.push([c, 1]);
    }
    return out;
  };
  const d = newDeck(obj.name || "読み込んだデッキ");
  d.description = obj.description || "";
  d.chara = collapse(obj.chara_deck);
  d.action = collapse(obj.action_deck);
  d.art = {};
  const take = (codes, arts) => {
    if (!Array.isArray(codes) || !Array.isArray(arts)) return;
    codes.forEach((code, i) => {
      const c = String(code).trim(); if (!c) return;
      (d.art[c] = d.art[c] || []).push(VARIANTS.includes(arts[i]) ? arts[i] : "base");
    });
  };
  if (obj.art) { take(obj.chara_deck, obj.art.chara); take(obj.action_deck, obj.art.action); }
  return d;
}
async function exportDeck() {
  const d = deck();
  const text = JSON.stringify(deckToJSON(d), null, 2);
  const safe = (d.name || "deck").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60) || "deck";
  const filename = safe + ".json";
  if (saveFile(filename, new Blob([text], { type: "application/json" }))) { toast(`${filename} を保存した`); return; }
  showTextFallback(filename, text);
}
// ブラウザの普通のダウンロード。使えない環境（一部のスマホの埋め込み表示など）では false
function saveFile(filename, blob) {
  try {
    const url = URL.createObjectURL(blob);
    const a = el("a"); a.href = url; a.download = filename; a.style.display = "none";
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    return true;
  } catch { return false; }
}
function showTextFallback(filename, text) {
  closeScrim();
  const scrim = el("div", "scrim");
  const panel = el("div", "panel sheet");
  const head = el("div", "sheet-head");
  head.append(el("h2", null, filename));
  const x = el("button", "btn ghost", "閉じる"); x.onclick = closeScrim; head.append(x);
  const body = el("div", "sheet-body");
  const lead = el("p", null, "ファイルに保存できなかったので、内容をコピーして保存する。");
  lead.style.cssText = "font-size:11.5px;color:var(--muted);margin:10px 0";
  body.append(lead);
  const ta = el("textarea", "out"); ta.value = text; ta.readOnly = true; body.append(ta);
  const btns = el("div", "btns"); btns.style.cssText = "display:flex;gap:8px;margin-top:10px";
  const cp = el("button", "btn primary", "コピー");
  cp.onclick = async () => { try { await navigator.clipboard.writeText(text); toast("コピーした"); } catch { ta.select(); document.execCommand("copy"); toast("コピーした"); } };
  btns.append(cp); body.append(btns);
  panel.append(head, body); scrim.append(panel);
  scrim.onclick = (e) => { if (e.target === scrim) closeScrim(); };
  document.body.append(scrim); ta.focus(); ta.select();
}

/* ---------------------------- デッキコード（R-CODE・APP-018） ---------------------------- */
function codeSheet(title, lead, build) {
  closeScrim();
  const scrim = el("div", "scrim");
  const panel = el("div", "panel sheet"); panel.id = "code-sheet";
  const head = el("div", "sheet-head");
  head.append(el("h2", null, title));
  const x = el("button", "btn ghost", "閉じる"); x.onclick = closeScrim; head.append(x);
  const body = el("div", "sheet-body");
  const p = el("p", null, lead); p.style.cssText = "font-size:11.5px;color:var(--muted);margin:10px 0"; body.append(p);
  build(body);
  panel.append(head, body); scrim.append(panel);
  scrim.onclick = (e) => { if (e.target === scrim) closeScrim(); };
  document.body.append(scrim);
}
function exportCode() {
  const d = deck();
  if (!d.chara.length && !d.action.length) { toast("デッキが空なので、コードにできない"); return; }
  let code;
  try { code = encodeDeck(deckToJSON(d)); } catch (e) { toast(String(e.message || e)); return; }
  codeSheet("デッキコード", "カード番号と枚数だけを詰めた英数字の 1 行。通話のチャット欄などに貼れば、相手は「コードから読む」で同じデッキを作れる。デッキ名・メモ・画像の版は入らない。", (body) => {
    const ta = el("textarea", "out"); ta.id = "code-out"; ta.value = code; ta.readOnly = true; ta.rows = 3; body.append(ta);
    const btns = el("div", "btns"); btns.style.cssText = "display:flex;gap:8px;margin-top:10px";
    const cp = el("button", "btn primary", "コピー"); cp.id = "code-copy";
    cp.onclick = async () => { try { await navigator.clipboard.writeText(code); toast("コピーした"); } catch { ta.select(); document.execCommand("copy"); toast("コピーした"); } };
    btns.append(cp); body.append(btns);
    setTimeout(() => { ta.focus(); ta.select(); }, 0);
  });
}
function importCode() {
  codeSheet("コードから読む", "受け取ったデッキコード（英数字の 1 行）を貼る。新しいデッキとして入る。", (body) => {
    const ta = el("textarea", "out"); ta.id = "code-in"; ta.rows = 3; ta.placeholder = "例: 4fK2…"; body.append(ta);
    const name = el("input", "deckname"); name.id = "code-name"; name.value = "コードから読んだデッキ"; name.setAttribute("aria-label", "デッキ名"); name.style.marginTop = "8px"; body.append(name);
    const err = el("p", "code-err"); err.id = "code-err"; err.style.cssText = "color:var(--danger, #e66);font-size:12px;min-height:1.2em;margin:6px 0"; body.append(err);
    const btns = el("div", "btns"); btns.style.cssText = "display:flex;gap:8px;margin-top:4px";
    const go = el("button", "btn primary", "読み込む"); go.id = "code-load";
    go.onclick = () => {
      let parsed;
      const kindOf = S.cards.length ? (c) => (S.byCode.get(c) || {}).kind : null;   // カードの一覧が取れていれば、知らない番号も拒む
      try { parsed = decodeDeck(ta.value, kindOf); } catch (e) { err.textContent = e instanceof DeckCodeError ? e.message : "読めなかった: " + (e.message || e); return; }
      closeScrim();
      loadDeckObject({ ...parsed, name: (name.value || "").trim() || "コードから読んだデッキ" }, "デッキコード");
    };
    btns.append(go); body.append(btns);
    setTimeout(() => ta.focus(), 0);
  });
}

function loadDeckObject(obj, label) {
  const d = jsonToDeck(obj);
  const unknown = [...d.chara, ...d.action].map(([c]) => c).filter(c => S.cards.length && !S.byCode.has(c));
  S.decks.push(d); S.deckId = d.id; saveDecks(); render();
  toast(unknown.length ? `${label} を読み込んだ（未知の番号 ${[...new Set(unknown)].length} 件）` : `${label} を読み込んだ`);
}

/* ------------------- デッキを 1 枚の画像にする ------------------------ */
/* 8 列 × 7 段。上 2 段がキャラデッキ（8 枚 + 7 枚まで）、下 5 段がアクションデッキ（8×5=40）。
   キャラ 15・アクション 40 で 55 枚、枠は 56 なので 2 段目の右端が 1 つ空く。 */
const SHEET = { cols: 8, cw: 300, ch: 421, gap: 14, pad: 36, head: 136, cap: 50, blockGap: 26, r: 14 };

function deckSlots(d) {
  const flat = (list) => deckRows(list).flatMap(r => {
    const art = syncArt(d, r.code, r.n);
    return Array.from({ length: r.n }, (_, i) => ({ code: r.code, card: r.c, variant: art[i] || "base" }));
  });
  return { chara: flat(d.chara), action: flat(d.action) };
}
const charaRowCount = (n) => n <= 8 ? Math.max(1, Math.ceil(n / 8)) : (n <= 15 ? 2 : 2 + Math.ceil((n - 15) / 8));
function charaPos(i) {                       // 段 0 は 8 枚、段 1 は 7 枚まで
  if (i < 8) return [0, i];
  if (i < 15) return [1, i - 8];
  const j = i - 15; return [2 + Math.floor(j / 8), j % 8];
}

function loadImage(src) {
  return new Promise(res => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = src; });
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function wrapText(ctx, text, maxW, maxLines) {
  const out = []; let line = "";
  for (const ch of String(text)) {
    if (ctx.measureText(line + ch).width > maxW && line) { out.push(line); line = ch; if (out.length >= maxLines) return out; }
    else line += ch;
  }
  if (line && out.length < maxLines) out.push(line);
  return out;
}

async function buildDeckSheet(d) {
  const { chara, action } = deckSlots(d);
  const S_ = SHEET;
  const cRows = charaRowCount(chara.length);
  const aRows = Math.max(5, Math.ceil(action.length / 8));
  const gridW = S_.cols * S_.cw + (S_.cols - 1) * S_.gap;
  const W = S_.pad * 2 + gridW;
  const blockH = (rows) => rows * S_.ch + (rows - 1) * S_.gap;
  const charaTop = S_.pad + S_.head + S_.cap;
  const actionTop = charaTop + blockH(cRows) + S_.blockGap + S_.cap;
  const H = actionTop + blockH(aRows) + S_.pad;

  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  const INK = "#10161B", MUTED = "#5D6B74", LINE = "#D2DADE", PAPER = "#F5F7F8", HOLE = "#E4EAEC";
  const COL = { "赤": "#BB3B35", "青": "#2C6BB0", "緑": "#377F4C" };

  ctx.fillStyle = PAPER; ctx.fillRect(0, 0, W, H);
  try { await document.fonts.ready; } catch {}

  // 見出し
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = INK;
  ctx.font = '600 50px "Zen Old Mincho","Hiragino Mincho ProN",serif';
  ctx.fillText(d.name || "デッキ", S_.pad, S_.pad + 54);
  ctx.fillStyle = MUTED;
  ctx.font = '400 26px "JetBrains Mono",monospace';
  const counts = `キャラ ${chara.length} 枚 ／ アクション ${action.length} 枚`;
  ctx.textAlign = "right"; ctx.fillText(counts, W - S_.pad, S_.pad + 54); ctx.textAlign = "left";
  ctx.strokeStyle = LINE; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(S_.pad, S_.pad + 84); ctx.lineTo(W - S_.pad, S_.pad + 84); ctx.stroke();

  const caption = (text, y) => {
    ctx.fillStyle = MUTED;
    ctx.font = '700 22px "Zen Kaku Gothic New",sans-serif';
    ctx.fillText(text, S_.pad, y);
    const tw = ctx.measureText(text).width;
    ctx.strokeStyle = LINE; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(S_.pad + tw + 14, y - 7); ctx.lineTo(W - S_.pad, y - 7); ctx.stroke();
  };
  caption(`キャラデッキ ${chara.length} 枚`, charaTop - 18);
  caption(`アクションデッキ ${action.length} 枚`, actionTop - 18);

  // 画像は URL ごとに 1 回だけ読む
  const urls = new Set();
  for (const s of [...chara, ...action]) {
    const slot = S.images.get(s.code);
    const u = slot && (slot[s.variant] || imgOf(s.code));
    if (u) urls.add(u);
  }
  const cache = new Map();
  await Promise.all([...urls].map(async u => cache.set(u, await loadImage(u))));

  const drawSlot = (s, x, y) => {
    const w = S_.cw, h = S_.ch;
    const slot = S.images.get(s.code) || {};
    const im = cache.get(slot[s.variant] || imgOf(s.code));
    ctx.save(); roundRect(ctx, x, y, w, h, S_.r); ctx.clip();
    if (im) {
      const sr = im.width / im.height, dr = w / h;
      let sw = im.width, sh = im.height, sx = 0, sy = 0;
      if (sr > dr) { sw = im.height * dr; sx = (im.width - sw) / 2; }
      else { sh = im.width / dr; sy = (im.height - sh) / 2; }
      ctx.drawImage(im, sx, sy, sw, sh, x, y, w, h);
    } else {
      ctx.fillStyle = HOLE; ctx.fillRect(x, y, w, h);
      const c = s.card;
      ctx.fillStyle = (c && COL[c.color]) || "#B7C2C8";
      ctx.fillRect(x, y, 8, h);
      ctx.fillStyle = MUTED;
      ctx.font = '400 17px "JetBrains Mono",monospace';
      ctx.fillText(s.code, x + 22, y + 34);
      ctx.fillStyle = INK;
      ctx.font = '600 26px "Zen Old Mincho","Hiragino Mincho ProN",serif';
      wrapText(ctx, c ? c.name : "不明なカード", w - 40, 3).forEach((ln, i) => ctx.fillText(ln, x + 22, y + 74 + i * 32));
      if (c) {
        ctx.fillStyle = MUTED;
        ctx.font = '400 17px "JetBrains Mono",monospace';
        const bits = [isNone(c.cost) ? null : "◈" + c.cost, isNone(c.speed) ? null : "速" + c.speed,
                      isNone(c.damage) ? null : "打" + c.damage, isNone(c.level) ? null : "Lv" + c.level].filter(Boolean);
        ctx.fillText(bits.join("  "), x + 22, y + h - 24);
      }
    }
    ctx.restore();
    ctx.strokeStyle = LINE; ctx.lineWidth = 2;
    roundRect(ctx, x + 1, y + 1, w - 2, h - 2, S_.r); ctx.stroke();
  };

  const colX = (col) => S_.pad + col * (S_.cw + S_.gap);
  chara.forEach((s, i) => { const [row, col] = charaPos(i); drawSlot(s, colX(col), charaTop + row * (S_.ch + S_.gap)); });
  action.forEach((s, i) => { drawSlot(s, colX(i % 8), actionTop + Math.floor(i / 8) * (S_.ch + S_.gap)); });

  return new Promise(res => cv.toBlob(b => res({ blob: b, canvas: cv, width: W, height: H }), "image/png"));
}

async function exportDeckImage() {
  const d = deck();
  if (!d.chara.length && !d.action.length) { toast("デッキが空なので画像にできない"); return; }
  toast("画像を作っている…");
  let sheet;
  try { sheet = await buildDeckSheet(d); }
  catch (e) { toast("画像を作れなかった: " + (e.message || e)); return; }
  if (!sheet || !sheet.blob) { toast("画像を作れなかった"); return; }
  openSheetPreview(d, sheet);
}

function openSheetPreview(d, sheet) {
  closeScrim();
  const url = URL.createObjectURL(sheet.blob);
  const scrim = el("div", "scrim");
  const panel = el("div", "panel sheet");
  panel.style.maxWidth = "820px";
  const head = el("div", "sheet-head");
  head.append(el("h2", null, "デッキ画像"));
  const x = el("button", "btn ghost", "閉じる");
  const done = () => { URL.revokeObjectURL(url); closeScrim(); };
  x.onclick = done; head.append(x);
  const body = el("div", "sheet-body");
  const info = el("p", null, `${sheet.width} × ${sheet.height} px ／ ${(sheet.blob.size / 1048576).toFixed(1)} MB`);
  info.style.cssText = "font-size:11.5px;color:var(--muted);margin:10px 0";
  body.append(info);
  const im = el("img"); im.src = url; im.alt = (d.name || "デッキ") + " の一覧";
  im.style.cssText = "width:100%;height:auto;border:1px solid var(--line);border-radius:var(--r);display:block";
  body.append(im);
  const btns = el("div"); btns.style.cssText = "display:flex;gap:8px;margin-top:14px;align-items:center";
  const safe = (d.name || "deck").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60) || "deck";
  const saveAs = async (ext, blob) => {
    if (saveFile(safe + "." + ext, blob)) toast(safe + "." + ext + " を保存した");
    else toast("この環境では保存が使えない。画像を長押し／右クリックで保存する");
  };
  const save = el("button", "btn primary", "PNG を保存");
  save.onclick = () => saveAs("png", sheet.blob);
  const saveJpg = el("button", "btn", "JPEG で保存（軽い）");
  saveJpg.onclick = () => {
    if (!sheet.canvas) { toast("JPEG に変換できなかった"); return; }
    sheet.canvas.toBlob(b => { if (b) saveAs("jpg", b); else toast("JPEG に変換できなかった"); }, "image/jpeg", 0.92);
  };
  btns.append(save, saveJpg); body.append(btns);
  panel.append(head, body); scrim.append(panel);
  scrim.onclick = (e) => { if (e.target === scrim) done(); };
  document.body.append(scrim); save.focus();
}

/* ------------------------------ filter UI ----------------------------- */
function chipRow(hostId, key, values, labels, extraCls) {
  const host = $(hostId); host.textContent = "";
  values.forEach((v, i) => {
    const b = el("button", "chip" + (extraCls ? " " + extraCls(v) : ""), labels ? labels[i] : v);
    b.setAttribute("aria-pressed", S.filters[key].has(v));
    b.onclick = () => {
      const s = S.filters[key];
      s.has(v) ? s.delete(v) : s.add(v);
      b.setAttribute("aria-pressed", s.has(v));
      renderPool();
    };
    host.append(b);
  });
}
function uniq(field) {
  return [...new Set(S.cards.map(c => c[field]).filter(v => !isNone(v)))]
    .sort((a, b) => (num(a) != null && num(b) != null) ? num(a) - num(b) : a.localeCompare(b, "ja"));
}
function buildFilterOptions() {
  chipRow("f-type", "type", ["chara", "action"], ["キャラ", "アクション"]);
  chipRow("f-color", "color", ["赤", "青", "緑"].filter(v => S.cards.some(c => c.color === v)), null,
          (v) => "c-" + ({ "赤": "red", "青": "blue", "緑": "green" }[v]));
  chipRow("f-cost", "cost", uniq("cost"), uniq("cost").map(v => "◈" + v));
  chipRow("f-level", "level", uniq("level"), uniq("level").map(v => "Lv" + v));
  chipRow("f-attribute", "attribute", uniq("attribute"));
  chipRow("f-weapon", "weapon", uniq("weapon"));
  chipRow("f-affiliation", "affiliation", uniq("affiliation"));
  const sets = [...new Set(S.cards.flatMap(c => c.set.split(/[、,]/).map(s => s.trim())).filter(s => !isNone(s)))].sort();
  chipRow("f-set", "set", sets);
  for (const id of ["f-attribute", "f-weapon", "f-affiliation", "f-set", "f-cost", "f-level"]) {   // 値が無い絞り込みは出さない（公式のデータを重ねるまで、属性・武器・所属は空）
    const g = $(id).closest(".fgroup"); if (g) g.hidden = !$(id).childElementCount;
  }
  const sel = $("f-ded"); sel.textContent = "";
  const all = el("option", null, "すべて"); all.value = ""; sel.append(all);
  const common = el("option", null, "共通（専用でない）"); common.value = "__common__"; sel.append(common);
  for (const v of uniq("dedicated_to")) { const o = el("option", null, v); o.value = v; sel.append(o); }
  sel.value = S.filters.ded;
}

/* -------------------------------- toast ------------------------------- */
let toastTimer = null;
function toast(msg) {
  document.querySelectorAll(".toast").forEach(n => n.remove());
  const t = el("div", "toast", msg);
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 3600);
}

/* ------------------------------- file in ------------------------------ */
async function readCardFile(file) {
  const text = await file.text();
  try {
    let raw;
    if (/\.csv$/i.test(file.name)) raw = parseCSV(text);
    else {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) raw = parsed;
      else if (parsed && Array.isArray(parsed.cards)) raw = parsed.cards;
      else if (parsed && Array.isArray(parsed.chara_deck)) { loadDeckObject(parsed, file.name); return; }
      else throw new Error("配列でも cards でもない");
    }
    ingestCards(raw);
    closeScrim();
  } catch (e) {
    toast("読み込めなかった: " + (e.message || e));
  }
}
async function readAnyFiles(files) {
  const arr = [...files];
  const imgs = arr.filter(f => IMG_RE.test(f.name));
  const data = arr.filter(f => /\.(json|csv)$/i.test(f.name));
  if (imgs.length) await ingestImages(imgs);
  for (const f of data) await readCardFile(f);
  if (!imgs.length && !data.length) toast("JSON / CSV / カード画像のいずれかを渡す");
}

/* -------------------------------- wiring ------------------------------ */
function hiddenInput(id, attrs, handler) {
  const i = el("input"); i.type = "file"; i.id = id; i.hidden = true;
  Object.entries(attrs).forEach(([k, v]) => v === true ? i.setAttribute(k, "") : i.setAttribute(k, v));
  i.addEventListener("change", async () => { if (i.files && i.files.length) await handler(i.files); i.value = ""; });
  document.body.append(i);
}

function setTab(name) {
  S.tab = name;
  $("pane-filter").classList.toggle("active", name === "filter");
  $("pane-pool").classList.toggle("active", name === "pool");
  $("pane-deck").classList.toggle("active", name === "deck");
  ["filter", "pool", "deck"].forEach(n => $("tab-" + n).setAttribute("aria-pressed", n === name));
}

async function boot() {
  hiddenInput("in-cards", { accept: ".json,.csv" }, (fs) => readCardFile(fs[0]));
  hiddenInput("in-imgdir", { webkitdirectory: true, directory: true, multiple: true }, ingestImages);
  hiddenInput("in-imgs", { accept: "image/*", multiple: true }, ingestImages);

  restoreDecks();
  try { await loadBaseCards(); } catch { S.cards = []; S.byCode = new Map(); }
  buildFilterOptions();
  render();
  art.onChange(() => render());
  art.restore();                  // 入ったら onChange で描き直す

  const ui = lsGet(LS_UI, null);
  if (ui) { S.sort = ui.sort || "code"; S.big = !!ui.big; $("sort").value = S.sort;
            $("size-s").setAttribute("aria-pressed", !S.big); $("size-l").setAttribute("aria-pressed", S.big); }

  // filters
  let qTimer = null;
  $("f-q").addEventListener("input", (e) => { S.filters.q = e.target.value; clearTimeout(qTimer); qTimer = setTimeout(renderPool, 120); });
  $("f-ded").addEventListener("change", (e) => { S.filters.ded = e.target.value; renderPool(); });
  ["legal", "indeck", "hasimg"].forEach(k => $("f-" + k).addEventListener("change", (e) => { S.filters[k] = e.target.checked; renderPool(); }));
  $("f-reset").addEventListener("click", () => {
    S.filters = { q:"", type:new Set(), color:new Set(), cost:new Set(), level:new Set(),
                  attribute:new Set(), weapon:new Set(), affiliation:new Set(), set:new Set(),
                  ded:"", legal:false, indeck:false, hasimg:false };
    $("f-q").value = ""; ["legal", "indeck", "hasimg"].forEach(k => $("f-" + k).checked = false);
    buildFilterOptions(); renderPool();
  });

  // pool bar
  $("sort").addEventListener("change", (e) => { S.sort = e.target.value; lsSet(LS_UI, { sort: S.sort, big: S.big }); renderPool(); });
  const setSize = (big) => { S.big = big; $("size-s").setAttribute("aria-pressed", !big); $("size-l").setAttribute("aria-pressed", big); lsSet(LS_UI, { sort: S.sort, big: S.big }); renderPool(); };
  $("size-s").addEventListener("click", () => setSize(false));
  $("size-l").addEventListener("click", () => setSize(true));

  // deck management
  $("deck-select").addEventListener("change", (e) => { S.deckId = e.target.value; saveDecks(); render(); });
  $("deck-name").addEventListener("input", (e) => { deck().name = e.target.value; saveDecks();
    const o = [...$("deck-select").options].find(o => o.value === S.deckId); if (o) o.textContent = e.target.value || "(無題)"; });
  $("deck-desc").addEventListener("input", (e) => { deck().description = e.target.value; saveDecks(); });
  $("deck-new").addEventListener("click", () => { const d = newDeck("新しいデッキ " + (S.decks.length + 1)); S.decks.push(d); S.deckId = d.id; saveDecks(); render(); $("deck-name").focus(); $("deck-name").select(); });
  $("deck-dup").addEventListener("click", () => { const s = deck(); const d = newDeck(s.name + " の写し"); d.description = s.description; d.chara = s.chara.map(x => [...x]); d.action = s.action.map(x => [...x]); S.decks.push(d); S.deckId = d.id; saveDecks(); render(); });
  $("deck-del").addEventListener("click", () => {
    if (S.decks.length <= 1) return;
    const i = S.decks.findIndex(d => d.id === S.deckId);
    S.decks.splice(i, 1); S.deckId = S.decks[Math.max(0, i - 1)].id; saveDecks(); render(); toast("デッキを削除した");
  });
  $("deck-clear").addEventListener("click", () => { const d = deck(); d.chara = []; d.action = []; saveDecks(); render(); });
  $("deck-export").addEventListener("click", exportDeck);
  $("deck-code").addEventListener("click", exportCode);
  $("deck-code-in").addEventListener("click", importCode);
  $("deck-image").addEventListener("click", exportDeckImage);
  $("deck-import").addEventListener("change", async (e) => {
    const f = e.target.files && e.target.files[0]; e.target.value = "";
    if (!f) return;
    try { loadDeckObject(JSON.parse(await f.text()), f.name); } catch (err) { toast("デッキファイルを読み込めなかった: " + (err.message || err)); }
  });

  $("btn-data").addEventListener("click", openDataSheet);
  ["filter", "pool", "deck"].forEach(n => $("tab-" + n).addEventListener("click", () => setTab(n)));

  // keyboard
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeScrim();
    if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); setTab("filter"); $("f-q").focus(); }
  });

  // drag & drop
  let dragDepth = 0, zone = null;
  const showZone = () => { if (zone) return; zone = el("div", "dropzone"); zone.append(el("div", null, "ここに落とす")); document.body.append(zone); };
  const hideZone = () => { if (zone) { zone.remove(); zone = null; } };
  window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; showZone(); });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) hideZone(); });
  window.addEventListener("drop", async (e) => {
    e.preventDefault(); dragDepth = 0; hideZone();
    if (e.dataTransfer && e.dataTransfer.files.length) await readAnyFiles(e.dataTransfer.files);
  });
}

boot();
