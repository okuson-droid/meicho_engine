// 設定（要件 R-SET-1・R-SET-2）。端末ごとにブラウザへ保管する。対局中でも変えられる。
// 項目: 音量とミュート・演出と速さ・カード拡大の常時表示・棋譜の送信の同意・カード画像（素材パックの第 1 段）・表示名・版と更新
import { h, openModal, closeModal, toast } from "./ui.js";
import * as store from "./store.js";
import * as art from "./art.js";
import { info } from "./cards.js";

// 初期音量は控えめ（R-SND-2）。拡大は触れている間だけ（hover）／最後に見たカードを出したまま（pin）。棋譜の送信は同意が無ければ送らない（D-108 追記 2）
// autoPay: 協奏エリアからのコストの支払いを自動で選ぶ（古いカードから・APP-022）。対局画面のボタンで切り替える
const DEFAULTS = { volume: 0.3, muted: false, fx: "auto", speed: 1, zoom: "hover", feedConsent: false, autoPay: false };
let current = { ...DEFAULTS, ...(store.load("settings", {}) || {}) };
const listeners = new Set();

export function get() { return current; }
export function set(patch) {
  current = { ...current, ...patch };
  store.save("settings", current);
  for (const fn of listeners) fn(current);
}
export function onChange(fn) { listeners.add(fn); }

