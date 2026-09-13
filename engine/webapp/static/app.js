/* 検証アプリのブラウザ側（APP_DESIGN.md §0.4 / 表示は UI_DESIGN.md v1.4）。
 *
 * **ここにルールは一行も無い。**
 * - 押せる手はサーバ（実エンジンの legal_actions）が返した一覧そのもの
 * - 押した結果どうなるかもサーバが決める
 * - このファイルがやるのは「描く」「押す」「キーを拾う」だけである
 *
 * 行動の選び方（D-063 v3）:
 *   1段目で**何をするか**（チャージ／レベルアップ／切り替え／対抗へ…）を選び、
 *   2段目で**対象をカード画像のクリック**で選ぶ。
 *   ただし**画面は行動を組み立てていない。** 種類と対象の組から
 *   `s.legal` の**添字を引いているだけ**であり、そこに無い手は押せない。
 *   組み立ての漏れに備えて、合法手そのままの一覧（L キー）を必ず残す。
 *
 * 画像について（UI_DESIGN.md §P2〜§P4）:
 * - 画像は**見た目でしかない**。observe に無い情報は描かない。
 *   相手の手札・山札は裏面（`cardback`）で描き、**要素にカードIDを持たせない**。
 * - 画像が無いカードは**必ずテキスト表示に落ちる**。黙って消さない。
 * - **エンジンの実装文（オペコードの言い換え）は消さない。** 拡大パネルに常に併記し、
 *   Z キーで全カードの下に出せる。画像の文面と読み比べるのが検証の本体である。
 * - **拡大はマウスがカードに乗っている間だけ出る。**（D-063 v2）
 */
'use strict';

let S = null;          // 直近のスナップショット
let PREV = null;       // ひとつ前（数値の差分表示に使う・§4.3）
let SEL = 0;           // キーボードで選択中の項目（KEYS の添字）
let KEYS = [];         // いま数字キーで押せるもの [{node, run}]
let CDOPEN = true;     // キャラデッキ欄を開いているか（C で開閉）
let LISTOPEN = false;  // 合法手そのままの一覧を出しているか（L で開閉）
let MULL = new Set();  // マリガンで戻すことにした手札の位置
let PICK = null;       // 対象を選んでいる最中 {type, spec, targets:Map, order:[]}
let CONF = null;       // /api/config の中身（画像の状況を含む）

const $ = (id) => document.getElementById(id);
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt !== undefined) e.textContent = txt;
  return e;
};

/* ------------------------------------------------------------ 表示設定
 * 記録には一切入れない（UI_DESIGN.md §P6）。ローカルの見た目だけの話。 */
function store(key, val) {
  try { if (val === undefined) return localStorage.getItem(key);
        localStorage.setItem(key, val); } catch (e) { /* 使えなくてもよい */ }
  return null;
}
let CW = Math.min(140, Math.max(64, +(store('meicho.cw') || 88)));
let SHOWTEXT = store('meicho.text') === '1';
function applyView() {
  document.documentElement.style.setProperty('--cwbase', CW + 'px');
  document.body.classList.toggle('showtext', SHOWTEXT);
}
applyView();

/* ------------------------------------------------------------ 通信 */
async function api(path, body) {
  const opt = body === undefined
    ? {}
    : {method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({error: '応答が壊れています'}));
  if (!r.ok || j.error) {
    showError((j.error || ('HTTP ' + r.status)) + (j.traceback ? '\n\n' + j.traceback : ''));
    return null;
  }
  hideError();
  return j;
}
function showError(msg) { const e = $('err'); e.textContent = '■ ' + msg; e.hidden = false; }
function hideError() { $('err').hidden = true; }

/* ------------------------------------------------------------ 拡大パネル
 * 実卓でカードを手に取る代わり（UI_DESIGN.md §6）。
 * **左が画像（カードの文面）、右がエンジンの実装。**この並びが検証機能の本体。
 * **規則はひとつだけ: マウスがカードに乗っている間だけ出る。** */
let HOVER = null;
let zoomTimer = null;

function showZoom(anchor, p) {
  if (!p) return;
  const z = $('zoom');
  const img = $('zoom-img');
  if (p.img) { img.src = p.img; img.alt = p.title; img.hidden = false; }
  else { img.removeAttribute('src'); img.hidden = true; }
  $('zoom-title').textContent = p.title;
  $('zoom-meta').textContent = p.meta || '';
  const lines = $('zoom-lines');
  lines.textContent = '';
  if (!p.lines || !p.lines.length) lines.appendChild(el('div', 'muted', 'スキルなし'));
  else p.lines.forEach((t) => lines.appendChild(el('div', 'zl', t)));
  z.hidden = false;
  place(z, anchor);
}

