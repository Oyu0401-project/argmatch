#!/usr/bin/env python3
"""答案スキャン画像 → セル単位の解答（answer_match.py の前段）。

なぜセル単位か:
  ページ全体をOCRすると罫線・氏名欄・設問文まで混ざって精度が落ちる。
  答案は様式が固定なので、四隅のマーカーで位置を補正し、解答欄だけを切り出して
  1セルずつ認識する（誤読がセル内に閉じ、そのセルだけ人に返せる）。

認識エンジン:
  tesseract      : 速い。印刷文字・数字向き（既定）
  tesseract+vlm  : tesseract で読み、信頼度が低いセルだけ VLM で再読（推奨）
  vlm            : 全セル VLM。手書きに強いが遅い
  --mode omr     : マーク式。セル内を選択肢の帯に分け、黒画素率で判定

使い方:
    python3 ocr_cells.py --make-template sheet01.png --grid 4x8 --out template.json
    python3 ocr_cells.py --batch scans/ --template template.json --out answers.csv \\
        --engine tesseract+vlm --mode text
    python3 ocr_cells.py --batch scans/ --template template.json --out answers.csv \\
        --mode omr --choices 4

出力: answers.csv（1列目=生徒ID、以降=設問）と answers_review.csv（人要確認セル）。
"""

import argparse
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np

PAGE = (1400, 1980)
IMG_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".pdf")


# ---------------------------------------------------------------- 幾何

