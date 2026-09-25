// 通信。WebSocket を 1 本張り、切れたら席の鍵でつなぎ直す（要件 R-NET-1・R-NET-3・R-NET-4）。
// ここはメッセージの中身を解釈しない。受けたものをそのまま上へ渡す。
export const PROTOCOL_VERSION = 1;
const FATAL = new Set(["version", "bad_pass", "no_room", "bad_name", "room_full", "replaced", "flood"]);

export class Conn {
  constructor({ room, name, pass, key, onMessage, onStatus }) {
    Object.assign(this, { room, name, pass, key, onMessage, onStatus });
    this.ws = null; this.closedByUs = false; this.retry = 0; this.timer = null; this.status = "idle";
  }

  start() { this.closedByUs = false; this._open(); }

  _set(status, detail) { this.status = status; this.onStatus(status, detail); }

  _open() {
    clearTimeout(this.timer);
    this._set(this.retry ? "reconnecting" : "connecting");
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ t: "hello", v: PROTOCOL_VERSION, room: this.room, name: this.name, pass: this.pass, key: this.key }));
    };
    ws.onmessage = (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.t === "welcome") { this.key = msg.key; this.retry = 0; this._set("open"); }
      if (msg.t === "bye") { this.byeCode = msg.code; }
      this.onMessage(msg);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.closedByUs) return this._set("closed");
      if (this.byeCode && FATAL.has(this.byeCode)) return this._set("fatal", this.byeCode);
      this.byeCode = null;
      this.retry += 1;
      this._set("reconnecting");
      this.timer = setTimeout(() => this._open(), Math.min(8000, 400 * 2 ** Math.min(this.retry, 5)));
    };
  }

  send(msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(msg)); return true; }
    return false;
  }

  stop() { this.closedByUs = true; clearTimeout(this.timer); if (this.ws) this.ws.close(); }
}

export async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.msg || "通信に失敗した"), { code: data.code });
  return data;
}