// 演出を出すか。"auto" は OS の「視差効果を減らす」に従う（R-FX-7）。音の設定とは独立している（R-SND-2）
export function fxEnabled() {
  if (current.fx === "on") return true;
  if (current.fx === "off") return false;
  return !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

// 版と更新（要件 R-UPD-8・R-UPD-9）。サーバが `/api/version` で答える。配布版でなければ「開発版」とだけ出る
const UPDATE_JA = {
  latest: "最新の版を使っている",
  updated: "起動のときに、新しい版へ更新した",
  offline: "更新元に届かなかったので、手元の版で起動した",
  failed: "更新を取り込めなかったので、手元の版で起動した",
  rolled_back: "新しい版が起動しなかったので、一つ前の版に戻した",
  launcher_outdated: "新しい起動役が必要。配布者から新しい zip を受け取ってほしい（data フォルダを移せば記録を引き継げる）",
  no_feed: "自動更新の設定が無い",
};
let versionCache = null;
export async function versionInfo() {
  if (!versionCache) {
    try { const r = await fetch("/api/version", { cache: "no-store" }); versionCache = r.ok ? await r.json() : {}; } catch { versionCache = {}; }
  }
  return versionCache;
}
export function updateMessage(v) {
  const u = v && v.update;
  return u && UPDATE_JA[u.state] ? UPDATE_JA[u.state] + (u.detail && !["launcher_outdated", "offline"].includes(u.state) ? `（${u.detail}）` : "") : "";
}
function versionSection() {
  const box = h("div", { class: "version-box", id: "set-version" }, h("p", { class: "muted", text: "版を確かめている…" }));
  versionInfo().then((v) => {
    const lines = [h("p", {}, h("b", { text: `版 ${v.version || "不明"}` }),
      h("span", { class: "muted", text: `　ルール ${v.rules_version || "?"}・カードデータ ${v.cards_version || "?"}・通信の版 ${v.protocol ?? "?"}` }))];
    const msg = updateMessage(v);
    if (msg) lines.push(h("p", { class: v.update.state === "latest" || v.update.state === "updated" ? "muted" : "warn-text", text: msg }));
    if ((v.history || []).length) {
      lines.push(h("details", {}, h("summary", { text: "更新の履歴" }),
        h("ul", { class: "history" }, v.history.map((x) => h("li", {}, h("b", { text: x.version || "" }), ` ${String(x.built || "").slice(0, 10)}　${x.notes || ""}`)))));
    }
    box.replaceChildren(...lines);
  });
  return box;
}

// カード画像（APP-013）。手元の画像を選ぶと、この端末のブラウザにだけ保管される。どこにも送らない（要件 R-ASSET-1）
function artSection() {
  const status = h("p", { class: "muted", id: "set-art-status" });
  const paint = () => {
    const n = art.count(), hit = art.codes().filter((c) => info(c)).length;
    status.textContent = n ? `画像 ${n} 種を保管している（このアプリのカードと一致 ${hit} 種）。追加で選べば継ぎ足される。`
      : "未登録。画像が無いカードは文字で表示される。";
    clearBtn.hidden = !n;
  };
  const pick = async (input) => {
    const files = input.files; if (!files || !files.length) return;
    const r = await art.ingest(files); input.value = "";
    if (!r.added) toast("カード画像として読めるファイルが無かった（名前の例: BP01-001_ツバキ_LV2.png）");
    else toast(`画像 ${r.added} 枚を読み込んだ` + (r.skipped ? `（名前がカード番号で始まらない画像 ${r.skipped} 枚は入れなかった）` : "") + (r.saved ? "" : "。保管できなかったので、このタブを閉じるまで有効"));
    paint();
  };
  const dir = h("input", { type: "file", id: "set-art-dir", webkitdirectory: true, directory: true, multiple: true, hidden: true });
  const files = h("input", { type: "file", id: "set-art-files", accept: "image/png,image/jpeg,image/webp", multiple: true, hidden: true });
  dir.addEventListener("change", () => pick(dir));
  files.addEventListener("change", () => pick(files));
  const clearBtn = h("button", { class: "btn", id: "set-art-clear", onclick: async () => { await art.clear(); paint(); toast("カード画像を消した"); }, text: "すべて消す" });
  paint();
  return h("div", { class: "art-box" }, status,
    h("div", { class: "row", style: "margin:6px 0 8px" },
      h("button", { class: "btn", id: "set-art-pick-dir", onclick: () => dir.click(), text: "フォルダを選ぶ" }),
      h("button", { class: "btn", id: "set-art-pick", onclick: () => files.click(), text: "画像を選ぶ" }), clearBtn),
    dir, files,
    h("p", { class: "muted", text: "ファイル名の先頭がカード番号なら自動で対応づく（例: BP01-001_ツバキ_LV2.png）。cards フォルダごと選ぶのが早い。画像はこの端末のブラウザにだけ保管され、相手にもサーバにも送られない。相手の画面の画像は、相手が自分で読み込んだものになる。" }));
}

export function openSettings({ onTestSound } = {}) {
  const vol = h("input", { type: "range", min: 0, max: 100, step: 5, value: Math.round(current.volume * 100), id: "set-volume" });
  const mute = h("input", { type: "checkbox", id: "set-mute", checked: current.muted });
  const fx = h("select", { id: "set-fx" },
    [["auto", "端末の設定に従う"], ["on", "出す"], ["off", "出さない（ログには同じ内容が出る）"]].map(([v, t]) => h("option", { value: v, selected: current.fx === v, text: t })));
  const speed = h("select", { id: "set-speed" },
    [[1, "ふつう"], [1.5, "速い"], [2.5, "とても速い"]].map(([v, t]) => h("option", { value: v, selected: Number(current.speed) === v, text: t })));
  vol.addEventListener("input", () => set({ volume: Number(vol.value) / 100 }));
  vol.addEventListener("change", () => onTestSound && onTestSound());
  mute.addEventListener("change", () => { set({ muted: mute.checked }); if (!mute.checked && onTestSound) onTestSound(); });
  fx.addEventListener("change", () => set({ fx: fx.value }));
  speed.addEventListener("change", () => set({ speed: Number(speed.value) }));
  const zoom = h("select", { id: "set-zoom" },
    [["hover", "触れている間だけ出す"], ["pin", "最後に見たカードを出したままにする"]].map(([v, t]) => h("option", { value: v, selected: current.zoom === v, text: t })));
  zoom.addEventListener("change", () => { set({ zoom: zoom.value }); if (zoom.value !== "pin") { const l = document.getElementById("layer-zoom"); if (l) { l.classList.remove("on"); l.replaceChildren(); } } });
  const feed = h("input", { type: "checkbox", id: "set-feed", checked: !!current.feedConsent });
  feed.addEventListener("change", () => set({ feedConsent: feed.checked }));
  const name = h("input", { id: "set-name", maxlength: 24, value: store.load("name", ""), autocomplete: "off" });
  name.addEventListener("change", () => {
    const v = name.value.trim();
    if (!v) { name.value = store.load("name", ""); return toast("表示名は空にできない"); }
    store.save("name", v);
    const home = document.getElementById("name"); if (home) home.value = v;       // ホームや参加の画面の入力欄にもすぐ映す
    toast("表示名を変えた。次に部屋へ入るときから使われる");
  });
  openModal([
    h("h3", { text: "設定" }),
    h("label", { class: "field" }, h("span", { text: "効果音の音量" }), vol),
    h("label", { class: "row", style: "margin-bottom:12px" }, mute, h("span", { text: "音を消す（ミュート）" })),
    h("label", { class: "field" }, h("span", { text: "演出（カードの動き・判定の表示）" }), fx),
    h("label", { class: "field" }, h("span", { text: "演出の速さ" }), speed),
    h("p", { class: "muted", text: "再生中に盤面をタップすると、その回の演出を飛ばせる。設定はこの端末に保管される。" }),
    h("label", { class: "field" }, h("span", { text: "カードの拡大表示（ホバー・長押し）" }), zoom),
    h("label", { class: "field" }, h("span", { text: "表示名（次に部屋へ入るときから）" }), name),
    h("label", { class: "row", style: "margin-bottom:4px" }, feed, h("span", { text: "対局の記録（棋譜）を AI の研究のために送ってよい" })),
    h("p", { class: "muted", id: "set-feed-note", text: "送るもの: 表示名・デッキ名・相手の AI・シード・行動列・各手の所要時間・結果。使い道: AI の検証。既定は送らない。送り先はまだ用意していないので、いまは入れても何も送られない。いつでも外せる。" }),
    h("h3", { text: "カード画像" }), artSection(),
    h("h3", { text: "版と更新" }), versionSection(),
    h("div", { class: "row end" }, h("button", { class: "btn primary", dataset: { act: "close" }, onclick: closeModal, text: "閉じる" })),
  ]);
}
