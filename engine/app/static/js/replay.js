// リプレイ（要件 R-REP-1〜3・APP-019）。終局した対局を、対局と同じ盤面の上で 1 手ずつ見直す。
// 手の列（盤面と出来事）はサーバが記録から当て直して作る。画面はそれを並べて見せるだけで、ルールを持たない。
// 1 手送り（演出つき）・1 手戻し・ターン単位の移動・最初と最後・自動再生・視点の切り替え（先攻の席／後攻の席／公開情報のみ／全情報）。
// 入力はいっさい受けない。下にある対局の画面（部屋）は、そのまま生きている。
// 感想戦（R-REP-4・APP-029）: 部屋の最後の局のリプレイでは、部屋の全員が同じ位置を見られる。位置を動かせるのは操作する 1 人で、誰でも代われる。
// 位置はサーバの部屋の情報（room.review）で配られ、画面はそれに合わせるだけ。視点は各自が選ぶ。
import { h, toast } from "./ui.js";
import { Board } from "./board.js";
import { logLine } from "./fx.js";

export const VIEWERS = [[0, "先攻の席"], [1, "後攻の席"], ["spec", "公開情報のみ"], ["full", "全情報"]];
const same = (a, b) => String(a) === String(b);

export class Replay {
  // fetchFrames(viewer) → Promise<{frames, names, result, viewer}>
  // sync: 部屋の最後の局のときだけ。{ me: 自分の member, send(msg), name(member) → 表示名 }。記録のリプレイには無い
  constructor({ fetchFrames, viewer = "full", onClose = null, sync = null }) {
    this.fetchFrames = fetchFrames; this.onClose = onClose; this.sync = sync; this.rv = null; this.sendTimer = null;
    this.viewer = viewer; this.frames = []; this.i = 0; this.auto = false; this.names = ["", ""]; this.result = null;
    this.layer = h("div", { id: "layer-replay", class: "replay-layer", role: "dialog", "aria-label": "リプレイ" });
    this.badge = h("div", { class: "review-badge", role: "status", hidden: true });   // 感想戦のあいだ、誰が操作しているかを盤面の上に出す
    document.body.append(this.layer);
    this.board = new Board(this.layer, { send: () => false, onMenu: () => {}, replay: { bar: () => this._bar(), label: () => this._label() } });
    this.onKey = (e) => {
      if (document.getElementById("layer-modal").childElementCount) return;
      if (!this.canDrive() && e.key !== "Escape") return;          // 感想戦でほかの人が操作しているあいだは動かさない
      if (e.key === "ArrowRight") { e.preventDefault(); this.step(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); this.jump(this.i - 1); }
      else if (e.key === " ") { e.preventDefault(); this.toggleAuto(); }
      else if (e.key === "Escape") this.close();
    };
    document.addEventListener("keydown", this.onKey);
  }

  async load(viewer = this.viewer) {
    let msg;
    try { msg = await this.fetchFrames(viewer); } catch (e) { toast(e.message || "リプレイを読めなかった"); if (!this.frames.length) this.close(); return false; }
    this.viewer = msg.viewer; this.frames = msg.frames || []; this.names = msg.names || ["", ""]; this.result = msg.result || null;
    this.room = { order: [0, 1], seats: [{ name: this.names[0] || "先攻" }, { name: this.names[1] || "後攻" }], state: "finished" };
    this.jump(Math.min(this.i, this.frames.length - 1), true);
    if (this.rv) this._follow();
    return true;
  }

  // ---------------------------------------------------------------- 感想戦
  canDrive() { return !this.rv || this.rv.driver === this.sync.me; }

  // 部屋の情報が届くたびに呼ばれる。rv は room.review（感想戦をしていなければ null）
  syncReview(rv) {
    if (!this.sync) return;
    const prev = this.rv;
    this.rv = rv || null;
    if (prev && !this.rv) toast("感想戦が終わった。自由に送れる");
    else if (prev && this.rv && prev.n === this.rv.n && prev.driver !== this.rv.driver && this.rv.driver !== this.sync.me)
      toast(`${this.sync.name(this.rv.driver)}が操作を代わった`);
    if (!this.canDrive()) this.stopAuto();
    if (this.frames.length) this._follow();
    this._refresh();
  }

  // 操作している人の位置に合わせる。1 手先なら演出つきで進め、それ以外は飛ぶ
  _follow() {
    if (!this.rv || this.canDrive()) return;
    const pos = Math.max(0, Math.min(this.last, this.rv.pos));
    if (pos === this.i) return;
    if (pos === this.i + 1) this.step(true); else this.jump(pos, false, true);
  }

  // 自分が操作しているとき、位置が動いたら部屋へ知らせる。キーを押し続けても送りすぎないよう、短い間はまとめる
  _announce() {
    if (!this.rv || !this.canDrive()) return;
    clearTimeout(this.sendTimer);
    this.sendTimer = setTimeout(() => { if (this.rv && this.canDrive()) this.sync.send({ t: "review", op: "move", pos: this.i }); }, 120);
  }

  // 帯のボタンは 1 つだけ（狭い画面で帯からはみ出さないように）。誰が操作しているかは盤面の上の札に出す
  _reviewButton() {
    if (!this.sync) return null;
    const btn = (act, text, label, fn) => h("button", { class: "btn review-btn", dataset: { act }, "aria-label": label, title: label, onclick: fn, text });
    if (!this.rv) return btn("rp-review-start", "感想戦", "感想戦を始める（部屋の全員が同じ手を見る）", () => this.sync.send({ t: "review", op: "start", pos: this.i }));
    if (this.canDrive()) return btn("rp-review-stop", "終える", "感想戦を終える", () => this.sync.send({ t: "review", op: "stop" }));
    return btn("rp-review-take", "代わる", "操作を代わる", () => this.sync.send({ t: "review", op: "take" }));
  }

