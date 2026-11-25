#!/usr/bin/env python3
"""答案の一致率チェッカー — 手書き答案の解答一致から「写し」の候補ペアを統計的に絞る。

設計の芯:
  正答同士が一致するのは当たり前なので、生の一致率はほぼ使えない。効くのは
  「誤答が一致すること」で、しかも集団内で珍しい誤答ほど強い証拠になる。
    score      : 希少度で重み付けした一致率（部分一致0.5点）
    llr        : 証拠量。同一解答が偶然出る確率の逆数の対数和（bits）
    err_concord: 両者誤答のうち同一解答だった割合
  偶然水準は「設問ごとに解答を列シャッフルした世界」で校正する（条件付き検定）。
  これで実力の近い者同士が正答で揃う分を割り引ける。

使い方:
    python3 answer_match.py answers.csv --key key.csv --out out/
    python3 answer_match.py answers.csv --key key.csv --seats seats.csv --title "1年2組 小テスト5"

入力:
    answers.csv : 1列目=生徒ID、以降=設問ごとの解答（ヘッダは設問名）
    key.csv     : question,answer の2列（または answers.csv と同じ設問順の1行）
    seats.csv   : student,row,col（任意。隣接ペアに印を付けるだけ）

出力:
    pairs.csv / matrix.csv / summary.json / report.html

注意:
  一致率は「調査の入口」であって判定ではない。最終判断は原本確認と聞き取りで行う。
"""

import argparse
import bisect
import csv
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict

from metrics import ability, build_weights, normalize, pair_metrics, same_answer


def read_answers(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    questions = [h.strip() for h in rows[0][1:]]
    sheets = {}
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        sid = r[0].strip()
        if sid in sheets:
            raise ValueError(f"生徒IDが重複しています: {sid}（answers.csv を確認してください）")
        vals = (r[1:] + [""] * len(questions))[:len(questions)]
        sheets[sid] = [normalize(v) for v in vals]
    return questions, sheets


def read_key(path, questions):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    head = [h.strip().lower() for h in rows[0]]
    if "question" in head and "answer" in head:
        qi, ai = head.index("question"), head.index("answer")
        m = {r[qi].strip(): normalize(r[ai]) for r in rows[1:] if len(r) > ai}
        return [m.get(q, "") for q in questions]
    vals = [normalize(x) for x in rows[0]] + [""] * len(questions)
    return vals[:len(questions)]


def read_seats(path):
    if not path:
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["student"].strip(): (float(r["row"]), float(r["col"])) for r in csv.DictReader(f)}


def shuffle_null(answers, ids, keys, w, freq, pair_index, perms, seed=7):
    """設問ごとに解答をシャッフルした世界で、各ペアの指標を作り直す。

    ペアを組み替える方式だと「本物のペア」が偶然再現されて基準を汚すため、
    列シャッフル（生徒間の独立性だけを壊す）で帰無分布を作る。
    """
    rnd = random.Random(seed)
    cols = [[answers[s][qi] for s in ids] for qi in range(len(keys))]
    null = {k: {"score": [], "llr": [], "swr": []} for k in pair_index}
    for _ in range(perms):
        perm = []
        for col in cols:
            c = col[:]
            rnd.shuffle(c)
            perm.append(c)
        sh = {s: [perm[qi][i] for qi in range(len(keys))] for i, s in enumerate(ids)}
        for (i, j) in pair_index:
            m = pair_metrics(sh[ids[i]], sh[ids[j]], keys, w, freq)
            null[(i, j)]["score"].append(m["score"])
            null[(i, j)]["llr"].append(m["llr"])
            null[(i, j)]["swr"].append(m["shared_wrong_rare"])
    return null


