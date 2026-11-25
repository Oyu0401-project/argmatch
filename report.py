#!/usr/bin/env python3
"""一致率レポートの HTML 生成（answer_match.py から呼ばれる）。"""

import html as H


def _pct(x):
    return f"{x * 100:.0f}%"


def _q(v):
    return f"{v:.0e}" if 0 < v < 0.001 else f"{v:.3f}"


def _heat(score):
    # 0.4→薄い紙色, 1.0→濃い朱。彩度は控えめに。
    a = max(0.0, min(1.0, (score - 0.4) / 0.5))
    return f"oklch({97 - 34 * a}% {0.02 + 0.13 * a:.3f} 40)"


def render(res, title, meta=None):
    ids = res["ids"]
    pairs = res["pairs"]
    flagged = [p for p in pairs if p["flag"]]
    top = pairs[:20]
    mat = {(p["a"], p["b"]): p for p in pairs}

    def cell_style(s, t):
        if s == t:
            return "background:oklch(96% .005 40)"
        pr = mat.get((s, t)) or mat.get((t, s))
        v = pr["score"] if pr else 0
        ring = "outline:2px solid oklch(50% .16 25);outline-offset:-2px;" if pr and pr["flag"] else ""
        return f"background:{_heat(v)};{ring}"

    def score_of(s, t):
        if s == t:
            return "—"
        pr = mat.get((s, t)) or mat.get((t, s))
        return f"{pr['score']:.2f}" if pr else ""

    rows_flag = "\n".join(
        f"<tr><td class='mono'>{H.escape(p['a'])}</td><td class='mono'>{H.escape(p['b'])}</td>"
        f"<td class='num strong'>{p['score']:.2f}</td><td class='num'>{_pct(p['raw'])}</td>"
        f"<td class='num'>{p['err_concord']:.2f}</td>"
        f"<td class='num'>{p['shared_wrong']}<span class='dim'> / うち希少 {p['shared_wrong_rare']}</span></td>"
        f"<td class='num'>{p['p']:.1e}</td><td class='num'>{_q(p['q'])}</td><td class='num'>{p['z']:.1f}</td>"
        f"<td>{'隣接' if p['adjacent'] else '—'}</td></tr>"
        for p in flagged) or "<tr><td colspan='10' class='empty'>該当なし。しきい値を満たすペアはありませんでした。</td></tr>"

    rows_top = "\n".join(
        f"<tr><td class='mono'>{H.escape(p['a'])}</td><td class='mono'>{H.escape(p['b'])}</td>"
        f"<td class='num strong'>{p['score']:.2f}</td><td class='num'>{_pct(p['raw'])}</td>"
        f"<td class='num'>{p['err_concord']:.2f}</td><td class='num'>{p['shared_wrong']}</td>"
        f"<td class='num'>{p['q']:.4f}</td>"
        f"<td>{'要確認' if p['flag'] else ''}</td></tr>"
        for p in top)

    meta = meta or {}
    meta_html = ""
    if meta.get("review") is not None:
        meta_html = f"<span>OCR要確認 <b>{meta['review']}</b> セル</span>"
    q_rows = "\n".join(
        f"<tr class='{'bad' if x['note'] and '誤答' in x['note'] else ''}'>"
        f"<td class='mono'>{H.escape(x['q'])}</td>"
        f"<td class='num'>{x['answered']}</td>"
        f"<td class='num'>{x['correct_rate'] * 100:.0f}%</td>"
        f"<td class='mono'>{H.escape(x['majority']) or '—'}</td>"
        f"<td class='num'>{x['majority_share'] * 100:.0f}%</td>"
        f"<td class='note-cell'>{H.escape(x['note'])}</td></tr>"
        for x in res.get("quality", []))

    head = "".join(f"<th class='rot'><span>{H.escape(s)}</span></th>" for s in ids)
    body = ""
    for s in ids:
        tds = "".join(f"<td class='m' style='{cell_style(s, t)}' title='{s} × {t}: "
                      f"{score_of(s, t)}'>{score_of(s, t)}</td>" for t in ids)
        body += f"<tr><th class='rowh mono'>{H.escape(s)}</th>{tds}</tr>"

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{H.escape(title)}</title>
<style>
:root{{
  --ink:oklch(24% .02 40); --ink-2:oklch(46% .02 40); --line:oklch(88% .01 40);
  --paper:oklch(98.5% .004 60); --card:oklch(100% 0 0); --accent:oklch(48% .15 28);
  --mono:"SFMono-Regular",Menlo,Consolas,monospace;
  --sans:"Hiragino Sans","Yu Gothic","Noto Sans JP",sans-serif;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  line-height:1.7;font-size:15px;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1040px;margin:0 auto;padding:48px 28px 72px}}
header{{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:8px}}
.eyebrow{{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:700}}
h1{{font-size:30px;line-height:1.3;margin:6px 0 10px;font-weight:700;letter-spacing:-.01em;text-wrap:pretty}}
.meta{{display:flex;flex-wrap:wrap;gap:22px;font-size:12.5px;color:var(--ink-2)}}
.meta b{{color:var(--ink);font-variant-numeric:tabular-nums}}
h2{{font-size:15px;letter-spacing:.04em;margin:38px 0 12px;padding-bottom:6px;
  border-bottom:1px solid var(--line);font-weight:700}}
