// 効果音（要件 R-SND-1〜4）。**音のファイルは 1 つも持たない。**全部をその場で合成する（Web Audio）。
// 自作なので権利の問題が無く、同梱する素材も増えない。鳴らす音は 1 拍につき 1 つで、どの拍にどの音かは fx.js の表で決める。
import * as settings from "./settings.js";

let ctx = null;
let master = null;

function ensure() {
  if (ctx) return ctx;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  ctx = new AC();
  master = ctx.createGain();
  master.connect(ctx.destination);
  return ctx;
}

// ブラウザは、利用者が一度触るまで音を出させない。最初の操作で起こす
export function unlock() {
  const c = ensure();
  if (c && c.state === "suspended") c.resume().catch(() => {});
}

function tone(c, { type = "sine", f = 440, f2 = null, t = 0, dur = 0.15, gain = 0.5, attack = 0.005 }) {
  const o = c.createOscillator(); const g = c.createGain();
  const t0 = c.currentTime + t;
  o.type = type; o.frequency.setValueAtTime(f, t0);
  if (f2) o.frequency.exponentialRampToValueAtTime(f2, t0 + dur);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(gain, t0 + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g); g.connect(master); o.start(t0); o.stop(t0 + dur + 0.02);
}

function noise(c, { t = 0, dur = 0.12, gain = 0.3, lp = 2500, hp = 200 }) {
  const n = Math.max(1, Math.floor(c.sampleRate * dur));
  const buf = c.createBuffer(1, n, c.sampleRate); const d = buf.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n);
  const src = c.createBufferSource(); src.buffer = buf;
  const f1 = c.createBiquadFilter(); f1.type = "lowpass"; f1.frequency.value = lp;
  const f2 = c.createBiquadFilter(); f2.type = "highpass"; f2.frequency.value = hp;
  const g = c.createGain(); g.gain.value = gain;
  src.connect(f1); f1.connect(f2); f2.connect(g); g.connect(master); src.start(c.currentTime + t);
}

// 音の定義はここ 1 か所。12 種（R-SND-1）＋軽い移動音
const SOUNDS = {
  draw: (c) => noise(c, { dur: 0.09, gain: 0.35, lp: 5000, hp: 1200 }),
  move: (c) => noise(c, { dur: 0.07, gain: 0.22, lp: 3000, hp: 600 }),
  charge: (c) => { noise(c, { dur: 0.06, gain: 0.2, lp: 4000, hp: 800 }); tone(c, { type: "triangle", f: 520, f2: 780, dur: 0.16, gain: 0.25 }); },
  place: (c) => { noise(c, { dur: 0.1, gain: 0.4, lp: 1400, hp: 120 }); tone(c, { f: 150, f2: 90, dur: 0.1, gain: 0.35 }); },
  reveal: (c) => { noise(c, { dur: 0.16, gain: 0.35, lp: 6000, hp: 900 }); tone(c, { type: "triangle", f: 660, dur: 0.22, gain: 0.3, t: 0.05 }); tone(c, { type: "triangle", f: 990, dur: 0.25, gain: 0.22, t: 0.05 }); },
  win: (c) => { tone(c, { type: "triangle", f: 523, dur: 0.14, gain: 0.35 }); tone(c, { type: "triangle", f: 784, dur: 0.24, gain: 0.35, t: 0.11 }); },
  lose: (c) => { tone(c, { type: "triangle", f: 392, dur: 0.16, gain: 0.3 }); tone(c, { type: "triangle", f: 277, dur: 0.28, gain: 0.3, t: 0.13 }); },
  damage: (c) => { noise(c, { dur: 0.18, gain: 0.5, lp: 900, hp: 60 }); tone(c, { type: "sawtooth", f: 140, f2: 55, dur: 0.22, gain: 0.3 }); },
  heal: (c) => { tone(c, { f: 660, f2: 880, dur: 0.2, gain: 0.25 }); tone(c, { f: 990, f2: 1320, dur: 0.26, gain: 0.18, t: 0.08 }); },
  levelup: (c) => [392, 523, 659, 784].forEach((f, i) => tone(c, { type: "triangle", f, dur: 0.16, gain: 0.28, t: i * 0.07 })),
  call: (c) => { tone(c, { type: "square", f: 740, dur: 0.12, gain: 0.16 }); tone(c, { type: "square", f: 988, dur: 0.12, gain: 0.16, t: 0.13 }); tone(c, { type: "triangle", f: 1480, dur: 0.3, gain: 0.2, t: 0.26 }); },
  clash: (c) => { noise(c, { dur: 0.3, gain: 0.45, lp: 7000, hp: 500 }); tone(c, { type: "sawtooth", f: 220, f2: 440, dur: 0.25, gain: 0.22 }); tone(c, { type: "triangle", f: 880, dur: 0.35, gain: 0.25, t: 0.18 }); tone(c, { type: "triangle", f: 1320, dur: 0.4, gain: 0.2, t: 0.18 }); },
  draw_clash: (c) => { tone(c, { type: "triangle", f: 440, dur: 0.2, gain: 0.25 }); tone(c, { type: "triangle", f: 440, dur: 0.3, gain: 0.2, t: 0.2 }); },
  turn: (c) => { tone(c, { f: 587, dur: 0.18, gain: 0.22 }); tone(c, { f: 880, dur: 0.3, gain: 0.18, t: 0.1 }); },
  victory: (c) => [523, 659, 784, 1047, 1319].forEach((f, i) => tone(c, { type: "triangle", f, dur: 0.32, gain: 0.3, t: i * 0.13 })),
  defeat: (c) => [440, 392, 330, 262].forEach((f, i) => tone(c, { type: "sine", f, dur: 0.4, gain: 0.3, t: i * 0.2 })),
};
export const SOUND_NAMES = Object.keys(SOUNDS);
export const played = [];          // 直近に鳴らした音の名前（検査と調べもの用）

export function play(name) {
  const s = settings.get();
  played.push(name); if (played.length > 50) played.shift();
  if (s.muted || !(s.volume > 0) || !SOUNDS[name]) return;
  const c = ensure(); if (!c || c.state !== "running") return;
  master.gain.value = Math.min(1, s.volume);
  try { SOUNDS[name](c); } catch { /* 音が出せなくても対局は続ける */ }
}
