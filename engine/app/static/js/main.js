// 入口。画面の切り替え（ホーム → 入室 → ロビー → 対局）と、通信の受け口。
import { h, toast, confirmDialog, openModal, closeModal } from "./ui.js";
import { Conn, api } from "./net.js";
import { loadCards, dbInfo, info } from "./cards.js";
import { decodeDeck, looksLikeDeckCode, DeckCodeError } from "./deckcode.js";
import { Board } from "./board.js";
import * as store from "./store.js";
import * as settings from "./settings.js";
import * as help from "./help.js";
import { Replay } from "./replay.js";
import * as art from "./art.js";

const app = document.getElementById("app");
const APP_NAME = "MeichoSim";
const NOTICE = "これは『鳴潮：対決』の非公式のファン製ツールで、権利者とは関係が無い。公式のカード画像とテキストは含まない。無償で、招待された人だけが使う。";
const FIRST_JA = { random: "ランダム", seat0: "席 1 が先攻", seat1: "席 2 が先攻", loser: "前の局の敗者が選ぶ（再戦から）" };

const S = { conn: null, room: null, member: null, view: null, board: null, online: false, forceLobby: false, builtin: [], pass: "", cpu: { enabled: false, decks: {} } };
window.__meichosim = S;      // 調べもの用の取っ手（コンソールから状態を見る）。画面の動作には使わない
const roomId = new URLSearchParams(location.search).get("room");

function brand() {
  return h("div", { class: "brand" }, h("h1", { text: APP_NAME }), h("span", { class: "tag", text: "非公式" }));
}
function notice() { return h("p", { class: "legal-note", text: NOTICE }); }

// ------------------------------------------------------------------ ホーム（S1）
function renderHome(message) {
  document.title = `${APP_NAME}（非公式）`;
  const name = h("input", { id: "name", maxlength: 24, value: store.load("name", ""), autocomplete: "off" });
  const pass = h("input", { id: "pass", maxlength: 64, autocomplete: "off" });
  const err = h("div", { class: "err", text: message || "" });
  const create = async () => {
    err.textContent = "";
    if (!name.value.trim()) return (err.textContent = "表示名を入れてほしい");
    if (!pass.value) return (err.textContent = "合言葉を決めてほしい（入室する人に口頭で伝える）");
    store.save("name", name.value.trim());
    try {
      const r = await api("/api/rooms", { pass: pass.value });
      try { sessionStorage.setItem("meichosim.pass." + r.room, pass.value); } catch { /* なくても入室画面で入れ直せる */ }
      location.href = `/?room=${encodeURIComponent(r.room)}`;
    } catch (e) { err.textContent = e.message; }
  };
  app.replaceChildren(h("div", { class: "page" }, brand(),
    h("div", { class: "panel" }, h("h2", { text: "あなたの表示名" }), h("label", { class: "field" }, h("span", { text: "対局の画面と記録に出る名前" }), name)),
    cpuPanel(name),
    h("div", { class: "panel" }, h("h2", { text: "部屋を作る（人と対戦）" }),
      h("label", { class: "field" }, h("span", { text: "合言葉（リンクには入らない。相手には通話で伝える）" }), pass),
      err, h("div", { class: "row end" }, h("button", { class: "btn primary", id: "create", onclick: create, text: "部屋を作る" }))),
    h("div", { class: "panel" }, h("h2", { text: "招待された人は" }), h("p", { class: "muted", text: "受け取った招待リンクを開くと、入室の画面になる。" })),
    h("p", { class: "muted", id: "home-version", text: `ルール ${dbInfo.rules}・カードデータ ${dbInfo.version}` }),
    h("div", { class: "row" }, h("a", { class: "btn", id: "home-deck", href: "/deck", text: "デッキを組む" }),
      h("button", { class: "btn", id: "home-help", onclick: () => help.openHelp(), text: "遊び方" }),
      S.cpu.enabled ? h("button", { class: "btn", id: "home-records", onclick: openRecords, text: "記録を見る" }) : null,
      h("button", { class: "btn", id: "home-settings", onclick: () => settings.openSettings(), text: "設定・版と更新の履歴" })),
    notice()));
  help.maybeFirstTime();                       // 初回だけ遊び方を開く（R-HELP-1）
  // 版と、更新がうまくいかなかったときの案内（要件 R-UPD-8・R-UPD-9）。うまくいっているときは版の名前だけを足す
  settings.versionInfo().then((v) => {
    const line = document.getElementById("home-version");
    if (!line || !v.version) return;
    line.textContent = `版 ${v.version}・` + line.textContent;
    const st = v.update && v.update.state;
    if (st && !["latest", "updated", "no_feed", "offline"].includes(st)) {        // 繋がっていないのは普通のことなので、ホームでは騒がない（設定画面には出る）
      line.before(h("div", { class: "panel notice-panel", id: "update-notice" }, h("p", { class: "warn-text", text: settings.updateMessage(v) })));
    }
  });
}

