#!/usr/bin/env python3
"""スキャン画像 → 解答データ → 一致率 → レポート を1コマンドで通す。

    python3 pipeline.py --scans scans/ --key key.csv --out run/

やること:
  1. テンプレートが無ければ1枚目から作る（マーカー4点＋格子）
  2. 全員分をセル単位で認識（低信頼セルは VLM で再読、それでも駄目なら人要確認）
  3. 一致率・検定 → report.html / pairs.csv / matrix.csv
  4. 要確認セルの確認ページ review.html（切り抜き画像つき・直したCSVをコピーできる）

人がやるのは 4 の確認だけ。answers.csv を直して再実行すれば結果が更新される。
"""

import argparse
import base64
import csv
import glob
import html
import json
import os
import sys

import cv2

import answer_match as am
import ocr_cells as oc
import report


def _first_scan(scans):
    files = sorted(p for p in glob.glob(os.path.join(scans, "*"))
                   if p.lower().endswith(oc.IMG_EXT) and "_warped" not in p)
    if not files:
        raise SystemExit(f"スキャン画像がありません: {scans}")
    return files[0]


def write_review_page(outdir, review_csv, answers_csv, title, limit=240):
    """低信頼セルの切り抜きを見ながら直し、CSVをコピーできるページ。"""
    if not os.path.exists(review_csv):
        rows = []
    else:
        rows = list(csv.DictReader(open(review_csv, encoding="utf-8-sig")))
    rows.sort(key=lambda r: float(r["conf"]))
    shown = rows[:limit]

    def thumb(rel):
        p = os.path.join(outdir, rel)
        if not os.path.exists(p):
            return ""
        ok, buf = cv2.imencode(".png", cv2.imread(p))
        return "data:image/png;base64," + base64.b64encode(buf).decode() if ok else ""

    trs = "\n".join(
        f"<tr><td class='sid'>{html.escape(r['student'])}</td><td class='q'>{html.escape(r['question'])}</td>"
        f"<td class='img'>{('<img src=\"' + thumb(r['crop']) + '\" alt=\"\">') if r.get('crop') else ''}</td>"
        f"<td><input class='v' data-s='{html.escape(r['student'])}' data-q='{html.escape(r['question'])}' "
        f"value='{html.escape(r['text'])}'></td>"
        f"<td class='num'>{float(r['conf']):.2f}</td></tr>" for r in shown)

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} 確認</title>
<style>
:root{{--ink:oklch(24% .02 40);--ink2:oklch(48% .02 40);--line:oklch(88% .01 40);
--paper:oklch(98.5% .004 60);--accent:oklch(48% .15 28)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);
font-family:"Hiragino Sans","Yu Gothic","Noto Sans JP",sans-serif;font-size:14px;line-height:1.6}}
.wrap{{max-width:880px;margin:0 auto;padding:40px 24px 80px}}
h1{{font-size:24px;margin:0 0 6px}}p.note{{color:var(--ink2);font-size:13px;margin:0 0 22px}}
table{{width:100%;border-collapse:collapse;background:#fff}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}}
th{{font-size:11px;letter-spacing:.06em;color:var(--ink2);border-bottom:1px solid var(--ink)}}
td.img img{{height:42px;display:block;border:1px solid var(--line);background:#fff}}
td.sid,td.q{{font-family:Menlo,monospace;font-size:12.5px}}td.num{{text-align:right;font-variant-numeric:tabular-nums}}
input.v{{width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:4px;font:inherit}}
.bar{{position:sticky;bottom:0;background:var(--paper);border-top:1px solid var(--ink);
padding:14px 0;margin-top:20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
button{{font:inherit;font-weight:600;padding:9px 16px;border:1px solid var(--ink);
background:var(--ink);color:#fff;border-radius:4px;cursor:pointer}}
textarea{{width:100%;height:90px;font-family:Menlo,monospace;font-size:12px;display:none}}
.hint{{font-size:12px;color:var(--ink2)}}
</style></head><body><div class="wrap">
<h1>{html.escape(title)} — 読み取り確認</h1>
<p class="note">信頼度の低いセルだけを表示しています（{len(rows)}件中 {len(shown)}件）。
切り抜きを見て、違っていれば右の欄を直してください。直したら
「CSVをコピー」→ <code>{html.escape(os.path.basename(answers_csv))}</code> に貼り付けて再実行します。</p>
<table><thead><tr><th>生徒</th><th>設問</th><th>切り抜き</th><th>読み取り（修正可）</th><th class="num">信頼度</th></tr></thead>
<tbody>{trs or "<tr><td colspan='5'>要確認セルはありません。</td></tr>"}</tbody></table>
<div class="bar">
  <button onclick="copyCsv()">CSVをコピー</button>
  <span class="hint" id="msg">修正はこのページ内だけ。保存はCSVへの貼り付けで行います。</span>
</div>
<textarea id="out"></textarea>
<script>
function copyCsv(){{
  const base = JSON.parse(document.getElementById('base').value);
  document.querySelectorAll('input.v').forEach(i=>{{
    base[i.dataset.s] = base[i.dataset.s] || {{}};
    base[i.dataset.s][i.dataset.q] = i.value;
  }});
  const header = document.getElementById('hdr').value;
  const qs = header.split(',').slice(1);
  let lines = [header];
  Object.keys(base).sort().forEach(s=>{{
    lines.push([s].concat(qs.map(q=>base[s][q] || '')).join(','));
  }});
  const text = lines.join('\n');
  const ta = document.getElementById('out');
  ta.style.display = 'block'; ta.value = text;
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(text).then(
      ()=>document.getElementById('msg').textContent='コピーしました。answers.csv に貼り付けてください。',
      ()=>ta.select());
  }} else {{ ta.select(); }}
}}
</script>
<input type="hidden" id="hdr" value="{html.escape(_header(answers_csv))}">
<input type="hidden" id="base" value="{html.escape(_base_json(answers_csv), quote=True)}">
</div></body></html>"""


def _base_json(answers_csv):
    """確認ページの下敷き。修正したセルだけ上書きし、他は元の値を保つ。"""
    if not os.path.exists(answers_csv):
        return "{}"
    with open(answers_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    qs = rows[0][1:]
    data = {r[0]: dict(zip(qs, r[1:])) for r in rows[1:] if r}
    return json.dumps(data, ensure_ascii=False)


def _header(answers_csv):
    if not os.path.exists(answers_csv):
        return "student"
    with open(answers_csv, encoding="utf-8-sig", newline="") as f:
        return ",".join(next(csv.reader(f)))


def run_pipeline(scans, key, seats=None, out="run", grid="4x8", mode="text", choices=4,
                 engine="tesseract+vlm", min_conf=0.6, perms=300, fdr=0.05,
                 title="答案 一致率レポート", answers=None, reocr=False, log=print):
    """1コマンド実行の中身。CLI からも関数としても呼べる。"""
    os.makedirs(out, exist_ok=True)
    answers = answers or os.path.join(out, "answers.csv")
    n_rev = 0

    if reocr or not answers_exist(answers):
        tpl_path = os.path.join(out, "template.json")
        if not os.path.exists(tpl_path):
            first = _first_scan(scans)
            if first.lower().endswith(".pdf"):
                first = oc.pdf_to_png(first, 300)
            oc.make_template(first, grid, tpl_path)
        answers, review, n_rev = oc.batch(scans, tpl_path, answers, engine,
                                          min_conf, mode, choices)
        log(f"要確認セル {n_rev} 件 → {os.path.basename(review)}")
    review = os.path.splitext(answers)[0] + "_review.csv"

    res = am.run(answers, key, seats, perms, fdr)
    am.write_csv(res, out)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in res.items() if k not in ("answers", "pairs")},
                  f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as f:
        f.write(report.render(res, title, {"review": n_rev, "engine": engine}))
    with open(os.path.join(out, "review.html"), "w", encoding="utf-8") as f:
        f.write(write_review_page(out, review, answers, title))

    warn = [x for x in res["quality"] if x["note"]]
    if warn:
        log(f"設問の注意: {len(warn)} 問")
        for x in warn[:5]:
            log(f"  {x['q']}: 最多解答「{x['majority']}」が {x['majority_share'] * 100:.0f}% — {x['note']}")
    flagged = [p for p in res["pairs"] if p["flag"]]
    log(f"生徒 {len(res['ids'])} 名 / 設問 {len(res['questions'])} 問 / 要確認 {len(flagged)} 組")
    for pr in flagged[:8]:
        log(f"  {pr['a']} × {pr['b']}  一致率 {pr['score']:.2f} / 証拠 {pr['llr']:.0f}b / "
            f"誤答一致 {pr['err_concord']:.2f}({pr['shared_wrong']}問) / q {pr['q']:.1e}")
    log(f"→ {os.path.join(out, 'report.html')}")
    return res


def score_only(answers, key, seats=None, out="run", perms=300, fdr=0.05,
               title="答案 一致率レポート", log=print):
    """OCRをせず、answers.csv から判定とレポートだけ作る（修正後の再計算用）。"""
    os.makedirs(out, exist_ok=True)
    res = am.run(answers, key, seats, perms, fdr)
    am.write_csv(res, out)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in res.items() if k not in ("answers", "pairs")},
                  f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as f:
        f.write(report.render(res, title))
    rev = os.path.splitext(answers)[0] + "_review.csv"
    with open(os.path.join(out, "review.html"), "w", encoding="utf-8") as f:
        f.write(write_review_page(out, rev, answers, title))
    flagged = [p for p in res["pairs"] if p["flag"]]
    log(f"生徒 {len(res['ids'])} 名 / 設問 {len(res['questions'])} 問 / 要確認 {len(flagged)} 組")
    return res


def answers_exist(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def main():
    ap = argparse.ArgumentParser(description="スキャン→OCR→一致率→レポートを1コマンドで")
    ap.add_argument("--scans", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--seats")
    ap.add_argument("--out", default="run")
    ap.add_argument("--grid", default="4x8")
    ap.add_argument("--mode", default="text", choices=["text", "omr"])
    ap.add_argument("--choices", type=int, default=4)
    ap.add_argument("--engine", default="tesseract+vlm",
                    choices=["tesseract", "tesseract+vlm", "vlm"])
    ap.add_argument("--min-conf", type=float, default=0.6)
    ap.add_argument("--perms", type=int, default=300)
    ap.add_argument("--fdr", type=float, default=0.05)
    ap.add_argument("--title", default="答案 一致率レポート")
    ap.add_argument("--answers", help="OCRを飛ばして既存の answers.csv を使う")
    ap.add_argument("--reocr", action="store_true", help="answers.csv があってもOCRをやり直す")
    a = ap.parse_args()
    run_pipeline(a.scans, a.key, a.seats, a.out, a.grid, a.mode, a.choices, a.engine,
                 a.min_conf, a.perms, a.fdr, a.title, a.answers, a.reocr)


if __name__ == "__main__":
    main()
