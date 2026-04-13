#!/usr/bin/env python3
"""
annotate.py — 互動式標注工具
逐筆顯示 annotation_queue.csv 中的 pending 案例，讓標注者填入 gold_intent / gold_needs_human
進度自動存檔，可中途離開再繼續。

用法：
    python3 Ahwoo_plan/scripts/annotate.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

QUEUE_PATH = Path(__file__).parent.parent / "eval_datasets" / "raw_eval" / "annotation_queue.csv"

# 所有合法意圖（縮寫 → 完整）
INTENT_MAP = {
    "1":  "price_inquiry",
    "2":  "request_form",
    "3":  "delivery_inquiry",
    "4":  "date_inquiry",
    "5":  "catering_inquiry",
    "6":  "pickup_location",
    "7":  "pickup_time",
    "8":  "payment_inquiry",
    "9":  "flavor_inquiry",
    "10": "size_inquiry",
    "11": "addons_inquiry",
    "12": "greeting",
    "13": "acknowledgement",
    "14": "pre_form_filled",
    "15": "form_submitted",
    "16": "payment_received",
    "17": "custom_design",
    "18": "change_reschedule",
    "19": "complaint",
    "20": "other",
}

INTENT_DISPLAY = {
    "1":  "price_inquiry       詢問價格",
    "2":  "request_form        索取表單",
    "3":  "delivery_inquiry    詢問宅配",
    "4":  "date_inquiry        詢問檔期",
    "5":  "catering_inquiry    詢問外燴",
    "6":  "pickup_location     詢問取貨地址",
    "7":  "pickup_time         詢問取貨時段",
    "8":  "payment_inquiry     詢問付款方式",
    "9":  "flavor_inquiry      詢問口味",
    "10": "size_inquiry        詢問尺寸",
    "11": "addons_inquiry      詢問加購配件",
    "12": "greeting            一般問候",
    "13": "acknowledgement     致謝/確認結束",
    "14": "pre_form_filled     顧客填回預篩選",
    "15": "form_submitted      顧客填完整表單",
    "16": "payment_received    顧客回報付款",
    "17": "custom_design       客製設計需求",
    "18": "change_reschedule   改期/取消",
    "19": "complaint           抱怨/不滿",
    "20": "other               其他",
}

# 需要人工介入的意圖（gold_needs_human 自動設為 true）
NEEDS_HUMAN_INTENTS = {
    "pre_form_filled", "form_submitted", "payment_received",
    "custom_design", "change_reschedule", "complaint", "other",
}


def print_legend():
    print("\n" + "=" * 60)
    print("意圖代號表（輸入數字）：")
    for k, v in INTENT_DISPLAY.items():
        print(f"  [{k:>2}] {v}")
    print()
    print("  [s]  skip（跳過此筆，稍後再標）")
    print("  [q]  quit（存檔並離開）")
    print("  [?]  再次顯示代號表")
    print("=" * 60)


def load_rows() -> list[dict]:
    with open(QUEUE_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list[dict]):
    fieldnames = list(rows[0].keys())
    with open(QUEUE_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def annotate():
    rows = load_rows()
    pending = [r for r in rows if r["review_status"] == "pending"]
    total_pending = len(pending)

    if total_pending == 0:
        print("✅ 所有案例已標注完畢！")
        return

    print(f"\n🐺 嗷嗚工作室 — 意圖標注工具")
    print(f"待標注：{total_pending} 筆（共 {len(rows)} 筆）")
    print_legend()

    done_this_session = 0

    for i, row in enumerate(rows):
        if row["review_status"] != "pending":
            continue

        progress = f"[{done_this_session + 1}/{total_pending}]"
        print(f"\n{progress} ─────────────────────────────────────")
        print(f"顧客訊息：\n  {row['user_message']}")
        print(f"\nBot 回覆：\n  {row['observed_reply'][:200]}")
        print()

        while True:
            raw = input("gold_intent（輸入數字/s/q/?）: ").strip().lower()

            if raw == "q":
                save_rows(rows)
                print(f"\n✅ 已存檔。本次標注 {done_this_session} 筆，剩餘 {total_pending - done_this_session} 筆。")
                sys.exit(0)

            elif raw == "s":
                print("  → 跳過")
                break

            elif raw == "?":
                print_legend()
                continue

            elif raw in INTENT_MAP:
                intent = INTENT_MAP[raw]
                needs_human = intent in NEEDS_HUMAN_INTENTS
                notes = ""

                # 可選：填備註
                notes_raw = input(f"  gold_reply_notes（可空白直接 Enter）: ").strip()
                if notes_raw:
                    notes = notes_raw

                # 更新 row（in-place，因為 rows list 持有同一個 dict）
                row["gold_intent"] = intent
                row["gold_needs_human"] = str(needs_human).lower()
                row["gold_reply_notes"] = notes
                row["review_status"] = "reviewed"
                row["reviewer"] = "stev"

                save_rows(rows)
                done_this_session += 1
                print(f"  ✓ {intent}  needs_human={needs_human}")
                break

            else:
                print(f"  ⚠️  無效輸入，請輸入 1–20 的數字、s、q 或 ?")

    save_rows(rows)
    print(f"\n🎉 全部 {total_pending} 筆標注完成！")


if __name__ == "__main__":
    annotate()
