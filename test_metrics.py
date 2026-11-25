"""正規化・同値判定・統計ユーティリティの単体テスト。"""

import pytest

from metrics import normalize, same_answer, build_weights, pair_metrics
from answer_match import bh, robust_z


@pytest.mark.parametrize("raw,expect", [
    ("２ｘ＋３", "2x+3"),          # 全角英数
    (" 2 x + 3 ", "2x+3"),        # 空白
    ("－４", "-4"),                # 全角マイナス
    ("X=3", "x=3"),               # 大文字
    ("１２。", "12"),              # 句点
    ("ー", ""),                    # 長音だけ＝無解答扱い
    ("無解答", ""),
])
def test_normalize(raw, expect):
    assert normalize(raw) == expect


@pytest.mark.parametrize("a,b,expect", [
    ("2x+3", "3+2x", 1.0),        # 数式の同値（項の順序）
    ("1/2", "0.5", 1.0),          # 分数と小数
    ("2(x+1)", "2x+2", 1.0),      # 展開
    ("x=3", "x=-3", 0.0),         # 符号違いは別解
    ("", "5", 0.0),               # 無解答は一致にしない
    ("", "", 0.0),                # 両者無解答も一致にしない
    ("三角形", "三角形", 1.0),
])
def test_same_answer(a, b, expect):
    assert same_answer(a, b) == pytest.approx(expect)


def test_partial_match_is_half():
    """1文字違いの書き写し損ないは 0.5（score には効くが llr には効かない）。"""
    assert same_answer("y=2x-1", "y=2x-!") == 0.5


def test_weights_reward_rare_answers():
    answers = {f"S{i:02d}": ["2", "x"] for i in range(10)}
    answers["S00"] = ["2", "y"]     # 「y」は1人だけ＝珍しい
    keys = ["2", "x"]
    w, freq = build_weights(answers, keys)
    assert w[(1, "y")] > w[(1, "x")]
    assert freq[(1, "y")] < freq[(1, "x")]


def test_pair_metrics_detects_shared_wrong():
    keys = ["1", "2", "3", "4"]
    a = ["1", "2", "9", "8"]        # 2問誤答
    b = ["1", "2", "9", "8"]        # 完全一致
    c = ["1", "2", "9", "7"]        # 1問だけ一致
    w, freq = build_weights({"a": a, "b": b, "c": c, "d": keys}, keys)
    m = pair_metrics(a, b, keys, w, freq)
    assert m["shared_wrong"] == 2
    assert m["err_concord"] == pytest.approx(1.0)
    assert m["score"] == pytest.approx(1.0)
    assert pair_metrics(a, c, keys, w, freq)["shared_wrong"] == 1


def test_bh_matches_hand_calculation():
    p = [0.01, 0.04, 0.03, 0.2]
    q = bh(p)
    # 手計算: 0.01→0.04, 0.03→0.0533, 0.04→0.0533, 0.2→0.2
    assert q == pytest.approx([0.04, 0.0533, 0.0533, 0.2], abs=1e-4)
    assert all(q[i] <= 1.0 for i in range(len(q)))


def test_robust_z_ignores_outlier_scale():
    vals = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 5]
    assert robust_z(vals, 5) > 3
    assert abs(robust_z(vals, 1)) < 0.01
