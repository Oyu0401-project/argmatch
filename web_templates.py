#!/usr/bin/env python3
"""Web UI のテンプレート（Flask から呼ばれる）。"""

import html

CSS = """
:root{
  --ink:oklch(22% .02 40); --ink2:oklch(46% .02 40); --line:oklch(87% .012 40);
  --paper:oklch(98.4% .004 60); --card:oklch(100% 0 0); --accent:oklch(48% .15 28);
  --ok:oklch(52% .12 150); --warn:oklch(58% .13 70);
  --sans:"Hiragino Sans","Yu Gothic","Noto Sans JP",system-ui,sans-serif;
  --mono:ui-monospace,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  line-height:1.7;font-size:15px;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:36px 24px 80px}
header{display:flex;justify-content:space-between;align-items:baseline;gap:16px;
  border-bottom:2px solid var(--ink);padding-bottom:12px;margin-bottom:26px;flex-wrap:wrap}
.brand{font-size:15px;font-weight:700;letter-spacing:.02em}
.brand span{color:var(--accent)}
header a{color:var(--ink2);font-size:12.5px;text-decoration:none}
h1{font-size:26px;line-height:1.35;margin:0 0 8px;letter-spacing:-.01em;text-wrap:pretty}
h2{font-size:15px;margin:34px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
p.lead{color:var(--ink2);font-size:13.5px;margin:0 0 22px;max-width:62ch}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:20px}
label{display:block;font-size:12.5px;color:var(--ink2);margin:14px 0 5px;font-weight:600}
label:first-of-type{margin-top:0}
input[type=file],input[type=text],select{width:100%;padding:9px 10px;border:1px solid var(--line);
  border-radius:5px;font:inherit;font-size:13.5px;background:#fff;color:var(--ink)}
input[type=file]{padding:7px}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
button{font:inherit;font-size:14px;font-weight:600;padding:10px 18px;border-radius:5px;
  border:1px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
button:disabled{opacity:.45;cursor:default}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px;align-items:center}
.hint{font-size:12px;color:var(--ink2)}
table{width:100%;border-collapse:collapse;background:var(--card);font-size:13px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{font-size:11px;letter-spacing:.06em;color:var(--ink2);border-bottom:1px solid var(--ink);white-space:nowrap}
.num{text-align:right;font-variant-numeric:tabular-nums}
.mono{font-family:var(--mono);font-size:12.5px}
.pill{display:inline-block;font-size:11px;font-weight:700;padding:2px 9px;border-radius:99px;
  border:1px solid var(--line);color:var(--ink2)}
.pill.running{color:var(--warn);border-color:var(--warn)}
.pill.done{color:var(--ok);border-color:var(--ok)}
.pill.error{color:var(--accent);border-color:var(--accent)}
pre.log{background:oklch(24% .02 40);color:oklch(93% .01 60);padding:14px;border-radius:6px;
  font-family:var(--mono);font-size:12px;line-height:1.6;max-height:300px;overflow:auto;
  white-space:pre-wrap;margin:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:18px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums;line-height:1.2}
.kpi span{font-size:11.5px;color:var(--ink2);letter-spacing:.04em}
tr.flag td{background:oklch(96.5% .02 30)}
td.img img{height:40px;display:block;border:1px solid var(--line);background:#fff}
input.v{padding:6px 8px;font-size:13px}
.err{background:oklch(96% .03 30);border-left:3px solid var(--accent);padding:12px 14px;
  border-radius:4px;font-size:13px;white-space:pre-wrap}
footer{margin-top:46px;padding-top:12px;border-top:1px solid var(--line);
  font-size:11.5px;color:var(--ink2);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media (max-width:600px){.wrap{padding:24px 16px 60px}h1{font-size:22px}}
"""


