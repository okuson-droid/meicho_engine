// 対局画面（S3）。対人戦・観戦で共用する（要件 5 章）。
//
// 決まり:
// - 盤面は毎回 `view` の全量から描き直す。画面は状態を持たない（持つのは「いま持ち上げているカード」のような手元の操作だけ）
// - 光らせる対象と所作の割り当ては intents.js の表だけから作る。ルールを判定しない（R-PLAY-3）
// - 入力は Pointer Events の 1 経路（マウス・タッチ・ペン共通・R-PLAY-6）。すぐ動かせばドラッグ、押し続ければ拡大（R-PLAY-7）
import { h, toast, confirmDialog, openModal, closeModal, modalOpen, cssMs } from "./ui.js";
import { cardEl, zoomEl, info, nameOf, HIDDEN } from "./cards.js";
import { build, findDrag, dropsFor } from "./intents.js";
import { Fx, logLine } from "./fx.js";
import * as settings from "./settings.js";
import * as sfx from "./sfx.js";
import * as help from "./help.js";

const PHASE_JA = {
  setup_chara: "準備: キャラの配置", mulligan: "準備: マリガン", action: "アクションフェイズ",
  clash_submit: "対抗フェイズ: カードを置く", choice: "効果の選択", rush: "連撃",
  turn_end_discard: "ターン終了: 手札の調整", game_over: "対局終了",
};
// ゾーンの名前と並びは公式のプレイマットに合わせる（R-PLAY-2・2026-09-20 にマスターが実物の写真で確認）
const ZONE_JA = { concerto: "協奏エリア", action_area: "アクションエリア", trash: "トラッシュ", charadeck: "キャラデッキ", deck: "アクションデッキ", life: "ライフ" };
const SLOT_JA = ["リーダー", "バック", "バック"];
const CLASH_PROMPT = "対抗: 手札から 1 枚をアクションエリアへ伏せて出す（出さないなら「置かない」）";

export class Board {
  // replay: リプレイの画面から使うとき（APP-019）。{ bar(): 真ん中の帯に出す操作, label(): 帯の文 }。入力は一切受けない
  constructor(root, { send, onMenu, replay = null }) {
    this.root = root; this.send = send; this.onMenu = onMenu; this.replay = replay;
    this.view = null; this.room = null; this.intents = build({});
    this.lifted = null;           // いま持ち上げているカード（タップで持ち上げ → 置き先をタップ・R-PLAY-6）
    this.marks = new Set();       // マリガンで戻す印
    this.placed = [null, null, null];   // 準備で手元に置いたキャラ（リーダー・バック 1・バック 2）
    this.pending = false;         // 送った手の返事待ち。次の view が来るまで入力を止める
    this.online = true;
    this.pickHidden = false;      // 一覧から選ぶ選択を、盤面を見るために畳んでいる
    this.pickKey = "";
    this.log = [];
    this.press = null; this.drag = null;
    this.lastViewAt = Date.now();
    this.resultShownFor = -1;
    this.queue = [];              // 届いた盤面の待ち行列。演出の再生中に次が届いても、順に見せる（R-FX-1）
    this.playing = false;         // 演出の再生中。入力を止める（R-FX-3）
    this.el = h("div", { id: "board" });
    root.replaceChildren(this.el, h("div", { class: "rotate-hint", text: "横向きにすると盤面が見やすい" }));
    this.fx = new Fx(this);
    this.callLayer = document.getElementById("layer-call") || document.body.appendChild(h("div", { id: "layer-call", "aria-hidden": "true" }));
    this.calledFor = null;        // 知らせを出した局面（同じ局面で 2 度出さない・APP-022）
    this.sfxPlayed = sfx.played;  // 調べもの用: 直近に鳴らした音の名前
    this._bindPointer();
    this.clock = setInterval(() => this._tick(), 1000);
  }

  destroy() { clearInterval(this.clock); this.queue = []; this.fx.skip(); this.fx._clear(); this.callLayer.replaceChildren(); this._hideZoom(); closeModal(); }

  // ------------------------------------------------------------------ 受け取る
  setOnline(on) { this.online = on; this._renderBanner(); this.el.classList.toggle("blocked", !on); if (!on) this._cancelPointer(); }

  update(view, room, events, full = false) {
    this.queue.push({ view, room, events: events || [], full });
    if (!this.playing) this._drain();
  }

  async _drain() {
    while (this.queue.length) {
      const item = this.queue.shift();
      const sameGame = this.view && !(item.view.applies === 0 && this.view.applies > 0) && item.view.viewer === this.view.viewer;
      // 演出するのは: 設定が入・前の盤面がある・全量の送り直しではない（再接続中の出来事は演出しない・R-NET-3）・溜まっていない・画面が見えている
      const play = settings.fxEnabled() && sameGame && !item.full && item.events.length && this.queue.length < 2 && !document.hidden;
      if (play) {
        this.playing = true; this.el.classList.add("playing");
        this._cancelPointer(); this.lifted = null;
        try { await this.fx.play(this.view, item.view, item.events); } catch (err) { console.error(err); }
        this.playing = false; this.el.classList.remove("playing");
      } else if (item.events.length && sameGame && !item.full) this._soundOnly(item.events);
      this._show(item);
    }
  }

  // 演出を切っていても、音の設定は独立している（R-SND-2）。いちばん大事な出来事の音を 1 つだけ鳴らす
  _soundOnly(events) {
    const has = (t) => events.find((e) => e.t === t);
    const over = has("game_over"), judge = has("judge"), life = has("life");
    if (over) sfx.play(this.me === null || over.outcome === this.me ? "victory" : "defeat");
    else if (judge) sfx.play(this.me === null || judge.winner === this.me ? "win" : "lose");
    else if (life) sfx.play(life.delta < 0 ? "damage" : "heal");
    else if (has("turn")) sfx.play("turn");
    else if (has("placed")) sfx.play("place");
    else if (events.some((e) => e.t === "move")) sfx.play("move");
  }

  _show({ view, room, events }) {
    const newGame = !this.view || (view.applies === 0 && this.view.applies > 0);
    if (newGame) { this.log = []; this.placed = [null, null, null]; this.marks.clear(); this.calledFor = null; }
    if (!this.view || view.token !== this.view.token || view.phase !== this.view.phase) { this.lifted = null; this.marks.clear(); }
    this.view = view; this.room = room || this.room;
    this.pending = false; this.lastViewAt = Date.now();
    this.me = view.viewer === 0 || view.viewer === 1 ? view.viewer : null;
    this.bottom = this.me === null ? 0 : this.me;
    this.intents = !this.replay && this.me !== null && view.awaiting.includes(this.me) ? build(view) : build({});
    const who = (g) => (g === this.me ? "あなた" : this._name(g));
    for (const e of events || []) { const line = logLine(e, who); if (line) this.log.push(line); }      // 演出を切っていても、ログには同じ出来事が順に出る（R-FX-7）
    if (this.log.length > 400) this.log.splice(0, this.log.length - 400);
    this._cancelPointer();
    this.render();
    if (newGame && this.me !== null && !this.replay && view.phase === "setup_chara") {       // APP-022: 自分が先攻か後攻かを最初に知らせる
      this.announce(this.me === 0 ? "あなたは先攻" : "あなたは後攻", this.me === 0 ? "先に動く" : "相手が先に動く", this.me === 0 ? "first" : "");
    }
    this._afterRender();
  }