def order_corners(pts):
    pts = np.array(pts, dtype="float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def find_markers(img):
    """黒い四角マーカー4点を検出し、左上・右上・右下・左下の順で返す。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    cands = []
    for c in cnts:
        area = cv2.contourArea(c)
        if not (0.0002 * h * w < area < 0.02 * h * w):
            continue
        approx = cv2.approxPolyDP(c, 0.04 * cv2.arcLength(c, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        x, y, ww, hh = cv2.boundingRect(approx)
        if not (0.7 < ww / max(hh, 1) < 1.4) or area / (ww * hh) < 0.75:
            continue
        cands.append((x + ww / 2, y + hh / 2))
    if len(cands) < 4:
        raise RuntimeError(f"マーカーが4点見つかりません（検出 {len(cands)} 点）。"
                           "--no-marker（整列済み画像）を使うか、四隅の黒塗りを確認してください")
    picked = []
    for cx, cy in [(0, 0), (w, 0), (w, h), (0, h)]:
        best = min(cands, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        if best not in picked:
            picked.append(best)
    if len(picked) != 4:
        raise RuntimeError("マーカー4点を一意に選べませんでした（余計な黒い四角がありませんか）")
    return order_corners(picked)


def warp(img, markers, size=PAGE):
    dst = np.array([[0, 0], [size[0], 0], [size[0], size[1]], [0, size[1]]], dtype="float32")
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(markers, dst),
                               (int(size[0]), int(size[1])))


def normalize_page(path, no_marker=False):
    img = cv2.imread(path)
    if img is None:
        raise RuntimeError(f"画像を開けません: {path}")
    if no_marker:
        return cv2.resize(img, PAGE)
    return warp(img, find_markers(img))


def make_template(path, grid, out):
    img = cv2.imread(path)
    if img is None:
        sys.exit(f"画像を開けません: {path}")
    warped = normalize_page(path)
    rows, cols = (int(x) for x in grid.lower().split("x"))
    x0, y0 = 120, 260
    cw, ch = (PAGE[0] - 240) / cols, (PAGE[1] - 420) / rows
    cells = [{"q": f"Q{r * cols + c + 1}",
              "x": int(x0 + c * cw) + 8, "y": int(y0 + r * ch) + 8,
              "w": int(cw) - 16, "h": int(ch) - 16}
             for r in range(rows) for c in range(cols)]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    json.dump({"page": list(PAGE), "grid": grid, "cells": cells},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cv2.imwrite(os.path.splitext(out)[0] + "_warped.png", warped)
    print(f"テンプレート: {out}（{rows}行×{cols}列, セル {len(cells)}）")


# ---------------------------------------------------------------- 認識

def omr_choice(crop, choices):
    """マーク式: セルを選択肢の帯に分け、黒画素率が最大の帯を選ぶ。"""
    h = crop.shape[0]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, ink = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)
    band = h / choices
    ratios = []
    for i in range(choices):
        seg = ink[int(i * band):int((i + 1) * band), :]
        ratios.append(float(seg.mean()) / 255.0)
    best = int(np.argmax(ratios))
    top = ratios[best]
    if top < 0.01:
        return "", 0.2                       # 無記入
    if sorted(ratios)[-2] > top * 0.75:
        return str(best + 1), 0.4            # 二重マークの疑い
    return str(best + 1), min(0.95, 0.5 + top)


def run_vlm(cell_path):
    """セル画像1枚を VLM に読ませる。gsk が無い環境では例外。"""
    exe = shutil.which("gsk")
    if not exe:
        raise RuntimeError("gsk が見つかりません（--engine tesseract を使ってください）")
    p = subprocess.run([exe, "understand_images", "-i", os.path.abspath(cell_path), "-r",
                        "この解答欄に手書きで書かれた答えだけを1行で出力。"
                        "数式はそのまま、余計な説明は書かない。判読不能なら空。"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:200])
    try:
        res = json.loads(p.stdout)["data"]["results"][0]["result"]
    except Exception:
        return ""
    return re.sub(r"[\s　]", "", res.splitlines()[0] if res else "")


def tesseract(cell_path):
    p = subprocess.run(["tesseract", cell_path, "stdout", "-l", "jpn+eng",
                        "--psm", "7", "tsv"], capture_output=True, text=True)
    if p.returncode != 0:
        return "", 0.0
    text, confs = [], []
    for line in p.stdout.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        text.append(f[11])
        try:
            if float(f[10]) >= 0:
                confs.append(float(f[10]))
        except ValueError:
            pass
    return "".join(text).strip(), (sum(confs) / len(confs) / 100 if confs else 0.0)


def recognize(crop, cell_path, engine, min_conf, mode, choices):
    """1セルの認識 → (text, confidence)。低信頼なら VLM で再読する。"""
    if mode == "omr":
        return omr_choice(crop, choices)
    big = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(cell_path, big)
    if engine == "vlm":
        return run_vlm(cell_path), 0.9
    text, conf = tesseract(cell_path)
    if engine == "tesseract+vlm" and conf < min_conf and text.strip():
        try:
            alt = run_vlm(cell_path)
            if alt:
                return alt, 0.9
        except RuntimeError:
            pass
    return text, conf


def process(path, tpl, engine, min_conf, mode, choices, cells_dir, out_size):
    warped = normalize_page(path, getattr(tpl, "no_marker", False))
    out, review = {}, []
    for cell in tpl["cells"]:
        q = cell["q"]
        x, y, w, h = cell["x"], cell["y"], cell["w"], cell["h"]
        crop = warped[y:y + h, x:x + w]
        if crop.size == 0:
            out[q], conf = "", 0.0
        else:
            cell_path = os.path.join(cells_dir, f"{q}.png")
            text, conf = recognize(crop, cell_path, engine, min_conf, mode, choices)
            out[q] = re.sub(r"[\s　]", "", text)
        if conf < min_conf or out[q] in ("", "?", "？"):
            review.append({"q": q, "text": out[q], "conf": round(conf, 2),
                           "crop": os.path.join(os.path.basename(cells_dir), f"{q}.png")})
    return out, review


# ---------------------------------------------------------------- バッチ

def pdf_to_png(path, dpi):
    out = tempfile.mkdtemp(prefix="sheet_")
    stem = os.path.join(out, "page")
    if not shutil.which("pdftoppm"):
        raise RuntimeError("PDFを読むには poppler-utils（pdftoppm）が必要です")
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1", path, stem],
                   check=True, capture_output=True)
    hits = glob.glob(stem + "*.png")
    return hits[0] if hits else None


def batch(scans, template, out_csv, engine="tesseract", min_conf=0.6,
          mode="text", choices=4, dpi=300, no_marker=False):
    tpl = json.load(open(template, encoding="utf-8"))
    tpl = type("Tpl", (dict,), {"__getattr__": lambda s, k: s[k]})(tpl)
    tpl.no_marker = no_marker
    files = sorted(p for p in glob.glob(os.path.join(scans, "*"))
                   if p.lower().endswith(IMG_EXT) and "_warped" not in p
                   and not p.endswith("template.png"))
    if not files:
        raise RuntimeError(f"画像が見つかりません: {scans}")

    outdir = os.path.dirname(os.path.abspath(out_csv))
    os.makedirs(outdir, exist_ok=True)
    cells_root = os.path.join(outdir, "cells")
    questions, rows, review_rows = None, [], []
    for f in files:
        sid = os.path.splitext(os.path.basename(f))[0]
        cells_dir = os.path.join(cells_root, sid)
        os.makedirs(cells_dir, exist_ok=True)
        src = pdf_to_png(f, dpi) if f.lower().endswith(".pdf") else f
        answers, review = process(src, tpl, engine, min_conf, mode, choices, cells_dir, PAGE)
        questions = list(answers)
        rows.append([sid] + [answers[q] for q in questions])
        for r in review:
            r["crop"] = os.path.relpath(os.path.join(cells_dir, f"{r['q']}.png"),
                                        outdir).replace(os.sep, "/")
        review_rows += [[sid, r["q"], r["text"], r["conf"], r["crop"]] for r in review]
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["student"] + questions)
        wr.writerows(rows)
    rev = os.path.splitext(out_csv)[0] + "_review.csv"
    with open(rev, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["student", "question", "text", "conf", "crop"])
        wr.writerows(review_rows)
    print(f"→ {out_csv}（{len(rows)}名 × {len(questions)}問） / 要確認 {len(review_rows)} セル")
    return out_csv, rev, len(review_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-template")
    ap.add_argument("--grid", default="4x8")
    ap.add_argument("--template")
    ap.add_argument("--batch")
    ap.add_argument("--out", default="answers.csv")
    ap.add_argument("--engine", default="tesseract", choices=["tesseract", "tesseract+vlm", "vlm"])
    ap.add_argument("--mode", default="text", choices=["text", "omr"])
    ap.add_argument("--choices", type=int, default=4)
    ap.add_argument("--min-conf", type=float, default=0.6)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--no-marker", action="store_true")
    a = ap.parse_args()

    if a.make_template:
        tpl_out = a.template or (a.out if a.out.endswith(".json") else "template.json")
        make_template(a.make_template, a.grid, tpl_out)
        return
    if not (a.template and a.batch):
        sys.exit("--template と --batch が必要です（初回は --make-template）")
    try:
        batch(a.batch, a.template, a.out, a.engine, a.min_conf, a.mode, a.choices,
              a.dpi, a.no_marker)
    except RuntimeError as e:
        sys.exit(f"エラー: {e}")


if __name__ == "__main__":
    main()
