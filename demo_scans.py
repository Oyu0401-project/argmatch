#!/usr/bin/env python3
"""answers.csv から「答案画像」を作る（実データが無いときの通し試験用）。

スキャナの癖（傾き・位置ずれ）を模して、マーカー補正が効くことも同時に確かめる。

    python3 demo_scans.py --answers demo/answers.csv --out scans/ --n 8
    python3 pipeline.py --scans scans/ --key demo/key.csv --out run/
"""

import argparse
import csv
import os

import cv2
import numpy as np

PAGE = (1400, 1980)
PAD = 40
GRID = (8, 4)          # 列, 行
X0, Y0 = 120, 260


def cell_rect(qi):
    cols, rows = GRID
    cw, ch = (PAGE[0] - 240) / cols, (PAGE[1] - 420) / rows
    r, c = divmod(qi, cols)
    return int(X0 + c * cw), int(Y0 + r * ch), int(cw), int(ch)


def render_page(answers, seed=0):
    w, h = PAGE[0] + 2 * PAD, PAGE[1] + 2 * PAD
    img = np.full((h, w, 3), 250, np.uint8)
    for cx, cy in [(PAD, PAD), (w - PAD, PAD), (w - PAD, h - PAD), (PAD, h - PAD)]:
        cv2.rectangle(img, (cx - 26, cy - 26), (cx + 26, cy + 26), (10, 10, 10), -1)
    for qi, val in enumerate(answers):
        x, y, cw, ch = cell_rect(qi)
        cv2.rectangle(img, (x + PAD, y + PAD), (x + cw + PAD, y + ch + PAD), (200, 200, 200), 1)
        if val:
            cv2.putText(img, val, (x + PAD + 26, y + ch + PAD - 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (40, 40, 120), 3, cv2.LINE_AA)
    # スキャナの癖：1.2度の傾きと数pxのずらし
    rng = np.random.default_rng(seed)
    ang = rng.uniform(-1.2, 1.2)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    M[0, 2] += rng.uniform(-6, 6)
    M[1, 2] += rng.uniform(-6, 6)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(250, 250, 250))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", required=True)
    ap.add_argument("--out", default="scans")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--tag", default="sheet")
    a = ap.parse_args()

    with open(a.answers, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    qs, data = rows[0][1:], rows[1:1 + a.n]
    os.makedirs(a.out, exist_ok=True)
    for i, r in enumerate(data):
        sid = r[0]
        img = render_page(r[1:len(qs) + 1], seed=i)
        path = os.path.join(a.out, f"{a.tag}{i + 1:02d}_{sid}.png")
        cv2.imwrite(path, img)
        print(f"{path}")
    print(f"→ {len(data)}枚（{len(qs)}問）")


if __name__ == "__main__":
    main()