  // 演出の途中の盤面（前の盤面の写しに出来事を当てたもの）を描く。触れるものは無い
  renderShown(dview) {
    this.view = dview; this.intents = build({});
    this.render();
  }

  // 手元の画像を読み込んだ・消したとき（APP-013）。演出の途中なら描き直さない（次の盤面で画像が出る）
  refreshArt() { if (this.view && !this.playing && !this.press) this.render(); }

  setRoom(room) { this.room = room; if (this.view) { this._renderBanner(); this._renderMid(); this._maybeResult(); } }

  // ------------------------------------------------------------------ 描く
  render() {
    const v = this.view; if (!v) return;
    const top = 1 - this.bottom;
    this.el.replaceChildren(
      this._handRow(top, false),
      this._side(top, false),
      this.mid = h("div", { class: "midbar" }),
      this._side(this.bottom, true),
      this._bottomRow(),
    );
    for (const fan of this.el.querySelectorAll(".fan")) this._fit(fan);
    for (const st of this.el.querySelectorAll(".vstack")) this._fitV(st);
    for (const row of this.el.querySelectorAll(".handrow")) this._fit2(row);
    const cw = parseFloat(getComputedStyle(this.el).getPropertyValue("--cw")) || this.el.querySelector(".card")?.getBoundingClientRect().width || 80;
    this.el.classList.toggle("tiny", (this.el.querySelector(".side .card")?.getBoundingClientRect().width || cw) < 52);
    this._renderMid(); this._renderBanner(); this._applyLit();
  }

  _name(gseat) {
    const r = this.room; if (!r || !r.order) return gseat === this.me ? "あなた" : `席 ${gseat + 1}`;
    const s = r.seats[r.order[gseat]];
    return (s && s.name) || `席 ${gseat + 1}`;
  }

  _side(seat, mine) {
    const p = this.view.players[seat];
    const own = mine && this.me !== null;
    const z = (name, cls, label, children, extra = {}) => h("div", {
      class: "zone " + cls, dataset: { zone: name, owner: seat, ...(own && extra.drop ? { drop: extra.drop } : {}), ...(extra.slot !== undefined ? { slot: extra.slot } : {}) },
      title: label,
    }, h("span", { class: "zlabel", text: label }), children);

    // アクションエリア: 左から右へ。まだ公開していない提出は裏向きで見せる（R-ACT-7・R-CLASH-2）
    const area = p.action_area.map((cid) => cardEl(cid));
    const held = this.view.submitted.includes(seat) && this.view.phase === "clash_submit";
    if (held) {
      const a = own && this.view.my_held;
      if (a && a.type === "submit") { const c = cardEl(p.hand[a.hand]); c.classList.add("facedown-mine"); area.push(c); }
      else if (!own) area.push(cardEl(null));
    }
    const areaZ = z("action_area", "area", ZONE_JA.action_area, h("div", { class: "fan" }, area), { drop: "action_area" });
    const lifeZ = h("div", { class: "zone life", dataset: { zone: "life", owner: seat }, title: "ライフ" },
      h("div", { class: "num", text: p.life }), h("div", { class: "cap" }, this._name(seat), h("span", { class: "order-chip" + (seat === 0 ? " first" : ""), text: seat === 0 ? "先攻" : "後攻" })));

    // 協奏エリアはプレイマットと同じく縦長で、カードは**横向き**に置く（2026-09-20 マスターの指摘。実物の置き方）。
    // 横向きのカードを、上の帯（コストと名前）が見えるように縦に重ねる。文字は読めるように正立のまま描く
    const concerto = p.concerto.map((cid) => { const c = cardEl(cid); c.classList.add("side"); if (own) { c.dataset.role = "concerto"; c.dataset.card = cid; } return c; });
    const slot = (i) => {
      const stack = own && this.intents.special === "setup" ? (this.placed[i] ? [this.placed[i]] : []) : p.slots[i];
      let body = null;
      if (stack.length) {
        body = cardEl(stack[stack.length - 1], { under: stack.length - 1 });
        if (own && this.intents.special === "setup") { body.dataset.role = "placed"; body.dataset.slot = i; }
      }
      return z("slot", "slotz" + (i === 0 ? " leader" : ""), SLOT_JA[i], body, { drop: "slot" + i, slot: i });
    };
    const pile = (n, face) => h("div", { class: "pile" }, n > 0 ? (face || cardEl(null)) : null, h("span", { class: "count", text: n }));
    const cdCount = p.chara_deck ? p.chara_deck.length : null;
    const slots = mine ? [slot(1), slot(0), slot(2)] : [slot(2), slot(0), slot(1)];      // 相手側は 180° 回した並び
    const side = h("div", { class: "side " + (mine ? "me" : "opp") },
      z("concerto", "concerto", `${ZONE_JA.concerto} ${p.concerto.length}`, h("div", { class: "vstack" }, concerto), { drop: "concerto" }),
      areaZ, lifeZ,
      z("charadeck", "cdeck", ZONE_JA.charadeck, cdCount === null ? cardEl(null) : pile(cdCount)),
      h("div", { class: "slots" }, slots),
      z("trash", "trash", ZONE_JA.trash, pile(p.trash.length, p.trash.length ? cardEl(p.trash[p.trash.length - 1]) : null), { drop: "trash" }),
      z("deck", "deck", ZONE_JA.deck, pile(p.deck_count)));
    return side;
  }

  _fitV(stack) {
    const n = stack.childElementCount; if (n < 2) return;
    const zone = stack.parentElement; if (!zone || !stack.firstElementChild) return;
    const ch = stack.firstElementChild.getBoundingClientRect().height;
    const room = zone.clientHeight - parseFloat(getComputedStyle(zone).paddingTop) - 4;
    const gap = Math.min(3, (room - ch * n) / (n - 1));
    stack.style.setProperty("--stack-gap", `${Math.max(gap, -ch * 0.87)}px`);
  }

  // 並べたカードがゾーンからはみ出さないよう、枚数に応じて重ねる
  _fit(fan) {
    const n = fan.childElementCount; if (n < 2) return;
    const zone = fan.parentElement; if (!zone) return;
    const cw = fan.firstElementChild.getBoundingClientRect().width;
    const room = zone.clientWidth - 10;
    const gap = Math.min(4, (room - cw * n) / (n - 1));
    fan.style.setProperty("--fan-gap", `${Math.max(gap, -cw * 0.78)}px`);
  }

