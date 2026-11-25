"""Web UI（Flask）の配線テスト。ジョブ実行そのものは test_engine 側で担保する。"""

import csv

import pytest

import webapp


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "WORK", str(tmp_path / "work"))
    webapp.app.config.update(TESTING=True)
    return webapp.app.test_client()


def test_home_and_health(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "答案一致率" in home.get_data(as_text=True)
    assert client.get("/health").json["ok"] is True


def test_run_rejects_missing_files(client):
    r = client.post("/run", data={})
    assert r.status_code == 400
    assert "正答CSV" in r.get_data(as_text=True)


def test_bad_grid_rejected(client, tmp_path):
    key = tmp_path / "key.csv"
    key.write_text("question,answer\nQ1,1\n", encoding="utf-8")
    r = client.post("/run", data={
        "scans": (open(key, "rb"), "x.png"), "key": (open(key, "rb"), "key.csv"),
        "grid": "4*8"}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_job_page_and_404(client):
    assert client.get("/job/" + "0" * 12).status_code == 404
    jid = "a" * 12
    webapp.JOBS[jid] = {"id": jid, "label": "テスト", "status": "done", "log": [], "t0": 0}
    r = client.get(f"/job/{jid}")
    assert r.status_code == 200 and "テスト" in r.get_data(as_text=True)
    webapp.JOBS.pop(jid)


def test_review_save_rewrites_answers(client, tmp_path):
    jid = "b" * 12
    d = tmp_path / "work" / jid
    run = d / "run"
    (run / "cells").mkdir(parents=True)
    (run / "answers.csv").write_text(
        "student,Q1,Q2,Q3\nS01,1,2,3\nS02,1,3,3\nS03,2,2,1\n", encoding="utf-8-sig")
    (run / "answers_review.csv").write_text(
        "student,question,text,conf,crop\nS01,Q2,2,0.4,\n", encoding="utf-8-sig")
    (d / "key.csv").write_text("question,answer\nQ1,1\nQ2,2\nQ3,3\n", encoding="utf-8")
    webapp.JOBS[jid] = {"id": jid, "label": "t", "status": "done", "log": [], "t0": 0}

    r = client.post(f"/job/{jid}/review", data={"v::S01::Q2": "9"})
    assert r.status_code == 302

    rows = list(csv.reader(open(run / "answers.csv", encoding="utf-8-sig")))
    assert rows[1][2] == "9"
    left = list(csv.DictReader(open(run / "answers_review.csv", encoding="utf-8-sig")))
    assert all(r["student"] != "S01" for r in left)      # 確認済みはキューから外れる
    assert webapp.JOBS[jid]["status"] == "done"
    webapp.JOBS.pop(jid)


def test_cell_image_rejects_traversal(client, tmp_path):
    jid = "c" * 12
    webapp.JOBS[jid] = {"id": jid, "label": "t", "status": "done", "log": [], "t0": 0}
    assert client.get(f"/job/{jid}/cell/..%2F..%2Fetc/passwd.png").status_code == 404
    webapp.JOBS.pop(jid)
