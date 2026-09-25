// 演出層（M4・要件 R-FX-1〜7・R-CLASH-4・R-SND-3）。
//
// 考え方: サーバから届くのは「新しい盤面の全量」と「その間に起きた出来事の列」。演出は、
//   (1) 手元にある**前の盤面の写し**に、出来事を 1 拍ずつ当てて描き直し、カードが飛ぶ・表になる・数字が動くのを見せる
//   (2) 最後に必ず**本物の新しい盤面**で描き直す
// の 2 段で行う。(1) の写しは見せるためだけのもので、当て方が粗くても (2) で必ず正しい盤面に戻る。
// 出来事に載っているカード番号は、サーバがその席の視点だけから作ったものなので、見えないものは演出にも出てこない（R-FX-6）。
import { h, cssMs } from "./ui.js";
import { cardEl, HIDDEN, nameOf, info } from "./cards.js";
import * as settings from "./settings.js";
import * as sfx from "./sfx.js";

const ZONE_SEL = { deck: "deck", trash: "trash", concerto: "concerto", action_area: "action_area", chara_deck: "charadeck" };

// ------------------------------------------------------------------ 拍に分ける
// 出来事の列（サーバが見せる順に並べてある）を「拍」にまとめる。1 拍 = 1 つの見せ場 = 音は 1 つ（R-SND-3）。
const NO_BEAT = new Set(["clash_reveal", "phase", "count", "submitted", "start"]);      // 盤面の描き直しだけで足りるもの
export function toBeats(allEvents, before, after = null) {
  const events = allEvents.filter((e) => !NO_BEAT.has(e.t));
  const beats = [];
  const submitted = new Set(before.submitted || []);
  let i = 0;
  const same = (a, b) => a.t === "move" && b.t === "move" && a.player === b.player && a.from === b.from && a.to === b.to;
  while (i < events.length) {
    const e = events[i];
    if (e.t === "move") {
      let j = i + 1;
      if (e.to === "action_area") {
        while (j < events.length && events[j].t === "move" && events[j].to === "action_area") j++;
        const group = events.slice(i, j);
        const reveal = group.some((m) => submitted.has(m.player));          // 裏向きで置いてあったカードを表にする＝対抗の公開
        beats.push({ kind: reveal ? "reveal" : "moves", moves: group });
      } else if (e.to.startsWith("slot") && e.from.startsWith("slot")) {
        while (j < events.length && events[j].t === "move" && events[j].to.startsWith("slot") && events[j].from.startsWith("slot")) j++;
        beats.push({ kind: "switch", moves: events.slice(i, j) });
      } else if (e.to.startsWith("slot")) {
        while (j < events.length && events[j].t === "move" && events[j].to.startsWith("slot") && !events[j].from.startsWith("slot")) j++;
        beats.push({ kind: "chara", moves: events.slice(i, j) });
      } else {
        while (j < events.length && same(e, events[j])) j++;
        beats.push({ kind: "moves", moves: events.slice(i, j) });
      }
      i = j; continue;
    }
    if (e.t === "life") {
      let j = i + 1; while (j < events.length && events[j].t === "life") j++;
      beats.push({ kind: "life", lives: events.slice(i, j) }); i = j; continue;
    }
    if (e.t === "judge") { beats.push({ kind: "verdict", winner: e.winner }); i++; continue; }
    if (e.t === "skill") { beats.push({ kind: "skill", e }); i++; continue; }        // 効果の解決の区切り（APP-024）
    if (e.t === "turn" || e.t === "refresh" || e.t === "known" || e.t === "game_over" || e.t === "placed" || e.t === "show") beats.push({ kind: e.t, e });
    i++;
  }
  // 対抗が引き分けで終わった（青どうしなど）。エンジンは引き分けの判定を出来事にしないので、公開のあとに判定が無く、
  // 公開したカードがそのまま「前回の対抗」になり勝者が無いことで見分ける（APP-022）
  const shown = beats.findIndex((b) => b.kind === "reveal");
  if (shown >= 0 && !beats.some((b) => b.kind === "verdict") && after) {
    const cards = [null, null]; for (const m of beats[shown].moves) cards[m.player] = m.card;
    const last = after.last_clash_cards || [];
    if (after.last_clash_winner === null && after.clash_winner === null && cards[0] === (last[0] ?? null) && cards[1] === (last[1] ?? null)) {
      beats.splice(shown + 1, 0, { kind: "verdict", winner: null });
    }
  }
  return beats;
}

