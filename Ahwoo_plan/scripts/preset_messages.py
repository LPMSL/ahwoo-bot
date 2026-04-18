"""
preset_messages.py — 將 LINE OA 預設訊息 CSV 載入並提供模糊比對功能

使用方式：
    from preset_messages import load_preset_messages, match_reply

    presets = load_preset_messages()
    result = match_reply(some_text, presets)
    if result["matched"]:
        print(result["intent"], result["confidence"])

自我測試：
    python3 Ahwoo_plan/scripts/preset_messages.py --test
"""
from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# 預設 CSV 路徑
DEFAULT_PRESET_CSV = Path.home() / "Documents/projects/data/raw/LINE OA 預設訊息 - 預設訊息.csv"

# 預設訊息標題 → (gold_intent, gold_needs_human)
PRESET_INTENT_MAP: dict[str, tuple[str, bool]] = {
    "蛋糕表單":  ("pre_form_filled",       True),
    "外燴1":     ("request_form",           True),
    "外燴2":     ("request_form",           True),
    "報價":      ("price_inquiry",          False),
    "匯款":      ("payment_inquiry",        False),
    "自取":      ("delivery_inquiry",       False),
    "宅配":      ("delivery_inquiry",       False),
    "取貨時間":  ("delivery_inquiry",       False),
    "地址":      ("delivery_inquiry",       False),
    "遲到":      ("delivery_inquiry",       True),
    "宅配問題":  ("delivery_inquiry",       False),
    "日期接近":  ("availability_inquiry",   True),
    "複製設計":  ("customization_request",  False),
    "心得回饋":  ("acknowledgement",        False),
    "重複訊息":  ("unknown",                False),
    "公仔寄放":  ("customization_request",  True),
    "公仔代購":  ("customization_request",  True),
    "司機問題":  ("delivery_inquiry",       False),
}


def _normalize(text: str) -> str:
    """Unicode NFKC 正規化 + 壓縮空白"""
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", text)


def load_preset_messages(csv_path: Path = DEFAULT_PRESET_CSV) -> list[dict[str, Any]]:
    """
    讀取預設訊息 CSV，回傳清單，每筆包含：
        title, content, intent, needs_human, _norm_content
    """
    presets: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            title = (row.get("標題") or "").strip()
            content = (row.get("訊息") or "").strip()
            intent, needs_human = PRESET_INTENT_MAP.get(title, ("unknown", False))
            presets.append(
                {
                    "title":        title,
                    "content":      content,
                    "intent":       intent,
                    "needs_human":  needs_human,
                    "_norm":        _normalize(content),
                }
            )
    return presets


def match_reply(
    reply_text: str,
    presets: list[dict[str, Any]],
    threshold: float = 0.80,
) -> dict[str, Any]:
    """
    以預設訊息清單比對 observed_reply。

    回傳 dict：
        matched (bool), title (str), intent (str),
        needs_human (bool), confidence (float)

    比對策略：
    1. 精確子字串：reply 包含 content 或 content 包含 reply → confidence=1.0
    2. 正規化後 SequenceMatcher ratio → 取最高分
    任何分數 >= threshold 即視為命中。
    """
    if not reply_text:
        return _no_match()

    norm_reply = _normalize(reply_text)
    best_score = 0.0
    best_preset: dict[str, Any] | None = None

    for preset in presets:
        content = preset["content"]
        norm_content = preset["_norm"]

        # 精確子字串比對
        if content and (reply_text in content or content in reply_text):
            score = 1.0
        elif norm_content and (norm_reply in norm_content or norm_content in norm_reply):
            score = 1.0
        else:
            # 模糊比對（正規化後）
            score = SequenceMatcher(None, norm_reply, norm_content).ratio()

        if score > best_score:
            best_score = score
            best_preset = preset

    if best_score >= threshold and best_preset is not None:
        return {
            "matched":      True,
            "title":        best_preset["title"],
            "intent":       best_preset["intent"],
            "needs_human":  best_preset["needs_human"],
            "confidence":   round(best_score, 4),
        }
    return _no_match()


def _no_match() -> dict[str, Any]:
    return {
        "matched":     False,
        "title":       "",
        "intent":      "",
        "needs_human": False,
        "confidence":  0.0,
    }


# ── 自我測試 ────────────────────────────────────────────────────────────────

def _run_tests(presets: list[dict[str, Any]]) -> None:
    cases = [
        (
            "由於日期接近 為了可以儘快保留名額\r\n可以先填寫完整表單給我",
            "日期接近", "availability_inquiry", True,
        ),
        (
            "報價部分要麻煩填寫「完整訂單內容」後才會統一報價哦",
            "報價", "price_inquiry", False,
        ),
        (
            # 實際 annotation_queue 中的真實回覆格式（含 <MASKED> 個資遮蔽）
            "𝐚𝐡𝐰𝐨𝐨𝐝𝐞𝐬𝐬𝐞𝐫𝐭客製蛋糕表單🥞 — LINE名稱（非ID）：<MASKED> 取貨日期： 取貨地點（工作室/宅配確切地址）：<MASKED> 蛋糕口味、內餡（各擇1）： 蛋糕尺寸： 客製需求（請以詳細文字說明或附圖）： — 是否需要盤叉組(5人份/組)： 是否需要蠟燭(1支 工作室搭配)：",
            "蛋糕表單", "pre_form_filled", True,
        ),
        (
            "我想訂蛋糕",  # 不應匹配任何預設訊息
            None, None, None,
        ),
    ]

    passed = 0
    for text, exp_title, exp_intent, exp_nh in cases:
        result = match_reply(text, presets)
        if exp_title is None:
            ok = not result["matched"]
        else:
            ok = (
                result["matched"]
                and result["title"] == exp_title
                and result["intent"] == exp_intent
                and result["needs_human"] == exp_nh
            )
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        label = result["title"] if result["matched"] else "(no match)"
        print(f"  [{status}] '{text[:40]}...' → {label} (conf={result['confidence']:.2f})")

    print(f"\n{passed}/{len(cases)} tests passed")
    if passed < len(cases):
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="預設訊息比對工具")
    parser.add_argument("--test", action="store_true", help="執行自我測試")
    parser.add_argument(
        "--preset-csv",
        type=Path,
        default=DEFAULT_PRESET_CSV,
        help="預設訊息 CSV 路徑",
    )
    args = parser.parse_args()

    presets = load_preset_messages(args.preset_csv)
    print(f"已載入 {len(presets)} 筆預設訊息")

    if args.test:
        print("\n--- 執行自我測試 ---")
        _run_tests(presets)
    else:
        print("使用 --test 執行自我測試，或 import 此模組使用 match_reply()")


if __name__ == "__main__":
    main()