function place(z, anchor) {
  const r = anchor.getBoundingClientRect();
  const zw = z.offsetWidth, zh = z.offsetHeight;
  let x = r.right + 12;
  if (x + zw > window.innerWidth - 8) x = r.left - zw - 12;
  if (x < 8) x = Math.max(8, window.innerWidth - zw - 8);
  let y = r.top - 8;
  if (y + zh > window.innerHeight - 8) y = window.innerHeight - zh - 8;
  if (y < 8) y = 8;
  z.style.left = x + 'px';
  z.style.top = y + 'px';
}

function hideZoom() {
  clearTimeout(zoomTimer);
  HOVER = null;
  $('zoom').hidden = true;
}

function bindZoom(node, payload) {
  if (!payload) return node;
  node.addEventListener('mouseenter', () => {
    clearTimeout(zoomTimer);
    HOVER = node;
    zoomTimer = setTimeout(() => {
      if (HOVER === node) showZoom(node, payload);
    }, 150);
  });
  node.addEventListener('mouseleave', () => {
    if (HOVER === node) hideZoom();
  });
  return node;
}

/* 取りこぼしの受け皿。
 * カードの上にマウスがあるまま盤面を描き直すと、古い要素の mouseleave は
 * **二度と来ない**（要素ごと消えるため）。それだけで拡大が居座るので、
 * 「どのカードにも乗っていないのに出ている」状態を毎回ここで畳む。 */
document.addEventListener('mousemove', () => {
  if (!$('zoom').hidden && (!HOVER || !HOVER.isConnected)) hideZoom();
}, {passive: true});
window.addEventListener('scroll', () => {
  if (!$('zoom').hidden) hideZoom();
}, {passive: true});

/* 拡大パネルに出す中身。**エンジンが返した値と文だけを使う。** */
function zoomOfAction(c) {
  const lines = (c.skills || []).slice();
  if (c.leader_skill) lines.unshift('リーダースキル（専用: ' + c.dedicated_to + '）');
  else if (c.dedicated_to) lines.unshift('専用: ' + c.dedicated_to);
  if (c.unverified) lines.push('※テキスト未確認のカード');
  return {img: c.img, title: `${c.id} ${c.name}`,
          meta: `${c.color} / コスト${c.cost} / 速${c.speed} / ダメ${c.damage}`,
          lines: lines};
}
function zoomOfChara(c) {
  return {img: c.img, title: `${c.id || ''} ${c.name} Lv${c.level}`.trim(),
          meta: (c.tags && c.tags.length) ? c.tags.join('・') : '',
          lines: (c.skills || []).slice()};
}
function zoomOfSlot(s) {
  if (s.empty) return null;
  const top = s.stack[s.stack.length - 1];
  const many = s.stack.length > 1;
  return {img: top.img, title: s.label,
          meta: many ? ('下に重ねている: ' + s.under.join(' / ')) : '',
          // 重ねた下のカードのスキルも有効（§6.3-3）。全部出す
          lines: (s.skills || []).map((sk) => (many ? sk.from + '｜' : '') + sk.text)};
}

/* ------------------------------------------------------------ モーダル
 * トラッシュの中身（**両者とも公開情報**・rules_draft.md §11）。 */
function openModal(title, cards) {
  $('modal-title').textContent = title;
  const body = $('modal-body');
  body.textContent = '';
  if (!cards.length) body.appendChild(el('span', 'muted', '（1枚も無い）'));
  else cards.forEach((c) => body.appendChild(cardEl(c)));
  $('modal').hidden = false;
}
function closeModal() { $('modal').hidden = true; }
function modalOpen() { return !$('modal').hidden; }

/* ------------------------------------------------------------ 描画 */
const COLCLS = {'赤': 'red', '緑': 'green', '青': 'blue'};

/* カードの面。画像が無ければ ID と名前を出す枠になる（**黙って消さない**） */
function faceEl(img, alt) {
  const e = el('div', 'cardimg' + (img ? '' : ' noimg'));
  if (img) {
    const im = el('img');
    im.src = img; im.alt = alt; im.draggable = false;
    e.appendChild(im);
  } else {
    e.appendChild(el('span', 'altname', alt));
  }
  return e;
}

/* 裏面。**カードIDを持たせない**（DOM から覗けないようにする・§P2） */
function backEl(label, cls) {
  const e = el('div', 'cardback' + (cls ? ' ' + cls : ''));
  if (label) e.appendChild(el('span', 'n', label));
  return e;
}

/* 選べる対象にする。**押すと `s.legal[idx]` をそのまま送る。** */
function makeTarget(node, idx) {
  node.classList.add('target');
  node.appendChild(el('span', 'pin', String(KEYS.length + 1)));
  const run = () => play(idx);
  node.addEventListener('click', run);
  KEYS.push({node: node, run: run});
  return node;
}