// 拍ごとの長さ（ミリ秒）と音。**音の優先順位はこの表 1 か所**
function plan(beat, me) {
  const ms = (name, fb) => cssMs(name, fb);
  switch (beat.kind) {
    case "moves": {
      const m = beat.moves[0];
      const n = Math.min(beat.moves.length, 6);
      const sound = m.from === "deck" && m.to === "hand" ? "draw" : m.to === "concerto" ? "charge" : m.to === "action_area" ? "place" : "move";
      return { ms: ms("--fx-flight", 300) + (n - 1) * ms("--fx-stagger", 90), sound };
    }
    case "reveal": return { ms: ms("--fx-reveal", 1300), sound: "clash" };
    case "verdict": return { ms: ms("--fx-judge", 1700), sound: beat.winner === null || beat.winner === undefined ? "draw_clash" : (me === null || beat.winner === me ? "win" : "lose") };
    case "chara": return { ms: ms("--fx-chara", 600), sound: beat.moves.length >= 3 ? "reveal" : "levelup" };
    case "switch": return { ms: ms("--fx-switch", 450), sound: "move" };
    case "life": return { ms: ms("--fx-life", 650), sound: beat.lives.some((l) => l.delta < 0) ? "damage" : "heal" };
    case "turn": return { ms: ms("--fx-turn", 750), sound: "turn" };
    case "refresh": return { ms: ms("--fx-refresh", 600), sound: "move" };
    case "known": return { ms: ms("--fx-known", 850), sound: "reveal" };
    case "skill": return { ms: ms("--fx-skill", 700), sound: null };
    case "show": return { ms: ms("--fx-show", 1700), sound: "reveal" };
    case "placed": return { ms: ms("--fx-placed", 350), sound: "place" };
    case "game_over": return { ms: ms("--fx-over", 1600), sound: me === null ? "victory" : (beat.e.outcome === me ? "victory" : beat.e.outcome === -1 ? "lose" : "defeat") };
    default: return { ms: 0, sound: null };
  }
}

// ------------------------------------------------------------------ 盤面の写しに出来事を当てる
function removeOne(list, card) { const k = list.lastIndexOf(card); if (k >= 0) list.splice(k, 1); else if (list.length && card === null) list.pop(); }

export function applyMove(dv, m) {
  const p = dv.players[m.player]; if (!p) return;
  const slotOf = (z) => (z.startsWith("slot") ? p.slots[Number(z.slice(4))] : null);
  // 出る側
  if (m.from === "hand") {
    if (p.hand) removeOne(p.hand, m.card); else { p.hand_count = Math.max(0, p.hand_count - 1); if (m.card) removeOne(p.hand_known, m.card); }
  } else if (m.from === "deck") p.deck_count = Math.max(0, p.deck_count - 1);
  else if (m.from === "chara_deck") { if (p.chara_deck) removeOne(p.chara_deck, m.card); }
  else if (slotOf(m.from)) removeOne(slotOf(m.from), m.card);
  else if (Array.isArray(p[m.from])) removeOne(p[m.from], m.card);
  // 入る側
  if (m.to === "hand") { if (p.hand) { if (m.card) p.hand.push(m.card); } else p.hand_count += 1; }
  else if (m.to === "deck") p.deck_count += 1;
  else if (m.to === "chara_deck") { if (p.chara_deck && m.card) p.chara_deck.push(m.card); }
  else if (slotOf(m.to)) {
    const st = slotOf(m.to); const k = st.indexOf(HIDDEN);
    if (k >= 0 && m.from === "chara_deck") st[k] = m.card; else st.push(m.card);      // 裏向きだったキャラが表になる
  } else if (Array.isArray(p[m.to]) && m.card) p[m.to].push(m.card);
}

// ------------------------------------------------------------------ 再生
export class Fx {
  constructor(board) {
    this.board = board;
    this.layer = document.getElementById("layer-fx") || document.body.appendChild(h("div", { id: "layer-fx", "aria-hidden": "true" }));
    this.skipped = false; this._wake = null; this.anims = new Set();
    this.stats = { plays: 0, skips: 0, maxMs: 0, lastMs: 0, fast: 0 };
  }

  skip() { if (!this.skipped) { this.skipped = true; this.stats.skips += 1; } for (const a of this.anims) { try { a.finish(); } catch { /* 済んでいる */ } } if (this._wake) this._wake(); }

