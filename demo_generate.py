#!/usr/bin/env python3
"""動作確認用の合成データ。実データが無くても指標の意味を確かめられるようにする。

条件: 32名 × 32問（1-8は選択式、9-32は短答・数式）。
誤答は「本人固有のつまずき」に近づけるため、数値なら値のずれ、式なら係数/符号の
ずれとして作る（誤答の種類が豊富 → 偶然の一致が起きにくい）。

仕込み:
  - S07 が S03 から 0.85 の確率で写す（一部を全角数字にして偽装）
  - S21 が S18 から 0.70 の確率で写す（改変多め）
  - 上位4名は正答率が高く正答同士がよく一致する（誤検知の罠）
"""

import csv
import os
import random
import re

NQ = 32
Q = [f"Q{i}" for i in range(1, NQ + 1)]
MCQ = ["2", "1", "4", "3", "2", "1", "3", "4"]
NUM = ["12", "-4", "36", "8", "-6", "15", "24", "9", "-18", "7",
       "45", "-9", "16", "28", "-12", "6", "20", "-3", "11", "30"]
EXPR = ["2x+3", "y=2x-1", "x=3", "3a-2"]
KEYS = MCQ + NUM + EXPR
assert len(KEYS) == NQ


def wrong_for(qi, rnd):
    k = KEYS[qi]
    if qi < 8:                                  # 選択式: 他の選択肢
        return rnd.choice([c for c in "1234" if c != k])
    if qi < 28:                                 # 数値: 本人固有のずれ
        v = int(k)
        d = rnd.choice([-1, 1]) * rnd.randint(1, 9)
        return str(v + d)
    if k == "x=3":                              # 式: 係数・符号のずれ
        return rnd.choice(["x=2", "x=-3", "x=1/3", "3"])
    m = re.match(r"^(-?)(\d*)([a-z])([+-]\d+)?$", k.replace("y=", ""))
    if not m:
        return k.replace("2", "3")
    sign, coef, var, const = m.groups()
    coef = str(rnd.randint(1, 4))
    const = f"{rnd.choice(['+', '-'])}{rnd.randint(1, 6)}" if const is None or rnd.random() < .6 else const
    out = f"{sign}{coef}{var}{const}"
    return ("y=" + out) if k.startswith("y=") else out


def sheet(rnd, p):
    return [KEYS[qi] if rnd.random() < min(0.97, p) else wrong_for(qi, rnd) for qi in range(NQ)]


def main(outdir="demo"):
    rnd = random.Random(20261125)
    os.makedirs(outdir, exist_ok=True)
    ids = [f"S{i:02d}" for i in range(1, 33)]
    data = {s: sheet(rnd, rnd.uniform(0.45, 0.8) + (0.15 if s in ("S01", "S02", "S04", "S05") else 0))
            for s in ids}

    copied = []
    for i, v in enumerate(data["S03"]):
        if rnd.random() < 0.85:                 # 写した
            copied.append(v.replace("2", "２") if rnd.random() < 0.15 else v)
        else:                                   # 自力（別解）
            copied.append(wrong_for(i, rnd))
    data["S07"] = copied
    data["S21"] = [v if rnd.random() < 0.70 else wrong_for(i, rnd)
                   for i, v in enumerate(data["S18"])]

    with open(os.path.join(outdir, "answers.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["student"] + Q)
        for s in ids:
            wr.writerow([s] + data[s])
    with open(os.path.join(outdir, "key.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["question", "answer"])
        for q, k in zip(Q, KEYS):
            wr.writerow([q, k])
    with open(os.path.join(outdir, "seats.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["student", "row", "col"])
        for i, s in enumerate(ids):
            wr.writerow([s, i // 6 + 1, i % 6 + 1])
    print(f"生成: {outdir}/answers.csv, key.csv, seats.csv（32名×32問）")


if __name__ == "__main__":
    main()