function cardEl(c, pickIdx) {
  const e = el('div', 'card ' + (COLCLS[c.color] || '')
                    + (c.unverified ? ' unv' : '') + (c.img ? '' : ' noimg'));
  e.appendChild(faceEl(c.img, `${c.id} ${c.name}`));
  const t = el('div', 'txt');
  t.appendChild(el('span', 'id', c.id));
  t.appendChild(el('span', 'nm', c.name));
  t.appendChild(el('div', 'num',
    `${c.color} / コスト${c.cost} / 速${c.speed} / ダメ${c.damage}`));
  if (c.leader_skill) t.appendChild(el('span', 'sk', 'リーダースキル: ' + c.dedicated_to));
  else if (c.dedicated_to) t.appendChild(el('span', 'sk', '専用: ' + c.dedicated_to));
  (c.skills || []).forEach((s) => t.appendChild(el('span', 'sk', s)));
  if (c.unverified) t.appendChild(el('span', 'sk', '※テキスト未確認'));
  e.appendChild(t);
  bindZoom(e, zoomOfAction(c));
  if (pickIdx !== undefined && pickIdx >= 0) makeTarget(e, pickIdx);
  return e;
}

/* `pick` は Map(手札の位置 → 合法手の添字)。無ければただ並べるだけ。 */
function fillCards(node, list, pick) {
  node.textContent = '';
  if (!list.length) { node.appendChild(el('span', 'muted', '—')); return; }
  list.forEach((c, i) => {
    node.appendChild(cardEl(c, pick ? pick.get(i) : undefined));
  });
}

/* 相手の手札と山札。**枚数だけが情報**なので裏面をその数だけ並べる（§4.4） */
function fillBacks(node, hand, deck) {
  node.textContent = '';
  for (let i = 0; i < hand; i++) node.appendChild(backEl('', 'inhand'));
  node.appendChild(backEl(String(deck), 'deck'));
}

/* `pick` は Map(枠の位置 → 合法手の添字)。自分の枠だけに渡す。 */
function fillCharas(node, slots, pick) {
  node.textContent = '';
  slots.forEach((s, i) => {
    const e = el('div', 'chara' + (i === 0 ? ' lead' : ''));
    e.appendChild(el('span', 'role', i === 0 ? 'リーダー' : 'バック' + i));
    const stack = el('div', 'stack');
    if (s.empty) {
      stack.appendChild(el('div', 'cardimg empty', '（空）'));
    } else {
      // 下から順にずらして重ねる（実卓と同じ見え方・UI_DESIGN.md §5.4）
      s.stack.forEach((c) => {
        stack.appendChild(bindZoom(faceEl(c.img, c.label), zoomOfChara(c)));
      });
    }
    e.appendChild(bindZoom(stack, zoomOfSlot(s)));
    const t = el('div', 'txt');
    t.appendChild(el('div', 'nm', s.label));
    if (s.under && s.under.length) {
      t.appendChild(el('div', 'under', '下に重ねている: ' + s.under.join(' / ')));
    }
    // 重ねた下のカードのスキルも有効（§6.3-3）
    (s.skills || []).forEach((sk) => {
      const d = el('div', 'sk');
      if (s.stack && s.stack.length > 1) d.appendChild(el('span', 'src', sk.from));
      d.appendChild(document.createTextNode(sk.text));
      t.appendChild(d);
    });
    e.appendChild(t);
    const idx = pick ? pick.get(i) : undefined;
    if (idx !== undefined && idx >= 0) makeTarget(e, idx);
    node.appendChild(e);
  });
}

/* 自分のキャラデッキ全体（ルール上、自分にとっては公開情報）。
 * `pick` は Map(キャラカードID → 合法手の添字)。 */