  _sleep(ms) {
    if (this.skipped || ms <= 0) return Promise.resolve();
    return new Promise((res) => { const t = setTimeout(done, ms); const self = this; function done() { clearTimeout(t); self._wake = null; res(); } this._wake = done; });
  }

  // before: いま画面に出ている盤面。events: サーバが見せる順に並べた出来事。戻るころには、呼び出し側が本物の盤面で描き直す
  async play(before, after, events) {
    const board = this.board;
    const beats = toBeats(events, before, after);
    if (!beats.length) return;
    const plans = beats.map((b) => plan(b, board.me));
    const gap = cssMs("--fx-gap", 120);
    const total = plans.reduce((s, p) => s + p.ms + gap, 0);
    const max = cssMs("--fx-max", 6000);
    const speed = Math.max(0.5, Number(settings.get().speed) || 1);
    const squeeze = Math.min(1, max / total);                  // 上限を超えるぶんは、全体を同じ割合で早回しにする（R-FX-4）
    const k = squeeze / speed;
    const started = performance.now();
    this.skipped = false; this.stats.plays += 1;
    if (squeeze < 0.75) { this.stats.fast += 1; this._badge("出来事が多いので早送り"); }

    const dv = JSON.parse(JSON.stringify(before));
    dv.legal = []; dv.awaiting = []; dv.hints = {}; dv.choice = null;      // 再生中の盤面には、問いかけも触れるものも出さない（R-FX-2・R-FX-3）
    try {
      for (let n = 0; n < beats.length && !this.skipped; n++) {
        const beat = beats[n]; const d = plans[n].ms * k;
        if (plans[n].sound) sfx.play(plans[n].sound);
        await this._beat(beat, dv, d, after);
        await this._sleep(gap * k);
      }
    } finally {
      this._clear();
      const took = performance.now() - started;
      this.stats.lastMs = took; if (!this.skipped) this.stats.maxMs = Math.max(this.stats.maxMs, took);
    }
  }

