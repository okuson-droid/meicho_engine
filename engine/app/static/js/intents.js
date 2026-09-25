// 合法手 → 所作 の対応表（要件 R-PLAY-1・R-PLAY-3・R-PLAY-11）。
//
// **ここはルールを判定しない。**サーバが送ってきた合法手の「種類」と「対象」を、盤面のどの所作に割り当てるかを
// 決めるだけである。何ができるかは合法手が決める。割り当てを知らない種類の合法手は `unmapped` に入り、
// 安全網の一覧から打てる（対局が止まらない）。
//
// 返す表:
//   drags   [{from: {zone, index? , card?}, to: 置き先のゾーン, idx}]   カードを持って、置く
//   clicks  [{on: {kind:"slot", slot} | {kind:"pick", card, slot?}, idx, confirm?}]   直接触って選ぶ
//   buttons [{label, idx, confirm?, tone?}]   口で宣言するもの
//   special "setup" | "mulligan" | null      手元で組み立ててから 1 手にまとめるもの
//   picks   {title, kind} | null              一覧から選ぶ選択（ゾーンのカード・効果でのレベルアップ）
import { nameOf, info } from "./cards.js";

export function build(view) {
  const out = { drags: [], clicks: [], buttons: [], special: null, picks: null, unmapped: [] };
  const legal = view.legal || [];
  const choice = view.choice || null;
  const kind = choice ? choice.kind : null;
  legal.forEach((a, idx) => {
    switch (a.type) {
      case "setup": out.special = "setup"; break;
      case "mulligan": out.special = "mulligan"; break;
      case "charge": out.drags.push({ from: { zone: "hand", index: a.hand }, to: "concerto", idx }); break;
      case "submit": case "rush": out.drags.push({ from: { zone: "hand", index: a.hand }, to: "action_area", idx }); break;
      case "discard": out.drags.push({ from: { zone: "hand", index: a.hand }, to: "trash", idx }); break;
      case "switch":
        out.clicks.push({ on: { kind: "slot", slot: a.back }, idx, confirm: "このキャラをリーダーにする。よい？" }); break;
      case "choose_back":
        out.clicks.push({ on: { kind: "slot", slot: a.back }, idx, confirm: "効果で、このキャラをリーダーにする。よい？" }); break;
      case "levelup": {
        const c = info(a.card);
        const n = c ? c.level : 0;
        out.clicks.push({ on: { kind: "charadeck", card: a.card, slot: a.slot }, idx,
          confirm: `${nameOf(a.card)} Lv.${n} を重ねる。` + (n > 0 ? `\nコストとして手札を ${n} 枚捨てる（このあと選ぶ）。` : "\n手札のコストは無い。") + "\n確定すると戻せない。" });
        break;
      }
      case "choose_card":
        if (kind === "pay_cost_card" && a.zone === "concerto") {
          out.drags.push({ from: { zone: "concerto", card: a.card }, to: "trash", idx });
        } else if (kind === "levelup_by_effect") {
          out.clicks.push({ on: { kind: "pick", card: a.card, slot: a.slot }, idx, confirm: `${nameOf(a.card)} を重ねる。よい？` });
          out.picks = { kind };
        } else {
          out.clicks.push({ on: { kind: "pick", card: a.card }, idx });
          out.picks = { kind };
        }
        break;
      case "to_clash": out.buttons.push({ label: "対抗フェイズへ", idx, tone: "primary" }); break;
      case "end_turn": out.buttons.push({ label: "ターン終了", idx, confirm: "ターンを終える。よい？" }); break;
      case "pass": out.buttons.push({ label: legal.length === 1 ? "置けない（パス）" : "置かない", idx }); break;
      case "stop": out.buttons.push({ label: kind === "zone_card" ? "ここで選び終える" : "連撃を終える", idx }); break;
      case "use": out.buttons.push({ label: "使う", idx, tone: "primary" }); break;
      case "skip": out.buttons.push({ label: "使わない", idx }); break;
      case "pay": out.buttons.push({ label: "支払う", idx, tone: "primary" }); break;
      case "decline": out.buttons.push({ label: "支払わない", idx }); break;
      case "choose_count": out.buttons.push({ label: `${a.count} 枚`, idx }); break;
      case "resolve": out.buttons.push({ label: `先に解決: ${resolveLabel(choice, a)}`, idx, long: true }); break;
      default: out.unmapped.push(idx);
    }
  });
  return out;
}

function resolveLabel(choice, a) {
  const o = ((choice && choice.options) || []).find((x) => x.index === a.index);
  if (!o) return `${a.index + 1} 番目`;
  const c = info(o.card);
  const text = c && c.skills ? c.skills[o.skill_index] : "";
  return `${nameOf(o.card)}${text ? "「" + text + "」" : ""}`;
}

// 同じ「持つカード → 置き先」の所作に当たる合法手を探す。
export function findDrag(intents, from, to) {
  return intents.drags.find((d) => d.to === to && d.from.zone === from.zone &&
    (d.from.index !== undefined ? d.from.index === from.index : d.from.card === from.card)) || null;
}
export function dropsFor(intents, from) {
  return [...new Set(intents.drags.filter((d) => d.from.zone === from.zone &&
    (d.from.index !== undefined ? d.from.index === from.index : d.from.card === from.card)).map((d) => d.to))];
}
