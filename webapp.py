#!/usr/bin/env python3
"""argmatch の Web UI（ローカルサーバー）。

    python3 webapp.py --port 5000        →  http://127.0.0.1:5000
    argmatch web --port 5000

ブラウザでできること:
  1. 答案スキャン（複数/zip/PDF）と正答CSVを選んで実行
  2. 進行状況と結果（要確認ペア・設問の注意）を表示
  3. 低信頼セルの切り抜きを見ながら修正 → その場で再計算
  4. レポート（ヒートマップ）を開く

答案はこのPC内で処理される。外部に送るのは VLM 再読（--engine vlm 系）を選んだときだけ。
"""

import argparse
import csv
import html
import io
import os
import re
import shutil
import threading
import time
import uuid
import zipfile

from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory

import ocr_cells as oc
import pipeline
import web_templates as tpl

app = Flask(__name__)
JOBS = {}
WORK = os.path.abspath(os.environ.get("ARGMATCH_HOME", "web_runs"))
JID_RE = re.compile(r"^[0-9a-f]{12}$")
IMG_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".pdf")


def _safe(name):
    return os.path.basename(name.replace("\\", "/")).strip() or "file"


def _job(jid):
    if not JID_RE.match(jid) or jid not in JOBS:
        abort(404)
    return JOBS[jid]


def _log(jid, msg):
    st = JOBS[jid]
    st["log"].append(str(msg))
    st["log"] = st["log"][-400:]


def _worker(jid, cfg):
    st = JOBS[jid]
    st["status"] = "running"
    d = os.path.join(WORK, jid)
    try:
        if cfg["kind"] == "demo":
            import demo_generate
            demo_generate.main(os.path.join(d, "demo"))
            cfg["key"] = os.path.join(d, "demo", "key.csv")
            cfg["seats"] = os.path.join(d, "demo", "seats.csv")
            if cfg["demo"] == "scan":
                import cv2
                import demo_scans
                scans = os.path.join(d, "scans")
                os.makedirs(scans, exist_ok=True)
                with open(os.path.join(d, "demo", "answers.csv"), encoding="utf-8-sig") as f:
                    rows = list(csv.reader(f))[1:9]
                for i, r in enumerate(rows):
                    img = demo_scans.render_page(r[1:], seed=i)
                    cv2.imwrite(os.path.join(scans, f"sheet{i + 1:02d}_{r[0]}.png"), img)
                _log(jid, f"合成答案 {len(rows)} 枚を生成")
                cfg["scans"] = scans
                cfg["engine"] = "tesseract"
            if cfg["demo"] == "score":
                res = pipeline.score_only(os.path.join(d, "demo", "answers.csv"),
                                          cfg["key"], cfg["seats"], os.path.join(d, "run"),
                                          log=lambda m: _log(jid, m))
                st["res"] = res
                st["status"] = "done"
                return
        res = pipeline.run_pipeline(cfg["scans"], cfg["key"], cfg.get("seats"),
                                    out=os.path.join(d, "run"), grid=cfg["grid"],
                                    mode=cfg["mode"], choices=cfg["choices"],
                                    engine=cfg["engine"], title=cfg["title"],
                                    log=lambda m: _log(jid, m))
        st["res"] = res
        st["status"] = "done"
        _log(jid, "完了")
    except Exception as e:                                    # noqa: BLE001
        st["status"] = "error"
        st["error"] = f"{type(e).__name__}: {e}"
        _log(jid, st["error"])


def _summary(st):
    res = st.get("res") or {}
    pairs = [{"a": p["a"], "b": p["b"], "score": p["score"], "llr": p["llr"],
              "err_concord": p["err_concord"], "shared_wrong": p["shared_wrong"],
              "q": p["q"]} for p in res.get("pairs", []) if p["flag"]]
    warns = [{"q": x["q"], "note": x["note"], "majority": x["majority"],
              "share": x["majority_share"]} for x in res.get("quality", []) if x["note"]]
    rev = st.get("n_review", 0)
    return {"n_students": len(res.get("ids", [])), "n_questions": len(res.get("questions", [])),
            "n_flagged": len(pairs), "n_review": rev, "pairs": pairs, "warnings": warns}