  async _beat(beat, dv, d, after) {
    const b = this.board;
    switch (beat.kind) {
      case "moves": return this._fly(beat.moves, dv, d);
      case "reveal": {
        dv.submitted = []; delete dv.my_held; dv.phase = after.phase === "clash_submit" ? "choice" : after.phase;
        for (const m of beat.moves) applyMove(dv, m);
        b.renderShown(dv);
        const cards = [undefined, undefined]; for (const m of beat.moves) cards[m.player] = m.card;
        this.lastClash = cards;
        return this._stageOpen(cards, d);
      }
      case "verdict": return this._verdict(beat.winner, d);
      case "chara": {
        for (const m of beat.moves) applyMove(dv, m);
        b.renderShown(dv);
        const els = beat.moves.map((m) => this._zone(m.player, m.to)?.querySelector(".card")).filter(Boolean);
        return this._animate(els, [{ transform: "translateY(-18%) scale(1.18)", filter: "brightness(2.2)" }, { transform: "none", filter: "none" }], d);
      }
      case "switch": {
        for (const m of beat.moves) applyMove(dv, m);
        b.renderShown(dv);
        const zones = [...new Set(beat.moves.flatMap((m) => [m.from, m.to]))].map((z) => this._zone(beat.moves[0].player, z)?.querySelector(".card")).filter(Boolean);
        return this._animate(zones, [{ transform: "scale(.8)", opacity: 0.3 }, { transform: "none", opacity: 1 }], d);
      }
      case "placed": {
        if (!dv.submitted.includes(beat.e.player)) dv.submitted.push(beat.e.player);
        if (after.my_held) dv.my_held = after.my_held;
        dv.phase = after.phase;
        b.renderShown(dv);
        const area = this._zone(beat.e.player, "action_area");
        const el = area && [...area.querySelectorAll(".card")].pop();
        return this._animate(el ? [el] : [], [{ transform: "translateY(-30%) scale(1.15)", opacity: 0 }, { transform: "none", opacity: 1 }], d);
      }
      case "life": {
        for (const l of beat.lives) if (dv.players[l.player]) dv.players[l.player].life = l.value;
        b.renderShown(dv);
        const jobs = beat.lives.map((l) => {
          const z = b.el.querySelector(`[data-zone="life"][data-owner="${l.player}"]`); if (!z) return null;
          const r = z.getBoundingClientRect();
          // ダメージの出どころ（APP-016）: 数字の下にカードの名前を添え、盤面にそのカードがあれば光らせる
          const pop = h("div", { class: "fx-pop " + (l.delta < 0 ? "bad" : "good") }, (l.delta > 0 ? "+" : "") + l.delta,
            l.src ? h("small", { class: "fx-src", text: nameOf(l.src) }) : null);
          pop.style.left = `${r.left + r.width / 2}px`; pop.style.top = `${r.top + r.height / 2}px`;
          this.layer.append(pop);
          // 画面の端のライフでは、数字と名前がはみ出さないように内側へ寄せる。途中で 1.25 倍に膨らみ、上へ高さの 1.7 倍ぶん昇るのを見込む
          const half = pop.offsetWidth * 1.25 / 2 + 6;
          pop.style.left = `${Math.min(Math.max(r.left + r.width / 2, half), window.innerWidth - half)}px`;
          pop.style.top = `${Math.max(r.top + r.height / 2, pop.offsetHeight * 1.7 + 6)}px`;
          const a1 = this._animate([pop], [{ transform: "translate(-50%,-50%) scale(.6)", opacity: 0 }, { transform: "translate(-50%,-90%) scale(1.25)", opacity: 1, offset: 0.25 }, { transform: "translate(-50%,-170%) scale(1)", opacity: 0 }], d);
          const a2 = this._animate([z], l.delta < 0 ? [{ transform: "translateX(0)" }, { transform: "translateX(-7px)" }, { transform: "translateX(7px)" }, { transform: "translateX(-4px)" }, { transform: "none" }] : [{ filter: "brightness(2)" }, { filter: "none" }], d * 0.6);
          const srcEl = l.src ? [...b.el.querySelectorAll(`.card[data-cid="${CSS.escape(l.src)}"]`)].pop() : null;
          const a3 = srcEl ? this._animate([srcEl], [{ filter: "brightness(1)", transform: "none" }, { filter: "brightness(2.2) drop-shadow(0 0 8px var(--danger))", transform: "scale(1.08)", offset: 0.3 }, { filter: "none", transform: "none" }], d) : null;
          return Promise.all([a1, a2, a3]);
        });
        return Promise.all(jobs);
      }
      case "turn": {
        dv.turn_no = beat.e.turn_no; dv.turn_player = beat.e.player; b.renderShown(dv);
        return this._banner(`ターン ${beat.e.turn_no}`, "", d, b.me === beat.e.player ? "あなたの番" : `${b._name(beat.e.player)} の番`);
      }
      case "refresh": {
        const p = dv.players[beat.e.player];
        if (p) { p.deck_count += beat.e.n; p.trash = p.trash.slice(0, Math.max(0, p.trash.length - beat.e.n)); }
        const src = this._rect(beat.e.player, "trash", null);
        b.renderShown(dv);
        return this._ghosts([{ card: null, src, dst: this._rect(beat.e.player, "deck", null) }], d, `${beat.e.n} 枚`);
      }
      case "skill": {                        // どのカードの効果か。盤面のそのカードを光らせ、上に名前を出す。次の効果との間の「間」でもある
        const e = beat.e; const b2 = this.board;
        const who = e.player === b2.me ? "あなた" : b2._name(e.player);
        const tag = h("div", { class: "fx-skill" + (e.player === b2.me ? " me" : " opp") }, h("small", { text: who }), h("b", { text: e.card ? nameOf(e.card) : "伏せたカード" }), " の効果");
        this.layer.append(tag);
        const card = e.card ? [...b2.el.querySelectorAll(`.zone[data-owner="${e.player}"] .card[data-cid="${CSS.escape(e.card)}"]`)].pop() : null;
        await Promise.all([
          this._animate([tag], [{ opacity: 0, transform: "translate(-50%,-8px)" }, { opacity: 1, transform: "translate(-50%,0)", offset: 0.2 }, { opacity: 1, transform: "translate(-50%,0)", offset: 0.8 }, { opacity: 0, transform: "translate(-50%,0)" }], d, { fill: "both" }),
          card ? this._animate([card], [{ filter: "none", transform: "none" }, { filter: "brightness(1.8) drop-shadow(0 0 10px var(--warn))", transform: "scale(1.08)", offset: 0.3 }, { filter: "brightness(1.4) drop-shadow(0 0 6px var(--warn))", transform: "scale(1.04)", offset: 0.8 }, { filter: "none", transform: "none" }], d) : null,
        ]);
        tag.remove(); return undefined;
      }
      case "known": {
        const p = dv.players[beat.e.player];
        if (p && !p.hand) for (const c of beat.e.cards) if (!p.hand_known.includes(c)) p.hand_known.push(c);
        b.renderShown(dv);
        const row = this._zone(beat.e.player, "hand");
        const els = row ? [...row.querySelectorAll(".card.known")].slice(-beat.e.cards.length) : [];
        return this._animate(els, [{ transform: "rotateY(90deg)", filter: "brightness(2)" }, { transform: "none", filter: "none" }], d);
      }
      case "show": {                         // エンジンが知らせた「公開」。宛先に入っている相手にしか届かない（APP-003）
        const box = h("div", { class: "fx-show" }, h("div", { class: "cap", text: `${b._name(beat.e.owner)} のカードを公開` }),
          h("div", { class: "cards" }, beat.e.cards.slice(0, 8).map((c) => cardEl(c))));
        this.layer.append(box);
        await this._animate([box], [{ opacity: 0, transform: "translate(-50%,-50%) scale(.9)" }, { opacity: 1, transform: "translate(-50%,-50%) scale(1)", offset: 0.15 }, { opacity: 1, transform: "translate(-50%,-50%) scale(1)", offset: 0.85 }, { opacity: 0, transform: "translate(-50%,-50%) scale(1)" }], d, { fill: "both" });
        box.remove(); return undefined;
      }
      case "game_over": {
        const o = beat.e.outcome; const mine = b.me !== null;
        const text = o === -1 ? "引き分け" : !mine ? `${b._name(o)} の勝ち` : (o === b.me ? "勝利" : "敗北");
        return this._banner(text, o === -1 || !mine ? "" : (o === b.me ? "good big" : "bad big"), d, beat.e.reason === "resign" ? "投了" : "");
      }
      default: return undefined;
    }
  }