def _page(title, body):
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class="wrap">
<header><div class="brand">argmatch <span>/ 答案一致率</span></div>
<a href="/">← 新しい解析</a></header>
{body}
<footer><span>解答一致は調査の入口です。判定は原本確認と聞き取りで行ってください。</span>
<span>argmatch web</span></footer>
</div></body></html>"""


def home(jobs):
    rows = "".join(
        f"<tr><td class='mono'><a href='/job/{j['id']}'>{j['id']}</a></td>"
        f"<td>{html.escape(j['label'])}</td>"
        f"<td><span class='pill {j['status']}'>{j['status']}</span></td>"
        f"<td class='num'>{j['when']}</td></tr>" for j in jobs)
    body = f"""
<h1>手書き答案から「写し」の候補を出す</h1>
<p class="lead">答案をスキャンした画像と正答CSVを入れると、全ペアの解答一致率を
偶然一致を割り引いた統計量で計算し、調べるべきペアだけを出します。
出力は判定ではなく、調査対象の順位と根拠です。</p>

<form class="card" method="post" action="/run" enctype="multipart/form-data">
  <label>答案スキャン（複数可 / zip / PDF）</label>
  <input type="file" name="scans" multiple accept=".png,.jpg,.jpeg,.tif,.tiff,.bmp,.pdf,.zip" required>
  <div class="row">
    <div><label>正答CSV（question,answer）</label>
      <input type="file" name="key" accept=".csv" required></div>
    <div><label>席データ（任意: student,row,col）</label>
      <input type="file" name="seats" accept=".csv"></div>
  </div>
  <div class="row">
    <div><label>マス目（列×行）</label><input type="text" name="grid" value="4x8"></div>
    <div><label>形式</label><select name="mode">
      <option value="text">記述・短答（OCR）</option><option value="omr">マーク式（黒画素）</option></select></div>
    <div><label>選択肢数（マーク式）</label><input type="text" name="choices" value="4"></div>
    <div><label>読み取り</label><select name="engine">
      <option value="tesseract+vlm">tesseract＋低信頼だけVLM</option>
      <option value="tesseract">tesseract（速い）</option>
      <option value="vlm">VLM（手書き向き・遅い）</option></select></div>
  </div>
  <div class="actions">
    <button type="submit">解析する</button>
    <span class="hint">答案画像はこのPC内で処理されます（サーバーはローカル）。</span>
  </div>
</form>

<h2>データが無いとき</h2>
<div class="actions">
  <form method="post" action="/demo?kind=scan"><button class="ghost" type="submit">合成答案で試す（8枚・約1分）</button></form>
  <form method="post" action="/demo?kind=score"><button class="ghost" type="submit">判定だけ試す（5秒）</button></form>
</div>

<h2>これまでの解析</h2>
<table><thead><tr><th>ID</th><th>内容</th><th>状態</th><th class="num">開始</th></tr></thead>
<tbody>{rows or "<tr><td colspan='4' class='hint'>まだありません。</td></tr>"}</tbody></table>
"""
    return _page("argmatch — 答案一致率チェッカー", body)


JOB_JS = """
const JID = "__JID__";
const pill = document.getElementById('pill');
const logBox = document.getElementById('log');
const result = document.getElementById('result');
const kpi = (v, label) => `<div class="kpi"><b>${v}</b><span>${label}</span></div>`;

