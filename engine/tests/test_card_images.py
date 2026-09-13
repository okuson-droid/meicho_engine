"""カード画像の索引の検査（UI_DESIGN.md §7.2）。

画像は見た目でしかないので、ここで守るのは 3 つだけである。

1. **実装しているカードに画像の欠けが無い**（増えたら気付ける）
2. **索引がファイル名の綴りに依存しない**（先頭のカードIDだけを見る）
3. **画像が隠蔽情報を持ち込まない**（非公開のキャラに画像を渡さない）
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "experiments"))

from meicho.cards import ACTION_CARDS, CHARA_CARDS
from webapp import images, view

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)      # 中身は見ないので偽物でよい


def _write(d, name):
    with open(os.path.join(d, name), "wb") as f:
        f.write(PNG)


# --- 1. 網羅 ---------------------------------------------------------------

def test_every_implemented_card_has_an_image():
    """実装しているカードすべてに画像がある（UI_DESIGN.md §2）。

    落ちたら「カードを足したのに画像を置いていない」か、その逆である。
    どちらも画面に穴が開くので、**気付けること**が目的。
    """
    st = images.status()
    assert st["missing"] == [], f"画像が無い実装カード: {st['missing']}"


def test_index_keys_are_official_card_ids():
    for cid in images.get_index():
        assert images.FULL_ID_RE.match(cid), cid


def test_unused_images_are_the_unregistered_cards_not_a_mistake():
    """画像はあるが実装に無いカード＝未登録カード（D-062 の残り）。

    ここは 0 でなくてよい。**数が分かること**が目的である。
    """
    st = images.status()
    for cid in st["unused"]:
        assert cid not in ACTION_CARDS and cid not in CHARA_CARDS


# --- 2. 索引の規則 ---------------------------------------------------------

def test_parallel_art_is_not_preferred(tmp_path):
    """`-R` はパラレル（別イラスト・同じカード）。既定は非パラレル（裁定 Q2）。"""
    d = str(tmp_path)
    _write(d, "BP01-003_ツバキ_LV1-R.png")
    _write(d, "BP01-003_ツバキ_LV1.png")
    idx = images.build_index(d)
    assert os.path.basename(idx["BP01-003"]) == "BP01-003_ツバキ_LV1.png"


def test_parallel_art_is_used_when_it_is_the_only_one(tmp_path):
    d = str(tmp_path)
    _write(d, "BP01-061_黒メェと白メェ-R.png")
    idx = images.build_index(d)
    assert os.path.basename(idx["BP01-061"]) == "BP01-061_黒メェと白メェ-R.png"


def test_index_ignores_everything_after_the_card_id(tmp_path):
    """**ファイル名の誤字・異体字・レベル欠落があっても引ける**（UI_DESIGN.md §2.2）。

    これが通る限り、`cards/` の画像名を直す必要はない（裁定 Q3）。
    """
    d = str(tmp_path)
    _write(d, "BP01-023_秋秋_LV1.png")        # 誤字（正しくは 秧秧）
    _write(d, "SD01-021_鈎縄.png")            # 異体字（正しくは 鉤縄）
    _write(d, "BP01-026_熾霞.png")            # _LV1 が無い
    idx = images.build_index(d)
    assert set(idx) == {"BP01-023", "SD01-021", "BP01-026"}


def test_index_skips_files_without_a_card_id(tmp_path):
    d = str(tmp_path)
    _write(d, "cards_structured.png")
    _write(d, "メモ.png")
    with open(os.path.join(d, "cards_structured.csv"), "w") as f:
        f.write("x")
    assert images.build_index(d) == {}


def test_index_is_deterministic(tmp_path):
    d = str(tmp_path)
    for n in ("SD01-009_b.png", "SD01-009_a.png"):
        _write(d, n)
    first = images.build_index(d)
    assert images.build_index(d) == first
    assert os.path.basename(first["SD01-009"]) == "SD01-009_a.png"


def test_missing_folder_is_not_an_error(tmp_path):
    """`cards/` が無くてもアプリは動く（全部テキスト表示に落ちる・§P3）。"""
    assert images.build_index(os.path.join(str(tmp_path), "no_such_dir")) == {}


# --- 3. 経路の安全性 -------------------------------------------------------

def test_url_path_accepts_only_well_formed_ids():
    assert images.id_from_url_path("/card/SD01-009.png") == "SD01-009"
    for bad in ("/card/../../etc/passwd", "/card/SD01-009.png/../x",
                "/card/.png", "/card/sd01-009.png", "/card/SD01-9.png",
                "/card/SD01-009.txt", "/api/state", "/card/"):
        assert images.id_from_url_path(bad) is None, bad


def test_url_for_returns_none_when_there_is_no_image():
    assert images.url_for("NOPE-999") is None
    any_id = next(iter(images.get_index()))
    assert images.url_for(any_id) == "/card/" + any_id + ".png"


# --- 4. 画面に渡す形 -------------------------------------------------------

def test_view_carries_an_image_url_without_dropping_the_engine_text():
    """画像を足しても**エンジンのオペコード言い換え文は消えない**（§P4）。"""
    cid = next(iter(ACTION_CARDS))
    c = view.action_card(cid)
    assert c["img"] == "/card/" + cid + ".png"
    assert "skills" in c and isinstance(c["skills"], list)
    assert c["label"]                       # 既存の項目を削っていない


def test_hidden_chara_never_gets_an_image():
    """非公開のキャラに画像を渡さない（§P2）。裏面は画面側が描く。"""
    c = view.chara_card(view.HIDDEN)
    assert c["img"] is None
    assert c["id"] == view.HIDDEN


def test_chara_card_carries_an_image():
    cid = next(iter(CHARA_CARDS))
    assert view.chara_card(cid)["img"] == "/card/" + cid + ".png"


def test_screen_html_and_script_do_not_hardcode_card_ids():
    """画面のファイルにカードIDを直書きしない（プールが増えても直さなくてよい・D-047）。"""
    here = os.path.join(os.path.dirname(__file__), "..", "webapp", "static")
    for name in ("index.html", "app.js", "style.css"):
        with open(os.path.join(here, name), encoding="utf-8") as f:
            body = f.read()
        # 説明文の例として書くこともあるので、**識別子として使っていない**ことを見る
        for m in re.finditer(r"[A-Z]{2}[0-9]{2}-[0-9]{3}", body):
            line = body[:m.start()].rsplit("\n", 1)[-1]
            assert line.lstrip().startswith(("*", "//", "/*")), \
                f"{name} にカードIDが直書きされている: {m.group(0)}"


# --- 5. 拡大パネルが居座らないこと（D-063 v2） -----------------------------

def _static(name):
    here = os.path.join(os.path.dirname(__file__), "..", "webapp", "static")
    with open(os.path.join(here, name), encoding="utf-8") as f:
        return f.read()


def test_zoom_panel_can_actually_be_hidden():
    """`.zoom` は `display:flex` なので、**`hidden` 属性は効かない**。

    明示的に打ち消さないと「隠したつもりで出たまま」になる。
    実際に D-063 の初版がこれで、拡大が消えずに盤面を覆っていた。
    """
    css = _static("style.css").replace(" ", "").replace("\n", "")
    assert ".zoom[hidden]{display:none}" in css


def test_zoom_has_no_sticky_state():
    """拡大は**マウスが乗っている間だけ**。留め置きの状態を持たない。"""
    js = _static("app.js")
    assert "mouseleave" in js, "離れたときに消す経路が無い"
    assert "pinned" not in js, "留め置きが復活している（居座る原因になる）"
    # カードの上にマウスがあるまま盤面を描き直すと mouseleave は二度と来ない。
    # その取りこぼしを畳む受け皿が要る。
    assert "mousemove" in js, "描き直しで取りこぼした拡大を畳む経路が無い"


# --- 6. 画像の取り違え（D-063 v3） -----------------------------------------

# **既知の 1 件は解消した。** `cards/SD01-019_轟音.png` が `SD01-018_音の形回避.png` の
# 複製で轟音の画像が入っていなかったが、2026-09-13 に手動スクショへ切り替えたとき
# 轟音に自前の画像が入って直った（D-084）。以後ここは空で保つ。
# また同じ事故が起きたら、ここに足して通すのではなく画像の方を直すこと。
KNOWN_DUPLICATES = []


def test_no_new_cards_share_the_same_image():
    """**別のカードが同じ画像ファイルを指していたら、どちらかが間違い**である。

    パラレル（`-R`）は別イラストなので中身が違う。したがって中身の一致は
    取り込みの事故を意味する。ここが増えたら気付けるようにしておく。
    """
    found = images.status()["duplicates"]
    new = [g for g in found if g not in KNOWN_DUPLICATES]
    assert new == [], f"別カードが同じ画像を指している: {new}"


# --- 7. トラッシュは公開情報（D-063 v3） -----------------------------------

def test_view_exposes_both_trashes():
    """トラッシュは**両者とも公開情報**（rules_draft.md §11）。

    observe が最初から中身を返しているので、画面に出しても情報は増えていない。
    """
    import random
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))
    from arena import load_deck, mirror_config
    from webapp import agents
    from webapp.session import Session
    deck = load_deck("SD001")
    cfg, pool = mirror_config(deck), deck["action_deck"]
    s = Session("t", cfg, pool, 130000, 0, "heuristic",
                agents.build("heuristic", pool, 1), 1)
    rng = random.Random(5)
    for _ in range(200):                     # トラッシュが溜まるまで進める
        if s.finished:
            break
        acts = s.legal()
        if not acts:
            break
        s.play(rng.randrange(len(acts)), s.ply)
        b = s.snapshot()["board"]
        if b["me"]["trash_count"] and b["opp"]["trash_count"]:
            break
    b = s.snapshot()["board"]
    for side in ("me", "opp"):
        assert len(b[side]["trash"]) == b[side]["trash_count"]
        for c in b[side]["trash"]:
            assert c["id"] and "skills" in c        # 画面に出せる形になっている
    assert b["me"]["trash_count"] and b["opp"]["trash_count"], "トラッシュが溜まらなかった"


# --- 8. 画面は行動を組み立てない（D-063 v3） -------------------------------

def test_screen_only_sends_a_legal_index():
    """クリックで選ぶ形にしても、**送るのは合法手の添字だけ**である。

    画面が行動の中身（辞書）を組み立てて送るようになったら、
    そこはもうエンジンの合法手ではない。
    """
    js = _static("app.js")
    assert "'/api/play'" in js
    body = js[js.index("'/api/play'"):js.index("'/api/play'") + 120]
    assert "index:" in body, "/api/play に添字以外を送ろうとしている"
    # 種類→対象 の対応づけは合法手そのものから取り出している
    assert "a.action.hand" in js and "a.action.card" in js and "a.action.back" in js