  // ---------------------------------------------------------------- 対抗の見せ場（APP-022）
  // 公開: 両者のカードを画面の真ん中に大きく並べて表にする。判定: 勝った側を光らせ、負けた側を沈める。
  // 左が自分（観戦なら下の席）、右が相手。出さなかった側は「出さなかった」の札を置く
  _stageOpen(cards, d) {
    const b = this.board; const left = b.bottom, right = 1 - b.bottom;
    const side = (g) => {
      const c = cards[g];
      const face = c ? cardEl(c) : h("div", { class: "card none", text: "出さなかった" });
      const i = c ? info(c) : null;
      const sub = i && i.kind !== "chara" ? `${COLOR_JA[i.color] || ""}・速 ${i.speed}` : "";
      const back = cardEl(null); back.classList.add("fx-back");
      return h("div", { class: "fx-duel-side " + (g === b.me ? "me" : "opp"), dataset: { g } },
        h("div", { class: "who", text: g === b.me ? "あなた" : b._name(g) }), h("div", { class: "flip" }, face, back),
        h("div", { class: "sub", text: sub }), h("div", { class: "res" }));
    };
    const L = side(left), R = side(right);
    const stage = h("div", { class: "fx-stage" }, h("div", { class: "fx-duel" }, L, h("div", { class: "vs", text: "VS" }), R), h("div", { class: "fx-reason" }));
    this.layer.append(stage);
    this.stage = stage;
    // 裏向きのカードが両脇から滑り込み、裏が倒れて（90 度）表が起き上がる。表の面は裏返った向きを一度も見せない
    const a0 = this._animate([stage], [{ opacity: 0 }, { opacity: 1, offset: 0.15 }, { opacity: 1 }], d, { fill: "both" });
    const flips = [[L, -1], [R, 1]].flatMap(([el, dir]) => {
      const face = el.querySelector(".flip > .card:not(.fx-back)"), back = el.querySelector(".fx-back");
      return [
        this._animate([back], [{ transform: `translateX(${dir * 60}vw)`, opacity: 0 }, { transform: "none", opacity: 1, offset: 0.35 },
          { transform: "rotateY(90deg)", opacity: 1, offset: 0.5 }, { transform: "rotateY(90deg)", opacity: 0 }], d, { fill: "both" }),
        this._animate([face], [{ transform: "rotateY(90deg)", opacity: 0 }, { transform: "rotateY(90deg)", opacity: 0, offset: 0.5 },
          { transform: "rotateY(0deg) scale(1.08)", filter: "brightness(2.2)", opacity: 1, offset: 0.68 }, { transform: "none", filter: "none", opacity: 1 }], d, { fill: "both" }),
      ];
    });
    const a3 = this._animate([stage.querySelector(".vs")], [{ transform: "scale(0)", opacity: 0 }, { transform: "scale(0)", opacity: 0, offset: 0.55 }, { transform: "scale(1.5)", opacity: 1, offset: 0.7 }, { transform: "scale(1)", opacity: 1 }], d, { fill: "both" });
    return Promise.all([a0, ...flips, a3]);
  }