function renderCharaDeck(s, pick) {
  const box = $('charadeck-body');
  box.textContent = '';
  $('charadeck').classList.toggle('closed', !CDOPEN);
  if (!CDOPEN) return;
  // 「今レベルアップできる札」はエンジンの合法手から引く（画面は判断しない）
  const upable = new Set(
    (s.legal || []).filter((a) => a.type === 'levelup')
                   .map((a) => a.action.card));
  (s.board.me.chara_overview || []).forEach((row) => {
    const g = el('div', 'cdgroup');
    g.appendChild(el('div', 'cdname', row.name));
    const line = el('div', 'cdline');
    row.levels.forEach((c) => {
      const e = el('div', 'cdcard' + (c.where === 'キャラデッキ' ? '' : ' onfield')
                              + (upable.has(c.id) ? ' up' : ''));
      e.appendChild(faceEl(c.img, c.label));
      const cap = el('div', 'cap');
      cap.appendChild(el('span', 'lv', 'Lv' + c.level));
      cap.appendChild(el('span', 'where', (upable.has(c.id) ? '★ ' : '') + c.where));
      e.appendChild(cap);
      const t = el('div', 'txt');
      if (c.tags && c.tags.length) t.appendChild(el('div', 'tags', c.tags.join('・')));
      if (!c.skills.length) t.appendChild(el('div', 'sk muted', 'スキルなし'));
      c.skills.forEach((x) => t.appendChild(el('div', 'sk', x)));
      e.appendChild(t);
      bindZoom(e, zoomOfChara(c));
      const idx = pick ? pick.get(c.id) : undefined;
      if (idx !== undefined && idx >= 0) makeTarget(e, idx);
      line.appendChild(e);
    });
    g.appendChild(line);
    box.appendChild(g);
  });
}

function delta(node, now, before) {
  node.textContent = '';
  node.className = '';
  if (before === undefined || before === null || now === before) return;
  const d = now - before;
  node.textContent = (d > 0 ? '▲' : '▼') + Math.abs(d);
  node.className = d > 0 ? 'up' : 'down';
}

function effectsHtml(b) {
  const out = [];
  const ef = b.effects;
  const say = (label, v) => {
    if (v.me) out.push('あなた: ' + label);
    if (v.opp) out.push('CPU: ' + label);
  };
  say('赤のコスト +1（旋風）', ef.red_cost_up);
  say('次のターン 赤のコスト +1（予約）', ef.pending_red_cost_up);
  say('連撃できない', ef.rush_forbidden);
  say('次のターン 連撃できない（予約）', ef.pending_rush_forbidden);
  say('リーダーを切り替えられない', ef.leader_switch_forbidden);
  const cc = b.clash_counts;
  out.push(`対抗の履歴（赤/緑/青/パス） あなた ${cc.me.join('・')} ／ CPU ${cc.opp.join('・')}`);
  return out;
}

/* ------------------------------------------------------------ 行動の選び方
 *
 * **画面は行動を組み立てない。** 合法手を種類でまとめ、
 * 対象（手札の位置・キャラカードID・枠の位置）から
 * `s.legal` の添字を引けるようにしているだけである。
 * ここに無い種類は下の一覧（L）から必ず打てる（§5.6）。 */
const KIND = {
  charge:      {label: 'チャージ', target: 'hand',
                what: '協奏エリアに置くカード', hint: '手札のカードをクリック'},
  submit:      {label: '対抗に出す', target: 'hand',
                what: '対抗に提出するカード', hint: '手札のカードをクリック'},
  rush:        {label: '連撃する', target: 'hand',
                what: '連撃で使うカード', hint: '手札のカードをクリック'},
  discard:     {label: '手札を捨てる', target: 'hand',
                what: '捨てるカード', hint: '手札のカードをクリック'},
  levelup:     {label: 'レベルアップ', target: 'chara',
                what: '重ねるキャラ', hint: 'キャラデッキの ★ の札をクリック'},
  switch:      {label: 'リーダーを切り替える', target: 'slot',
                what: 'リーダーにするキャラ', hint: '自分のキャラ枠をクリック'},
  choose_back: {label: 'リーダーにするキャラを選ぶ', target: 'slot',
                what: 'リーダーにするキャラ', hint: '自分のキャラ枠をクリック'},
  to_clash:    {label: '対抗フェイズへ進む'},
  end_turn:    {label: 'ターンを終える'},
  pass:        {label: '対抗しない（パス）'},
  stop:        {label: '連撃をやめる'},
  pay:         {label: 'コストを支払う'},
  decline:     {label: '支払わずダメージを受ける'},
  use:         {label: '効果を使う'},
  skip:        {label: '効果を使わない'},
};

/* 対象の識別子。合法手そのものから取り出す（画面が決めているのではない） */
function targetKey(kind, a) {
  if (kind === 'hand') return a.action.hand;
  if (kind === 'chara') return a.action.card;
  if (kind === 'slot') return a.action.back;
  return undefined;
}

function startPick(type, group) {
  const spec = KIND[type];
  const targets = new Map();
  group.forEach((a) => {
    const k = targetKey(spec.target, a);
    if (k !== undefined) targets.set(k, a.index);
  });
  PICK = {type: type, spec: spec, targets: targets};
  if (spec.target === 'chara') CDOPEN = true;   // 選ぶ先が見えていないと押せない
  paint();
}

function cancelPick() { if (PICK) { PICK = null; paint(); } }

