// 端末ごとの保管（表示名・席の鍵・手元のデッキ）。使えない環境（プライベートウィンドウ等）でも落ちない。
const PREFIX = "meichosim.";

export function load(key, fallback) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch { return fallback; }
}

export function save(key, value) {
  try { localStorage.setItem(PREFIX + key, JSON.stringify(value)); } catch { /* 保管できなくても遊べる */ }
}

// 席の鍵は部屋ごと（要件 R-NET-4）。合言葉は保管しない（R-SEC-4）。
export function seatKey(room) { return (load("keys", {}) || {})[room] || null; }
export function setSeatKey(room, key) {
  const keys = load("keys", {}) || {};
  if (key) keys[room] = key; else delete keys[room];
  const ids = Object.keys(keys);
  for (const id of ids.slice(0, Math.max(0, ids.length - 12))) delete keys[id];   // 古い部屋の鍵を溜めない
  save("keys", keys);
}