  async _verdict(winner, d) {
    const b = this.board;
    if (!this.stage) {                      // 判定だけが後から届いた（公開と判定の間に選択が挟まった）。覚えている対抗のカードで開き直す
      if (!this.lastClash) return this._banner(winner === null || winner === undefined ? "引き分け" : (b.me === null ? `判定: ${b._name(winner)} の勝ち` : (winner === b.me ? "判定に勝った" : "判定に負けた")), "", d);
      await this._stageOpen(this.lastClash, d * 0.35);
    }
    const stage = this.stage; const draw = winner === null || winner === undefined;
    const sides = [...stage.querySelectorAll(".fx-duel-side")];
    const grow = window.innerHeight < 480 ? 1.04 : 1.14;       // 背の低い画面（スマホの横持ち）では、名前と色の行に被らないよう控えめに
    const jobs = [];
    for (const el of sides) {
      const g = Number(el.dataset.g); const won = !draw && g === winner;
      el.classList.add(draw ? "draw" : won ? "won" : "lost");
      el.querySelector(".res").textContent = draw ? "引き分け" : won ? "勝ち" : "負け";
      const card = el.querySelector(".flip");
      jobs.push(this._animate([card], won
        ? [{ transform: "none" }, { transform: `scale(${grow + 0.08})`, offset: 0.25 }, { transform: `scale(${grow})` }]
        : draw ? [{ transform: "none" }, { transform: "scale(.96)" }]
          : [{ transform: "none" }, { transform: "translateX(-8px) rotate(-3deg)", offset: 0.15 }, { transform: "translateX(8px) rotate(3deg)", offset: 0.3 }, { transform: "translateY(10px) scale(.9) rotate(-2deg)" }], d * 0.5, { fill: "both" }));
      jobs.push(this._animate([el.querySelector(".res")], [{ transform: "scale(2.2)", opacity: 0 }, { transform: "scale(1)", opacity: 1, offset: 0.4 }, { transform: "scale(1)", opacity: 1 }], d * 0.5, { fill: "both" }));
    }
    stage.querySelector(".fx-reason").textContent = clashReason(this.lastClash, winner, b);
    const head = draw ? "判定: 引き分け" : b.me === null ? `判定: ${b._name(winner)} の勝ち` : (winner === b.me ? "判定: 勝ち" : "判定: 負け");
    const cap = h("div", { class: "fx-verdict " + (draw ? "" : b.me === null ? "" : winner === b.me ? "good" : "bad"), text: head });
    stage.prepend(cap);
    jobs.push(this._animate([cap], [{ opacity: 0, transform: "translateY(-12px)" }, { opacity: 1, transform: "none", offset: 0.3 }, { opacity: 1 }], d * 0.6, { fill: "both" }));
    await Promise.all(jobs);
    await this._sleep(d * 0.5);
    const out = this._animate([stage], [{ opacity: 1 }, { opacity: 0 }], Math.min(300, d * 0.2), { fill: "both" });
    await out; stage.remove(); this.stage = null;
    return undefined;
  }

  // ---------------------------------------------------------------- 飛ぶカード
  async _fly(moves, dv, d) {
    const b = this.board;
    const srcs = moves.map((m) => this._rect(m.player, m.from, m.card));
    for (const m of moves) applyMove(dv, m);
    b.renderShown(dv);
    const used = new Set();
    const jobs = moves.map((m, i) => {
      const el = this._last(m.player, m.to, m.card, used); if (el) used.add(el);
      const dst = el ? el.getBoundingClientRect() : this._rect(m.player, m.to, null);
      return { card: m.card, src: srcs[i], dst, hide: el, side: m.to === "concerto" };
    });
    return this._ghosts(jobs, d);
  }

