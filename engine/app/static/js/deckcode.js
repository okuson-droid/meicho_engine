// デッキコード（要件 R-CODE-1〜3・R-EXT-9・R-EXT-10・R-EXT-13・APP-018／APP-018 追記 1）。デッキを英数字だけの短い 1 行にし、文字列からデッキを戻す。
// 中身はカード番号と枚数と形式の版だけ。カード名とテキストは入れない。デッキメーカーとロビーの読み込みがこの 1 か所を使う。
//
// 版 2（いまの形・英数字 62 種だけ）: ビット列を 1 つの大きな整数にして 62 進で書く。長さは実測を APP-018 追記 1 に書いた（SD001・SD02 で 25 字前後、自分で組んだデッキで 30 字台）。
//   ビット列 = 目印 1 ＋ 版（4 ビット）＋ キャラの欄 ＋ アクションの欄 ＋ 検査用の 8 ビット（CRC-8）
//   欄       = 収録の数 ＋ 収録ごとに［収録の名前・（表に無い収録だけ）番号の桁・カードの数・（番号の差・枚数）×カードの数］
//   枚数     = キャラは γ（ふつう 1 枚で 1 ビット）、アクションは 2 ビット（1〜3 枚。4 枚以上は続けて γ）
//   数はすべて Elias γ 符号（小さい数ほど短い）。番号は番号順に並べて「前の番号との差」で書く（連番のデッキほど短い）
//   収録の名前は、よく使うものは表の番号（KNOWN_SETS。後ろに足すだけで、並べ替えない）、表に無いものは文字そのものを書く
//   （SD・BP 以外の新しい接頭辞でも書けて読める・R-EXT-10）
// 圧縮しても英数字 8 字前後には収まらない（8 字は約 48 ビット、デッキの中身は最小でも約 120 ビット）。APP-018 追記 1 を参照。
// 版 1（`MS1:C…/A…` の読める形・2026-09-22 の数時間だけ出していた）も読める。

export const DECK_CODE_VERSION = 2;
export const KNOWN_SETS = ["SD01", "SD02", "BP01"];      // ★後ろに足すだけ。並べ替えると古いコードが別のカードになる
const B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const CARD_RE = /^([A-Z]{2,4})(\d{0,3})-(\d{2,5})$/;

export class DeckCodeError extends Error {}

// ---------------------------------------------------------------- ビット列
class Bits {
  constructor(s = "") { this.s = s; this.i = 0; }
  put(v, n) { for (let k = n - 1; k >= 0; k--) this.s += (v >> k) & 1; }
  gamma(v) {                                   // v >= 1
    const b = v.toString(2);
    this.s += "0".repeat(b.length - 1) + b;
  }
  take(n) {
    if (this.i + n > this.s.length) throw new DeckCodeError("コードが途中で切れている。全部をコピーできているか確かめてほしい");
    const v = parseInt(this.s.slice(this.i, this.i + n), 2); this.i += n; return v;
  }
  ungamma() {
    let z = 0;
    while (this.s[this.i] === "0") { z++; this.i++; if (z > 24) throw new DeckCodeError("コードの形が壊れている"); }
    if (this.i >= this.s.length) throw new DeckCodeError("コードが途中で切れている。全部をコピーできているか確かめてほしい");
    return this.take(z + 1);
  }
}

function crc8(bits) {                          // 多項式 0x07。文字の書き間違い・欠けを見つけるため
  let c = 0;
  for (const ch of bits) {
    const top = ((c >> 7) & 1) ^ (ch === "1" ? 1 : 0);
    c = ((c << 1) & 0xff) ^ (top ? 0x07 : 0);
  }
  return c;
}

function toB62(bits) {
  let n = BigInt("0b" + bits), out = "";
  while (n > 0n) { out = B62[Number(n % 62n)] + out; n /= 62n; }
  return out || "0";
}
function fromB62(text) {
  let n = 0n;
  for (const ch of text) {
    const d = B62.indexOf(ch);
    if (d < 0) throw new DeckCodeError(`コードに使わない文字「${ch}」が入っている（英数字だけのはず）`);
    n = n * 62n + BigInt(d);
  }
  return n.toString(2);
}