// CPU 対戦（要件 R-CPU）。手元で起動したときだけ、サーバが選択肢を返す。v1 は同じ固定デッキどうし
function cpuPanel(nameInput) {
  const decks = Object.keys(S.cpu.decks || {});
  if (!S.cpu.enabled || !decks.length) return null;
  const last = store.load("cpu", {}) || {};
  const deck = h("select", { id: "cpu-deck" }, decks.map((d) => h("option", { value: d, selected: last.deck === d, text: d })));
  const level = h("select", { id: "cpu-level" });
  const fill = () => level.replaceChildren(...(S.cpu.decks[deck.value] || []).map((o) => h("option", { value: o.level, selected: last.level === o.level, text: o.label })));
  deck.addEventListener("change", fill); fill();
  const first = h("select", { id: "cpu-first" }, [["random", "ランダム"], ["me", "自分が先攻"], ["cpu", "CPU が先攻"]].map(([v, t]) => h("option", { value: v, selected: last.first === v, text: t })));
  const err = h("div", { class: "err" });
  const go = async () => {
    err.textContent = "";
    const who = nameInput.value.trim() || "あなた";
    store.save("name", who);
    store.save("cpu", { deck: deck.value, level: Number(level.value), first: first.value });
    try {
      const r = await api("/api/cpu", { deck: deck.value, level: Number(level.value), first: first.value });
      try { sessionStorage.setItem("meichosim.pass." + r.room, r.pass); } catch { /* 入室画面で入れ直せないので、下で直接つなぐ */ }
      location.href = `/?room=${encodeURIComponent(r.room)}`;
    } catch (e) { err.textContent = e.message; }
  };
  return h("div", { class: "panel" }, h("h2", { text: "CPU と対戦" }),
    h("div", { class: "row" },
      h("label", { class: "field", style: "flex:1 1 120px" }, h("span", { text: "デッキ（あなたも CPU も同じ）" }), deck),
      h("label", { class: "field", style: "flex:1 1 120px" }, h("span", { text: "強さ" }), level),
      h("label", { class: "field", style: "flex:1 1 120px" }, h("span", { text: "先攻・後攻" }), first)),
    err, h("div", { class: "row end" }, h("button", { class: "btn primary", id: "cpu-start", onclick: go, text: "対戦を始める" })),
    h("p", { class: "muted", text: "CPU 対戦は、このアプリを手元の PC で起動したときだけ使える。" }));
}

// ------------------------------------------------------------------ 入室
function renderJoin(message) {
  const name = h("input", { id: "name", maxlength: 24, value: store.load("name", ""), autocomplete: "off" });
  const pass = h("input", { id: "pass", maxlength: 64, autocomplete: "off" });
  const err = h("div", { class: "err", text: message || "" });
  const go = () => {
    if (!name.value.trim()) return (err.textContent = "表示名を入れてほしい");
    store.save("name", name.value.trim());
    connect(name.value.trim(), pass.value, null);
  };
  app.replaceChildren(h("div", { class: "page" }, brand(),
    h("div", { class: "panel" }, h("h2", { text: "部屋に入る" }),
      h("label", { class: "field" }, h("span", { text: "表示名" }), name),
      h("label", { class: "field" }, h("span", { text: "合言葉（部屋を作った人に聞く）" }), pass),
      err, h("div", { class: "row end" }, h("a", { class: "btn", href: "/", style: "display:inline-grid;place-items:center;text-decoration:none", text: "ホームへ" }),
        h("button", { class: "btn primary", id: "join", onclick: go, text: "入室する" }))), notice()));
  pass.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  help.maybeFirstTime();                       // 招待リンクから来た人にも、初回だけ遊び方を開く（R-HELP-1）
}

// ------------------------------------------------------------------ 通信
function connect(name, pass, key) {
  if (S.conn) S.conn.stop();
  S.pass = pass;
  app.replaceChildren(h("p", { class: "boot", text: "つないでいる…" }));
  S.conn = new Conn({ room: roomId, name, pass, key, onMessage, onStatus });
  S.conn.start();
}

