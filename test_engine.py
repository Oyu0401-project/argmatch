"""エンジンの回帰テスト（合成データで「仕込みペアを検出・誤検知0」）。"""

import csv

import pytest

import demo_generate
import answer_match as am


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    demo_generate.main(str(d))
    return d


@pytest.fixture(scope="module")
def demo_result(demo_dir):
    return am.run(str(demo_dir / "answers.csv"), str(demo_dir / "key.csv"),
                  str(demo_dir / "seats.csv"), perms=100)


def test_planted_pairs_are_flagged(demo_result):
    flagged = {(p["a"], p["b"]) for p in demo_result["pairs"] if p["flag"]}
    assert flagged == {("S03", "S07"), ("S18", "S21")}


def test_agreement_without_error_overlap_never_flags(demo_result):
    """誤答が重なっていないペアは、一致率が高くても証拠にしない（できる生徒同士の罠）。"""
    clean = [p for p in demo_result["pairs"] if p["shared_wrong_rare"] == 0]
    assert clean, "比較対象がありません"
    assert all(not p["flag"] for p in clean)
    assert max(p["score"] for p in clean) > 0.3      # 一致率だけなら高いペアが存在する


def test_flagged_pairs_have_evidence(demo_result):
    for p in demo_result["pairs"]:
        if p["flag"]:
            assert p["shared_wrong_rare"] >= 3
            assert p["err_concord"] >= 0.5
            assert p["q"] <= 0.05
            assert p["z_llr"] >= 3


def test_scores_are_symmetric(demo_result):
    by_pair = {(p["a"], p["b"]): p for p in demo_result["pairs"]}
    assert len({(p["a"], p["b"]) for p in demo_result["pairs"]}) == len(demo_result["pairs"])
    assert all(p["a"] < p["b"] for p in demo_result["pairs"])
    assert ("S03", "S07") in by_pair


def test_duplicate_student_id_rejected(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("student,Q1,Q2,Q3\nS01,1,2,3\nS01,1,2,3\nS02,1,2,4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="重複"):
        am.read_answers(str(p))


def test_too_few_students_rejected(tmp_path):
    a = tmp_path / "a.csv"
    a.write_text("student,Q1,Q2,Q3\nS01,1,2,3\nS02,1,2,4\n", encoding="utf-8")
    k = tmp_path / "k.csv"
    k.write_text("question,answer\nQ1,1\nQ2,2\nQ3,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="3名以上"):
        am.run(str(a), str(k), perms=10)


def test_empty_key_rejected(tmp_path):
    a = tmp_path / "a.csv"
    a.write_text("student,Q1,Q2,Q3\nS01,1,2,3\nS02,1,2,4\nS03,1,2,5\n", encoding="utf-8")
    k = tmp_path / "k.csv"
    k.write_text("question,answer\nQ1,\nQ2,\nQ3,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="key.csv"):
        am.run(str(a), str(k), perms=10)


def test_write_csv_roundtrip(demo_result, tmp_path):
    am.write_csv(demo_result, str(tmp_path))
    rows = list(csv.DictReader(open(tmp_path / "pairs.csv", encoding="utf-8-sig")))
    assert len(rows) == len(demo_result["pairs"])
    assert {"score", "llr", "err_concord", "q", "flag"} <= set(rows[0])
    mat = list(csv.reader(open(tmp_path / "matrix.csv", encoding="utf-8-sig")))
    assert len(mat) == len(demo_result["ids"]) + 1


def test_pipeline_from_existing_answers(demo_dir, tmp_path):
    """OCRを飛ばす経路でも、レポートと確認ページまで出る。"""
    from pipeline import run_pipeline
    out = tmp_path / "run"
    res = run_pipeline(str(demo_dir / "answers.csv"), str(demo_dir / "key.csv"),
                       str(demo_dir / "seats.csv"), out=str(out),
                       answers=str(demo_dir / "answers.csv"), perms=50)
    assert len(res["pairs"]) == len(res["ids"]) * (len(res["ids"]) - 1) // 2
    assert (out / "report.html").exists() and (out / "review.html").exists()
    assert (out / "pairs.csv").exists() and (out / "summary.json").exists()


def test_cli_defaults():
    from cli import build_parser
    ns = build_parser().parse_args(["run", "--scans", "s", "--key", "k"])
    assert ns.engine == "tesseract+vlm" and ns.mode == "text" and ns.perms == 300