  async _ghosts(jobs, d, label = "") {
    const n = jobs.length; const shown = Math.min(n, 6);
    const stagger = n > 1 ? cssMs("--fx-stagger", 90) * (d / (cssMs("--fx-flight", 300) + (shown - 1) * cssMs("--fx-stagger", 90))) : 0;
    const each = Math.max(60, d - stagger * (shown - 1));
    await Promise.all(jobs.map((j, i) => {
      if (!j.src || !j.dst) return null;
      if (j.hide) j.hide.style.visibility = "hidden";
      const g = cardEl(j.card); g.classList.add("fx-ghost"); if (j.side) g.classList.add("side");
      if (label) g.append(h("div", { class: "fx-label", text: label }));
      g.style.left = `${j.src.left}px`; g.style.top = `${j.src.top}px`; g.style.width = `${j.src.width}px`; g.style.height = `${j.src.height}px`;
      this.layer.append(g);
      const dx = j.dst.left - j.src.left, dy = j.dst.top - j.src.top;
      const sx = j.dst.width / j.src.width, sy = j.dst.height / j.src.height;
      const delay = Math.min(i, shown - 1) * stagger;
      return this._animate([g], [{ transform: "none", opacity: 1 }, { transform: `translate(${dx}px,${dy}px) scale(${sx},${sy})`, opacity: 1 }], each, { delay, easing: "cubic-bezier(.3,.7,.3,1)", fill: "both" })
        .then(() => { g.remove(); if (j.hide) j.hide.style.visibility = ""; });
    }));
  }

  _zone(player, zone) {
    const el = this.board.el;
    if (zone === "hand") return el.querySelector(`.handrow[data-owner="${player}"]`) || (player === this.board.bottom ? el.querySelector(".tray") : null);
    if (zone.startsWith("slot")) return el.querySelector(`[data-zone="slot"][data-owner="${player}"][data-slot="${zone.slice(4)}"]`);
    return ZONE_SEL[zone] ? el.querySelector(`[data-zone="${ZONE_SEL[zone]}"][data-owner="${player}"]`) : null;
  }

  _last(player, zone, card, used = null) {
    const z = this._zone(player, zone); if (!z) return null;
    const all = [...z.querySelectorAll(card ? `.card[data-cid="${CSS.escape(card)}"]` : ".card.back")].filter((x) => !used || !used.has(x));
    return all.pop() || null;
  }

  // そのゾーンで、カード 1 枚ぶんの矩形。カードが見つからなければゾーンの中央
  _rect(player, zone, card) {
    const z = this._zone(player, zone); if (!z) return null;
    const el = (card && this._last(player, zone, card)) || z.querySelector(".pile") || [...z.querySelectorAll(".card")].pop();
    if (el) return el.getBoundingClientRect();
    const r = z.getBoundingClientRect();
    const any = this.board.el.querySelector(".side .card:not(.side)");
    const w = any ? any.getBoundingClientRect().width : 60, hgt = w * 1.4;
    return new DOMRect(r.left + r.width / 2 - w / 2, r.top + r.height / 2 - hgt / 2, w, hgt);
  }

  // ---------------------------------------------------------------- 下回り
  _animate(els, frames, ms, opts = {}) {
    if (this.skipped || !els.length || ms <= 0) return Promise.resolve();
    return Promise.all(els.map((el) => {
      if (!el.animate) return null;
      const a = el.animate(frames, { duration: ms, easing: "ease-out", ...opts });
      this.anims.add(a);
      return a.finished.catch(() => {}).then(() => this.anims.delete(a));
    }));
  }

  async _banner(text, tone, ms, sub = "") {
    const el = h("div", { class: "fx-banner " + tone }, h("div", { text }), sub ? h("small", { text: sub }) : null);
    this.layer.append(el);
    await this._animate([el], [{ opacity: 0, transform: "translate(-50%,-50%) scale(.85)" }, { opacity: 1, transform: "translate(-50%,-50%) scale(1)", offset: 0.18 }, { opacity: 1, transform: "translate(-50%,-50%) scale(1)", offset: 0.8 }, { opacity: 0, transform: "translate(-50%,-50%) scale(1.04)" }], ms, { fill: "both" });
    el.remove();
  }

  _badge(text) { const el = h("div", { class: "fx-badge", text }); this.layer.append(el); }