function onStatus(status, detail) {
  S.online = status === "open";
  if (S.board) S.board.setOnline(S.online);
  if (status === "fatal") {
    if (S.board) { S.board.destroy(); S.board = null; }
    for (const b of document.querySelectorAll(".banner")) b.remove();
    if (detail === "replaced") return app.replaceChildren(h("div", { class: "page" }, brand(), h("div", { class: "panel" }, h("h2", { text: "別の画面で開き直された" }), h("p", { text: "同じ席を別のタブか端末で開いたので、この画面は止めた。" }), h("button", { class: "btn primary", onclick: () => location.reload(), text: "この画面でつなぎ直す" }))));
    if (detail === "version") return app.replaceChildren(h("div", { class: "page" }, brand(), h("div", { class: "panel" }, h("h2", { text: "アプリの版が合わない" }), h("p", { text: "ページを読み込み直してほしい。" }), h("button", { class: "btn primary", onclick: () => location.reload(), text: "読み込み直す" }))));
    if (detail === "no_room") { store.setSeatKey(roomId, null); return renderHome("その部屋はもう無い（閉じたか、リンクが違う）"); }
    store.setSeatKey(roomId, null);
    const why = { bad_pass: "合言葉が違う", bad_name: "表示名を入れてほしい", room_full: "観戦者がいっぱい（4 人まで）", flood: "操作が速すぎて切断された" }[detail] || "入れなかった";
    return renderJoin(detail === "bad_pass" && !S.pass ? "" : why);      // 鍵が無効になっていただけなら、黙って入室の画面に戻す
  }
  if (!S.board && S.room && !S.online) toast("接続が切れた。つなぎ直している…");
}

function onMessage(msg) {
  switch (msg.t) {
    case "welcome":
      S.member = msg.member; S.room = msg.room; S.view = null;
      store.setSeatKey(roomId, msg.key);
      render(); break;
    case "room": {
      const before = S.room && S.room.state;
      S.room = msg.room;
      if (msg.room.state === "lobby" || msg.room.state === "choosing_first") { S.view = null; S.forceLobby = false; }
      if (before !== "playing" && msg.room.state === "playing") { S.forceLobby = false; closeModal(); }
      render(); break;
    }
    case "view":
      S.view = msg.view;
      render(msg.events || [], !!msg.full); break;
    case "replay":
      if (S.replayWait) { S.replayWait.resolve(msg); S.replayWait = null; }
      break;
    case "error":
      if (S.replayWait && ["not_finished", "no_room", "bad_record", "bad_message"].includes(msg.code)) { S.replayWait.reject(new Error(msg.msg || msg.code)); S.replayWait = null; break; }
      if (msg.code === "stale") toast("画面が古かったので、最新の状態に取り直した");      // R-NET-5
      else toast(msg.msg || msg.code);
      if (S.board && !S.board.playing) { S.board.pending = false; S.board.render(); } else if (S.board) S.board.pending = false;
      break;
    default: break;
  }
}

function send(msg) { return S.conn ? S.conn.send(msg) : false; }

// ------------------------------------------------------------------ 画面の切り替え
function render(events, full = false) {
  const r = S.room; if (!r) return;
  const showBoard = S.view && (r.state === "playing" || (r.state === "finished" && !S.forceLobby));
  if (showBoard) {
    if (!S.board) {
      S.board = new Board(app, { send, onMenu });
      S.board.setOnline(S.online);
    }
    if (events !== undefined) S.board.update(S.view, r, events, full); else S.board.setRoom(r);
    return;
  }
  if (S.board) { S.board.destroy(); S.board = null; for (const b of document.querySelectorAll(".banner")) b.remove(); }
  renderLobby();
}

async function onMenu(what) {
  if (what === "lobby") { S.forceLobby = true; render(); }
  if (what === "replay") openRoomReplay();
  if (what === "leave") {
    const playing = S.room && S.room.state === "playing" && mySeat() !== null;
    const ok = await confirmDialog(playing ? "退室する。対局は負けにならず、あとで同じ端末からこのリンクを開けば席に戻れる。よい？" : "退室する。よい？", { ok: "退室する" });   // R-NET-7
    if (ok) { S.conn.stop(); location.href = "/"; }
  }
}

