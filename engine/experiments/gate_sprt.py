"""門番を**逐次検定**で回す道具（文献計画 便 D 後半・D-4／第 2 集 §7.2.2〜§7.2.3）。

## 何のための道具か

いまの門番（`champion_challenge_vb.py`）は「**先に 1,200 局と決めて回し、終わってから
勝率の 95% 区間の下端が 0.5 を超えたかを見る**」型である。これは正しいが無駄が多い。
挑戦者が明らかに弱ければ 100 局でも分かるし、明らかに強ければ 300 局で分かる。
それでも 1,200 局を回している。

*逐次検定*（sequential test）とは「**1 局ごとに証拠を足していき、白黒がついた時点で止める**」
測り方である。止め時を「証拠の重さ」で決めるので、差が大きい候補は早く終わり、
差が小さい候補にだけ長く回すことになる。同じ判定の確からしさを、平均して少ない
局数で得られる。

**重要な約束**: 「勝率を見ながら止め時を決める」のは、ふつうは反則である
（見ている途中に有利な瞬間で止めれば、いくらでも良い数字が作れる）。逐次検定が
反則にならないのは、**止める規則を回す前に決めて動かさない**からである。
だからこの道具は母数（α・β・p₀・p₁・上限）を**定数で持ち、変える口を作らない**。

## この道具が使う「対」の考え方（ペンタノミアル）

同じシードでも、先手と後手では配られる手札が違う。ふつうの測り方（1 局 1 観測）だと、
「たまたま強い初手を引いた」ぶれが勝率のぶれに丸ごと乗る。

そこで **1 つのシードにつき、先後を入れ替えた 2 局を必ず両方回して 1 観測にする**。
同じ配り方を両側から見るので、配りの運が打ち消し合う。この 2 局の得点の平均を
**ペア得点**と呼ぶ。取りうる値は 5 通りしかない:

    0（2 連敗）／0.25／0.5（1 勝 1 敗、または引き分け 2 つ）／0.75／1（2 連勝）

5 通りなので *ペンタノミアル*（penta＝5）という。引き分けはこのゲームでは進行不能の
ときしか出ないので、実際にはほぼ {0, 0.5, 1} の三通りになるが、**五項のまま実装する**
（引き分けが出たときに黙って壊れないようにするため）。

## 検定の中身（GSPRT）

- 帰無仮説 H₀: 挑戦者の 1 局あたり期待得点は **p₀ = 0.50**（互角）
- 対立仮説 H₁: 挑戦者の 1 局あたり期待得点は **p₁ = 0.55**（勝ち越し）

観測が増えるたびに **LLR**（対数尤度比。log-likelihood ratio）を更新する。LLR とは
「いま見えている度数は、H₁ のもとでの方が H₀ のもとでより何倍もっともらしいか」の
対数である。**正なら H₁ 寄り、負なら H₀ 寄り、0 ならどちらとも言えない。**

LLR が

- **A = ln((1−β)/α) = ln(36) ≈ 3.584 以上**になったら → **合格**（挑戦者が強い）
- **B = ln(β/(1−α)) = ln(0.1/0.975) ≈ −2.277 以下**になったら → **不合格**
- どちらにも達しないまま **2,400 局（1,200 ペア）**回したら → **境界**（判定不能）

α = 0.025 は「本当は互角なのに合格させてしまう確率」の上限、
β = 0.10 は「本当に p₁ の強さがあるのに落としてしまう確率」の上限である。

*GSPRT*（generalized SPRT）の「G」は、五項分布の形そのものは分からないので、
**観測された度数から、平均だけを p₀ / p₁ に合わせた最尤の分布を作って比べる**という
一般化を指す（fishtest の型・第 2 集 §7.2.2）。1 局ごとの二項の LLR に落として
しまうと、**ペアにして得た分散の削減が消える**ので、そこは単純化しない（§7 の 1）。

## 使い方

    # 逐次検定（既定）
    python3 experiments/gate_sprt.py --deck SD001 --seed0 666000 --workers 2 \
        --challenger-json '{"value_net": "drl_sd001_vb3.json"}' \
        --out results/vb/gsprt_check_g1.json --budget-sec 480

    # 同じ帯で固定 n（切り替え前後の併記用・D-069(2)(i)）
    python3 experiments/gate_sprt.py --mode fixed --n 1200 --deck SD001 --seed0 666000 \
        --challenger-json '{...}' --out results/vb/gsprt_check_g1_fixedn.json

`--base-json` を渡すと基準側も現 champion への差分で指定できる（検算 G2 で
「旧 champion を基準に、現 champion を挑戦者として」回すために要る）。

`--budget-sec` を渡すと、その秒数を超えた**塊の切れ目**で途中経過を書いて終了コード 2 で
戻る。同じコマンドをもう一度打てば続きから回る（D-068 の型）。
**ペアの片方だけ回した状態では保存しない**（塊の切れ目＝ペアの切れ目）。

## 席をどうやって入れ替えているか（Rust は触っていない）

Rust の `series` は「シードの偶奇で A の席を決める」ので、**同じシードで両方の席**を
回す口が無い。しかし `series(A, B)` と `series(B, A)` を同じシードで回せば、A は必ず
反対の席に座る（偶奇の規則は同じで、A と B の役が入れ替わるため）。したがって
**Python 側で 2 回呼ぶだけ**でペアが作れる。Rust の再ビルドは要らない。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

JST = timezone(timedelta(hours=9))

# --- 母数。**候補を見る前に固定し、ここ以外から変えられないようにする**（§1） -------
ALPHA = 0.025          # 互角なのに合格させてしまう確率の上限
BETA = 0.10            # p₁ の強さがあるのに落としてしまう確率の上限
P0 = 0.50              # 帰無仮説（互角）
P1 = 0.55              # 対立仮説（勝ち越し）
MAX_GAMES = 2400       # 上限（= 1,200 ペア）
CHUNK_PAIRS = 20       # 塊 = 20 ペア = 40 局。**判定は塊の切れ目でだけ行う**

A_BOUND = math.log((1.0 - BETA) / ALPHA)        # ln(36)  ≈ +3.5835
B_BOUND = math.log(BETA / (1.0 - ALPHA))        # ln(0.1/0.975) ≈ −2.2773

PAIR_SCORES = (0.0, 0.25, 0.5, 0.75, 1.0)       # 五項の台
EPSILON = 1e-3                                  # 空の桝があるときだけ混ぜる一様事前分布


# ====================================================================== 検定の芯
def regularize(f: list) -> list:
    """空の桝（度数 0）があるときだけ、一様分布をごく薄く混ぜる（fishtest と同じ扱い）。

    なぜ要るか: 例えば全ペアが 1.0（2 連勝）だと、観測された台は {1.0} だけになる。
    「平均を 0.5 に合わせた分布」は {1.0} の上には作れないので、最尤の問題が解けない。
    ごく薄い一様分布を混ぜておけば台が 5 点すべてに広がり、常に解ける。
    混ぜる量は 1e-3 なので、桝が埋まっている普通の場合の値はほとんど動かない。
    """
    if all(x > 0 for x in f):
        return list(f)
    k = len(f)
    return [(1.0 - EPSILON) * x + EPSILON / k for x in f]


def mle_with_mean(f: list, p: float, xs=PAIR_SCORES, iters: int = 200) -> list:
    """観測度数 f（合計 1）に最も近く、**平均がちょうど p** になる五項分布 q を返す。

    「最も近い」は多項分布の尤度が最大という意味である。ラグランジュの未定乗数法で解くと

        q_k = f_k / (1 + t·(x_k − p))

    という形になり、t は Σ_k f_k·(x_k − p)/(1 + t·(x_k − p)) = 0 の解として決まる。
    左辺は t について**厳密に単調減少**なので解は 1 つだけで、二分法で確実に求まる
    （§7 の 4 で言う「初期値で答えが変わる」心配は、ここには無い）。
    """
    d = [x - p for x in xs]
    lo, hi = -1e18, 1e18
    for fk, dk in zip(f, d):
        if fk <= 0.0:
            continue
        if dk > 0.0:
            lo = max(lo, -1.0 / dk)
        elif dk < 0.0:
            hi = min(hi, -1.0 / dk)
    if not (lo < hi):
        raise ValueError(f"平均 {p} に合わせられない度数である: {f}")

    def phi(t: float) -> float:
        return sum(fk * dk / (1.0 + t * dk) for fk, dk in zip(f, d) if fk > 0.0)

    a, b = lo, hi
    for _ in range(iters):
        m = 0.5 * (a + b)
        if phi(m) > 0.0:
            a = m
        else:
            b = m
    t = 0.5 * (a + b)
    return [fk / (1.0 + t * dk) for fk, dk in zip(f, d)]


def llr_from_counts(counts, p0: float = P0, p1: float = P1, xs=PAIR_SCORES) -> float:
    """ペア得点の度数 counts（長さ 5）から LLR を返す。観測が無ければ 0。

    LLR = N · Σ_k f_k · log( q₁_k / q₀_k )
    q₀ は「平均を p₀ に合わせた最尤分布」、q₁ は「平均を p₁ に合わせた最尤分布」。
    **p₀ = p₁ なら q₀ = q₁ なので LLR = 0** になる（T-D2-1 がこれを固定する）。
    """
    n = float(sum(counts))
    if n <= 0:
        return 0.0
    f = regularize([c / n for c in counts])
    q0 = mle_with_mean(f, p0, xs)
    q1 = mle_with_mean(f, p1, xs)
    return n * sum(fk * math.log(b / a) for fk, a, b in zip(f, q0, q1) if fk > 0.0)


class Gsprt:
    """ペア得点を足しながら LLR と判定を持つ係。**対局のことは何も知らない**（検査しやすい）。"""

    def __init__(self, p0: float = P0, p1: float = P1,
                 a_bound: float = A_BOUND, b_bound: float = B_BOUND,
                 max_games: int = MAX_GAMES):
        self.p0, self.p1 = p0, p1
        self.a_bound, self.b_bound = a_bound, b_bound
        self.max_games = max_games
        self.counts = [0] * len(PAIR_SCORES)

    @staticmethod
    def bucket(score: float) -> int:
        """ペア得点 → 桝の番号（0..4）。台の外の値は受け付けない。"""
        k = int(round(score * 4))
        if k < 0 or k >= len(PAIR_SCORES) or abs(PAIR_SCORES[k] - score) > 1e-9:
            raise ValueError(f"ペア得点が台の外である: {score!r}")
        return k

    def add(self, score: float) -> None:
        self.counts[self.bucket(score)] += 1

    @property
    def pairs(self) -> int:
        return sum(self.counts)

    @property
    def games(self) -> int:
        return 2 * self.pairs

    @property
    def llr(self) -> float:
        return llr_from_counts(self.counts, self.p0, self.p1)

    @property
    def mean_score(self) -> float:
        """1 局あたりの期待得点の推定（ペア得点の平均）。"""
        n = self.pairs
        return sum(c * x for c, x in zip(self.counts, PAIR_SCORES)) / n if n else float("nan")

    def verdict(self) -> str:
        """"pass"（合格）／"fail"（不合格）／"cap"（上限で境界）／"continue"。"""
        llr = self.llr
        if llr >= self.a_bound:
            return "pass"
        if llr <= self.b_bound:
            return "fail"
        if self.games >= self.max_games:
            return "cap"
        return "continue"

    def paired_se(self) -> dict:
        """対応のある差の広がり（第 2 集 §7.2.3 (d)・McNemar 型）。

        ペア得点の 0.5（1 勝 1 敗）は差に何も足さないので、**差の情報は
        「割れなかったペア」だけから来る**。それが「不一致ペアだけ数える」の意味である。

        - `delta` … 1 局あたりの得点が 0.5 からどれだけ離れているか（＝ p̂ − 0.5）
        - `se`    … その標準誤差（ペア単位の分散から。ふつうの 1 局 1 観測より小さくなる）
        - `n_win2` / `n_loss2` … 2 連勝・2 連敗のペア数（古典的な McNemar の b と c）
        - `mcnemar_z` … (b − c)/√(b + c)。**参考値**（0.25・0.75 の桝を無視するため）
        """
        n = self.pairs
        if n == 0:
            return {"delta": None, "se": None, "n_win2": 0, "n_loss2": 0, "mcnemar_z": None}
        dev = [x - 0.5 for x in PAIR_SCORES]
        m1 = sum(c * d for c, d in zip(self.counts, dev)) / n
        m2 = sum(c * d * d for c, d in zip(self.counts, dev)) / n
        var = max(0.0, (m2 - m1 * m1) / n)
        b, c = self.counts[4], self.counts[0]
        z = (b - c) / math.sqrt(b + c) if (b + c) else None
        return {"delta": m1, "se": math.sqrt(var), "n_win2": b, "n_loss2": c,
                "mcnemar_z": z}

    def params(self) -> dict:
        return {"alpha": ALPHA, "beta": BETA, "p0": self.p0, "p1": self.p1,
                "max_games": self.max_games, "A": self.a_bound, "B": self.b_bound,
                "chunk_pairs": CHUNK_PAIRS, "pair_scores": list(PAIR_SCORES),
                "epsilon": EPSILON}


def run_sequential(scores, **kw) -> dict:
    """得点の並びを順に食わせ、**塊の切れ目でだけ**判定する（検査用の純関数）。

    実対局を回さずに「合格側・不合格側・上限のどれで止まるか」を確かめられる。
    """
    chunk = kw.pop("chunk_pairs", CHUNK_PAIRS)
    g = Gsprt(**kw)
    verdict = "continue"
    for i, s in enumerate(scores, 1):
        g.add(s)
        if i % chunk == 0 or g.games >= g.max_games:
            verdict = g.verdict()
            if verdict != "continue":
                break
    return {"verdict": verdict, "llr": g.llr, "counts": list(g.counts),
            "pairs": g.pairs, "games": g.games, "mean_score": g.mean_score}


# ====================================================================== 対局まわり
def _score(a_won) -> float:
    """`series` の 1 局の結果（True / False / None）→ 得点。引き分け・打ち切りは 0.5。"""
    return 0.5 if a_won is None else (1.0 if a_won else 0.0)


def pair_block(chal: dict, base: dict, config, seed0: int, m: int, workers: int):
    """シード seed0..seed0+m−1 について、**先後を入れ替えた 2 局ずつ**を回す。

    `series(chal, base)` と `series(base, chal)` を同じシードで呼ぶと、挑戦者は
    必ず反対の席に座る（Rust は「シードの偶奇で A の席を決める」ので、A と B の
    役を入れ替えれば席も入れ替わる）。配り方はシードだけで決まるので、
    **同じ配り方を両側から見た 2 局**になる。
    """
    from arena_rs import series_rs_digest
    ra = series_rs_digest(chal, base, m, config, workers=workers, seed0=seed0)
    rb = series_rs_digest(base, chal, m, config, workers=workers, seed0=seed0)
    out = []
    for i in range(m):
        sa = _score(ra[i][0])                       # 挑戦者から見た得点
        sb = 1.0 - _score(rb[i][0])                 # 基準から見た値を裏返す
        out.append({"seed": seed0 + i, "score": (sa + sb) / 2.0,
                    "s_a": sa, "s_b": sb,
                    "undecided": int(ra[i][0] is None) + int(rb[i][0] is None),
                    "digests": [ra[i][4], rb[i][4]]})
    return out


def build_specs(deck: str, pool: list, chal_diff: dict, base_diff: dict | None):
    """現 champion への差分から、基準側と挑戦者側の spec を作る。"""
    import champion
    import meicho_rs as rs
    from arena_rs import PLANNER
    from meicho.drlnet import resolve_model

    def mk(diff):
        kw = {**champion.kwargs_for(deck), **(diff or {})}
        for key in ("opp_policy_net", "value_net", "policy_net"):
            if key in kw:
                kw[key] = resolve_model(kw[key])
                rs.net_forget(kw[key])
        return PLANNER(pool, **kw)

    return mk(base_diff), mk(chal_diff)


def provenance_for(base_kw: dict, chal_kw: dict, seed0: int, n_seeds: int,
                   workers: int) -> dict:
    """基準と挑戦者の由来。**測定の開始時に作る**（REPORTING_RULES §2.8 の V 凍結）。"""
    import provenance
    band = provenance.band_of(seed0, n_seeds)
    where = {"host": provenance.host_name(), "workers": int(workers)}
    return {"base": provenance.block(base_kw, "rust", band,
                                     extra={"role": "base", **where}),
            "challenger": provenance.block(chal_kw, "rust", band,
                                           extra={"role": "challenger", **where})}


class OutOfBudget(Exception):
    """持ち時間を使い切った。**塊の切れ目でだけ**投げる（途中経過は保存済み）。"""


# ====================================================================== 本体
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="SD001")
    ap.add_argument("--challenger-json", required=True,
                    help="現 champion への差分（JSON）。`{}` なら現 champion そのもの")
    ap.add_argument("--base-json", default=None,
                    help="基準側も現 champion への差分で指定する（既定は現 champion）")
    ap.add_argument("--mode", choices=("gsprt", "fixed"), default="gsprt",
                    help="gsprt=逐次検定／fixed=固定 n（併記用）")
    ap.add_argument("--n", type=int, default=1200,
                    help="--mode fixed のときの局数（1 シード 1 局・席はシードの偶奇）")
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--budget-sec", type=float, default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", default=None)
    ap.add_argument("--expect", default=None,
                    help="回す前に書いた予想（pass / fail / cap）。結果と一緒に残す")
    args = ap.parse_args(argv)

    from arena import Result, load_deck, mirror_config
    from arena_rs import ensure_cards, series_rs

    ensure_cards()
    deck = load_deck(args.deck)
    pool = deck["action_deck"]
    config = mirror_config(deck)
    chal_diff = json.loads(args.challenger_json)
    base_diff = json.loads(args.base_json) if args.base_json else None
    base, chal = build_specs(args.deck, pool, chal_diff, base_diff)

    strip = lambda sp: {k: v for k, v in sp.items() if k != "opp_decklist"}   # noqa: E731
    n_seeds = (MAX_GAMES // 2) if args.mode == "gsprt" else args.n
    out = {
        "tool": "gate_sprt.py", "mode": args.mode, "deck": args.deck,
        "base_diff": base_diff, "challenger_diff": chal_diff,
        "seed0": args.seed0, "workers": args.workers, "expect": args.expect,
        "params": Gsprt().params(),
        "provenance": provenance_for(strip(base), strip(chal),
                                     args.seed0, n_seeds, args.workers),
        "base_spec": {k: (os.path.basename(v) if isinstance(v, str) else v)
                      for k, v in strip(base).items()},
        "challenger_spec": {k: (os.path.basename(v) if isinstance(v, str) else v)
                            for k, v in strip(chal).items()},
        "when": datetime.now(JST).isoformat(timespec="seconds"),
        "platform": platform.platform(),
    }

    path = args.out
    rpath = args.resume or (os.path.splitext(path)[0] + ".resume.json")
    key = {"deck": args.deck, "mode": args.mode, "base_diff": base_diff,
           "challenger_diff": chal_diff, "seed0": args.seed0,
           "params": out["params"], "n": args.n if args.mode == "fixed" else None}
    st = {"key": key, "provenance": out["provenance"],
          "counts": [0] * 5, "pairs_done": 0, "games_done": 0, "undecided": 0,
          "wins": 0.0, "decided": 0, "sec": 0.0, "digests": []}
    if os.path.exists(rpath):
        old = json.load(open(rpath, encoding="utf-8"))
        if old.get("key") != key:
            raise SystemExit(
                f"途中経過 {rpath} は**別の条件**のものである。\n"
                f"  貯まっている　　　: {json.dumps(old.get('key'), ensure_ascii=False)}\n"
                f"  いま回そうとしている: {json.dumps(key, ensure_ascii=False)}\n"
                f"足し込むと混ざった数が出る。別の --resume を指すか、要らなければ消すこと。")
        st = old
        out["provenance"] = st.get("provenance", out["provenance"])   # 開始時の凍結を正とする
        print(f"  ※ 途中から再開する（{os.path.basename(rpath)}）")

    def save_state():
        os.makedirs(os.path.dirname(os.path.abspath(rpath)) or ".", exist_ok=True)
        tmp = rpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, rpath)

    save_state()          # 由来を最初の塊の前に残す（V 凍結の証拠）
    t_call = time.time()

    def budget_out() -> bool:
        return args.budget_sec is not None and time.time() - t_call >= args.budget_sec

    print("■ 門番（逐次検定 GSPRT・D-4）" if args.mode == "gsprt"
          else "■ 門番（固定 n・切り替え前後の併記用）")
    print(f"  基準　 : {out['base_spec']}")
    print(f"  挑戦者 : {out['challenger_spec']}")
    print(f"  帯 　　: {args.seed0}..")
    if args.mode == "gsprt":
        p = out["params"]
        print(f"  母数　 : α={p['alpha']} β={p['beta']} p₀={p['p0']} p₁={p['p1']} "
              f"上限={p['max_games']}局  A={p['A']:.4f} B={p['B']:.4f}")
        if args.expect:
            print(f"  予想　 : {args.expect}（回す前に書いた）")
    print()

    if args.mode == "gsprt":
        g = Gsprt()
        g.counts = list(st["counts"])
        verdict = g.verdict()
        while verdict == "continue":
            if budget_out():
                raise OutOfBudget
            m = min(CHUNK_PAIRS, (MAX_GAMES // 2) - st["pairs_done"])
            tc = time.time()
            blk = pair_block(chal, base, config,
                             args.seed0 + st["pairs_done"], m, args.workers)
            st["sec"] += time.time() - tc
            for row in blk:
                g.add(row["score"])
                st["undecided"] += row["undecided"]
                st["wins"] += row["s_a"] + row["s_b"]
                st["decided"] += 2 - row["undecided"]
                st["digests"].extend(row["digests"])
            st["pairs_done"] += m
            st["games_done"] = 2 * st["pairs_done"]
            st["counts"] = list(g.counts)
            save_state()
            verdict = g.verdict()
            if st["games_done"] % 1000 < 2 * CHUNK_PAIRS or verdict != "continue":
                print(f"  … {st['games_done']:>5} 局 / ペア {st['pairs_done']:>4}  "
                      f"LLR {g.llr:+.3f}  ペア平均 {g.mean_score:.4f}  "
                      f"度数 {g.counts}", flush=True)
        out["verdict"] = verdict
        out["llr"] = g.llr
        out["counts"] = list(g.counts)
        out["pairs"] = g.pairs
        out["games"] = g.games
        out["mean_score"] = g.mean_score
        out["paired"] = g.paired_se()
        out["undecided_games"] = st["undecided"]
        r = Result(st["wins"], st["decided"], g.games)
        out["winrate"] = {"wins": st["wins"], "decided": st["decided"],
                          "p": r.p, "ci": r.ci, "lo": r.p - r.ci, "hi": r.p + r.ci}
        out["wilson"] = wilson_interval(st["wins"], st["decided"])
        out["sec"] = round(st["sec"], 1)
        out["rate"] = (g.games / st["sec"]) if st["sec"] else None
        out["digest_hash"] = hashlib.sha256(
            json.dumps(st["digests"], sort_keys=True).encode()).hexdigest()[:16]
        out["expect_matched"] = (args.expect is None) or (args.expect == verdict)
        print()
        label = {"pass": "**合格側で止まった**（挑戦者が強い）",
                 "fail": "**不合格側で止まった**（挑戦者が弱い、または互角）",
                 "cap": "**上限まで回して境界**（どちらとも言い切れない）"}[verdict]
        print(f"→ {label}  LLR {g.llr:+.4f}  {g.games} 局（{g.pairs} ペア）"
              f"  {out['sec']} 秒")
        pr = out["paired"]
        print(f"   1 局あたり期待得点 {g.mean_score:.4f}"
              f"（0.5 との差 {pr['delta']:+.4f} ± {1.96 * pr['se']:.4f}・"
              f"対応のあるペアの標準誤差から）")
        w = out["wilson"]
        wtxt = f"  Wilson [{w[0]:.3f}, {w[1]:.3f}]" if w else ""
        print(f"   勝率（ふつうの数え方）{r}{wtxt}")
        print(f"   ペア得点の度数 {dict(zip(PAIR_SCORES, g.counts))}"
              f"  2 連勝 {pr['n_win2']} / 2 連敗 {pr['n_loss2']}")
        if args.expect:
            print(f"   予想 {args.expect} → {'一致' if out['expect_matched'] else '**外れた**'}")
    else:
        while st["games_done"] < args.n:
            if budget_out():
                raise OutOfBudget
            c = min(100, args.n - st["games_done"])
            tc = time.time()
            r = series_rs(chal, base, c, config, workers=args.workers,
                          seed0=args.seed0 + st["games_done"])
            st["sec"] += time.time() - tc
            st["wins"] += r.wins
            st["decided"] += r.decided
            st["games_done"] += c
            save_state()
            if st["games_done"] % 200 == 0:
                print(f"  … {st['games_done']:>5}/{args.n} 局"
                      f"（暫定 {st['wins']:.0f}/{st['decided']}）", flush=True)
        r = Result(st["wins"], st["decided"], args.n)
        out["games"] = args.n
        out["winrate"] = {"wins": st["wins"], "decided": st["decided"],
                          "p": r.p, "ci": r.ci, "lo": r.p - r.ci, "hi": r.p + r.ci}
        out["wilson"] = wilson_interval(st["wins"], st["decided"])
        out["sec"] = round(st["sec"], 1)
        out["rate"] = (args.n / st["sec"]) if st["sec"] else None
        w = out["wilson"]
        wtxt = f"  Wilson [{w[0]:.3f}, {w[1]:.3f}]" if w else ""
        print(f"→ 固定 n={args.n}  {r}  下端 {r.p - r.ci:.3f} / 上端 {r.p + r.ci:.3f}"
              f"{wtxt}  {out['sec']} 秒")

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"→ {path}")
    if os.path.exists(rpath):
        os.remove(rpath)
    return 0


def wilson_interval(x: float, n: int, z: float = 1.96):
    """Wilson の 95% 区間（`human_games_ci.wilson` と同じ式。端で 0/1 をはみ出さない）。"""
    if n <= 0:
        return None
    p = x / n
    z2 = z * z
    den = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / den
    half = (z / den) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return [max(0.0, center - half), min(1.0, center + half)]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OutOfBudget:
        print("\n■ 持ち時間を使い切った。**途中経過は残してある**ので、"
              "同じコマンドをもう一度打てば続きから回る。")
        sys.exit(2)