// ---------------------------------------------------------------- 収録の名前
function putSet(b, set) {
  const k = KNOWN_SETS.indexOf(set);
  if (k >= 0) { b.gamma(k + 2); return; }      // 表にある: 2 以上
  b.gamma(1);                                  // 1 = 文字そのものを書く
  const [, letters, digits] = /^([A-Z]{2,4})(\d{0,3})$/.exec(set);
  b.put(letters.length - 2, 2);
  for (const ch of letters) b.put(ch.charCodeAt(0) - 65, 5);
  b.put(digits.length, 2);
  if (digits.length) b.put(Number(digits), 10);
}
function takeSet(b) {
  const k = b.ungamma();
  if (k >= 2) {
    const set = KNOWN_SETS[k - 2];
    if (!set) throw new DeckCodeError("このアプリが知らない収録が入っている（アプリが古いか、コードが違う）");
    return set;
  }
  let letters = "";
  const nl = b.take(2) + 2;
  for (let i = 0; i < nl; i++) { const c = b.take(5); if (c > 25) throw new DeckCodeError("コードの形が壊れている"); letters += String.fromCharCode(65 + c); }
  const nd = b.take(2);
  const digits = nd ? String(b.take(10)).padStart(nd, "0") : "";
  if (digits.length > nd) throw new DeckCodeError("コードの形が壊れている");
  return letters + digits;
}

// ---------------------------------------------------------------- 欄
function putCount(b, n, action) {
  if (!action) { b.gamma(n); return; }         // キャラはふつう 1 枚ずつ（γ なら 1 ビット）
  if (n <= 3) { b.put(n - 1, 2); return; }     // アクションはふつう 1〜3 枚（2 ビット）。4 枚以上は 3 の後に γ で足す
  b.put(3, 2); b.gamma(n - 3);
}
function takeCount(b, action) {
  if (!action) return b.ungamma();
  const v = b.take(2);
  return v < 3 ? v + 1 : 3 + b.ungamma();
}
function putPart(b, list, action) {
  const bySet = new Map();
  for (const raw of list || []) {
    const cid = String(raw).trim();
    const m = CARD_RE.exec(cid);
    if (!m) throw new DeckCodeError(`コードにできないカード番号: ${cid}`);
    const set = m[1] + m[2];
    if (!bySet.has(set)) bySet.set(set, new Map());
    const nums = bySet.get(set); const key = m[3];
    nums.set(key, (nums.get(key) || 0) + 1);
  }
  const sets = [...bySet.keys()].sort();
  b.gamma(sets.length + 1);
  for (const set of sets) {
    putSet(b, set);
    const entries = [...bySet.get(set)].sort((x, y) => Number(x[0]) - Number(y[0]));
    const width = entries[0][0].length;
    if (entries.some(([k]) => k.length !== width)) throw new DeckCodeError(`${set} の番号の桁がそろっていない`);
    if (KNOWN_SETS.includes(set)) { if (width !== 3) throw new DeckCodeError(`${set} の番号は 3 桁のはず`); }
    else b.put(width - 2, 2);                  // 番号の桁（表にある収録は 3 桁。表に無い収録だけ 2〜5 を書く）
    b.gamma(entries.length);
    let prev = -1;
    for (const [key, n] of entries) {
      const num = Number(key);
      b.gamma(num - prev); prev = num;         // 差は 1 以上（番号 0 も書ける）
      putCount(b, n, action);
    }
  }
}
function takePart(b, action) {
  const out = [];
  const nsets = b.ungamma() - 1;
  for (let s = 0; s < nsets; s++) {
    const set = takeSet(b);
    const width = KNOWN_SETS.includes(set) ? 3 : b.take(2) + 2;
    const count = b.ungamma();
    let prev = -1;
    for (let i = 0; i < count; i++) {
      const num = prev + b.ungamma(); prev = num;
      const n = takeCount(b, action);
      if (n > 60) throw new DeckCodeError("コードの形が壊れている（枚数が多すぎる）");
      const key = String(num).padStart(width, "0");
      if (key.length > width) throw new DeckCodeError("コードの形が壊れている");
      for (let k = 0; k < n; k++) out.push(`${set}-${key}`);
    }
  }
  return out;
}

// { chara_deck: [...], action_deck: [...] }（decklists と同じ形・1 枚ずつ並べた番号）→ コード
export function encodeDeck(deck) {
  const b = new Bits();
  b.put(DECK_CODE_VERSION, 4);
  putPart(b, deck.chara_deck, false);
  putPart(b, deck.action_deck, true);
  b.put(crc8(b.s), 8);
  return toB62("1" + b.s);                     // 先頭の 1 は、頭の 0 が消えないための目印
}

