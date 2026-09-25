// カード画像（素材パックの第 1 段・APP-013）。**画像はアプリに入れない**（要件 R-ASSET-1）。
// 遊ぶ人が手元の画像（`cards/` フォルダなど）を選ぶと、この端末のブラウザの保管領域（IndexedDB）に入り、次からは自動で出る。
// どこにも送らない。相手の画面に出る画像は、相手が自分の端末で読み込んだものである。
// 方式はデッキメーカー（アーティファクト版）と同じ: ファイル名の先頭のカード番号で対応づけ、版（-R／-SP／-PR）は別枠に持つ。
// 対局の盤面には通常の版（無ければ次の版）を出す。

const IDB_NAME = "meichosim.images";
const STORE = "imgs";
// 例: BP01-001_ツバキ_LV2.png／SD01-005_x-R.jpg。番号の形は「英字 2 字＋数字 2 桁-数字 2〜3 桁」
export const IMG_RE = /^([A-Za-z]{2}\d{2}-\d{2,3})_[\s\S]*?(?:-(R|SP|PR))?\.(png|jpe?g|webp)$/i;
const VARIANTS = ["base", "R", "SP", "PR"];
const MAX_BYTES = 8 * 1024 * 1024;     // 1 枚の上限。カードのスクショは数百 KB なので十分

const slots = new Map();               // 番号 → { base?: objectURL, R?: …, SP?: …, PR?: … }
const listeners = new Set();
export function onChange(fn) { listeners.add(fn); }
function changed() { for (const fn of listeners) { try { fn(); } catch { /* 表示の失敗で保管を止めない */ } } }

// ---------------------------------------------------------------- 保管領域（使えない環境では、そのタブの間だけ効く）
let dbPromise = null;
function db() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    setTimeout(() => finish(null), 4000);           // プライベートウィンドウなどで返事が来ないときは待たない
    try {
      const req = indexedDB.open(IDB_NAME, 1);
      req.onupgradeneeded = () => { if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE, { keyPath: "key" }); };
      req.onsuccess = () => finish(req.result);
      req.onerror = () => finish(null);
      req.onblocked = () => finish(null);
    } catch { finish(null); }
  });
  return dbPromise;
}
function tx(mode, work) {
  return db().then((d) => new Promise((resolve) => {
    if (!d) return resolve(null);
    try {
      const t = d.transaction(STORE, mode);
      const out = work(t.objectStore(STORE));
      t.oncomplete = () => resolve(out && "result" in out ? out.result : true);
      t.onerror = () => resolve(null);
      t.onabort = () => resolve(null);
    } catch { resolve(null); }
  }));
}

// ---------------------------------------------------------------- 読み込み
function apply(records) {
  for (const r of records) {
    if (!VARIANTS.includes(r.variant) || !(r.blob instanceof Blob)) continue;
    let s = slots.get(r.code);
    if (!s) { s = {}; slots.set(r.code, s); }
    if (s[r.variant]) URL.revokeObjectURL(s[r.variant]);
    try { s[r.variant] = URL.createObjectURL(r.blob); } catch { /* 作れなければその 1 枚は出さない */ }
  }
}

export function parseName(name) {
  const m = String(name || "").match(IMG_RE);
  return m ? { code: m[1].toUpperCase(), variant: m[2] ? m[2].toUpperCase() : "base" } : null;
}

// 選ばれたファイル（フォルダごとでもよい）から、カード画像として読めるものを入れる。{ added, skipped, saved }
// skipped は「画像だが名前の形が違う・大きすぎる」ものの数（例: cards/手動スクショ/ の原本）
export async function ingest(fileList) {
  const records = [];
  let skipped = 0;
  for (const f of [...(fileList || [])]) {
    const p = parseName(f.name);
    if (!p || !f.size || f.size > MAX_BYTES || (f.type && !f.type.startsWith("image/"))) {
      if (/\.(png|jpe?g|webp)$/i.test(f.name)) skipped += 1;     // 画像なのに読めなかったものだけ数える（フォルダごと選ぶと JSON やメモも混じるので）
      continue;
    }
    records.push({ key: `${p.code}|${p.variant}`, code: p.code, variant: p.variant, blob: f, filename: f.name });
  }
  if (!records.length) return { added: 0, skipped, saved: true };
  apply(records);                                   // 表示は保管を待たない
  changed();
  const saved = (await tx("readwrite", (st) => { records.forEach((r) => st.put(r)); })) !== null;
  return { added: records.length, skipped, saved };
}

export async function restore() {
  const all = await tx("readonly", (st) => st.getAll());
  if (Array.isArray(all) && all.length) { apply(all); changed(); }
  return slots.size;
}

export async function clear() {
  await tx("readwrite", (st) => { st.clear(); });
  for (const s of slots.values()) for (const u of Object.values(s)) URL.revokeObjectURL(u);
  slots.clear();
  changed();
}

// ---------------------------------------------------------------- 引く
export function urlOf(cid) {
  const s = slots.get(cid);
  if (!s) return null;
  for (const v of VARIANTS) if (s[v]) return s[v];
  return null;
}
export function codes() { return [...slots.keys()]; }
export function count() { return slots.size; }
// 番号 → {base?, R?, SP?, PR?} の表そのもの（デッキメーカーが版を選ぶのに使う。読むだけにする）
export function allSlots() { return slots; }