def _count_review(run_dir):
    p = os.path.join(run_dir, "answers_review.csv")
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8-sig") as f:
        return max(0, len(list(csv.DictReader(f))))


@app.get("/")
def home():
    jobs = [{"id": j, "label": s["label"], "status": s["status"],
             "when": time.strftime("%H:%M", time.localtime(s["t0"]))}
            for j, s in sorted(JOBS.items(), key=lambda kv: -kv[1]["t0"])]
    return tpl.home(jobs)


@app.post("/run")
def run():
    scans = request.files.getlist("scans")
    key = request.files.get("key")
    if not scans or not key or not key.filename:
        return tpl.error("スキャン画像と正答CSVを選んでください。"), 400
    jid = uuid.uuid4().hex[:12]
    d = os.path.join(WORK, jid)
    sdir = os.path.join(d, "scans")
    os.makedirs(sdir, exist_ok=True)
    _save_scans(scans, sdir)
    key_path = os.path.join(d, "key.csv")
    key.save(key_path)
    seats = request.files.get("seats")
    seats_path = None
    if seats and seats.filename:
        seats_path = os.path.join(d, "seats.csv")
        seats.save(seats_path)
    grid = (request.form.get("grid") or "4x8").strip()
    if not re.match(r"^\d{1,2}x\d{1,2}$", grid):
        return tpl.error("マス目は 4x8 の形式で入力してください。"), 400
    JOBS[jid] = {"id": jid, "label": f"アップロード（{len(os.listdir(sdir))}枚）",
                 "status": "queued", "log": [], "t0": time.time()}
    cfg = {"kind": "upload", "scans": sdir, "key": key_path, "seats": seats_path,
           "grid": grid, "mode": request.form.get("mode", "text"),
           "choices": int(request.form.get("choices") or 4),
           "engine": request.form.get("engine", "tesseract+vlm"),
           "title": "答案 一致率レポート"}
    threading.Thread(target=_worker, args=(jid, cfg), daemon=True).start()
    return redirect(f"/job/{jid}")


def _save_scans(files, sdir):
    for f in files:
        name = _safe(f.filename)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(f.read())) as z:
                for m in z.namelist():
                    base = _safe(m)
                    if m.endswith("/") or not base.lower().endswith(IMG_EXT):
                        continue
                    with z.open(m) as src, open(os.path.join(sdir, base), "wb") as dst:
                        shutil.copyfileobj(src, dst)
        elif name.lower().endswith(IMG_EXT):
            f.save(os.path.join(sdir, name))


@app.post("/demo")
def demo():
    kind = request.args.get("kind", "scan")
    jid = uuid.uuid4().hex[:12]
    os.makedirs(os.path.join(WORK, jid), exist_ok=True)
    JOBS[jid] = {"id": jid, "label": "合成データ（デモ）", "status": "queued",
                 "log": [], "t0": time.time()}
    cfg = {"kind": "demo", "demo": kind, "grid": "4x8", "mode": "text", "choices": 4,
           "engine": "tesseract", "title": "合成データ（仕込みペア2組）"}
    threading.Thread(target=_worker, args=(jid, cfg), daemon=True).start()
    return redirect(f"/job/{jid}")


@app.get("/job/<jid>")
def job(jid):
    st = _job(jid)
    return tpl.job(jid, st["label"])


@app.get("/job/<jid>/status")
def status(jid):
    st = _job(jid)
    if st["status"] == "running" and "n_review" not in st:
        d = os.path.join(WORK, jid, "run")
        if os.path.exists(os.path.join(d, "answers_review.csv")):
            st["n_review"] = _count_review(d)
    return jsonify({"status": st["status"], "log": st["log"], "error": st.get("error", ""),
                    "elapsed": time.time() - st["t0"]})


@app.get("/job/<jid>/summary")
def summary(jid):
    st = _job(jid)
    if st["status"] != "done":
        return jsonify({"pairs": [], "warnings": [], "n_students": 0, "n_questions": 0,
                        "n_flagged": 0, "n_review": 0})
    st.setdefault("n_review", _count_review(os.path.join(WORK, jid, "run")))
    return jsonify(_summary(st))


@app.get("/job/<jid>/report")
def report_page(jid):
    _job(jid)
    p = os.path.join(WORK, jid, "run", "report.html")
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="text/html")