// コード → { chara_deck, action_deck }。`kindOf(cid)` を渡すと、知らない番号と欄の取り違えも拒む（"chara"／"action"／無ければ undefined）。
// 構築ルールそのもの（枚数・色など）は見ない。それはデッキメーカーの常時検査と、席に着くときのサーバ（正は GameConfig.validate）が見る。
export function decodeDeck(code, kindOf = null) {
  const s = String(code || "").replace(/\s+/g, "");
  if (!s) throw new DeckCodeError("コードが空");
  const deck = /^MS\d+:/.test(s) ? decodeV1(s) : decodeV2(s);
  if (kindOf) {
    const unknown = [...new Set([...deck.chara_deck, ...deck.action_deck])].filter((c) => !kindOf(c));
    if (unknown.length) throw new DeckCodeError(`このアプリが知らないカード番号がある: ${unknown.join("、")}（アプリが古いか、コードが違う）`);
    const wrong = [...new Set(deck.chara_deck)].filter((c) => kindOf(c) !== "chara")
      .concat([...new Set(deck.action_deck)].filter((c) => kindOf(c) !== "action"));
    if (wrong.length) throw new DeckCodeError(`欄の違うカードがある: ${wrong.join("、")}`);
  }
  return deck;
}

function decodeV2(s) {
  if (!/^[0-9A-Za-z]+$/.test(s)) {
    const bad = [...s].find((ch) => B62.indexOf(ch) < 0);
    throw new DeckCodeError(`デッキコードではない（使わない文字「${bad}」が入っている。デッキコードは英数字だけ）`);
  }
  const all = fromB62(s);
  if (all.length < 1 + 4 + 8 || all[0] !== "1") throw new DeckCodeError("デッキコードではない（短すぎる）");
  const body = all.slice(1, -8), check = parseInt(all.slice(-8), 2);
  const b = new Bits(body);
  const ver = b.take(4);
  if (ver !== DECK_CODE_VERSION) {
    throw new DeckCodeError(ver > DECK_CODE_VERSION
      ? `新しい形式（版 ${ver}）のコードで、このアプリでは読めない。アプリを更新してほしい`
      : `デッキコードではない（形式の版 ${ver} は無い）`);
  }
  if (crc8(body) !== check) throw new DeckCodeError("コードのどこかが違う（書き写しの間違いか、途中で切れている）。全部をコピーし直してほしい");
  const deck = { chara_deck: takePart(b, false), action_deck: takePart(b, true) };
  if (b.i !== b.s.length) throw new DeckCodeError("コードの形が壊れている（余りがある）");
  return deck;
}

// 版 1: MS1:C<キャラ>/A<アクション>。塊 = <収録>-<番号>[.<番号>…]、2 枚以上は 番号*枚数、塊どうしは ;
function decodeV1(s) {
  const head = /^MS(\d+):/.exec(s);
  if (Number(head[1]) !== 1) throw new DeckCodeError(`知らない形式（MS${head[1]}）のコード`);
  const m = /^C([^/]*)\/A(.*)$/.exec(s.slice(head[0].length));
  if (!m) throw new DeckCodeError("コードの形が壊れている（キャラの欄とアクションの欄が見つからない）");
  const part = (text, where) => {
    const out = [];
    if (!text) return out;
    for (const block of text.split(";")) {
      const dash = block.indexOf("-"); const set = dash > 0 ? block.slice(0, dash) : "";
      if (!/^[A-Z]{2,4}\d{0,3}$/.test(set)) throw new DeckCodeError(`${where}の「${block}」が読めない（収録の名前の形が違う）`);
      for (const p of block.slice(dash + 1).split(".")) {
        const q = /^(\d{2,4})(?:\*(\d{1,2}))?$/.exec(p);
        if (!q) throw new DeckCodeError(`${where}の「${set}-${p}」が読めない（番号か枚数の形が違う）`);
        const n = q[2] === undefined ? 1 : Number(q[2]);
        if (n < 1) throw new DeckCodeError(`${where}の「${set}-${p}」の枚数が 0`);
        for (let i = 0; i < n; i++) out.push(`${set}-${q[1]}`);
      }
    }
    return out;
  };
  return { chara_deck: part(m[1], "キャラの欄"), action_deck: part(m[2], "アクションの欄") };
}

// ロビーの貼り付け欄で、JSON かデッキコードかを見分ける
export function looksLikeDeckCode(text) { const t = String(text || "").trim(); return /^MS\d+:/.test(t) || /^[0-9A-Za-z\s]+$/.test(t); }
