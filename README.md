# 答案一致率チェッカー

手書き答案をスキャンし、**「写した可能性がある答案」と「写された可能性がある答案」の解答一致率**を、
偶然一致を割り引いた統計量で算出する。出力は調査対象の順位と根拠であり、判定ではない。

## できること

- スキャン画像 → 設問ごとの解答データ（マーカー4点で位置補正、セル単位OCR）
- 全ペアの一致率・**証拠量**（偶然その解答が一致する確率の逆数）・誤答一致率
- 偶然水準を設問ごとの列シャッフルで校正し、BH法で多重比較を補正
- 単体で開けるレポート（ヒートマップ＋根拠表＋設問の健全性）
- 低信頼セルの確認ページ（切り抜き画像つき、直したCSVをコピーできる）

## セットアップ

```bash
pip install -r requirements.txt
sudo apt-get install -y tesseract-ocr tesseract-ocr-jpn poppler-utils
```

`--engine tesseract+vlm`（推奨）を使う場合のみ `gsk`（Genspark CLI）が必要。
無い場合は `--engine tesseract` で動く（手書きの精度は落ちる）。

## インストール

```bash
pipx install .            # または pip install -e .
./bin/argmatch --version  # インストールせずに使う場合
```

## 使い方

```bash
argmatch selftest        # この環境で動くか確認（9項目・約10秒）
argmatch run --scans scans/ --key key.csv --seats seats.csv --out run/
```

| コマンド | 用途 |
|---|---|
| `argmatch run` | スキャン→OCR→判定→レポート（1コマンド） |
| `argmatch score` | answers.csv から判定だけ（速い） |
| `argmatch template` | 答案1枚からテンプレート作成 |
| `argmatch ocr` | スキャン画像を解答データに |
| `argmatch demo` | 合成データで一通り動かす |
| `argmatch selftest` | 依存とロジックの自己診断 |

## ブラウザで使う

```bash
pip install "argmatch[web]"      # または pip install flask
argmatch web --port 5000         # → http://127.0.0.1:5000
```

アップロード → 解析 → 要確認ペア → 読み取り修正（その場で再計算）までブラウザで完結する。
答案はローカルで処理され、外部に出るのは `--engine vlm` 系を選んだときのセル画像だけ。

出力は `run/report.html`（判定・まずこれを開く）、`run/review.html`（読み取り確認）、
`run/answers.csv`（手で直せる）、`run/pairs.csv`（全ペアの指標）。
マーク式は `--mode omr --choices 4`（黒画素率で判定、OCR不要）。
スクリプトを直接叩いてもよい（`python3 pipeline.py ...`）。

## 判定の読み方

| 指標 | 意味 |
|---|---|
| `score` | 希少度で重み付けした一致率（0〜1） |
| `llr` | 証拠量（bits）。30b超は偶然ではほぼ説明できない |
| `err_concord` | 両者誤答のうち同一解答だった割合 |
| `q` | BH法によるFDR調整後p値。0.05以下で「偶然ではない」 |
| `flag` | 上記＋希少な誤答一致3問以上を満たす「要確認」 |

`flag` は**調査対象**。原本の目視 → 席・提出順 → 聞き取り（複数で）の順に進める。

## テスト

```bash
argmatch selftest               # 依存＋ロジック＋OCRの自己診断（9項目）
python3 -m pytest tests -q      # 36件 / 約3秒
```

合成データで「仕込みペア2組を検出し、正答だけが一致するペア（誤検知の罠）を除外する」ことを回帰テストにしている。

## 構成

| ファイル | 役割 |
|---|---|
| `pipeline.py` | 1コマンド実行（OCR→検定→レポート→確認ページ） |
| `ocr_cells.py` | マーカー補正・セル切出・OCR・マーク式判定 |
| `metrics.py` | 正規化・数式同値判定・希少度・ペア指標 |
| `answer_match.py` | 帰無分布・FDR・証拠ゲート・CLI |
| `report.py` | HTMLレポート |
| `demo_generate.py` / `demo_scans.py` | 合成データ／合成スキャン画像の生成 |
| `SPEC.md` | エンジニア向け仕様書 |

## 限界

- どちらが写したかは決まらない（一致率は対称）。方向は席・提出順・聞き取りで決める。
- 4択だけの短いテストは誤答がぶつかりやすく、原理的に検出力が低い。
- 手書き日本語・数式は VLM の方が強い。tesseract 単体では誤読が増える。
- **OCRが全員を同じ誤答に変換すると一致が水増しされる**。頻出解答は重みが0になる設計で無効化しているが、
  レポートの「設問の健全性」で必ず確認する。
- 使う前に、不正の無かった過去回で誤検知率を校正する。
