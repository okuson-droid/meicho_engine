"""A-4 後半: 探索空間の縮小（レビュー 2026-08-23 §6 A-4「調整空間を絞る」）。

規則の削除（`ablation.py`）が「効かないコードを消す」作業なのに対し、
こちらは「**効かない次元を CEM の探索空間から外す**」作業である。
13次元の同時探索は個体数が同じなら次元あたりの情報が薄くなるので、
平坦な軸を落とすと A-3 の探索効率が上がる。

測り方: 調整済みの計画探索 (`TUNED_*`) を基準とし、1つの軸だけを
±（A-3 で使った初期σ）だけ動かした版と**直接対決**させる。
両方向とも 0.5 と信頼区間で重なれば、その軸に沿って目的関数は平坦である。

注意: これは調整済みの点**の近傍**での平坦さである。別の領域では効くかもしれない。
「探索空間から外してよい」までは言えるが、「このパラメータは無意味」ではない。

使い方: python3 experiments/param_sensitivity.py [n] [workers]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arena import load_deck, mirror_config, series                  # noqa: E402
from optimize_cem import MkPlanner, SPACE, NAMES, to_agent_kwargs   # noqa: E402
from meicho.planner import TUNED_PARAMS, TUNED_WEIGHTS              # noqa: E402

DECK = load_deck("SD001")
CONFIG = mirror_config(DECK)
VALID_SEED0 = 30000        # A-3 の探索・検証のどちらとも重ならないシード帯

# TUNED_* を SPACE のベクトル表現に戻す
BASE = {
    "w_concerto": TUNED_WEIGHTS.concerto, "w_hand": TUNED_WEIGHTS.hand,
    "w_live_red": TUNED_WEIGHTS.live_red, "w_level": TUNED_WEIGHTS.level,
    "w_resource": TUNED_WEIGHTS.resource,
    "p_own_color": TUNED_PARAMS.own_color_weight,
    "p_counter": TUNED_PARAMS.counter_weight,
    "p_scarce": TUNED_PARAMS.scarce_penalty,
    "p_concerto_tgt": TUNED_PARAMS.concerto_target,
    "p_charge_min": TUNED_PARAMS.charge_min_hand,
    "p_levelup_min": TUNED_PARAMS.levelup_min_hand,
    "p_switch_gain": TUNED_PARAMS.switch_min_gain,
    "p_pay_concerto": TUNED_PARAMS.pay_min_concerto,
}


def perturbed(name, direction):
    """1軸だけ ±σ 動かしたベクトル（範囲外は端で止める）。"""
    v = dict(BASE)
    _n, _init, sigma, lo, hi, is_int = next(x for x in SPACE if x[0] == name)
    x = min(max(BASE[name] + direction * sigma, lo), hi)
    v[name] = round(x) if is_int else x
    return v, v[name]


def run(n, workers):
    base = MkPlanner(**to_agent_kwargs(BASE), plan_samples=2)
    print("摂動版 vs 調整済み（0.5 と重なれば、その軸に沿って平坦）\n")
    print(f"| 軸 | 基準値 | −σ の版 | +σ の版 | 判定 |")
    print("|---|---|---|---|---|")
    flat = []
    for name in NAMES:
        cells, ps = [], []
        for d in (-1, +1):
            v, val = perturbed(name, d)
            if abs(val - BASE[name]) < 1e-9:      # 端で動けなかった
                cells.append("—")
                continue
            r = series(MkPlanner(**to_agent_kwargs(v), plan_samples=2),
                       base, n, CONFIG, workers, VALID_SEED0)
            cells.append(f"{val:.2f}: {r}")
            ps.append(r)
        verdict = "平坦" if all(abs(r.p - 0.5) <= r.ci for r in ps) else "効く"
        if verdict == "平坦":
            flat.append(name)
        print(f"| {name} | {BASE[name]:.3f} | {cells[0]} | "
              f"{cells[-1] if len(cells) > 1 else '—'} | {verdict} |", flush=True)
    print(f"\n探索空間から外してよい軸: {flat if flat else 'なし'}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    run(n, workers)