h2 small{{font-weight:400;color:var(--ink-2);font-size:12px;margin-left:10px;letter-spacing:0}}
p.note{{font-size:13px;color:var(--ink-2);margin:0 0 14px}}
.caveat{{border-left:3px solid var(--accent);background:oklch(97% .012 40);padding:12px 16px;
  font-size:13px;margin:18px 0 4px}}
.caveat b{{color:var(--accent)}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:var(--card)}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}}
thead th{{font-size:11px;letter-spacing:.06em;color:var(--ink-2);font-weight:600;
  border-bottom:1px solid var(--ink);white-space:nowrap}}
tbody tr:hover{{background:oklch(97.5% .008 45)}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.strong{{font-weight:700}}
.mono{{font-family:var(--mono);font-size:12.5px}}
.dim{{color:var(--ink-2)}}
.empty{{color:var(--ink-2);font-style:italic;text-align:center;padding:20px}}
tr.bad td{{background:oklch(96% .03 30)}}
.note-cell{{font-size:12px;color:var(--ink-2)}}
.matrix{{overflow-x:auto;padding-bottom:6px}}
.matrix table{{border-collapse:separate;border-spacing:1px;font-size:9px;width:auto}}
.matrix td.m{{width:26px;height:26px;text-align:center;padding:0;border:0;
  font-variant-numeric:tabular-nums;color:oklch(30% .02 40)}}
.matrix th.rowh{{position:sticky;left:0;background:var(--paper);padding:0 8px 0 0;border:0;
  font-size:10px;text-align:right}}
.matrix th.rot{{height:64px;width:26px;padding:0;border:0;vertical-align:bottom}}
.matrix th.rot span{{writing-mode:vertical-rl;transform:rotate(180deg);font-size:10px;
  color:var(--ink-2);display:block;white-space:nowrap}}
.legend{{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--ink-2);margin-top:10px}}
.swatch{{width:26px;height:11px;border:1px solid var(--line)}}
footer{{margin-top:44px;padding-top:14px;border-top:1px solid var(--line);
  font-size:11.5px;color:var(--ink-2);display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}}
</style></head><body><div class="wrap">
<header>
  <div class="eyebrow">Answer Sheet Similarity</div>
  <h1>{H.escape(title)}</h1>
  <div class="meta">
    <span>生徒 <b>{len(ids)}</b> 名</span>
    <span>設問 <b>{len(res['questions'])}</b> 問</span>
    <span>比較ペア <b>{len(pairs)}</b> 組</span>
    <span>偶然水準 <b>{res['null_mean']:.2f} ± {res['null_sd']:.2f}</b></span>
    <span>要確認 <b>{len(flagged)}</b> 組</span>{meta_html}
  </div>
</header>

<div class="caveat"><b>読み方。</b>一致率は調査の入口で、判定ではありません。正答だけが揃うのは実力でも起こります。
ここで見るのは<b>誤答の一致</b>と、集団内で珍しい誤答がどれだけ重なったか。それでも「どちらが写したか」は答案だけでは決まらないため、
席の位置・提出順・聞き取りと突き合わせて確定してください。</div>

<h2>要確認ペア<small>FDR 5%・z≥2・希少な誤答一致3問以上・誤答一致率50%以上をすべて満たす組</small></h2>
<table><thead><tr>
<th>生徒A</th><th>生徒B</th><th class="num">一致率</th><th class="num">生の一致</th>
<th class="num">誤答一致</th><th class="num">同時誤答</th><th class="num">p値</th><th class="num">q値</th><th class="num">z</th><th>席</th>
</tr></thead><tbody>{rows_flag}</tbody></table>

<h2>一致率マトリクス<small>朱が濃いほど一致。枠線は要確認ペア</small></h2>
<div class="matrix"><table><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></div>
<div class="legend"><span>0.40</span>
  <span class="swatch" style="background:{_heat(0.4)}"></span>
  <span class="swatch" style="background:{_heat(0.6)}"></span>
  <span class="swatch" style="background:{_heat(0.8)}"></span>
  <span class="swatch" style="background:{_heat(1.0)}"></span><span>1.00</span></div>

<h2>設問の健全性<small>同じ誤答が半数以上を占める設問は、OCRの誤読か正答設定の誤りの疑い</small></h2>
<table><thead><tr><th>設問</th><th class="num">解答数</th><th class="num">正答率</th>
<th>最多解答</th><th class="num">シェア</th><th>注意</th></tr></thead><tbody>{q_rows}</tbody></table>

<h2>上位20組<small>q値（偶然の割引後）が小さい順。q値が小さいほど「偶然では起きにくい」</small></h2>
<table><thead><tr><th>生徒A</th><th>生徒B</th><th class="num">一致率</th><th class="num">生の一致</th>
<th class="num">誤答一致</th><th class="num">同時誤答</th><th class="num">p値</th><th>判定</th></tr></thead>
<tbody>{rows_top}</tbody></table>

<footer>
  <span>answer_match.py により生成</span>
  <span>一致率 = 希少度で重み付けした解答一致（部分一致0.5点）／ 誤答一致 = 両者誤答のうち同一解答の割合</span>
</footer>
</div></body></html>"""