// ------------------------------------------------------------------ リプレイ（APP-019）
// 部屋の最後の局: 終局したあと、部屋の全員が見られる。手の列はサーバが作って送ってくる
function openRoomReplay() {
  const fetchFrames = (viewer) => new Promise((resolve, reject) => {
    if (S.replayWait) S.replayWait.reject(new Error("前の読み込みを取り消した"));
    S.replayWait = { resolve, reject };
    if (!send({ t: "replay", viewer })) { S.replayWait = null; reject(new Error("接続が切れている")); }
    setTimeout(() => { if (S.replayWait && S.replayWait.resolve === resolve) { S.replayWait = null; reject(new Error("リプレイの読み込みが時間切れになった")); } }, 20000);
  });
  const me = S.board && S.board.me !== null && S.board.me !== undefined ? S.board.me : "full";
  new Replay({ fetchFrames, viewer: me }).load(me);
}

// 手元の記録の一覧（手元で起動したときだけ）。終局した対局を新しい順に出し、選ぶとリプレイを開く
async function openRecords() {
  let list;
  try { list = (await api("/api/records")).records || []; } catch (e) { return toast(e.message); }
  const reason = (r) => (r.result ? (r.result.reason === "resign" ? "投了" : r.result.draw ? "引き分け" : "ライフ 0") : "");
  const winner = (r) => (!r.result || r.result.draw || r.result.winner === null ? "引き分け" : `${(r.names || [])[r.result.winner] || "?"} の勝ち`);
  const row = (r) => h("div", { class: "record-row", dataset: { id: r.id } },
    h("div", { class: "rec-main" },
      h("b", { text: `${(r.names || []).join(" 対 ")}` }),
      h("span", { class: "muted", text: `　${String(r.played_at || "").replace("T", " ").slice(0, 16)}・${r.kind === "cpu" ? `CPU（${r.opponent || ""}）` : "対人"}・${(r.decks || []).join(" / ")}` }),
      h("div", { class: r.problem ? "warn-text" : "muted", text: r.problem ? `再生できない: ${r.problem}` : `${winner(r)}（${reason(r)}・${(r.result || {}).turns ?? "?"} ターン）` })),
    h("button", { class: "btn primary", dataset: { act: "record-replay" }, disabled: !!r.problem, onclick: () => { closeModal(); openRecordReplay(r); }, text: "リプレイ" }));
  openModal([h("h3", { text: "記録（この PC で終局した対局）" }),
    list.length ? h("div", { class: "records" }, list.map(row)) : h("p", { class: "muted", text: "まだ記録が無い。対局を最後まで打つと、ここに出る。" }),
    h("div", { class: "row end" }, h("button", { class: "btn", dataset: { act: "close" }, onclick: closeModal, text: "閉じる" }))], { wide: true });
}

function openRecordReplay(r) {
  const fetchFrames = (viewer) => api("/api/records/replay", { id: r.id, viewer });
  const me = r.kind === "cpu" && (r.cpu_seat === 0 || r.cpu_seat === 1) ? 1 - r.cpu_seat : "full";
  new Replay({ fetchFrames, viewer: me }).load(me);
}

function mySeat() {
  const r = S.room; if (!r) return null;
  const i = r.seats.findIndex((s) => s && s.member === S.member);
  return i < 0 ? null : i;
}

// ------------------------------------------------------------------ ロビー（S2）
function allDecks() {
  // デッキメーカーの作りかけ（空のデッキ）は出さない。構築ルールの検査はサーバが行う（正は GameConfig.validate）
  const mine = (store.load("decks", []) || []).filter((d) => d && ((d.chara_deck || []).length || (d.action_deck || []).length));
  return [...S.builtin.map((d) => ({ ...d, builtin: true })), ...mine];
}