  _handRow(seat, mine) {
    const p = this.view.players[seat];
    const row = h("div", { class: "handrow " + (mine ? "me" : "opp"), dataset: { zone: "hand", owner: seat }, title: mine ? "あなたの手札" : `${this._name(seat)} の手札` });   // R-HELP-2
    if (p.hand) {
      const heldIdx = this.view.my_held && this.view.my_held.type === "submit" && this.view.submitted.includes(seat) ? this.view.my_held.hand : -1;
      p.hand.forEach((cid, i) => {
        if (i === heldIdx) return;                       // 裏向きで置いたカードはアクションエリアに描いている
        const c = cardEl(cid); c.dataset.role = "hand"; c.dataset.index = i;
        if (this.marks.has(i)) c.classList.add("marked");
        row.append(c);
      });
    } else {
      const known = p.hand_known || [];
      known.forEach((cid) => { const c = cardEl(cid); c.classList.add("known"); c.dataset.role = "known"; row.append(c); });
      const hidden = Math.max(0, p.hand_count - known.length - (this.view.submitted.includes(seat) && this.view.phase === "clash_submit" ? 1 : 0));
      for (let i = 0; i < hidden; i++) row.append(cardEl(null));
    }
    return row;
  }

  _fit2(row) {
    const n = row.childElementCount; if (n < 2) return;
    const cw = row.firstElementChild.getBoundingClientRect().width;
    const gap = Math.min(6, (row.clientWidth - 16 - cw * n) / (n - 1));
    row.style.setProperty("--fan-gap", `${Math.max(gap, -cw * 0.7)}px`);
  }

  _bottomRow() {
    if (this.me !== null && this.intents.special === "setup") {
      const p = this.view.players[this.me];
      const lv0 = (p.chara_deck || []).filter((cid) => (info(cid) || {}).level === 0 && !this.placed.includes(cid));
      return h("div", { class: "handrow me tray", dataset: { zone: "tray" }, title: "Lv.0 のキャラ（枠へ置く）" },
        h("div", { class: "hint" }, h("b", { class: "order-say" + (this.me === 0 ? " first" : ""), text: this.me === 0 ? "あなたは先攻" : "あなたは後攻" }),
          "Lv.0 のキャラ 3 枚を、リーダーとバックの枠へ置く。置いたあとも入れ替えられる"),
        lv0.map((cid) => { const c = cardEl(cid); c.dataset.role = "tray"; c.dataset.card = cid; return c; }));
    }
    return this._handRow(this.bottom, true);
  }

  _renderMid() {
    const v = this.view; if (!v || !this.mid) return;
    if (this.replay) return this._renderReplayMid();
    const mineNow = this.me !== null && v.awaiting.includes(this.me);
    const over = v.outcome !== null && v.outcome !== undefined;
    const turn = v.turn_no > 0 ? `ターン ${v.turn_no}・${v.turn_player === this.me ? "あなた" : this._name(v.turn_player)}の番`
      : (this.me === null ? "対局の準備" : `対局の準備・あなたは${this.me === 0 ? "先攻" : "後攻"}`);          // APP-022: 準備のうちから先攻後攻を出す
    this.waitEl = h("div", { class: "wait" + (mineNow ? " mine" : "") });
    const status = h("div", { class: "status" }, h("div", { class: "ph", text: `${PHASE_JA[over ? "game_over" : v.phase] || v.phase}｜${turn}` }), this.waitEl);
    const hints = v.hints || {};
    const clashCall = mineNow && v.phase === "clash_submit" && !this.pending;
    const src = this._effectSource();
    let promptText = mineNow ? (clashCall ? CLASH_PROMPT : (hints.prompt || this._specialPrompt() || "")) : "";
    if (mineNow && src && !clashCall) promptText = `【${src}】` + promptText;            // どのカードの効果の選択か（APP-023）
    const acts = h("div", { class: "acts" });
    if (mineNow && !this.pending && !this.playing) {
      for (const b of this._buttons()) {
        acts.append(h("button", { class: "btn" + (b.tone === "primary" ? " primary" : ""), disabled: b.disabled, dataset: { act: b.key || "legal", idx: b.idx ?? "" },
          onclick: () => b.run(), text: b.label }));
      }
      if (this.intents.picks && this.pickHidden) acts.append(h("button", { class: "btn primary", dataset: { act: "reopen" }, onclick: () => { this.pickHidden = false; this._afterRender(); }, text: "選択を開く" }));
    }
    if (over) acts.append(h("button", { class: "btn primary", dataset: { act: "result" }, onclick: () => this._showResult(), text: "結果" }));
    if (this.me !== null && !over) {                // 協奏エリアからの支払いを自動にする（APP-022）
      const on = !!settings.get().autoPay;
      acts.append(h("button", { class: "btn toggle" + (on ? " on" : ""), dataset: { act: "autopay" }, "aria-pressed": on ? "true" : "false",
        title: "協奏エリアからのコストの支払いを自動で選ぶ（古いカードから）", onclick: () => this._toggleAutoPay(), text: on ? "自動支払い 入" : "自動支払い 切" }));
    }
    acts.append(h("button", { class: "btn", "aria-label": "メニュー", title: "メニュー", dataset: { act: "menu" }, onclick: () => this._menu(), text: "≡" }));
    this.mid.replaceChildren(...[status, h("div", { class: "prompt", text: promptText }), acts, this._effectsPanel()].filter(Boolean));
    this.mid.classList.toggle("alert", clashCall);
    this._markResolving();
    const myArea = this.el.querySelector(`[data-zone="action_area"][data-owner="${this.me}"]`);
    if (myArea) myArea.classList.toggle("call", clashCall);
    this._tick();
  }

  // ---------------------------------------------------------------- 効果の解決（APP-023）
  // 解決中のカードの名前（見えないカードなら「伏せたカード」）。解決中が無ければ ""
  _effectSource() {
    const r = this.view && this.view.effects && this.view.effects.resolving;
    if (!r) return "";
    return r.card ? nameOf(r.card) : "伏せたカード";
  }

  // 解決中と待っている効果の一覧。中央の帯の上に重ねて出す。何も積まれていなければ出さない
  _effectsPanel() {
    const e = this.view && this.view.effects;
    if (!e || (!e.resolving && !(e.queue || []).length)) return null;
    const row = (it, label, cls) => {
      const c = it.card ? info(it.card) : null;
      const skill = c && c.skills ? (it.skill_index !== null && it.skill_index !== undefined ? c.skills[it.skill_index] : (c.skills.length === 1 ? c.skills[0] : "")) : "";
      const mine = this.me !== null ? it.player === this.me : it.player === this.bottom;
      return h("div", { class: "effrow " + cls + (mine ? " me" : " opp"), dataset: it.card ? { cid: it.card } : {} },
        h("span", { class: "tag", text: label }),
        h("span", { class: "who", text: it.player === this.me ? "あなた" : this._name(it.player) }),
        h("b", { text: it.card ? nameOf(it.card) : "伏せたカード" }),
        skill ? h("span", { class: "sk", text: skill }) : null);
    };
    const n = (e.resolving ? 1 : 0) + e.queue.length;
    return h("div", { class: "effects", dataset: { n } },
      h("div", { class: "eh", text: `効果 ${n} 件` + (e.queue.length ? `（あと ${e.queue.length} 件）` : "") }),
      e.resolving ? row(e.resolving, "解決中", "now") : null,
      e.queue.slice(0, 5).map((it, i) => row(it, i === 0 ? "次" : `${i + 1}`, "wait")),
      e.queue.length > 5 ? h("div", { class: "more", text: `ほか ${e.queue.length - 5} 件` }) : null);
  }