function buildKinds(s) {
  const box = $('kinds');
  box.textContent = '';
  if (PICK) { box.hidden = true; return; }
  box.hidden = false;

  const groups = new Map();
  s.legal.forEach((a) => {
    if (!groups.has(a.type)) groups.set(a.type, []);
    groups.get(a.type).push(a);
  });

  groups.forEach((group, type) => {
    const spec = KIND[type];
    if (spec && spec.target) {
      const b = el('button', 'kind');
      b.appendChild(el('span', 'k', String(KEYS.length + 1)));
      b.appendChild(el('span', 't', spec.label));
      b.appendChild(el('span', 'n', group.length + ' 通り'));
      const run = () => startPick(type, group);
      b.onclick = run;
      KEYS.push({node: b, run: run});
      box.appendChild(b);
    } else if (spec && group.length === 1) {
      const a = group[0];
      const b = el('button', 'kind plain');
      b.appendChild(el('span', 'k', String(KEYS.length + 1)));
      b.appendChild(el('span', 't', spec.label));
      const run = () => play(a.index);
      b.onclick = run;
      KEYS.push({node: b, run: run});
      box.appendChild(b);
    } else {
      // 種類でまとめられないものは、**その手そのもの**をボタンにする
      // （キャラ配置・「何枚にする」など。隠さずに必ず出す）
      group.forEach((a) => {
        const b = el('button', 'kind plain');
        b.appendChild(el('span', 'k', String(KEYS.length + 1)));
        b.appendChild(el('span', 't', a.label));
        const run = () => play(a.index);
        b.onclick = run;
        KEYS.push({node: b, run: run});
        box.appendChild(b);
      });
    }
  });
}

/* ------------------------------------------------------------ 全体の描画 */
function render(s) {
  if (!s) return;
  if (s.no_game) { $('setup').hidden = false; $('game').hidden = true; return; }
  PREV = (S && S.game_id === s.game_id) ? S : null;
  S = s;
  PICK = null;
  paint();
}