function renderLobby() {
  const r = S.room; const seatNo = mySeat(); const isOwner = r.owner === S.member;
  document.title = `${APP_NAME}（非公式）`;
  const link = `${location.origin}/?room=${encodeURIComponent(r.id)}`;
  const linkInput = h("input", { readonly: true, value: link, id: "invite", onfocus: (e) => e.target.select() });
  const copy = async () => {
    try { await navigator.clipboard.writeText(link); toast("招待リンクをコピーした。合言葉は通話で伝える"); }
    catch { linkInput.select(); toast("コピーできなかった。リンクを選んであるので、手でコピーしてほしい"); }
  };
  const seatCard = (i) => {
    const s = r.seats[i]; const mine = seatNo === i;
    const head = h("h3", {}, h("span", { text: `席 ${i + 1}` }), r.order ? null : null,
      s ? h("span", { class: "pill " + (s.connected ? (s.ready ? "ok" : "") : "warn"), text: !s.connected ? "切断中" : s.ready ? "準備完了" : "準備中" }) : h("span", { class: "pill", text: "空席" }));
    const body = [head];
    if (s) {
      body.push(h("div", { class: "who", text: s.name + (s.member === r.owner ? "（部屋主）" : "") }),
        h("div", { class: "muted", text: s.has_deck ? `デッキ: ${s.deck_name || "（名前なし）"}` : "デッキ: まだ選んでいない" }));
    }
    if (!s && r.state !== "choosing_first") body.push(h("button", { class: "btn primary", dataset: { act: "sit", seat: i }, onclick: () => send({ t: "sit", seat: i }), text: "この席に着く" }));
    if (s && !s.connected && !mine && seatNo === null) body.push(h("button", { class: "btn", onclick: () => send({ t: "sit", seat: i }), text: "切断中の席に代わりに着く" }));
    if (mine && r.state !== "choosing_first") {
      const decks = allDecks();
      const sel = h("select", { id: "deck-select" }, h("option", { value: "", text: "デッキを選ぶ…" }),
        decks.map((d, k) => h("option", { value: k, selected: s.has_deck && d.name === s.deck_name, text: (d.builtin ? "［同梱］" : "") + d.name })));
      sel.addEventListener("change", () => { const d = decks[Number(sel.value)]; if (sel.value !== "" && d) send({ t: "deck", deck: { name: d.name, chara_deck: d.chara_deck, action_deck: d.action_deck } }); });
      body.push(h("label", { class: "field" }, h("span", { text: "使うデッキ（中身は相手にも観戦者にも送られない）" }), sel),
        h("div", { class: "row" },
          h("button", { class: "btn small", onclick: importDeck, text: "デッキを読み込む" }),
          h("a", { class: "btn small", href: "/deck", target: "_blank", rel: "noopener", text: "デッキを組む" }),
          h("button", { class: "btn small", onclick: () => send({ t: "stand" }), text: "席を立つ" }),
          h("button", { class: "btn " + (s.ready ? "" : "primary"), id: "ready", disabled: !s.has_deck, onclick: () => send({ t: "ready", on: !s.ready }), text: s.ready ? "準備完了を取り消す" : "準備完了" })));
    }
    return h("div", { class: "seat" + (mine ? " mine" : "") }, body);
  };
  const first = h("select", { id: "first", disabled: !isOwner || r.state !== "lobby" }, Object.entries(FIRST_JA).map(([k, t]) => h("option", { value: k, selected: r.first === k, text: t })));
  first.addEventListener("change", () => send({ t: "settings", first: first.value }));

  const panels = [
    h("div", { class: "panel" }, h("h2", { text: "招待" }),
      h("div", { class: "invite" }, linkInput, h("button", { class: "btn primary", id: "copy", onclick: copy, text: "リンクをコピー" })),
      r.kind === "cpu"
        ? h("p", { class: "muted", text: `CPU 対戦の部屋。観戦してもらうには、このリンクと合言葉「${S.pass || "（この画面を作った人に聞く）"}」を伝える。` })
        : h("p", { class: "muted", text: "合言葉はリンクに入っていない。入る人には通話で伝える。" })),
  ];
  if (r.state === "choosing_first") {
    const chooser = r.chooser === seatNo;
    panels.push(h("div", { class: "panel" }, h("h2", { text: "先攻・後攻を決める" }),
      chooser ? h("div", { class: "row" }, h("p", { text: "前の局の敗者が選ぶ。" }),
        h("button", { class: "btn primary", dataset: { act: "first-me" }, onclick: () => send({ t: "first", choice: "me" }), text: "自分が先攻" }),
        h("button", { class: "btn", dataset: { act: "first-opp" }, onclick: () => send({ t: "first", choice: "opp" }), text: "相手が先攻" }))
        : h("p", { text: `${(r.seats[r.chooser] || {}).name || "相手"} が先攻・後攻を選んでいる。` })));
  }
  if (r.state === "finished" && S.view) panels.push(h("div", { class: "panel" }, h("div", { class: "row" }, h("span", { text: "前の対局は終わっている。" }), h("button", { class: "btn", onclick: () => { S.forceLobby = false; render(); }, text: "盤面と結果を見る" }))));
  panels.push(
    h("div", { class: "panel" }, h("h2", { text: "席" }), h("div", { class: "seats" }, seatCard(0), seatCard(1)),
      h("label", { class: "field", style: "margin-top:12px" }, h("span", { text: "先攻・後攻" + (isOwner ? "" : "（部屋主が決める）") }), first),
      h("p", { class: "muted", text: "2 人とも準備完了になると対局が始まる。席に着かなければ観戦になる。" })),
    h("div", { class: "panel" }, h("h2", { text: `観戦者（${r.spectators.length} / 4）` }),
      h("p", { class: "muted", text: r.spectators.length ? r.spectators.map((s) => s.name).join("、") : "いない" }),
      h("div", { class: "row end" }, h("button", { class: "btn", onclick: () => onMenu("leave"), text: "退室する" }))));
  app.replaceChildren(h("div", { class: "page" }, brand(), panels, notice()));
}