  _clear() { for (const a of this.anims) { try { a.cancel(); } catch { /* 済んでいる */ } } this.anims.clear(); this.layer.replaceChildren(); this.stage = null; this._wake = null; }
}

const COLOR_JA = { red: "赤", green: "緑", blue: "青" };
const BEATS = { red: "green", green: "blue", blue: "red" };

// 判定の理由の 1 行（見せるためだけ。ルールは判定しない）。スピードを書き換える効果があるので、同じ色のときは数字を言い切らない
export function clashReason(cards, winner, board) {
  if (!cards) return "";
  const [c0, c1] = [cards[0] ? info(cards[0]) : null, cards[1] ? info(cards[1]) : null];
  if (!c0 && !c1) return "";
  if (!c0 || !c1) return "片方だけが出した";
  if (c0.color !== c1.color && BEATS[c0.color] === c1.color) return `${COLOR_JA[c0.color]} は ${COLOR_JA[c1.color]} に勝つ（3 すくみ）`;
  if (c0.color !== c1.color && BEATS[c1.color] === c0.color) return `${COLOR_JA[c1.color]} は ${COLOR_JA[c0.color]} に勝つ（3 すくみ）`;
  if (c0.color === "blue" && c1.color === "blue") return "青どうしは引き分け";
  return winner === null || winner === undefined ? "" : `同じ色: スピードの比べ合い${board && winner === board.view?.turn_player ? "（同じならターンプレイヤー）" : ""}`;
}

// ログの 1 行（要件 R-FX-8）。移動は、どこからどこへ動いたかで書き分ける
const Z = { hand: "手札", deck: "デッキ", trash: "トラッシュ", concerto: "協奏エリア", action_area: "アクションエリア", chara_deck: "キャラデッキ", slot0: "リーダー", slot1: "バック", slot2: "バック", unknown: "？" };
export function logLine(e, who) {
  const w = e.player !== undefined ? who(e.player) : "";
  const c = e.card ? nameOf(e.card) : "カード 1 枚";
  switch (e.t) {
    case "turn": return `—— ターン ${e.turn_no}（${w}）——`;
    case "move": {
      const f = e.from, t = e.to;
      if (f === "deck" && t === "hand") return `${w}: ドロー ${e.card ? c : ""}`.trim();
      if (f === "hand" && t === "concerto") return `${w}: チャージ ${c}`;
      if (f === "concerto" && t === "trash") return `${w}: コストの支払い ${c}`;
      if (t === "action_area") return `${w}: 使用 ${c}`;
      if (f === "action_area" && t === "trash") return `${w}: 使い終わった札 ${c}`;
      if (f === "hand" && t === "trash") return `${w}: 捨て札 ${c}`;
      if (f === "hand" && t === "deck") return `${w}: 手札をデッキに戻した（${c}）`;
      if (f === "chara_deck" && t.startsWith("slot")) return `${w}: ${Z[t]}に重ねた ${c}`;
      if (f.startsWith("slot") && t.startsWith("slot")) return `${w}: 入れ替え ${c}（${Z[f]} → ${Z[t]}）`;
      return `${w}: 効果による移動 ${c}（${Z[f] || f} → ${Z[t] || t}）`;
    }
    case "placed": return `${w}: 裏向きで 1 枚置いた`;
    case "submitted": return `${w}: 選び終えた`;
    case "clash_reveal": return `${w}: 公開 ${nameOf(e.card)}`;
    case "judge": return `判定: ${who(e.winner)} の勝ち`;
    case "skill": return `${w}: ${e.card ? nameOf(e.card) : "伏せたカード"} の効果`;
    case "life": {
      const base = `${w}: ライフ ${e.delta > 0 ? "+" : ""}${e.delta} → ${e.value}`;
      if (e.delta >= 0) return base;
      const amt = e.amount && e.amount !== -e.delta ? ` ${e.amount} ダメージ` : "";
      return e.src ? `${base}（${nameOf(e.src)} の${amt || "ダメージ"}）` : (amt ? `${base}（${amt.trim()}）` : base);
    }
    case "refresh": return `${w}: トラッシュ ${e.n} 枚をデッキに戻した`;
    case "known": return `${w} の手札が判明: ${e.cards.map(nameOf).join("、")}`;
    case "show": return `${who(e.owner)}: 公開 ${e.cards.map(nameOf).join("、")}`;
    case "game_over": return "対局終了";
    default: return "";
  }
}
