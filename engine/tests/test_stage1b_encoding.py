# -*- coding: utf-8 -*-
"""D-089 / Stage 1B: v5の公開観測・選択符号・モデル移行。"""
import json
import numpy as np
import pytest

from meicho import encode as E
from meicho.engine import observe
from meicho.state import CharaSlot, GameState, Phase, PlayerState


def _state():
    s=GameState(seed=1); s.players=[PlayerState(),PlayerState()]
    s.turn_no=3; s.turn_player=0; s.phase=Phase.ACTION
    for p in s.players:
        p.action_deck=["SD01-007"]*10; p.slots[0]=CharaSlot(stack=["SD01-001"])
    return s


def test_v5_dimensions_and_version_are_derived():
    # D-124: 現行は v6（v5 の列の後ろに信念の要約と統一した hand_known を足した）。v5 の部分の形はここで守る
    assert E.ENCODING_VERSION == 6
    assert E.OBS_DIM_V5 == E.N_SCALAR + 14*E.NA + 13*E.NC + 2*len(E.ACTION_TAGS)
    assert E.OBS_DIM == E.OBS_DIM_V5 + E.N_BELIEF + E.NA
    assert E.ACT_DIM == len(E.ACTION_TYPES)+E.NA+3*E.NC+6+E.NA
    assert E.ACT_CODE_LEN == 13


def test_public_bp01_state_changes_observation_without_hidden_cards():
    s=_state(); base=E.encode(observe(s,0),0)
    s.damage_taken_mod[0]=2; s.last_turn_clash_winner=1
    s.tag_uses_this_turn[0]={E.ACTION_TAGS[0]:2}; s.last_used_card[0]="SD01-007"
    now=E.encode(observe(s,0),0)
    assert len(now)==E.OBS_DIM and now != base
    assert "action_deck" not in observe(s,0)["opp"]


def test_setup_and_choose_card_have_distinct_v5_action_features():
    ob=observe(_state(),0)
    a={"type":"setup","leader":"アンコ","backs":["ツバキ","ショアキーパー"]}
    b={"type":"setup","leader":"アンコ","backs":["ショアキーパー","ツバキ"]}
    assert E.expand_action(E.action_code(ob,a)) != E.expand_action(E.action_code(ob,b))
    c={"type":"choose_card","zone":"concerto","index":0,"card":"SD01-007"}
    assert E.expand_action(E.action_code(ob,c))[E.T_INDEX["choose_card"]] == 1


def test_training_expansion_matches_python_for_v5_setup():
    torch=pytest.importorskip("torch")
    from experiments.drl_train import expand_codes
    ob=observe(_state(),0)
    a={"type":"setup","leader":"アンコ","backs":["ツバキ","ショアキーパー"]}
    code=E.action_code(ob,a)
    got=expand_codes(torch.tensor([[code]])).numpy()[0,0]
    np.testing.assert_array_equal(got,np.asarray(E.expand_action(code)))


def test_model_migration_keeps_old_outputs(tmp_path):
    from meicho.drlnet import random_net
    from scripts import migrate_nets_stage1b as M
    p=tmp_path/"net.json"
    net=random_net(seed=4,hidden=8,obs_dim=M.OLD_OBS,act_dim=M.OLD_ACT)
    net.encoding_version=4; net.save(str(p))
    assert M.migrate(str(p))=="migrated"
    with open(p,encoding="utf-8") as f: d=json.load(f)
    assert (d["encoding_version"],d["obs_dim"],d["act_dim"])==(5,E.OBS_DIM_V5,E.ACT_DIM)
    assert (tmp_path/"net.json.enc4.bak.json").exists()