  _renderBadge() {
    if (!this.badge.isConnected) this.layer.append(this.badge);            // 盤面を描き直しても札は残す
    this.badge.hidden = !this.rv;
    if (this.rv) this.badge.textContent = `感想戦: ${this.canDrive() ? "あなた" : this.sync.name(this.rv.driver)}が操作中`;
  }

  get last() { return this.frames.length - 1; }

  _log(upto) {
    const who = (g) => (g === this.board.me ? "あなた" : this.board._name(g));
    const out = [];
    for (let k = 1; k <= upto; k++) for (const e of this.frames[k].events) { const l = logLine(e, who); if (l) out.push(l); }
    return out.slice(-400);
  }

  // 1 手進める。演出の設定が入っていれば、対局と同じ演出で見せる
  step(fromSync = false) {
    if (this.i >= this.last) { this.stopAuto(); return; }
    this.i += 1;
    const f = this.frames[this.i];
    this.board.update(f.view, this.room, f.events, false);
    this._refresh();
    if (!fromSync) this._announce();
  }

  // 好きな手へ飛ぶ（演出なし）
  jump(k, force = false, fromSync = false) {
    k = Math.max(0, Math.min(this.last, k));
    if (k === this.i && !force && this.board.view) return;
    if (!force) this.stopAuto();
    this.board.queue = [];
    if (this.board.playing) this.board.fx.skip();
    this.i = k;
    const f = this.frames[k];
    this.board.view = null;                       // 別の局面から来たことにする（新しい盤面として描き直す）
    this.board.update(f.view, this.room, [], true);
    this.board.log = this._log(k);
    this._refresh();
    if (!force && !fromSync) this._announce();
  }

  _turnStarts() {
    const out = [];
    let prev = null;
    this.frames.forEach((f, k) => { const t = f.view.turn_no; if (t !== prev) { out.push(k); prev = t; } });
    return out;
  }
  nextTurn() { const s = this._turnStarts().find((k) => k > this.i); this.jump(s === undefined ? this.last : s); }
  prevTurn() {
    const starts = this._turnStarts().filter((k) => k < this.i);
    this.jump(starts.length ? starts[starts.length - 1] : 0);
  }

  toggleAuto() { if (this.auto) this.stopAuto(); else this.startAuto(); }
  stopAuto() { if (this.auto) { this.auto = false; this._refresh(); } }
  async startAuto() {
    if (this.i >= this.last) this.jump(0);
    this.auto = true; this._refresh();
    while (this.auto && this.i < this.last) {
      this.step();
      await new Promise((r) => setTimeout(r, 60));
      while (this.auto && (this.board.playing || this.board.queue.length)) await new Promise((r) => setTimeout(r, 60));
      await new Promise((r) => setTimeout(r, 350));
    }
    this.stopAuto();
  }

  async setViewer(v) {
    if (same(v, this.viewer)) return;
    this.stopAuto();
    await this.load(v);
  }

  _label() {
    const res = this.result;
    let tail = "";
    if (this.i === this.last && res) {
      const why = res.reason === "resign" ? "投了" : (res.draw ? "引き分け" : "ライフが 0");
      tail = res.draw || res.winner === null ? `｜引き分け（${why}）` : `｜${this.room.seats[res.winner].name} の勝ち（${why}）`;
    }
    return `${this.i} / ${this.last} 手${tail}`;
  }

  _refresh() {
    const l = document.getElementById("replay-label"); if (l) l.textContent = this._label();
    const bar = this.layer.querySelector(".replay-bar"); if (bar) bar.replaceWith(this._bar());
    if (this.sync) this._renderBadge();
  }

  _bar() {
    const btn = (act, text, label, fn, disabled = false) => h("button", { class: "btn", dataset: { act }, "aria-label": label, title: label, disabled, onclick: fn, text });
    const drive = this.canDrive();
    const atStart = this.i <= 0 || !drive, atEnd = this.i >= this.last || !drive;
    const sel = h("select", { class: "sel", id: "replay-viewer", "aria-label": "視点", title: "視点" },
      VIEWERS.map(([v, t]) => h("option", { value: String(v), selected: same(v, this.viewer), text: t })));
    sel.addEventListener("change", () => this.setViewer(sel.value === "0" || sel.value === "1" ? Number(sel.value) : sel.value));
    return h("div", { class: "acts replay-bar" },
      btn("rp-first", "⏮", "最初へ", () => this.jump(0), atStart),
      btn("rp-prev-turn", "⏪", "前のターンへ", () => this.prevTurn(), atStart),
      btn("rp-prev", "◀", "1 手戻す", () => this.jump(this.i - 1), atStart),
      h("button", { class: "btn primary", dataset: { act: "rp-auto" }, "aria-label": this.auto ? "止める" : "自動再生", title: this.auto ? "止める" : "自動再生",
        disabled: !drive, onclick: () => this.toggleAuto(), text: this.auto ? "⏸" : "▶▶" }),
      btn("rp-next", "▶", "1 手進める", () => this.step(), atEnd),
      btn("rp-next-turn", "⏩", "次のターンへ", () => this.nextTurn(), atEnd),
      btn("rp-last", "⏭", "最後へ", () => this.jump(this.last), atEnd),
      sel,
      btn("rp-log", "ログ", "ログ", () => this.board._showLog()),
      this._reviewButton(),
      btn("rp-close", "閉じる", "リプレイを閉じる", () => this.close()));
  }

  close() {
    this.auto = false;
    clearTimeout(this.sendTimer);
    document.removeEventListener("keydown", this.onKey);
    this.board.destroy();
    this.layer.remove();
    if (this.onClose) this.onClose();
  }
}
