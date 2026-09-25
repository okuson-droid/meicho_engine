// 小さな UI 部品: 要素を作る・通知・確認・ダイアログ。
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function cssMs(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const n = parseFloat(v);
  return Number.isFinite(n) ? (v.endsWith("ms") || !v.endsWith("s") ? n : n * 1000) : fallback;
}

let lastToast = "";
export function toast(msg) {
  if (!msg) return;
  const layer = document.getElementById("layer-toast");
  if (msg === lastToast && layer.childElementCount) return;      // 同じ文を連打で積まない
  lastToast = msg;
  const el = h("div", { class: "toast", text: msg });
  layer.append(el);
  while (layer.childElementCount > 2) layer.firstChild.remove();
  setTimeout(() => { el.remove(); if (!layer.childElementCount) lastToast = ""; }, cssMs("--t-toast", 2600));
}

const modalLayer = () => document.getElementById("layer-modal");
export function closeModal() { modalLayer().replaceChildren(); }
export function modalOpen() { return modalLayer().childElementCount > 0; }

// 中身を渡してダイアログを開く。外側をタップすると onDismiss（あれば）を呼んで閉じる。
export function openModal(content, { wide = false, onDismiss = null, dismissable = true } = {}) {
  const box = h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" }, content);
  const layer = modalLayer();
  layer.replaceChildren(box);
  layer.onpointerdown = (e) => {
    if (e.target === layer && dismissable) { closeModal(); if (onDismiss) onDismiss(); }
  };
  const first = box.querySelector("button, input, select, textarea");
  if (first) first.focus({ preventScroll: true });
  return box;
}

// 確認（要件 R-PLAY-5）。クリック 1 回で確定してしまう操作にだけ使う。
export function confirmDialog(message, { ok = "はい", cancel = "やめる", danger = false, title = "確認" } = {}) {
  return new Promise((resolve) => {
    const done = (v) => { closeModal(); resolve(v); };
    openModal([
      h("h3", { text: title }), h("p", { text: message }),
      h("div", { class: "row end" },
        h("button", { class: "btn", dataset: { act: "cancel" }, onclick: () => done(false), text: cancel }),
        h("button", { class: "btn " + (danger ? "danger" : "primary"), dataset: { act: "ok" }, onclick: () => done(true), text: ok })),
    ], { onDismiss: () => resolve(false) });
  });
}