function paint() {
  const s = S;
  hideZoom();
  closeModal();
  KEYS = []; SEL = 0;
  $('setup').hidden = true; $('game').hidden = false;

  const b = s.board, pb = PREV ? PREV.board : null;
  $('gmeta').textContent =
    `${s.game_id}｜${s.deck || ''} 同型｜相手 ${s.opponent}｜あなたは${s.human_seat === 0 ? '先攻' : '後攻'}`
    + `｜シード ${s.seed}｜ターン ${b.turn_no}｜印 ${s.flags}`;
  $('opp-name').textContent = '（' + s.opponent + '）';

  // 数値
  $('opp-life').textContent = b.opp.life;
  delta($('opp-life-d'), b.opp.life, pb ? pb.opp.life : null);
  $('opp-hand').textContent = b.opp.hand_count;
  $('opp-conc').textContent = b.opp.concerto.length;
  $('opp-trash').textContent = b.opp.trash_count;
  $('opp-deck').textContent = b.opp.deck_count;
  $('me-life').textContent = b.me.life;
  delta($('me-life-d'), b.me.life, pb ? pb.me.life : null);
  $('me-hand').textContent = b.me.hand.length;
  $('me-conc').textContent = b.me.concerto.length;
  $('me-trash').textContent = b.me.trash_count;
  $('me-deck').textContent = b.me.deck_count;

  // 対象を選んでいる最中なら、その置き場だけを押せるようにする
  const tgt = PICK ? PICK.spec.target : null;
  fillCharas($('opp-charas'), b.opp.slots, null);
  fillCharas($('me-charas'), b.me.slots, tgt === 'slot' ? PICK.targets : null);
  fillBacks($('opp-backs'), b.opp.hand_count, b.opp.deck_count);
  fillBacks($('me-backs'), 0, b.me.deck_count);

  const known = b.opp.hand_known || [];
  $('opp-known-zone').hidden = !known.length;
  if (known.length) {
    fillCards($('opp-known'), known);
    $('opp-known-n').textContent = `${known.length} / ${b.opp.hand_count} 枚`;
  }

  fillCards($('opp-area'), b.opp.action_area);
  fillCards($('opp-conc-cards'), b.opp.concerto);
  fillCards($('me-area'), b.me.action_area);
  fillCards($('me-conc-cards'), b.me.concerto);

  const mulligan = isMulligan(s);
  const handBox = $('me-hand-cards');
  handBox.classList.toggle('tight', b.me.hand.length > 7);
  handBox.hidden = mulligan;               // マリガン中は下の専用画面で選ぶ
  if (!mulligan) {
    fillCards(handBox, b.me.hand, tgt === 'hand' ? PICK.targets : null);
  }

  // 継続効果と履歴（D-036 で観測に足した公開情報・§4.3）
  const ef = $('effects');
  ef.textContent = '';
  ef.appendChild(el('b', null, '継続効果・履歴'));
  effectsHtml(b).forEach((t) => ef.appendChild(el('div', null, t)));

  // ログ
  const log = $('log');
  log.textContent = '';
  s.log.forEach((line) => {
    let cls = null;
    if (line.startsWith('◆')) cls = 'clash';
    else if (line.startsWith('◇')) cls = 'peek';
    else if (line.startsWith('★')) cls = 'flag';
    else if (line.startsWith('■')) cls = 'bad';
    else if (line.startsWith('──')) cls = 'turn';
    log.appendChild(el('div', cls, line));
  });
  log.scrollTop = log.scrollHeight;

  // 行動
  $('phase').textContent = b.phase_ja + (s.your_turn ? '｜あなたの番' : '｜CPU 思考中…');
  const u = b.used;
  $('used').textContent = b.turn_player === s.human_seat
    ? `使用済: チャージ${u.charge ? '☑' : '□'} 切替${u.switch ? '☑' : '□'} Lv${u.levelup ? '☑' : '□'}`
    : '';
  $('choice').textContent = s.choice_reason || '';

  renderCharaDeck(s, tgt === 'chara' ? PICK.targets : null);

  $('mull').hidden = !mulligan;
  if (mulligan) {
    $('kinds').hidden = true;
    $('pickbar').hidden = true;
    MULL = new Set();
    renderMull(s);
  } else {
    buildKinds(s);
    const pb2 = $('pickbar');
    pb2.hidden = !PICK;
    if (PICK) {
      $('pick-what').textContent = PICK.spec.what + 'を選ぶ';
      $('pick-hint').textContent = PICK.spec.hint + '（数字キーでも選べる）';
    }
  }

  // 合法手そのままの一覧（安全網・§5.6）。
  // **押せるものが1つも作れなかったときだけ**勝手に開く。
  // 画面の組み立てに漏れがあっても、ここから必ず打てる。
  if (!KEYS.length && s.legal.length && !mulligan) LISTOPEN = true;
  const box = $('legal');
  box.hidden = !LISTOPEN;
  box.textContent = '';
  if (LISTOPEN) {
    s.legal.forEach((a) => {
      const btn = el('button', 'act');
      btn.appendChild(el('span', 'k', '·'));
      btn.appendChild(el('span', 't', a.label));
      btn.onclick = () => play(a.index);
      box.appendChild(btn);
    });
  }

  $('keyhint').textContent = mulligan
    ? 'カードをクリック / 数字キーで入切 / Enter で決定'
    : (PICK ? 'カードをクリック / 数字キー / Esc でやめる'
            : '1〜9 か ↑↓ Enter でも選べる ／ Z エンジン文 ／ +- 大きさ');

  // 終了
  const over = $('over');
  if (s.finished) {
    const r = s.result || {};
    over.hidden = false;
    over.className = 'over ' + (r.winner === 'human' ? 'win' : r.winner === 'ai' ? 'lose' : '');
    let t = r.draw ? '引き分け'
      : r.winner === 'human' ? 'あなたの勝ち' : r.winner === 'ai' ? 'CPU の勝ち' : '終了';
    if (r.reason === 'resign') t = 'あなたの投了';
    if (r.reason === 'error') t = '異常終了';
    over.textContent = `${t}（${r.turns} ターン・ライフ ${(r.life || []).join(' / ')}）`
      + (s.error ? '\n' + s.error : '') + '\n「記録して終了」を押すと保存します。';
    $('finish').hidden = false;
    $('flag').disabled = false;
  } else {
    over.hidden = true; $('finish').hidden = true;
  }
  syncSel();
}

/* ------------------------------------------------------------ マリガン
 * 既定では合法手が 2^5 = 32 通り並ぶ。読めないので、**カード1枚ごとに
 * 入切する画面**に差し替える。ただし押した結果はあくまで
 * 「サーバが返した合法手のどれか」であって、ここで行動を組み立てはしない。
 */
function isMulligan(s) {
  return !!(s && !s.finished && s.legal.length
            && s.legal.every((a) => a.type === 'mulligan'));
}

function sameSet(arr, set) {
  return arr.length === set.size && arr.every((i) => set.has(i));
}

function mullIndex(s) {
  const hit = s.legal.find((a) => sameSet(a.action.cards, MULL));
  return hit ? hit.index : -1;
}

