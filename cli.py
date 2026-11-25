#!/usr/bin/env python3
"""argmatch — 答案一致率チェッカーの CLI。

    argmatch run --scans scans/ --key key.csv --seats seats.csv --out run/
    argmatch score --answers run/answers.csv --key key.csv --out run/
    argmatch template sheet01.png --grid 4x8
    argmatch ocr --scans scans/ --template template.json --out answers.csv
    argmatch demo
    argmatch selftest
"""

import argparse
import os
import shutil
import sys
import tempfile

VERSION = "1.0.0"


def cmd_run(a):
    from pipeline import run_pipeline
    run_pipeline(a.scans, a.key, a.seats, a.out, a.grid, a.mode, a.choices, a.engine,
                 a.min_conf, a.perms, a.fdr, a.title, a.answers, a.reocr)


def cmd_score(a):
    """OCRをせず、answers.csv から統計とレポートだけ。"""
    import json
    import answer_match as am
    import report
    from pipeline import write_review_page

    os.makedirs(a.out, exist_ok=True)
    res = am.run(a.answers, a.key, a.seats, a.perms, a.fdr)
    am.write_csv(res, a.out)
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in res.items() if k not in ("answers", "pairs")},
                  f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(a.out, "report.html"), "w", encoding="utf-8") as f:
        f.write(report.render(res, a.title))
    rev = os.path.splitext(a.answers)[0] + "_review.csv"
    with open(os.path.join(a.out, "review.html"), "w", encoding="utf-8") as f:
        f.write(write_review_page(a.out, rev, a.answers, a.title))
    flagged = [p for p in res["pairs"] if p["flag"]]
    print(f"{len(res['ids'])}名 / {len(res['questions'])}問 / 要確認 {len(flagged)}組 → "
          f"{os.path.join(a.out, 'report.html')}")


def cmd_template(a):
    import ocr_cells as oc
    oc.make_template(a.image, a.grid, a.out)


def cmd_ocr(a):
    import ocr_cells as oc
    oc.batch(a.scans, a.template, a.out, a.engine, a.min_conf, a.mode, a.choices)


def cmd_demo(a):
    """合成データで一通り動かす（実データが無くても感触を確かめられる）。"""
    import answer_match as am
    import demo_generate
    import report

    os.makedirs(a.out, exist_ok=True)
    demo_generate.main(a.out)
    res = am.run(os.path.join(a.out, "answers.csv"), os.path.join(a.out, "key.csv"),
                 os.path.join(a.out, "seats.csv"), a.perms, a.fdr)
    am.write_csv(res, a.out)
    with open(os.path.join(a.out, "report.html"), "w", encoding="utf-8") as f:
        f.write(report.render(res, "合成データ（仕込みペア2組）"))
    flagged = [p for p in res["pairs"] if p["flag"]]
    print(f"要確認 {len(flagged)}組（仕込みは2組）")
    for pr in flagged:
        print(f"  {pr['a']} × {pr['b']}  一致率 {pr['score']:.2f} / 証拠 {pr['llr']:.0f}b / q {pr['q']:.1e}")
    print(f"→ {os.path.join(a.out, 'report.html')}")


def cmd_web(a):
    """ブラウザで使う（ローカルサーバー）。"""
    from webapp import main as web_main
    argv = ["--host", a.host, "--port", str(a.port)]
    if a.work:
        argv += ["--work", a.work]
    web_main(argv)