function importDeck() {
  const ta = h("textarea", { id: "deck-json", placeholder: 'デッキコード（英数字の 1 行）か、{"name": "…", "chara_deck": ["…"], "action_deck": ["…"]}' });
  const err = h("div", { class: "err" });
  const file = h("input", { type: "file", accept: ".json,application/json" });
  file.addEventListener("change", async () => { if (file.files[0]) ta.value = await file.files[0].text(); });
  const add = () => {
    let d;
    if (looksLikeDeckCode(ta.value)) {                // デッキコード（APP-018）。名前は入っていないので付ける
      const taken = new Set((store.load("decks", []) || []).map((x) => x.name));
      let nm = "コードから読んだデッキ"; for (let i = 2; taken.has(nm); i++) nm = `コードから読んだデッキ ${i}`;   // 同じ名前のデッキを上書きしない
      try { d = { name: nm, ...decodeDeck(ta.value, (c) => (info(c) || {}).kind) }; }
      catch (e) { return (err.textContent = e instanceof DeckCodeError ? e.message : "読めなかった"); }
    } else {
      try { d = JSON.parse(ta.value); } catch { return (err.textContent = "デッキコードでも JSON でもないので読めない"); }
    }
    if (!d || !Array.isArray(d.chara_deck) || !Array.isArray(d.action_deck)) return (err.textContent = "chara_deck と action_deck が要る（decklists/ と同じ形式）");
    const deck = { name: String(d.name || "名前なし").slice(0, 40), chara_deck: d.chara_deck.map(String), action_deck: d.action_deck.map(String) };
    const mine = (store.load("decks", []) || []).filter((x) => x.name !== deck.name);
    mine.push(deck); store.save("decks", mine);
    closeModal(); send({ t: "deck", deck });        // 構築ルールの検査はサーバが行う（正は GameConfig.validate）
    renderLobby();
  };
  openModal([h("h3", { text: "デッキを読み込む" }),
    h("p", { class: "muted", text: "デッキコード（英数字の 1 行）か、decklists/ と同じ形式の JSON。この端末のブラウザに保管され、対局のとき以外はどこにも送られない。デッキメーカー（ホームの「デッキを組む」）で組んだデッキも同じ場所に入る。" }),
    h("label", { class: "field" }, h("span", { text: "ファイルから" }), file), h("label", { class: "field" }, h("span", { text: "または貼り付け" }), ta), err,
    h("div", { class: "row end" }, h("button", { class: "btn", onclick: closeModal, text: "やめる" }), h("button", { class: "btn primary", onclick: add, text: "読み込んで使う" }))]);
}

// ------------------------------------------------------------------ 起動
(async function boot() {
  try { await loadCards(); } catch { app.replaceChildren(h("p", { class: "boot", text: "サーバに届かない。少し待って読み込み直してほしい。" })); return; }
  art.onChange(() => { if (S.board) S.board.refreshArt(); });
  // デッキメーカー（別のタブ）でデッキを保存したら、ロビーの選択肢を取り直す（APP-014）
  window.addEventListener("storage", (e) => { if (e.key === "meichosim.decks" && S.room && !S.board) render(); });
  art.restore();                    // 手元の画像（APP-013）。待たない。入ったら盤面を描き直す
  try { S.builtin = (await api("/api/decks")).decks || []; } catch { S.builtin = []; }
  try { S.cpu = await api("/api/cpu"); } catch { S.cpu = { enabled: false, decks: {} }; }
  if (!roomId) return renderHome();
  const key = store.seatKey(roomId);
  let pass = ""; try { pass = sessionStorage.getItem("meichosim.pass." + roomId) || ""; } catch { /* 無ければ入室画面で聞く */ }
  const name = store.load("name", "");
  if ((key || pass) && name) connect(name, pass, key); else renderJoin();
})();
