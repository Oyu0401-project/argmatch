#!/usr/bin/env python3
"""答案比較の指標（正規化・同値判定・希少度・ペア指標）。

answer_match.py から import して使う。単体では動かない。
"""

import math
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

BLANK = {"", "-", "--", "―", "ー", "×", "x", "n/a", "na", "無解答", "未解答", "?", "？", "…"}
NEAR = 0.8  # これ以上の文字類似は部分一致(0.5点)


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def normalize(raw):
    """表記ゆれを潰す: 全角/半角・空白・句読点・大文字小文字。"""
    s = nfkc(raw).replace("\u3000", " ")
    s = "".join(ch for ch in s if not ch.isspace())
    for a in ("。", "、", "・", "「", "」", "（", "）", "(", ")"):
        s = s.replace(a, "")
    s = s.replace("，", ",").replace("．", ".")
    s = s.lower()
    return "" if s in BLANK else s


def _looks_like_math(s):
    if not s or len(s) > 40:
        return False
    if any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in s):
        return False
    return any(ch.isdigit() for ch in s) or "x" in s or "y" in s or "=" in s


_CANON = {}


def canon(s):
    """式として解釈できれば sympy の式に（方程式は左辺−右辺）、できなければ None。"""
    if s in _CANON:
        return _CANON[s]
    expr = None
    if _looks_like_math(s):
        try:
            from sympy import Eq
            from sympy.parsing.sympy_parser import (
                parse_expr, standard_transformations, implicit_multiplication_application)
            t = (s.replace("×", "*").replace("÷", "/").replace("−", "-").replace("＝", "=")
                  .replace("^", "**").replace("²", "**2").replace("／", "/"))
            tr = standard_transformations + (implicit_multiplication_application,)
            if "=" in t:
                l, r = t.split("=", 1)
                expr = parse_expr(l, transformations=tr, evaluate=True) - \
                       parse_expr(r, transformations=tr, evaluate=True)
                # 「x=3」と「3=x」を同じにする（左辺−右辺の符号の曖昧さを除く）
                try:
                    from sympy import Poly
                    poly = Poly(expr)
                    if poly.LC() < 0:
                        expr = -expr
                except Exception:
                    pass
            else:
                expr = parse_expr(t, transformations=tr, evaluate=True)
        except Exception:
            expr = None
    _CANON[s] = expr
    return expr


_SAME = {}


def same_answer(a, b):
    """1.0=同値, 0.5=表記ゆれ/近似, 0.0=別解。

    両方とも式として読める場合は「同値か別解か」を厳密に判定する（部分点なし）。
    片方でも読めない（手書きの崩れ等）ときだけ文字類似で 0.5 を与える。
    判定は高コストなので解答ペア単位でキャッシュする。
    """
    if a == b:
        return 0.0 if a == "" else 1.0
    if not a or not b:
        return 0.0
    key = (a, b) if a <= b else (b, a)
    hit = _SAME.get(key)
    if hit is not None:
        return hit

    ea, eb = canon(a), canon(b)
    if ea is not None and eb is not None:
        try:
            from sympy import simplify
            val = 1.0 if (ea == eb or simplify(ea - eb) == 0) else 0.0
        except Exception:
            val = 0.0
    else:
        val = 0.5 if SequenceMatcher(None, a, b).ratio() >= NEAR else 0.0
    _SAME[key] = val
    return val


def build_weights(answers, keys):
    """設問×解答の希少度 w と、その解答が集団で出る確率 freq。

    w     : 重み付き一致率に使う希少度 ln((N+2)/(出現数+1))
    freq  : 証拠量 llr に使う出現率。-log(freq) が「偶然一致する確率の逆数(bits)」。
    """
    n = len(answers)
    w, freq = {}, {}
    for qi in range(len(keys)):
        cnt = Counter(v[qi] for v in answers.values() if v[qi] != "")
        for ans, c in cnt.items():
            w[(qi, ans)] = max(0.0, math.log((n + 2) / (c + 1)))
            freq[(qi, ans)] = max(c / n, 0.5 / n)
        w[(qi, "")] = 0.0
        freq[(qi, "")] = 1.0
    return w, freq


def pair_metrics(a, b, keys, w, freq):
    """1ペア分の指標。a,b は正規化済み解答リスト。"""
    num = den = err_num = err_den = 0.0
    same = answered = shared_wrong = rare = 0
    llr = 0.0
    for qi, key in enumerate(keys):
        x, y = a[qi], b[qi]
        if x == "" and y == "":
            continue
        answered += 1
        wi = max(w[(qi, x)], w[(qi, y)])
        m = same_answer(x, y)
        num += wi * m
        den += wi
        if m == 1.0:
            same += 1
            if x != "":
                llr += -math.log(freq[(qi, x)])
        both_wrong = same_answer(x, key) != 1.0 and same_answer(y, key) != 1.0
        if both_wrong and x != "" and y != "":
            err_den += wi
            if m == 1.0:
                err_num += wi
                shared_wrong += 1
                if wi >= 1.0:
                    rare += 1
    return {
        "score": num / den if den else 0.0,
        "llr": llr,
        "raw": same / answered if answered else 0.0,
        "err_concord": err_num / err_den if err_den else 0.0,
        "shared_wrong": shared_wrong,
        "shared_wrong_rare": rare,
        "common": answered,
    }


def ability(sheet, keys):
    vals = [same_answer(a, k) for a, k in zip(sheet, keys) if a != ""]
    return sum(vals) / len(vals) if vals else 0.0