def cmd_selftest(a):
    """この環境で正しく動くかを確認する。壊れていれば終了コード1。"""
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond)))
        print(f"  {'✓' if cond else '✗'} {name}{(' — ' + detail) if detail and not cond else ''}")

    print("== 依存 ==")
    for mod in ("numpy", "cv2", "sympy"):
        try:
            __import__(mod)
            check(mod, True)
        except Exception as e:
            check(mod, False, str(e))
    tess = shutil.which("tesseract")
    check("tesseract", bool(tess), "apt-get install tesseract-ocr tesseract-ocr-jpn")
    check("pdftoppm（PDF入力）", bool(shutil.which("pdftoppm")) or not a.strict, "apt-get install poppler-utils")
    check("gsk（VLM再読）", bool(shutil.which("gsk")) or a.engine == "tesseract", "--engine tesseract で回避可")

    print("== 判定ロジック ==")
    import answer_match as am
    import demo_generate
    tmp = tempfile.mkdtemp(prefix="argmatch_selftest_")
    demo_generate.main(tmp)
    res = am.run(os.path.join(tmp, "answers.csv"), os.path.join(tmp, "key.csv"),
                 os.path.join(tmp, "seats.csv"), perms=100)
    flagged = {(p["a"], p["b"]) for p in res["pairs"] if p["flag"]}
    check("仕込みペア2組を検出", flagged == {("S03", "S07"), ("S18", "S21")}, str(flagged))
    clean = [p for p in res["pairs"] if p["shared_wrong_rare"] == 0]
    check("誤答一致0のペアは非検出", all(not p["flag"] for p in clean))

    print("== OCR ==")
    if tess:
        import cv2
        import demo_scans
        import ocr_cells as oc
        scans = os.path.join(tmp, "scans")
        os.makedirs(scans, exist_ok=True)
        img = demo_scans.render_page(["1", "2", "3", "4"] + [""] * 28, seed=1)
        png = os.path.join(scans, "t01.png")
        cv2.imwrite(png, img)
        tpl = os.path.join(tmp, "tpl.json")
        oc.make_template(png, "4x8", tpl)
        out = os.path.join(tmp, "answers.csv")
        oc.batch(scans, tpl, out, engine="tesseract")
        import csv
        row = list(csv.reader(open(out, encoding="utf-8-sig")))[1]
        got = row[1:5]
        check("セル単位OCR（Q1-Q4）", got == ["1", "2", "3", "4"], str(got))
    else:
        print("  - tesseract が無いためスキップ")

    ok = all(c for _, c in checks)
    print("== 結果 ==")
    print(f"  {sum(1 for _, c in checks if c)}/{len(checks)} 合格" + ("  → 使えます" if ok else "  → 未整備"))
    return 0 if ok else 1


def build_parser():
    ap = argparse.ArgumentParser(prog="argmatch",
                                 description="手書き答案の解答一致から「写し」の候補を統計的に絞る")
    ap.add_argument("--version", action="version", version=f"argmatch {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="スキャン→OCR→判定→レポート（1コマンド）")
    p.add_argument("--scans", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--seats")
    p.add_argument("--out", default="run")
    p.add_argument("--grid", default="4x8")
    p.add_argument("--mode", default="text", choices=["text", "omr"])
    p.add_argument("--choices", type=int, default=4)
    p.add_argument("--engine", default="tesseract+vlm",
                   choices=["tesseract", "tesseract+vlm", "vlm"])
    p.add_argument("--min-conf", type=float, default=0.6)
    p.add_argument("--perms", type=int, default=300)
    p.add_argument("--fdr", type=float, default=0.05)
    p.add_argument("--title", default="答案 一致率レポート")
    p.add_argument("--answers", help="OCRを飛ばして既存の answers.csv を使う")
    p.add_argument("--reocr", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("score", help="answers.csv から判定だけ（速い）")
    p.add_argument("--answers", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--seats")
    p.add_argument("--out", default="run")
    p.add_argument("--perms", type=int, default=300)
    p.add_argument("--fdr", type=float, default=0.05)
    p.add_argument("--title", default="答案 一致率レポート")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("template", help="答案1枚からテンプレートを作る")
    p.add_argument("image")
    p.add_argument("--grid", default="4x8")
    p.add_argument("--out", default="template.json")
    p.set_defaults(func=cmd_template)

    p = sub.add_parser("ocr", help="スキャン画像を解答データにする")
    p.add_argument("--scans", required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--out", default="answers.csv")
    p.add_argument("--engine", default="tesseract+vlm",
                   choices=["tesseract", "tesseract+vlm", "vlm"])
    p.add_argument("--mode", default="text", choices=["text", "omr"])
    p.add_argument("--choices", type=int, default=4)
    p.add_argument("--min-conf", type=float, default=0.6)
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("demo", help="合成データで一通り動かす")
    p.add_argument("--out", default="argmatch-demo")
    p.add_argument("--perms", type=int, default=300)
    p.add_argument("--fdr", type=float, default=0.05)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("web", help="ブラウザで使う（ローカルサーバー）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--work", default=None)
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("selftest", help="この環境で動くか確認する")
    p.add_argument("--engine", default="tesseract+vlm",
                   choices=["tesseract", "tesseract+vlm", "vlm"])
    p.add_argument("--strict", action="store_true", help="PDF/VLMの未整備も失敗扱い")
    p.set_defaults(func=cmd_selftest)
    return ap


def main():
    args = build_parser().parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
