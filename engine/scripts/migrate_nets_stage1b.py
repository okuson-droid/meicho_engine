#!/usr/bin/env python3
"""Stage 1B: encoding v4 の学習済みネットを v5 へ無損失移行する。

新しい公開入力と選択行動に対応する列を0で追加する。旧列は意味を保った位置へ写すため、
v4入力を埋め込んだときの幹・価値・方策出力はfloat64で一致する。
旧記録は新しい公開入力を復元できないので、この道具の対象外である。
"""
from __future__ import annotations

import argparse, glob, json, os, shutil
import numpy as np

from meicho.encode import ACT_DIM as NEW_ACT, OBS_DIM as NEW_OBS
from meicho.encode import ACTION_TAGS, NA, NC

OLD_OBS, OLD_ACT = 1313, 226
OLD_VERSION, NEW_VERSION = 4, 5
OLD_SCALAR, NEW_SCALAR = 62, 100
OLD_TYPES, NEW_TYPES = 19, 20


def obs_map():
    m = list(range(OLD_SCALAR))
    m += [NEW_SCALAR + i for i in range(12 * NA + 7 * NC)]
    assert len(m) == OLD_OBS and NEW_OBS == NEW_SCALAR + 14*NA + 13*NC + 2*len(ACTION_TAGS)
    return m


def act_map():
    m = list(range(OLD_TYPES))
    m += [NEW_TYPES + i for i in range(NA)]
    old_chara = OLD_TYPES + NA
    new_chara = NEW_TYPES + NA
    m += [new_chara + i for i in range(NC)]
    old_tail = old_chara + NC
    new_tail = new_chara + 3 * NC
    m += [new_tail + i for i in range(6)]
    m += [new_tail + 6 + i for i in range(NA)]
    assert len(m) == OLD_ACT
    return m


OBS_MAP, ACT_MAP = obs_map(), act_map()


def widen(w, mapping, new_cols, prefix=0):
    a=np.asarray(w,dtype=np.float64)
    assert a.shape[1]-len(mapping)==prefix
    z=np.zeros((a.shape[0],prefix+new_cols),dtype=np.float64)
    z[:,:prefix]=a[:,:prefix]
    for old,new in enumerate(mapping): z[:,prefix+new]=a[:,prefix+old]
    return z.tolist()


def dense(layer, x):
    return np.maximum(np.asarray(layer["w"],float) @ x + np.asarray(layer["b"],float), 0)


def trunk(net, x):
    for layer in net["trunk"]: x=dense(layer,x)
    return x


def policy(net, h, a):
    x=np.concatenate([h,a])
    for layer in net["policy"][:-1]: x=dense(layer,x)
    layer=net["policy"][-1]
    return np.asarray(layer["w"],float) @ x + np.asarray(layer["b"],float)


def migrate(path, check=False):
    with open(path,encoding="utf-8") as f: old=json.load(f)
    if old.get("encoding_version")==NEW_VERSION and old.get("obs_dim")==NEW_OBS: return "already"
    assert (old.get("encoding_version"),old.get("obs_dim"),old.get("act_dim"))==(OLD_VERSION,OLD_OBS,OLD_ACT)
    new=json.loads(json.dumps(old)); hidden=len(old["trunk"][-1]["w"])
    new["trunk"][0]["w"]=widen(old["trunk"][0]["w"],OBS_MAP,NEW_OBS)
    new["policy"][0]["w"]=widen(old["policy"][0]["w"],ACT_MAP,NEW_ACT,hidden)
    new.update(obs_dim=NEW_OBS,act_dim=NEW_ACT,encoding_version=NEW_VERSION)
    rng=np.random.RandomState(20260915); worst=0.0
    for _ in range(100):
        xo=rng.randint(-8,9,OLD_OBS).astype(float); xn=np.zeros(NEW_OBS); xn[OBS_MAP]=xo
        ao=rng.randint(0,2,OLD_ACT).astype(float); an=np.zeros(NEW_ACT); an[ACT_MAP]=ao
        ho,hn=trunk(old,xo),trunk(new,xn)
        worst=max(worst,float(np.max(np.abs(ho-hn))),float(np.max(np.abs(policy(old,ho,ao)-policy(new,hn,an)))))
    assert worst < 1e-10, worst
    if not check:
        backup=path+".enc4.bak.json"
        if not os.path.exists(backup): shutil.copy2(path,backup)
        with open(path,"w",encoding="utf-8",newline="\n") as f: json.dump(new,f,ensure_ascii=False,separators=(",",":"))
    print(f"{os.path.basename(path)}: {'checked' if check else 'migrated'} max_abs={worst:.3g}")
    return "checked" if check else "migrated"


def main():
    p=argparse.ArgumentParser(); p.add_argument("paths",nargs="+"); p.add_argument("--check",action="store_true"); a=p.parse_args()
    paths=[]
    for pat in a.paths: paths.extend(glob.glob(pat) or [pat])
    for path in paths: migrate(path,a.check)


if __name__=="__main__": main()