@app.get("/job/<jid>/file/<name>")
def job_file(jid, name):
    _job(jid)
    if name not in ("pairs.csv", "matrix.csv", "answers.csv", "summary.json"):
        abort(404)
    return send_from_directory(os.path.join(WORK, jid, "run"), name, as_attachment=True)


@app.get("/job/<jid>/cell/<sid>/<q>.png")
def cell_image(jid, sid, q):
    _job(jid)
    safe_sid = _safe(sid)
    if not re.match(r"^[A-Za-z0-9_.\-]+$", safe_sid) or not re.match(r"^[A-Za-z0-9_\-]+$", q):
        abort(404)
    p = os.path.join(WORK, jid, "run", "cells", safe_sid, f"{q}.png")
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png")


def _review_rows(jid):
    d = os.path.join(WORK, jid, "run")
    rv = os.path.join(d, "answers_review.csv")
    ap = os.path.join(d, "answers.csv")
    if not os.path.exists(rv) or not os.path.exists(ap):
        return []
    with open(ap, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    qs = rows[0][1:]
    cur = {r[0]: dict(zip(qs, r[1:])) for r in rows[1:] if r}
    out = []
    with open(rv, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            sid, q = r["student"], r["question"]
            text = cur.get(sid, {}).get(q, r.get("text", ""))
            img = (f"<img src='/job/{jid}/cell/{html.escape(sid)}/{html.escape(q)}.png' alt=''>"
                   if os.path.exists(os.path.join(d, "cells", sid, f"{q}.png")) else "")
            out.append({"student": sid, "question": q, "text": text, "img": img,
                        "conf": float(r.get("conf") or 0)})
    out.sort(key=lambda x: x["conf"])
    return out


@app.get("/job/<jid>/review")
def review(jid):
    st = _job(jid)
    return tpl.review(jid, _review_rows(jid), st["label"], request.args.get("saved") == "1")


@app.post("/job/<jid>/review")
def review_save(jid):
    st = _job(jid)
    d = os.path.join(WORK, jid, "run")
    ap, rv = os.path.join(d, "answers.csv"), os.path.join(d, "answers_review.csv")
    if not os.path.exists(ap):
        abort(404)
    with open(ap, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    qs, head = rows[0][1:], rows[0]
    data = {r[0]: dict(zip(qs, r[1:])) for r in rows[1:] if r}
    edited = set()
    for k, v in request.form.items():
        if not k.startswith("v::"):
            continue
        _, sid, q = k.split("::", 2)
        if sid in data and q in data[sid]:
            data[sid][q] = v.strip()
            edited.add((sid, q))
    with open(ap, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(head)
        for sid in [r[0] for r in rows[1:] if r]:
            wr.writerow([sid] + [data[sid].get(q, "") for q in qs])
    if os.path.exists(rv) and edited:
        with open(rv, encoding="utf-8-sig", newline="") as f:
            rr = list(csv.DictReader(f))
        keep = [r for r in rr if (r["student"], r["question"]) not in edited]
        with open(rv, "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=rr[0].keys() if rr else
                                ["student", "question", "text", "conf", "crop"])
            wr.writeheader()
            wr.writerows(keep)
    res = pipeline.score_only(ap, os.path.join(os.path.dirname(d), "key.csv"),
                              _seats_path(jid), d, log=lambda m: _log(jid, m))
    st["res"] = res
    st["n_review"] = _count_review(d)
    st["status"] = "done"
    return redirect(f"/job/{jid}/review?saved=1")


def _seats_path(jid):
    p = os.path.join(WORK, jid, "seats.csv")
    return p if os.path.exists(p) else None


@app.get("/health")
def health():
    return jsonify({"ok": True, "jobs": len(JOBS), "work": WORK})


def main(argv=None):
    ap = argparse.ArgumentParser(description="argmatch の Web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--work", default=None, help="解析結果の保存先（既定: ./web_runs）")
    a = ap.parse_args(argv)
    global WORK
    if a.work:
        WORK = os.path.abspath(a.work)
    os.makedirs(WORK, exist_ok=True)
    print(f"http://{a.host}:{a.port}  （保存先: {WORK}）")
    app.run(host=a.host, port=a.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