function renderMull(s) {
  const node = $('mull-cards');
  node.textContent = '';
  s.board.me.hand.forEach((c, i) => {
    const e = cardEl(c);
    e.classList.add('pick');
    if (MULL.has(i)) e.classList.add('picked');
    e.insertBefore(el('span', 'k', String(i + 1)), e.firstChild);
    e.appendChild(el('span', 'mark', MULL.has(i) ? '戻す' : '残す'));
    e.addEventListener('click', () => {
      MULL.has(i) ? MULL.delete(i) : MULL.add(i);
      renderMull(S);
    });
    node.appendChild(e);
  });
  $('mull-n').textContent = MULL.size;
  const names = [...MULL].sort((a, b) => a - b)
    .map((i) => s.board.me.hand[i].name);
  $('mull-sel').textContent = names.length ? '戻す: ' + names.join('、') : '';
  $('mull-go').disabled = mullIndex(s) < 0;
}

function playMull() {
  const i = mullIndex(S);
  if (i >= 0) play(i);
}

function syncSel() {
  KEYS.forEach((k, i) => k.node.classList.toggle('sel', i === SEL));
  const cur = KEYS[SEL];
  if (cur) cur.node.scrollIntoView({block: 'nearest'});
}

/* ------------------------------------------------------------ 操作 */
let busy = false;
async function play(i) {
  if (busy || !S || !S.legal.length) return;
  busy = true;
  try { render(await api('/api/play', {index: i, ply: S.ply})); }
  finally { busy = false; }
}

document.addEventListener('keydown', (ev) => {
  if ($('game').hidden || busy) return;
  if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'SELECT') return;
  const mull = isMulligan(S);

  if (ev.key === 'Escape') {
    ev.preventDefault();
    if (modalOpen()) closeModal(); else cancelPick();
    return;
  }
  if (modalOpen()) return;               // モーダル中は他のキーを拾わない
  if (ev.key === 'c' || ev.key === 'C') { ev.preventDefault(); $('charabtn').click(); return; }
  if (ev.key === 'z' || ev.key === 'Z') { ev.preventDefault(); $('textbtn').click(); return; }
  if (ev.key === 'l' || ev.key === 'L') { ev.preventDefault(); $('listbtn').click(); return; }
  if (ev.key === '+' || ev.key === ';' || ev.key === '=') { ev.preventDefault(); resize(+8); return; }
  if (ev.key === '-') { ev.preventDefault(); resize(-8); return; }
  if (ev.key === 'f' || ev.key === 'F') { ev.preventDefault(); $('flag').click(); return; }

  if (mull) {                       // マリガン中は数字＝入切、Enter＝決定
    const h = S.board.me.hand.length;
    if (ev.key >= '1' && ev.key <= '9') {
      const i = +ev.key - 1;
      if (i < h) { ev.preventDefault(); MULL.has(i) ? MULL.delete(i) : MULL.add(i); renderMull(S); }
    } else if (ev.key === 'Enter') {
      ev.preventDefault(); playMull();
    }
    return;
  }

  const n = KEYS.length;
  if (ev.key >= '1' && ev.key <= '9') {
    const i = +ev.key - 1;
    if (i < n) { ev.preventDefault(); KEYS[i].run(); }
  } else if (ev.key === 'ArrowDown' || ev.key === 'ArrowRight') {
    ev.preventDefault(); if (n) { SEL = (SEL + 1) % n; syncSel(); }
  } else if (ev.key === 'ArrowUp' || ev.key === 'ArrowLeft') {
    ev.preventDefault(); if (n) { SEL = (SEL - 1 + n) % n; syncSel(); }
  } else if (ev.key === 'Enter') {
    ev.preventDefault(); if (n) KEYS[SEL].run();
  }
});

function resize(d) {
  CW = Math.min(140, Math.max(64, CW + d));
  store('meicho.cw', String(CW));
  applyView();
}

$('charabtn').onclick = () => { CDOPEN = !CDOPEN; if (S) paint(); };
$('textbtn').onclick = () => {
  SHOWTEXT = !SHOWTEXT; store('meicho.text', SHOWTEXT ? '1' : '0'); applyView();
};
$('listbtn').onclick = () => { LISTOPEN = !LISTOPEN; if (S) paint(); };
$('pick-cancel').onclick = () => cancelPick();
$('modal-close').onclick = () => closeModal();
$('modal').onclick = (ev) => { if (ev.target === $('modal')) closeModal(); };
$('me-trash-btn').onclick = () => {
  if (S) openModal(`あなたのトラッシュ（${S.board.me.trash.length} 枚）`, S.board.me.trash);
};
$('opp-trash-btn').onclick = () => {
  if (S) openModal(`CPU のトラッシュ（${S.board.opp.trash.length} 枚）`, S.board.opp.trash);
};
$('mull-go').onclick = () => playMull();
$('mull-none').onclick = () => { MULL = new Set(); renderMull(S); playMull(); };