function render(s) {
  const rows = s.pairs.map(p => `<tr class="flag"><td class="mono">${p.a}</td><td class="mono">${p.b}</td>
      <td class="num">${p.score.toFixed(2)}</td><td class="num">${p.llr.toFixed(0)}b</td>
      <td class="num">${p.err_concord.toFixed(2)}</td><td class="num">${p.shared_wrong}</td>
      <td class="num">${p.q.toExponential(1)}</td></tr>`).join('');
  const table = s.pairs.length
    ? `<table><thead><tr><th>生徒A</th><th>生徒B</th><th class="num">一致率</th><th class="num">証拠量</th>
       <th class="num">誤答一致</th><th class="num">同時誤答</th><th class="num">q値</th></tr></thead>
       <tbody>${rows}</tbody></table>`
    : `<div class="card">要確認ペアはありませんでした。</div>`;
  const warn = s.warnings.length
    ? `<h2>設問の注意</h2><div class="err">` + s.warnings.map(w =>
        `${w.q}：${w.note}（最多解答 ${w.majority || '—'} ${(w.share * 100).toFixed(0)}%）`).join('<br>') + `</div>`
    : '';
  result.innerHTML = `<div class="kpis">${kpi(s.n_students, '生徒')}${kpi(s.n_questions, '設問')}`
    + `${kpi(s.n_flagged, '要確認ペア')}${kpi(s.n_review, 'OCR要確認セル')}</div>`
    + table + warn
    + `<div class="actions">
         <a href="/job/${JID}/report" target="_blank"><button type="button">レポートを開く</button></a>
         <a href="/job/${JID}/review"><button type="button" class="ghost">読み取りを確認する</button></a>
         <a href="/job/${JID}/file/pairs.csv"><button type="button" class="ghost">pairs.csv</button></a>
       </div>`;
}

async function tick() {
  const r = await fetch(`/job/${JID}/status`);
  const s = await r.json();
  pill.textContent = s.status;
  pill.className = 'pill ' + s.status;
  document.getElementById('elapsed').textContent = s.elapsed.toFixed(0) + '秒';
  logBox.textContent = s.log.join(String.fromCharCode(10)) || '…';
  logBox.scrollTop = logBox.scrollHeight;
  if (s.status === 'done') {
    const r2 = await fetch(`/job/${JID}/summary`);
    render(await r2.json());
    return;
  }
  if (s.status === 'error') { result.innerHTML = `<div class="err">${s.error}</div>`; return; }
  setTimeout(tick, 1200);
}
tick();
"""


def job(jid, label):
    body = f"""
<h1>{html.escape(label)}</h1>
<p class="lead">解析中はそのまま開いておいてください。終わると結果が出ます。</p>
<div class="actions" style="margin-top:0">
  <span class="pill" id="pill">queued</span><span class="hint" id="elapsed"></span>
</div>
<div id="result"></div>
<h2>ログ</h2>
<pre class="log" id="log">起動中…</pre>
<script>{JOB_JS.replace("__JID__", jid)}</script>
"""
    return _page("解析中 — argmatch", body)


def review(jid, rows, label, saved=False):
    trs = "".join(
        f"<tr><td class='mono'>{html.escape(r['student'])}</td>"
        f"<td class='mono'>{html.escape(r['question'])}</td>"
        f"<td class='img'>{r['img']}</td>"
        f"<td><input class='v' type='text' name='v::{html.escape(r['student'])}::{html.escape(r['question'])}' "
        f"value='{html.escape(r['text'])}'></td>"
        f"<td class='num'>{r['conf']:.2f}</td></tr>" for r in rows)
    body = f"""
<h1>読み取りの確認</h1>
<p class="lead">信頼度の低いセルだけを出しています。切り抜きと違っていれば直して保存すると、
その場で一致率を計算し直します（元の answers.csv も更新されます）。</p>
{'<div class="err" style="background:oklch(96% .02 150)">保存して再計算しました。</div>' if saved else ''}
<form method="post" action="/job/{jid}/review">
<table><thead><tr><th>生徒</th><th>設問</th><th>切り抜き</th><th>読み取り（修正可）</th><th class="num">信頼度</th></tr></thead>
<tbody>{trs or "<tr><td colspan='5' class='hint'>要確認セルはありません。</td></tr>"}</tbody></table>
<div class="actions"><button type="submit">保存して再計算</button>
<a href="/job/{jid}"><button type="button" class="ghost">結果に戻る</button></a></div>
</form>
"""
    return _page("読み取り確認 — argmatch", body)


def error(message):
    body = f"""<h1>処理できませんでした</h1>
<div class="err">{html.escape(message)}</div>
<div class="actions"><a href="/"><button type="button">戻る</button></a></div>"""
    return _page("エラー — argmatch", body)