  // 盤面の上で、解決中のカードを光らせる（持ち主の側のキャラ枠かアクションエリア）
  _markResolving() {
    for (const el of this.el.querySelectorAll(".card.resolving")) el.classList.remove("resolving");
    const r = this.view && this.view.effects && this.view.effects.resolving;
    if (!r || !r.card) return;
    const hit = [...this.el.querySelectorAll(`.zone[data-owner="${r.player}"] .card[data-cid="${CSS.escape(r.card)}"]`)].pop();
    if (hit) hit.classList.add("resolving");
  }

  _toggleAutoPay() {
    const on = !settings.get().autoPay;
    settings.set({ autoPay: on });
    toast(on ? "協奏エリアからの支払いを自動にした（古いカードから）" : "協奏エリアからの支払いを手で選ぶ");
    this._renderMid();
    if (on) this._afterRender();
  }

  // 協奏エリアからの支払いを自動で選ぶ（APP-022）。古いカード（協奏エリアの先頭）から。エンジンの既定の支払いと同じ順
  _autoPay() {
    const v = this.view;
    if (!settings.get().autoPay || !v.choice || v.choice.kind !== "pay_cost_card") return false;
    const pays = this.intents.drags.filter((d) => d.from.zone === "concerto");
    if (!pays.length) return false;
    const order = v.players[this.me].concerto || [];
    const pick = order.map((cid) => pays.find((d) => d.from.card === cid)).find(Boolean) || pays[0];
    toast(`自動で支払った: ${nameOf(pick.from.card)}`);
    this.commit(pick.idx);
    return true;
  }

  // 入力の番が来たことを強く知らせる（APP-022）。いまは対抗の提出だけ。同じ局面では 1 度だけ
  _call() {
    const v = this.view;
    if (this.me === null || this.replay || !v.awaiting.includes(this.me) || v.phase !== "clash_submit") return;
    const key = `${v.turn_no}:${v.token}`;
    if (this.calledFor === key) return;
    this.calledFor = key;
    sfx.play("call");
    this.announce("対抗！", "手札から 1 枚を伏せて出す");
  }

  // 盤面の上に短く出す知らせ。演出の層とは別の層に出す（演出の後片付けに巻き込まれない）
  announce(text, sub = "", tone = "") {
    const el = h("div", { class: "fx-call " + tone }, h("div", { text }), sub ? h("small", { text: sub }) : null);
    this.callLayer.replaceChildren(el);
    const ms = cssMs("--fx-call", 1500);
    if (el.animate && settings.fxEnabled()) {
      el.animate([{ opacity: 0, transform: "translate(-50%,-50%) scale(.8)" }, { opacity: 1, transform: "translate(-50%,-50%) scale(1.06)", offset: 0.15 },
        { opacity: 1, transform: "translate(-50%,-50%) scale(1)", offset: 0.3 }, { opacity: 1, transform: "translate(-50%,-50%) scale(1)", offset: 0.8 },
        { opacity: 0, transform: "translate(-50%,-50%) scale(1)" }], { duration: ms, easing: "ease-out", fill: "both" });
    }
    setTimeout(() => { if (el.parentNode) el.remove(); }, ms);
  }

  // リプレイの帯: 局面の文と、再生の操作（replay.js が作る）
  _renderReplayMid() {
    const v = this.view;
    const over = v.outcome !== null && v.outcome !== undefined;
    const turn = v.turn_no > 0 ? `ターン ${v.turn_no}・${this._name(v.turn_player)}の番` : "対局の準備";
    this.waitEl = h("div", { class: "wait mine", id: "replay-label" });      // 何手目か（狭い画面でも消えない場所に出す）
    const status = h("div", { class: "status" }, h("div", { class: "ph", text: `${PHASE_JA[over ? "game_over" : v.phase] || v.phase}｜${turn}` }), this.waitEl);
    this.mid.replaceChildren(status, this.replay.bar());
    this._tick();
  }

  _specialPrompt() {
    if (this.intents.special === "mulligan") return "戻したい手札をタップして印を付ける";
    return "";
  }

  _buttons() {
    const out = [];
    const it = this.intents;
    if (it.special === "setup") {
      out.push({ key: "setup-ok", label: "準備完了", tone: "primary", disabled: this.placed.includes(null), run: () => this._commitSetup() });
    } else if (it.special === "mulligan") {
      const n = this.marks.size;
      out.push({ key: "mulligan-ok", label: n ? `引き直す（${n} 枚）` : "このまま", tone: "primary", run: () => this._commitMulligan() });
    }
    for (const b of it.buttons) {
      if (b.long) continue;                   // 長い文のボタン（解決順）は一覧で出す
      out.push({ ...b, run: () => this.commit(b.idx, b.confirm) });
    }
    return out;
  }