def _norm_tail(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def _z(obs, vals):
    n = len(vals)
    mu = sum(vals) / n
    sd = (sum((v - mu) ** 2 for v in vals) / (n - 1)) ** 0.5
    return (obs - mu) / sd if sd > 1e-9 else 0.0


def _emp_p(obs, vals):
    s = sorted(vals)
    return (1 + (len(s) - bisect.bisect_left(s, obs))) / (len(s) + 1)


def bh(pvals):
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        q[i] = prev
    return q


def robust_z(values, x):
    """中央値・MAD基準の外れ度。MADが0（値が固まっている）なら平均絶対偏差で代替。"""
    med = sorted(values)[len(values) // 2]
    dev = sorted(abs(v - med) for v in values)
    mad = dev[len(dev) // 2] * 1.4826
    if mad < 1e-9:
        mad = sum(dev) / len(dev) * 1.2533      # 平均絶対偏差をσ相当に換算
    if mad < 1e-9:
        return 0.0
    return (x - med) / mad


def validate(questions, answers, keys):
    """実データでよく落ちる穴を、統計に入る前に止める。"""
    if len(questions) < 3:
        raise ValueError(f"設問が {len(questions)} 問しかありません（3問以上必要）")
    if len(answers) < 3:
        raise ValueError(f"生徒が {len(answers)} 名しかいません（比較には3名以上必要）")
    if not any(keys):
        raise ValueError("key.csv の解答が空です（question,answer の2列か、設問順の1行か確認）")
    missing = [q for q, k in zip(questions, keys) if not k]
    if missing:
        print(f"注意: 正答が未設定の設問が {len(missing)} 問あります（{', '.join(missing[:5])}…）。"
              "誤答判定に使えないため、その設問は実質「一致の証拠」にしか寄与しません")
    blank = [s for s, v in answers.items() if not any(v)]
    if blank:
        print(f"注意: 全問空欄の答案が {len(blank)} 名います（未提出・読み取り失敗の可能性）: "
              f"{', '.join(blank[:5])}")


def run(answers_path, key_path, seats_path=None, perms=300, fdr=0.05, seed=7):
    if not os.path.exists(answers_path):
        raise FileNotFoundError(f"answers.csv が見つかりません: {answers_path}")
    questions, answers = read_answers(answers_path)
    keys = read_key(key_path, questions)
    validate(questions, answers, keys)
    seats = read_seats(seats_path)
    ids = list(answers)
    w, freq = build_weights(answers, keys)
    ab = {s: ability(answers[s], keys) for s in ids}

    index = [(i, j) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    null = shuffle_null(answers, ids, keys, w, freq, index, perms, seed)

    pairs = []
    for (i, j) in index:
        s, t = ids[i], ids[j]
        m = pair_metrics(answers[s], answers[t], keys, w, freq)
        nv = null[(i, j)]
        z_llr = _z(m["llr"], nv["llr"])
        z_score = _z(m["score"], nv["score"])
        p = min(1.0, 2 * min(_norm_tail(z_llr), _norm_tail(z_score)))  # 2統計の補正
        adj = 0
        if s in seats and t in seats:
            d = abs(seats[s][0] - seats[t][0]) + abs(seats[s][1] - seats[t][1])
            adj = 1 if d <= 1 else 0
        pairs.append({"a": s, "b": t, "adjacent": adj, "p": p, "z_llr": z_llr,
                      "p_emp": _emp_p(m["llr"], nv["llr"]),
                      "null_mean": sum(nv["llr"]) / len(nv["llr"]),
                      "ability_gap": abs(ab[s] - ab[t]), **m})

    peers = defaultdict(list)
    for pr in pairs:
        peers[pr["a"]].append(pr["score"])
        peers[pr["b"]].append(pr["score"])
    for pr, q in zip(pairs, bh([x["p"] for x in pairs])):
        pr["q"] = q
        pr["z"] = min(robust_z(peers[pr["a"]], pr["score"]),
                      robust_z(peers[pr["b"]], pr["score"]))
        # 証拠ゲート: 「珍しい誤答の一致」が十分にあること。正答だけの一致は証拠にしない。
        pr["flag"] = bool(q <= fdr and pr["z_llr"] >= 3.0 and pr["z"] >= 2.0
                          and pr["shared_wrong_rare"] >= 3 and pr["err_concord"] >= 0.5
                          and pr["score"] >= 0.55)

    quality = []
    for qi, key in enumerate(keys):
        vals = [answers[s][qi] for s in ids if answers[s][qi] != ""]
        n_ans = len(vals)
        corr = sum(1 for v in vals if same_answer(v, key) == 1.0)
        cnt = Counter(vals)
        top, topc = cnt.most_common(1)[0] if cnt else ("", 0)
        share = topc / n_ans if n_ans else 0.0
        note = ""
        if n_ans and key and top != key and share >= 0.5 and n_ans >= 5:
            note = "誤答が半数以上（OCR誤読か正答設定の誤りの疑い）"
        elif n_ans < len(ids) * 0.5:
            note = "解答者が半分未満（未解答・読み取り失敗の疑い）"
        quality.append({"q": questions[qi], "answered": n_ans,
                        "correct_rate": corr / n_ans if n_ans else 0.0,
                        "majority": top, "majority_share": share, "note": note})

    pairs.sort(key=lambda x: (x["q"], -x["llr"]))
    nulls = [v for k in null for v in null[k]["llr"]]
    mean = sum(nulls) / len(nulls)
    sd = (sum((v - mean) ** 2 for v in nulls) / (len(nulls) - 1)) ** 0.5
    return {"questions": questions, "keys": keys, "ids": ids, "answers": answers,
            "seats": seats, "pairs": pairs, "null_mean": mean, "null_sd": sd,
            "ability": ab, "permutations": perms, "quality": quality}


def write_csv(result, outdir):
    cols = ["a", "b", "score", "llr", "raw", "err_concord", "shared_wrong", "shared_wrong_rare",
            "common", "z", "z_llr", "p", "p_emp", "q", "adjacent", "flag"]
    with open(os.path.join(outdir, "pairs.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for pr in result["pairs"]:
            wr.writerow({k: (round(pr[k], 4) if isinstance(pr[k], float) else pr[k]) for k in cols})
    ids = result["ids"]
    mat = {(pr["a"], pr["b"]): pr["score"] for pr in result["pairs"]}
    with open(os.path.join(outdir, "matrix.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["student"] + ids)
        for s in ids:
            wr.writerow([s] + [1.0 if s == t else
                               round(mat.get((s, t)) or mat.get((t, s)) or 0.0, 3) for t in ids])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("answers")
    ap.add_argument("--key", required=True)
    ap.add_argument("--seats")
    ap.add_argument("--out", default="out")
    ap.add_argument("--permutations", type=int, default=300)
    ap.add_argument("--fdr", type=float, default=0.05)
    ap.add_argument("--title", default="答案 一致率レポート")
    args = ap.parse_args()

    try:
        res = run(args.answers, args.key, args.seats, args.permutations, args.fdr)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f"エラー: {e}")
    os.makedirs(args.out, exist_ok=True)
    write_csv(res, args.out)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in res.items() if k not in ("answers", "pairs")}, f,
                  ensure_ascii=False, indent=1, default=str)
    from report import render
    with open(os.path.join(args.out, "report.html"), "w", encoding="utf-8") as f:
        f.write(render(res, args.title))

    flagged = [p for p in res["pairs"] if p["flag"]]
    print(f"生徒 {len(res['ids'])} 名 / 設問 {len(res['questions'])} 問 / ペア {len(res['pairs'])} 組")
    print(f"偶然水準（証拠量の帰無分布）: {res['null_mean']:.1f} ± {res['null_sd']:.1f} bits")
    print(f"要確認ペア: {len(flagged)} 組")
    for pr in flagged[:10]:
        print(f"  {pr['a']:>6} × {pr['b']:<6} 一致率={pr['score']:.2f} 証拠={pr['llr']:.0f}b "
              f"誤答一致={pr['err_concord']:.2f}({pr['shared_wrong']}問/希少{pr['shared_wrong_rare']}) "
              f"q={pr['q']:.2e} z_llr={pr['z_llr']:.1f}" + (" [隣接]" if pr["adjacent"] else ""))
    warn = [x for x in res["quality"] if x["note"]]
    if warn:
        print(f"設問の注意: {len(warn)} 問（レポートの「設問の健全性」を確認）")
        for x in warn[:5]:
            print(f"  {x['q']}: 最多解答「{x['majority']}」が {x['majority_share'] * 100:.0f}% — {x['note']}")
    print(f"→ {os.path.join(args.out, 'report.html')}")


if __name__ == "__main__":
    main()