$('flag').onclick = async () => { render(await api('/api/flag', {note: ''})); };
$('resign').onclick = async () => {
  if (!confirm('投了しますか？（取り消せません）')) return;
  render(await api('/api/resign', {}));
};
$('finish').onclick = async () => {
  const r = await api('/api/finish', {});
  if (!r) return;
  let msg = '記録しました: ' + r.saved;
  msg += r.verified ? '\n再生の照合: 一致（記録は正しい）'
                    : '\n■ 再生の照合に失敗: ' + r.problem;
  alert(msg);
  S = null; PREV = null;
  $('game').hidden = true; $('setup').hidden = false;
  boot();
};
$('start').onclick = async () => {
  render(await api('/api/new', {opponent: $('opp').value, deck: $('deck').value}));
};

/* ------------------------------------------------------------ 起動 */
function applyDist(c) {
  // 配布モード（D-074）: 名前・注意書きはサーバの dist.json から。公式名を名乗らない。
  // マーカーが無い（c.dist が無い）ときは何もしない＝従来どおりの画面。
  const d = c.dist;
  if (!d) return;
  document.body.classList.add('dist');
  document.title = d.name;
  const h1 = document.querySelector('#setup h1');
  h1.textContent = '';
  h1.appendChild(document.createTextNode(d.name));
  h1.appendChild(el('span', 'sub', d.version ? `v${d.version}` : '非公式'));
  const note = document.querySelector('#setup .note');
  note.textContent = '';
  note.appendChild(el('div', null, d.notice || ''));
  if (d.credits) note.appendChild(el('div', 'credits', d.credits));
  note.appendChild(el('div', null,
    'カードは文字で表示する（この配布版はカード画像を含まない）。'
    + 'カードにマウスを乗せると、エンジンの実装文が拡大して出る。'));
  const zf = document.querySelector('.zfoot');
  if (zf) zf.textContent = '実際のカードと表記が違うことがある。おかしいと思ったら F キーで印を付ける';
}

async function boot() {
  const c = await api('/api/config');
  if (!c) return;
  CONF = c;
  applyDist(c);
  const sel = $('opp');
  sel.textContent = '';
  c.opponents.forEach((o) => {
    const op = el('option', null, o.label);
    op.value = o.key;
    if (o.key === c.default) op.selected = true;
    sel.appendChild(op);
  });
  // デッキ（D-048: 人間の基準値はデッキごとに別物なので、必ず選べるようにする）
  const ds = $('deck');
  ds.textContent = '';
  (c.decks || [c.deck]).forEach((d) => {
    const op = el('option', null, d);
    op.value = d;
    if (d === c.deck) op.selected = true;
    ds.appendChild(op);
  });

  const h = c.history;
  $('tally').textContent = h.n
    ? `この起動での戦績: ${h.wins}/${h.n} 勝（勝率 ${h.rate} ±${h.ci}）`
    + `／ 次のシード ${c.next_seed}`
    : `まだ対局がありません。次のシード ${c.next_seed}`;

  // 画像の状況。**引けなかったカードも、中身が同じカードも黙って落とさない** (§7.3)
  const im = c.images || {missing: [], duplicates: []};
  const miss = im.missing || [], dup = im.duplicates || [];
  const box = $('imgstat');
  box.textContent = '';
  if (im.intentionally_absent) {
    // 配布版（D-074）: 画像が無いのは仕様。警告ではなく説明にとどめる
    box.appendChild(el('div', null, 'カード画像は含まれていない（文字表示）。'));
    box.className = 'tally';
    const w0 = $('imgwarn');
    w0.hidden = true;
    w0.textContent = '';
    const st0 = await api('/api/state');
    if (st0 && !st0.no_game) render(st0);
    return;
  }
  if (miss.length) {
    box.appendChild(el('div', null,
      `■ 画像が見つからないカードが ${miss.length} 枚ある: ${miss.join('、')}`
      + '（そのカードだけ文字表示になる）'));
  }
  dup.forEach((g) => {
    box.appendChild(el('div', null,
      `■ ${g.join(' と ')} が**同じ画像ファイル**を指している。`
      + 'どちらかが間違った絵なので、正しい画像を撮り直して置き換えること'));
  });
  if (!miss.length && !dup.length) {
    box.appendChild(el('div', null,
      `カード画像 ${im.indexed} 種を読み込んだ（実装カード ${im.implemented} 種すべてに画像がある）`));
  }
  box.className = (miss.length || dup.length) ? 'tally bad' : 'tally';
  const w = $('imgwarn');
  const n = miss.length + dup.length;
  w.hidden = !n;
  w.textContent = n ? `■ 画像に問題 ${n} 件（開始画面に詳細）` : '';

  const st = await api('/api/state');
  if (st && !st.no_game) render(st);
}
boot();