  _tick() {
    const v = this.view; if (!v || !this.waitEl) return;
    const over = v.outcome !== null && v.outcome !== undefined;
    if (this.replay) { this.waitEl.textContent = this.replay.label(); return; }
    if (this.playing) { this.waitEl.textContent = "再生中…（盤面をタップで飛ばす）"; return; }
    if (over) { this.waitEl.textContent = ""; return; }
    if (this.me !== null && v.awaiting.includes(this.me)) { this.waitEl.textContent = this.pending ? "送信中…" : "あなたの入力を待っている"; return; }
    const sec = Math.floor((Date.now() - this.lastViewAt) / 1000);
    const who = v.awaiting.map((g) => this._name(g)).join("・") || "相手";
    const src = this._effectSource();
    this.waitEl.textContent = `${who} の入力待ち${src ? `（${src} の効果）` : ""} ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;   // R-PLAY-9・APP-023
    this._renderBanner();
  }

  _renderBanner() {
    if (this.replay) return;                     // リプレイは部屋の帯に触らない（下の対局の画面のものを消さない）
    for (const b of document.querySelectorAll(".banner")) b.remove();
    if (!this.online) { document.body.append(h("div", { class: "banner", text: "接続が切れた。つなぎ直している…（入力は止めてある）" })); return; }   // R-NET-1
    const r = this.room; if (!r || r.state !== "playing") return;
    const gone = r.seats.filter((s) => s && !s.connected);
    if (gone.length) {
      if (!this.goneSince) this.goneSince = Date.now();
      const sec = Math.floor((Date.now() - this.goneSince) / 1000);
      document.body.append(h("div", { class: "banner opp", text: `${gone.map((s) => s.name).join("・")} が切断中 ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}（負けにはならない）` }));   // R-NET-2
    } else this.goneSince = null;
  }

  // 光らせる: 合法手の表に載っている所作の起点だけ（R-PLAY-3）
  _applyLit() {
    for (const el of this.el.querySelectorAll(".lit, .drop-ok, .lifted")) el.classList.remove("lit", "drop-ok", "lifted");
    if (this.me === null || this.pending || !this.online || this.playing) return;
    const it = this.intents;
    for (const c of this.el.querySelectorAll('[data-role="hand"], [data-role="concerto"], [data-role="tray"], [data-role="placed"]')) {
      if (this._dropsOf(this._from(c)).length) c.classList.add("lit");
    }
    if (it.special === "mulligan") for (const c of this.el.querySelectorAll('[data-role="hand"]')) c.classList.add("lit");
    for (const k of it.clicks) {
      if (k.on.kind === "slot") this._myZone("slot", k.on.slot)?.classList.add("lit");
      if (k.on.kind === "charadeck") {
        this._myZone("charadeck")?.classList.add("lit");
        if (k.on.slot !== undefined) this._myZone("slot", k.on.slot)?.classList.add("lit");     // 場のキャラからもレベルアップできる（APP-026）
      }
    }
    if (this.lifted) {
      const src = this._elOf(this.lifted); if (src) src.classList.add("lifted");
      for (const to of this._dropsOf(this.lifted)) this._dropZone(to)?.classList.add("drop-ok");
    }
  }

  _myZone(name, slot) {
    return this.el.querySelector(`.side.me [data-zone="${name}"]` + (slot !== undefined ? `[data-slot="${slot}"]` : ""));
  }
  _dropZone(to) { return this.el.querySelector(`.side.me [data-drop="${to}"]`); }

  _from(el) {
    const r = el.dataset.role;
    if (r === "hand") return { zone: "hand", index: Number(el.dataset.index) };
    if (r === "concerto") return { zone: "concerto", card: el.dataset.card };
    if (r === "tray") return { zone: "tray", card: el.dataset.card };
    if (r === "placed") return { zone: "placed", slot: Number(el.dataset.slot) };
    return null;
  }
  _elOf(from) {
    if (from.zone === "hand") return this.el.querySelector(`[data-role="hand"][data-index="${from.index}"]`);
    if (from.zone === "concerto") return this.el.querySelector(`[data-role="concerto"][data-card="${CSS.escape(from.card)}"]`);
    if (from.zone === "tray") return this.el.querySelector(`[data-role="tray"][data-card="${CSS.escape(from.card)}"]`);
    if (from.zone === "placed") return this.el.querySelector(`[data-role="placed"][data-slot="${from.slot}"]`);
    return null;
  }
  _dropsOf(from) {
    if (!from) return [];
    if (from.zone === "tray") return ["slot0", "slot1", "slot2"];
    if (from.zone === "placed") return ["slot0", "slot1", "slot2"].filter((s) => s !== "slot" + from.slot);
    return dropsFor(this.intents, from);
  }

  // ------------------------------------------------------------------ 手を送る
  async commit(idx, confirmText) {
    if (this.pending || this.playing || !this.online || idx === undefined || idx === null) return;
    const token = this.view.token;
    if (confirmText) {
      const ok = await confirmDialog(confirmText, { ok: "確定する" });        // R-PLAY-5
      if (!ok || token !== this.view.token) return;
    }
    this.pending = true; this.lifted = null;
    closeModal(); this._applyLit(); this._renderMid();
    if (!this.send({ t: "act", token, index: idx })) { this.pending = false; toast("送れなかった。接続を確かめている"); this._renderMid(); }
  }

  _drop(from, to) {
    if (from.zone === "tray" || from.zone === "placed") return this._placeLocal(from, Number(to.replace("slot", "")));
    const d = findDrag(this.intents, from, to);
    if (d) this.commit(d.idx, d.confirm);
  }

  _placeLocal(from, slot) {
    const card = from.zone === "tray" ? from.card : this.placed[from.slot];
    const prev = this.placed[slot];
    if (from.zone === "placed") this.placed[from.slot] = prev;         // 入れ替え
    this.placed[slot] = card;
    this.lifted = null; this.render();
  }

  _commitSetup() {
    const names = this.placed.map((cid) => (info(cid) || {}).name);
    const idx = (this.view.legal || []).findIndex((a) => a.type === "setup" && a.leader === names[0] && a.backs && a.backs[0] === names[1] && a.backs[1] === names[2]);
    if (idx < 0) return toast("この置き方は選べない");
    this.commit(idx);
  }

  _commitMulligan() {
    const want = [...this.marks].sort((a, b) => a - b).join(",");
    const idx = (this.view.legal || []).findIndex((a) => a.type === "mulligan" && a.cards.join(",") === want);
    if (idx < 0) return toast("この選び方はできない");
    this.commit(idx);
  }

  // ------------------------------------------------------------------ タップ
  _reason(kind, index) {
    const hints = this.view.hints || {};
    if (this.me === null) return hints.general || "観戦中は操作できない";
    if (!this.online) return "接続が切れている";
    if (this.pending) return "送った手の返事を待っている";
    if (kind === "hand") return (hints.hand && hints.hand[index]) || (this.view.phase === "action" && hints.charge) || hints.general;
    if (kind === "slot") return hints.switch || hints.general;
    if (kind === "charadeck") return hints.levelup || hints.general;
    return hints.general;
  }

  _tap(el) {
    const v = this.view; if (!v || this.playing) return;
    const role = el.dataset.role;
    const zoneEl = el.closest("[data-zone]");
    const mineZone = zoneEl && this.me !== null && Number(zoneEl.dataset.owner) === this.me && zoneEl.closest(".side.me");

    // 持ち上げているカードがあれば、置き先のタップを先に見る（R-PLAY-6）
    if (this.lifted) {
      const from = this.lifted;
      const dropEl = el.closest("[data-drop]");
      if (dropEl && dropEl.closest(".side.me") && this._dropsOf(from).includes(dropEl.dataset.drop)) { this.lifted = null; return this._drop(from, dropEl.dataset.drop); }
      this.lifted = null; this._applyLit();
      const same = this._elOf(from);
      if (from.zone === "placed" && el.dataset.role === "placed" && Number(el.dataset.slot) === from.slot) { this.placed[from.slot] = null; return this.render(); }   // もう一度タップで枠から戻す
      if (same && (same === el || same.contains(el))) return;
    }

    if (role === "hand" || role === "concerto" || role === "tray" || role === "placed") {
      if (this.intents.special === "mulligan" && role === "hand" && !this.pending) {
        const i = Number(el.dataset.index);
        if (this.marks.has(i)) this.marks.delete(i); else this.marks.add(i);
        el.classList.toggle("marked"); return this._renderMid();
      }
      const from = this._from(el);
      // 協奏エリアは縦に重ねてあって 1 枚ずつは狙いにくいので、支払いのときはタップで広げて選ぶ（ドラッグでトラッシュへ置いてもよい）
      if (role === "concerto" && !this.pending && this.online && this._dropsOf(from).length) return this._payPicker();
      if (!this.pending && this.online && this._dropsOf(from).length) { this.lifted = from; return this._applyLit(); }
      if (role === "placed") { this.placed[Number(el.dataset.slot)] = null; return this.render(); }
      if (role === "concerto") return this._viewer("協奏エリア", v.players[this.me].concerto);
      return toast(this._reason("hand", Number(el.dataset.index)));
    }
    if (role === "known") return this._viewer("判明している相手の手札", v.players[Number(zoneEl.dataset.owner)].hand_known);
    if (!zoneEl) return;
    const owner = Number(zoneEl.dataset.owner); const p = v.players[owner]; const zone = zoneEl.dataset.zone;
    if (zone === "slot") {
      const slot = Number(zoneEl.dataset.slot);
      const sw = mineZone && !this.pending ? this.intents.clicks.find((c) => c.on.kind === "slot" && c.on.slot === slot) : null;
      const lv = mineZone && !this.pending ? this.intents.clicks.filter((c) => c.on.kind === "charadeck" && c.on.slot === slot) : [];
      if (sw || lv.length) return this._slotMenu(slot, sw, lv);
      const stack = (p.slots[slot] || []).filter((c) => c !== HIDDEN);
      if (mineZone && slot > 0 && v.awaiting.includes(this.me) && v.phase === "action" && stack.length) toast(this._reason("slot"));
      if (stack.length > 1 || !mineZone) return stack.length ? this._viewer(`${this._name(owner)} の ${SLOT_JA[slot]}（重なっているカード）`, stack) : null;
      return;
    }
    if (zone === "charadeck") {
      if (!mineZone || !p.chara_deck) return toast(`${this._name(owner)} のキャラデッキ。中身は見られない`);
      return this._charaDeck();
    }
    if (zone === "trash") return this._viewer(`${this._name(owner)} のトラッシュ（${p.trash.length} 枚）`, p.trash);
    if (zone === "concerto" && mineZone && !this.pending && this.intents.drags.some((d) => d.from.zone === "concerto")) return this._payPicker();
    if (zone === "concerto") return this._viewer(`${this._name(owner)} の協奏エリア（${p.concerto.length} 枚）`, p.concerto);
    if (zone === "action_area") return p.action_area.length ? this._viewer(`${this._name(owner)} のアクションエリア`, p.action_area) : (mineZone ? toast(this._reason("zone")) : null);
    if (zone === "deck") return toast(`${this._name(owner)} のデッキ: ${p.deck_count} 枚`);
    if (zone === "hand" && owner !== this.me) return toast(`${this._name(owner)} の手札: ${p.hand_count} 枚`);
  }

  // ------------------------------------------------------------------ 一覧（R-PLAY-8）
  _grid(cards, { lit = null, onPick = null, onDim = null } = {}) {
    const grid = h("div", { class: "grid" });
    cards.forEach((cid) => {
      const c = cardEl(cid); c.dataset.role = "listed";
      if (lit && lit(cid)) { c.classList.add("lit"); c.dataset.pick = cid; c.addEventListener("click", () => onPick(cid)); }
      else if (lit) { c.classList.add("dim"); if (onDim) c.addEventListener("click", () => onDim(cid)); }
      grid.append(c);
    });
    if (!cards.length) grid.append(h("div", { class: "muted", text: "カードは無い" }));
    return grid;
  }

  _viewer(title, cards) {
    openModal([h("h3", { text: title }), this._grid(cards), h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "閉じる" }))], { wide: true });
  }

  _payPicker() {
    const pays = this.intents.drags.filter((d) => d.from.zone === "concerto");
    const find = (cid) => pays.find((d) => d.from.card === cid);
    const p = this.view.players[this.me];
    const remaining = (this.view.choice && this.view.choice.remaining) || 1;
    openModal([
      h("h3", { text: `協奏エリアから支払うカードを選ぶ（あと ${remaining} 枚）` }),
      h("p", { class: "muted", text: "選んだカードはトラッシュに置かれる。確定すると戻せない" }),
      this._grid(p.concerto, { lit: (cid) => !!find(cid), onPick: (cid) => this.commit(find(cid).idx) }),
      h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "閉じる" })),
    ], { wide: true });
  }

  // 場のキャラを選んだとき（APP-026）: レベルアップとリーダーへの切り替えの両方ができれば尋ね、片方だけならそれに進む
  _slotMenu(slot, sw, lv) {
    if (sw && !lv.length) return this.commit(sw.idx, sw.confirm);
    if (!sw) return this._levelupPick(slot, lv);
    const top = (this.view.players[this.me].slots[slot] || []).filter((c) => c !== HIDDEN).pop();
    openModal([
      h("h3", { text: `${SLOT_JA[slot]}の ${top ? nameOf(top) : "キャラ"}` }),
      h("p", { class: "muted", text: "このキャラで何をする？" }),
      h("div", { class: "list" },
        h("button", { class: "btn primary", dataset: { act: "slot-levelup", pick: "levelup" }, onclick: () => this._levelupPick(slot, lv), text: "レベルアップする" }),
        h("button", { class: "btn", dataset: { act: "slot-switch", pick: "switch" }, onclick: () => { closeModal(); this.commit(sw.idx, sw.confirm); }, text: "リーダーにする（切り替え）" })),
      h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "やめる" })),
    ]);
  }

  // レベルアップ先を選ぶ。候補が 1 つだけなら、選ぶ画面を飛ばして確認だけ出す
  _levelupPick(slot, lv) {
    const cards = [...new Set(lv.map((k) => k.on.card))];
    const find = (cid) => lv.find((k) => k.on.card === cid);
    if (cards.length === 1) { closeModal(); const k = find(cards[0]); return this.commit(k.idx, k.confirm); }
    const top = (this.view.players[this.me].slots[slot] || []).filter((c) => c !== HIDDEN).pop();
    openModal([
      h("h3", { text: `レベルアップ先を選ぶ（${SLOT_JA[slot]}の ${top ? nameOf(top) : "キャラ"}）` }),
      h("p", { class: "muted", text: "キャラデッキから、上に重ねるカードを選ぶ" }),
      this._grid(cards, { lit: () => true, onPick: (cid) => { const k = find(cid); this.commit(k.idx, k.confirm); } }),
      h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "やめる" })),
    ], { wide: true });
  }

  _charaDeck() {
    const p = this.view.players[this.me];
    const ks = this.pending ? [] : this.intents.clicks.filter((c) => c.on.kind === "charadeck");
    const find = (cid) => ks.find((c) => c.on.card === cid);
    openModal([
      h("h3", { text: `キャラデッキ（${p.chara_deck.length} 枚）` }),
      h("p", { class: "muted", text: ks.length ? "光っているカードはレベルアップに使える。重ねる先はカードの名前で決まる" : (this._reason("charadeck") || "") }),
      this._grid(p.chara_deck, { lit: ks.length ? (cid) => !!find(cid) : null, onPick: (cid) => { const k = find(cid); this.commit(k.idx, k.confirm); }, onDim: () => toast("このカードはいまレベルアップに使えない") }),
      h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "閉じる" })),
    ], { wide: true });
  }

  // 一覧から選ぶ選択（ゾーンのカード・効果でのレベルアップ・解決順）。選択が来たら自動で開く
  _afterRender() {
    this._maybeResult();
    const it = this.intents; const v = this.view;
    if (this.me === null || this.pending || !v.awaiting.includes(this.me)) return;
    if (!this.playing && this._autoPay()) return;
    this._call();
    const key = `${v.token}`;
    if (key !== this.pickKey) { this.pickKey = key; this.pickHidden = false; }
    const longs = it.buttons.filter((b) => b.long);
    const picks = it.clicks.filter((c) => c.on.kind === "pick");
    if ((picks.length || longs.length) && !this.pickHidden && !modalOpen()) {
      const cards = [...new Set(picks.map((c) => c.on.card))];
      const find = (cid) => picks.find((c) => c.on.card === cid);
      const others = it.buttons.filter((b) => !b.long);
      if (!it.picks) it.picks = { kind: "order" };
      openModal([
        h("h3", { text: (v.hints && v.hints.prompt) || "選ぶ" }),
        cards.length ? this._grid(cards, { lit: () => true, onPick: (cid) => { const k = find(cid); this.commit(k.idx, k.confirm); } }) : null,
        longs.length ? h("div", { class: "list" }, longs.map((b) => h("button", { class: "btn", dataset: { act: "legal", idx: b.idx }, onclick: () => this.commit(b.idx), text: b.label }))) : null,
        h("div", { class: "row end" },
          others.map((b) => h("button", { class: "btn", dataset: { act: "legal", idx: b.idx }, onclick: () => this.commit(b.idx, b.confirm), text: b.label })),
          h("button", { class: "btn", dataset: { act: "peek" }, onclick: () => { this.pickHidden = true; closeModal(); this._renderMid(); }, text: "盤面を見る" })),
      ], { wide: true, dismissable: false });
      return;
    }
    // 所作に割り当てられない合法手しか無いときは、安全網の一覧を自動で開く（R-PLAY-11）
    const mapped = it.drags.length + it.clicks.length + it.buttons.length + (it.special ? 1 : 0);
    if (it.unmapped.length && !mapped && !modalOpen()) this._legalList(true);
  }

  _legalList(auto = false) {
    const v = this.view; const legal = v.legal || [];
    openModal([
      h("h3", { text: "いま選べる手の一覧" }),
      h("p", { class: "muted", text: auto ? "この選択は盤面の操作にまだ割り当てられていない。ここから選べる" : "普段は盤面のカードを直接触って操作する。ここは予備の入口" }),
      legal.length ? h("div", { class: "list" }, legal.slice(0, 200).map((a, i) => h("button", { class: "btn", dataset: { act: "legal", idx: i }, onclick: () => this.commit(i, "この手を打つ。よい？\n" + ((v.labels || [])[i] || "")), text: (v.labels || [])[i] || JSON.stringify(a) })))
        : h("p", { text: "いまは選べる手が無い" }),
      h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "閉じる" })),
    ]);
  }

  _menu() {
    const playing = this.room && this.room.state === "playing" && this.me !== null;
    openModal([
      h("h3", { text: "メニュー" }),
      h("div", { class: "list" },
        h("button", { class: "btn", dataset: { act: "list" }, onclick: () => this._legalList(), text: "いま選べる手の一覧（予備の入口）" }),
        h("button", { class: "btn", dataset: { act: "log" }, onclick: () => this._showLog(), text: "ログ" }),
        h("button", { class: "btn", dataset: { act: "help" }, onclick: () => help.openHelp(), text: "遊び方" }),
        this.room && this.room.state === "finished" ? h("button", { class: "btn", dataset: { act: "replay" }, onclick: () => { closeModal(); this.onMenu("replay"); }, text: "リプレイ" }) : null,
        h("button", { class: "btn", dataset: { act: "settings" }, onclick: () => settings.openSettings({ onTestSound: () => sfx.play("charge") }), text: "設定" }),
        playing ? h("button", { class: "btn danger", dataset: { act: "resign" }, onclick: async () => {
          if (await confirmDialog("投了する。この対局は負けになる。よい？", { ok: "投了する", danger: true })) this.send({ t: "resign" });   // R-ACT-12
        }, text: "投了する" }) : null,
        h("button", { class: "btn", dataset: { act: "leave" }, onclick: () => this.onMenu("leave"), text: "退室する" })),
      h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "閉じる" })),
    ]);
  }

  _showLog() {
    const box = h("div", { class: "logbox" }, this.log.length ? this.log.map((t) => h("div", { text: t })) : h("div", { text: "まだ何も起きていない" }));
    openModal([h("h3", { text: "ログ" }), box, h("div", { class: "row end" }, h("button", { class: "btn", onclick: closeModal, text: "閉じる" }))]);
    box.scrollTop = box.scrollHeight;
  }

  // ------------------------------------------------------------------ 決着（最小限。演出は M4）
  _maybeResult() {
    if (this.replay) return;
    const r = this.room; const v = this.view;
    const over = v && v.outcome !== null && v.outcome !== undefined;
    if (!over || !r) return;
    if (this.resultShownFor === r.games_played && r.state === "finished") return;
    if (r.state !== "finished") return;
    this.resultShownFor = r.games_played;
    this._showResult();
  }

  _showResult() {
    const v = this.view; const r = this.room || {};
    const res = r.result || { winner: v.outcome === -1 ? null : v.outcome, draw: v.outcome === -1, reason: v.resigned !== undefined ? "resign" : "normal", turns: v.turn_no };
    let big, cls = "";
    if (res.draw || res.winner === null) big = "引き分け";
    else if (this.me === null) big = `${this._name(res.winner)} の勝ち`;
    else if (res.winner === this.me) { big = "勝ち"; cls = "win"; } else { big = "負け"; cls = "lose"; }
    const why = res.reason === "resign" ? "投了" : (res.draw ? "進行不能による引き分け" : "ライフが 0 になった");
    const seat = this.me !== null && r.order ? r.seats[r.order[this.me]] : null;
    openModal(h("div", { class: "result" },
      h("h3", { text: "対局終了" }), h("div", { class: "big " + cls, text: big }),
      h("p", { text: `${why}・${res.turns} ターン` }),
      h("div", { class: "row", style: "justify-content:center" },
        this.me !== null ? h("button", { class: "btn primary", dataset: { act: "rematch" }, disabled: seat && seat.rematch, onclick: (ev) => { this.send({ t: "rematch" }); ev.target.disabled = true; ev.target.textContent = "相手の返事を待っている"; }, text: seat && seat.rematch ? "相手の返事を待っている" : "同じデッキで再戦" }) : null,
        r.state === "finished" ? h("button", { class: "btn", dataset: { act: "replay" }, onclick: () => { closeModal(); this.onMenu("replay"); }, text: "リプレイ" }) : null,
        h("button", { class: "btn", dataset: { act: "lobby" }, onclick: () => { closeModal(); this.onMenu("lobby"); }, text: "ロビーへ" }),
        h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "盤面を見る" }))));
  }

  // ------------------------------------------------------------------ ポインタ（単一の入力経路・R-PLAY-6／7／10）
  _bindPointer() {
    const el = this.el;
    this.slop = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--drag-slop")) || 8;
    this.longMs = cssMs("--t-longpress", 380);
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("dragstart", (e) => e.preventDefault());
    el.addEventListener("pointerdown", (e) => {
      sfx.unlock();
      if (this.playing) { this.fx.skip(); return; }            // 再生はタップで飛ばせる（R-FX-4）
      if (e.button > 0 || this.press) return;
      const t = e.target.closest("[data-role], [data-zone]"); if (!t) return;
      this.press = { t, x: e.clientX, y: e.clientY, id: e.pointerId, zoomed: false, touch: e.pointerType !== "mouse" };
      this.press.timer = setTimeout(() => { if (this.press && !this.drag) { this.press.zoomed = true; this._zoomFor(this.press.t, this.press.x, this.press.y); } }, this.longMs);
    });
    window.addEventListener("pointermove", (e) => this._move(e));
    window.addEventListener("pointerup", (e) => this._up(e));
    window.addEventListener("pointercancel", () => this._cancelPointer());
    // タッチの直後に来る「マウスの」pointerover（互換のために端末やブラウザが出すもの）では拡大しない。出すと指を離しても消えない
    this.lastTouch = -Infinity;
    document.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse") this.lastTouch = performance.now(); }, true);
    const hover = (e) => {                                 // マウスのホバーでも拡大（R-PLAY-7）。通り過ぎただけでは出さない
      if (e.pointerType !== "mouse" || this.press || performance.now() - this.lastTouch < 1000) return;
      clearTimeout(this.hoverTimer);
      const c = e.target.closest(".card");
      if (!c) return this._releaseZoom();
      const x = e.clientX, y = e.clientY;
      this.hoverTimer = setTimeout(() => { if (!this.press && !this.drag && c.isConnected) this._zoomFor(c, x, y); }, 220);
    };
    el.addEventListener("pointerover", hover);
    el.addEventListener("pointerleave", () => { clearTimeout(this.hoverTimer); if (!this.press) this._releaseZoom(); });
    document.getElementById("layer-modal").addEventListener("pointerover", hover);
    this._bindModalPress();
  }

  // ダイアログの中のカードも、タッチの長押しで拡大する（R-PLAY-7）。動かさずに押し続けたら拡大、離すと閉じる。
  // 拡大したあとの指を離したときのクリックは捨てる（拡大を見るつもりで選んでしまわないように）。少し動いたら一覧のスクロールとみなしてやめる
  _bindModalPress() {
    const layer = document.getElementById("layer-modal");
    let mp = null, eatClick = false;
    const end = () => { if (mp) { clearTimeout(mp.timer); if (mp.zoomed) this._releaseZoom(); } mp = null; };
    layer.addEventListener("contextmenu", (e) => { if (e.target.closest(".card")) e.preventDefault(); });   // R-PLAY-10
    layer.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" || mp) return;
      const c = e.target.closest(".card"); if (!c || !c.dataset.cid) return;
      eatClick = false;
      mp = { id: e.pointerId, x: e.clientX, y: e.clientY, zoomed: false };
      mp.timer = setTimeout(() => { if (mp && c.isConnected) { mp.zoomed = true; eatClick = true; this._zoomFor(c, mp.x, mp.y); } }, this.longMs);
    });
    layer.addEventListener("pointermove", (e) => {
      if (mp && e.pointerId === mp.id && !mp.zoomed && Math.hypot(e.clientX - mp.x, e.clientY - mp.y) >= this.slop) end();
    });
    layer.addEventListener("pointerup", (e) => { if (mp && e.pointerId === mp.id) end(); });
    layer.addEventListener("pointercancel", end);
    layer.addEventListener("click", (e) => { if (eatClick) { eatClick = false; e.preventDefault(); e.stopPropagation(); } }, true);
  }

  _move(e) {
    const p = this.press; if (!p || e.pointerId !== p.id) return;
    if (this.drag) {
      const g = this.drag.ghost;
      g.style.left = `${e.clientX - this.drag.dx}px`; g.style.top = `${e.clientY - this.drag.dy}px`;
      const over = this._dropAt(e.clientX, e.clientY);
      for (const z of this.el.querySelectorAll(".drop-hover")) z.classList.remove("drop-hover");
      if (over) over.classList.add("drop-hover");
      return;
    }
    if (p.zoomed) return;
    if (Math.hypot(e.clientX - p.x, e.clientY - p.y) < this.slop) return;
    clearTimeout(p.timer); p.moved = true;
    const from = p.t.dataset.role ? this._from(p.t) : null;
    if (!from || this.pending || !this.online || this.me === null || !this._dropsOf(from).length) return;
    // ドラッグ開始: 置けるゾーンだけが光る（R-PLAY-3）
    const r = p.t.getBoundingClientRect();
    const ghost = p.t.cloneNode(true); ghost.classList.remove("lit", "lifted"); ghost.classList.add("ghost");
    ghost.style.width = `${r.width}px`; ghost.style.height = `${r.height}px`;
    document.body.append(ghost);
    this.drag = { from, ghost, dx: p.x - r.left, dy: p.y - r.top };
    ghost.style.left = `${e.clientX - this.drag.dx}px`; ghost.style.top = `${e.clientY - this.drag.dy}px`;
    p.t.classList.add("dragging"); this.lifted = null; this._hideZoom(); this._applyLit();
    for (const to of this._dropsOf(from)) this._dropZone(to)?.classList.add("drop-ok");
  }

  _dropAt(x, y) {
    const hit = document.elementFromPoint(x, y);
    const z = hit && hit.closest(".side.me [data-drop]");
    return z && z.classList.contains("drop-ok") ? z : null;
  }

  _up(e) {
    const p = this.press; if (!p || e.pointerId !== p.id) return;
    clearTimeout(p.timer); this.press = null;
    if (this.drag) {
      const { from, ghost } = this.drag; this.drag = null;
      const z = this._dropAt(e.clientX, e.clientY);
      ghost.remove(); p.t.classList.remove("dragging");
      for (const el of this.el.querySelectorAll(".drop-hover, .drop-ok")) el.classList.remove("drop-hover", "drop-ok");
      if (z) this._drop(from, z.dataset.drop);           // 置けない場所で離したら何も起きない（R-PLAY-3）
      else this._applyLit();
      return;
    }
    if (p.zoomed) { if (p.touch) this._releaseZoom(); return; }
    if (p.moved) return;
    if (p.touch) this._releaseZoom();
    this._tap(e.target.closest("[data-role], [data-zone]") || p.t);
  }

  _cancelPointer() {
    if (this.press) clearTimeout(this.press.timer);
    if (this.drag) { this.drag.ghost.remove(); this.drag = null; }
    this.press = null;
    for (const el of document.querySelectorAll(".ghost")) el.remove();
    clearTimeout(this.hoverTimer); this._hideZoom();
  }

  _zoomFor(el, x, y = 0) {
    const card = el.closest ? el.closest(".card") : null;
    const cid = card && card.dataset.cid; if (!cid) return this._hideZoom();
    let stack = null;
    const zoneEl = card.closest('[data-zone="slot"]');
    if (zoneEl && this.view) stack = (this.view.players[Number(zoneEl.dataset.owner)].slots[Number(zoneEl.dataset.slot)] || []).filter((c) => c !== HIDDEN);
    const body = zoomEl(cid, stack && stack.includes(cid) ? stack : null); if (!body) return this._hideZoom();
    const layer = document.getElementById("layer-zoom");
    layer.replaceChildren(body); layer.classList.add("on");
    layer.classList.toggle("left", x > window.innerWidth / 2);      // 指やカーソルの反対側に出す
    layer.classList.toggle("low", y < window.innerHeight / 2);
  }
  // 触れ終わったときの片付け。設定「カード拡大の常時表示」（R-SET-1）が入っていれば、最後に見たカードを出したままにする
  _releaseZoom() { if (settings.get().zoom !== "pin") this._hideZoom(); }
  _hideZoom() { const layer = document.getElementById("layer-zoom"); layer.classList.remove("on"); layer.replaceChildren(); }
}
