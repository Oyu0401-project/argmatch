"""OCR前処理（マーカー検出・セル切出・マーク式判定）のテスト。"""

import json

import cv2
import numpy as np
import pytest

import ocr_cells as oc


def make_sheet(path, answers=None):
    """マーカー4点＋格子の答案画像を作る（ページ座標に PAD を足すだけ）。"""
    pw, ph, pad = oc.PAGE[0], oc.PAGE[1], 40
    img = np.full((ph + 2 * pad, pw + 2 * pad, 3), 255, np.uint8)
    for cx, cy in [(pad, pad), (pw + pad, pad), (pw + pad, ph + pad), (pad, ph + pad)]:
        cv2.rectangle(img, (cx - 26, cy - 26), (cx + 26, cy + 26), (0, 0, 0), -1)
    if answers:
        x0, y0 = 120, 260
        cw, ch = (pw - 240) / 8, (ph - 420) / 4
        for i, v in enumerate(answers):
            r, c = divmod(i, 8)
            cv2.putText(img, v, (int(x0 + c * cw) + pad + 30, int(y0 + (r + 1) * ch) + pad - 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.7, (30, 30, 110), 3, cv2.LINE_AA)
    cv2.imwrite(str(path), img)
    return path


def test_markers_and_template(tmp_path):
    sheet = make_sheet(tmp_path / "s.png", ["1", "2"])
    tpl_path = tmp_path / "t.json"
    oc.make_template(str(sheet), "4x8", str(tpl_path))
    tpl = json.load(open(tpl_path, encoding="utf-8"))
    assert len(tpl["cells"]) == 32
    assert tpl["cells"][0]["q"] == "Q1"
    warped = cv2.imread(str(tmp_path / "t_warped.png"))
    assert warped.shape[1] == oc.PAGE[0] and warped.shape[0] == oc.PAGE[1]


def test_pdf_without_poppler_message(tmp_path, monkeypatch):
    monkeypatch.setattr(oc.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="poppler"):
        oc.pdf_to_png(str(tmp_path / "x.pdf"), 300)


def test_missing_markers_raises(tmp_path):
    blank = np.full((600, 400, 3), 255, np.uint8)
    cv2.imwrite(str(tmp_path / "b.png"), blank)
    with pytest.raises(RuntimeError, match="マーカー"):
        oc.normalize_page(str(tmp_path / "b.png"))


@pytest.mark.parametrize("marked,expect", [(0, "1"), (2, "3"), (3, "4")])
def test_omr_choice(marked, expect):
    crop = np.full((240, 120, 3), 255, np.uint8)
    band = 240 // 4
    cv2.rectangle(crop, (30, marked * band + 12), (90, (marked + 1) * band - 12), (0, 0, 0), -1)
    text, conf = oc.omr_choice(crop, 4)
    assert text == expect and conf > 0.5


def test_omr_blank_and_double():
    blank = np.full((240, 120, 3), 255, np.uint8)
    assert oc.omr_choice(blank, 4)[0] == ""
    double = blank.copy()
    cv2.rectangle(double, (30, 12), (90, 48), (0, 0, 0), -1)
    cv2.rectangle(double, (30, 72), (90, 108), (0, 0, 0), -1)
    text, conf = oc.omr_choice(double, 4)
    assert text != "" and conf < 0.5      # 二重マークは低信頼＝人要確認
