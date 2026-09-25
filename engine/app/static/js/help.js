// 遊び方（要件 R-HELP-1）。初回に 1 度だけ自動で開き、あとはホームとメニューの「遊び方」から開き直せる。
// 画面の見方と 1 ターンの流れを短く案内する。ルールの全文は載せず、公式サイトへの案内にとどめる。
import { h, openModal, closeModal } from "./ui.js";
import * as store from "./store.js";

const SEEN_KEY = "helpSeen";

const PAGES = [
  {
    title: "画面の見方",
    body: [
      "下半分があなた、上半分が相手。並びは公式のプレイマットに合わせてある。",
      "キャラエリア: 3 つの枠の真ん中（実線の枠）がリーダー、左右がバック。重なったカードは「+数字」で出る。",
      "アクションエリア: 対抗や連撃で使ったアクションカードが左から並ぶ。",
      "協奏エリア: コストの支払いに使うカード。横向きに置く。",
      "キャラデッキ・アクションデッキ・トラッシュ・ライフは、それぞれの名前の枠。自分のキャラデッキと、両者のトラッシュ・協奏エリアはクリックで広げて見られる。",
      "真ん中の帯に、いまのフェイズと、誰の入力を待っているかが出る。",
    ],
  },
  {
    title: "1 ターンの流れ",
    body: [
      "ドロー: アクションデッキから 2 枚引く（先攻の最初のターンは 1 枚）。",
      "アクション: チャージ・切り替え・レベルアップを、それぞれ 1 ターンに 1 回までできる。",
      "レベルアップすると、上に置いたカードの【登場】と、その下に重なっている全部のカードの【レベルアップ】が誘発する。間に別のカードが挟まっていても誘発する（公式の総合ルール 603.1.2.2.2 の読み）。",
      "対抗: ターンプレイヤーが先に手札を 1 枚伏せ、次に相手が伏せる（伏せなくてもよい）。そろったら同時に公開してコストを払う。",
      "判定: 赤は緑に、緑は青に、青は赤に勝つ。同じ色なら赤と緑はスピードの高い方が勝ち（同じならターンプレイヤー）、青どうしは引き分け。",
      "勝った方が相手のライフにダメージを与える。赤で勝つと、そのターンは赤のカードで続けて連撃できる。",
      "ライフ 20 を先に 0 にした方が勝ち。",
    ],
  },
  {
    title: "操作",
    body: [
      "チャージ: 手札のカードを協奏エリアへドラッグする。",
      "レベルアップ: レベルアップしたい場のキャラをクリック → 重ねるカードを選ぶ（候補が 1 枚なら確認だけ）→ 捨てる手札を選ぶ。キャラデッキをクリックして選んでもよい。",
      "切り替え: リーダーにしたいバックのキャラをクリックする。レベルアップもできるときは、どちらにするかを尋ねる。",
      "対抗・連撃: 手札のカードをアクションエリアへドラッグする。",
      "ドラッグが難しいときは、カードをタップして持ち上げ、光っている置き先をタップしてもよい。",
      "カードはマウスを乗せるか長押しで拡大する。演出の最中に盤面をタップすると、その回の演出を飛ばせる。",
      "困ったら、真ん中の帯の右端の ≡（メニュー）→「いま選べる手の一覧」から選べる。",
    ],
  },
];

export function seen() { return !!store.load(SEEN_KEY, false); }

// 初回だけ自動で開く。閉じたら「見た」と覚える（この端末のブラウザに保管）
export function maybeFirstTime() {
  if (seen()) return false;
  openHelp({ first: true });
  return true;
}

export function openHelp({ first = false, page = 0 } = {}) {
  const done = () => { store.save(SEEN_KEY, true); closeModal(); };
  const p = PAGES[page];
  const last = page === PAGES.length - 1;
  openModal([
    h("h3", { text: (first ? "はじめに: " : "遊び方: ") + p.title }),
    h("div", { class: "help-dots", "aria-label": `${page + 1} / ${PAGES.length} ページ` },
      PAGES.map((_, i) => h("span", { class: "dot" + (i === page ? " on" : "") }))),
    h("ul", { class: "help-list", id: "help-body" }, p.body.map((t) => h("li", { text: t }))),
    last ? h("p", { class: "muted", id: "help-rules", text: "ルールの全文は、公式サイトの総合ルールと FAQ を見てほしい。このアプリは非公式で、カードの文面や画像は同梱していない。" }) : null,
    h("div", { class: "row end" },
      first && !last ? h("button", { class: "btn", dataset: { act: "help-skip" }, onclick: done, text: "あとで読む" }) : null,
      page > 0 ? h("button", { class: "btn", dataset: { act: "help-prev" }, onclick: () => openHelp({ first, page: page - 1 }), text: "戻る" }) : null,
      last ? h("button", { class: "btn primary", dataset: { act: "help-close" }, onclick: done, text: "閉じる" })
        : h("button", { class: "btn primary", dataset: { act: "help-next" }, onclick: () => openHelp({ first, page: page + 1 }), text: "次へ" })),
    first ? h("p", { class: "muted", text: "あとからホームの「遊び方」や、対局中のメニューからいつでも開ける。" }) : null,
  ], { onDismiss: () => store.save(SEEN_KEY, true) });
}
