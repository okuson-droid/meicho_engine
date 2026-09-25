// カードの表示。データはサーバの /api/cards（番号・名前・色・数値・オペコードの言い換え文）だけを使う。
// 公式の画像とテキストはここに無い（要件 R-ASSET-1）。遊ぶ人が手元の画像を読み込んでいれば、その画像を重ねる（art.js・APP-013）。
import { h } from "./ui.js";
import { api } from "./net.js";
import * as art from "./art.js";

export const HIDDEN = "<hidden>";
let DB = {};
export let dbInfo = { version: "", rules: "" };

export async function loadCards() {
  const data = await api("/api/cards");
  DB = data.cards || {};
  dbInfo = { version: data.version, rules: data.rules };
}

export function info(cid) { return DB[cid] || null; }
export function nameOf(cid) { return (DB[cid] && DB[cid].name) || cid || "？"; }
const COLOR_JA = { red: "赤", green: "緑", blue: "青" };

// カード 1 枚の要素。cid が無い（null）か <hidden> なら裏向き。
export function cardEl(cid, { under = 0 } = {}) {
  const c = cid && cid !== HIDDEN ? DB[cid] : null;
  if (!c) {
    const el = h("div", { class: "card back", "aria-label": "裏向きのカード" });
    if (cid && cid !== HIDDEN) { el.dataset.cid = cid; el.classList.remove("back"); el.append(h("div", { class: "nm", text: cid })); }
    return el;
  }
  const el = h("div", { class: "card " + (c.kind === "chara" ? "chara" : c.color), dataset: { cid } });
  if (c.kind === "chara") {
    el.append(h("div", { class: "nm", text: c.name }), h("div", { class: "lv", text: "Lv." + c.level }));
    if (under > 0) el.append(h("div", { class: "under", title: "下に重なっているカード", text: "+" + under }));
  } else {
    el.append(h("div", { class: "cost", text: c.cost }), h("div", { class: "nm", text: c.name }),
      h("div", { class: "stat" }, h("span", { title: "速度" }, h("i", { text: "速" }), h("b", { text: c.speed })), h("span", { title: "ダメージ" }, h("i", { text: "ダ" }), h("b", { text: c.damage }))));
  }
  const url = art.urlOf(cid);
  if (url) {                        // 文字の要素は残す（読み上げ・検査が使う）。見た目だけ画像で覆う
    el.classList.add("has-art");
    el.prepend(h("img", { class: "art", src: url, alt: "", draggable: "false", loading: "lazy" }));
  }
  el.setAttribute("aria-label", c.name);
  return el;
}

// 拡大の中身。stack を渡すと、重なった全カードのスキルを並べる（下のカードのスキルも有効なため）。
export function zoomEl(cid, stack = null) {
  const c = DB[cid];
  if (!c) return null;
  const box = h("div", { class: "zoom" });
  const url = art.urlOf(cid);
  if (url) box.append(h("img", { class: "zoom-art", src: url, alt: c.name, draggable: "false" }));
  box.append(h("div", { class: "band " + (c.kind === "chara" ? "chara" : c.color) }),
    h("h4", { text: c.name + (c.kind === "chara" ? `　Lv.${c.level}` : "") }), h("div", { class: "id", text: cid }));
  if (c.kind === "action") {
    box.append(h("div", { class: "stats" },
      h("span", { text: COLOR_JA[c.color] || c.color }), h("span", { text: "コスト " + c.cost }),
      h("span", { text: "速度 " + c.speed }), h("span", { text: "ダメージ " + c.damage })));
    if (c.dedicated_to) box.append(h("div", { class: "muted", text: `専用: ${c.dedicated_to}` + (c.leader_skill ? "（リーダースキル: リーダーが一致するときだけ使える）" : "") }));
  }
  if (c.tags && c.tags.length) box.append(h("div", { class: "muted", text: c.tags.map((t) => `＜${t}＞`).join(" ") }));
  const cards = stack && stack.length ? stack.filter((x) => DB[x]) : [cid];
  const ul = h("ul");
  for (const x of cards) {
    for (const t of DB[x].skills || []) {
      ul.append(h("li", {}, cards.length > 1 ? h("span", { class: "from", text: `${DB[x].name} Lv.${DB[x].level}: ` }) : null, t));
    }
  }
  if (ul.childElementCount) box.append(ul); else box.append(h("div", { class: "muted", text: "スキルなし" }));
  if (c.unverified) box.append(h("div", { class: "note", text: "※ このカードのデータは未確認の項目を含む" }));
  box.append(h("div", { class: "note", text: "スキルの文はエンジンの処理の言い換えで、公式のテキストではない" }));
  return box;
}
