"""
auto_label.py — 自動標注 annotation_queue.csv 的 gold_intent / gold_needs_human

兩層策略：
  Layer 1 (靜態)：比對 observed_reply 與官方預設訊息 → 免費，高信心
  Layer 2 (LLM) ：未命中的 → 呼叫 Claude Haiku 批次分類 user_message

使用方式：
  # 僅靜態層，不寫檔
  python3 auto_label.py --dry-run --skip-llm

  # 靜態 + LLM，寫回 CSV
  python3 auto_label.py

  # 覆寫已有標注
  python3 auto_label.py --overwrite
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path
from typing import Any

from preset_messages import (
    DEFAULT_PRESET_CSV,
    load_preset_messages,
    match_reply,
)

# ── 路徑預設值 ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path("/Users/linstev/Documents/projects/Ahwoo-project")
DEFAULT_CSV = (
    PROJECT_ROOT
    / "Ahwoo_plan"
    / "eval_datasets"
    / "raw_eval_slice2"
    / "annotation_queue.csv"
)

VALID_INTENTS = {
    "price_inquiry", "delivery_inquiry", "request_form", "pre_form_filled",
    "acknowledgement", "availability_inquiry", "customization_request",
    "payment_inquiry", "cancel_or_reschedule", "complaint", "greeting", "unknown",
}

LLM_MODEL = "claude-haiku-4-5-20251001"
LLM_BATCH_SIZE = 20


# ── LLM 分類 ─────────────────────────────────────────────────────────────────

def _build_llm_prompt(batch: list[dict[str, str]]) -> str:
    items = "\n".join(
        f'[{i}] user_message: {row["user_message"][:300]}\n'
        f'    observed_reply: {row["observed_reply"][:200]}'
        for i, row in enumerate(batch)
    )
    intents = " / ".join(sorted(VALID_INTENTS))
    return f"""你是一個 LINE OA 客服意圖分類器。以下是嗷嗚工作室（客製蛋糕）的顧客對話片段。
請為每一筆回傳 JSON 陣列，索引對應輸入順序。

意圖標籤說明：
- price_inquiry：詢問價格/報價
- delivery_inquiry：詢問宅配/取貨方式/時間/地址
- request_form：索取訂購表單
- pre_form_filled：顧客填回預約項目+日期（待確認檔期）
- acknowledgement：致謝/確認/結束語
- availability_inquiry：詢問日期名額/檔期
- customization_request：客製設計/特殊需求
- payment_inquiry：詢問付款方式/帳號
- cancel_or_reschedule：取消/改期
- complaint：抱怨/不滿
- greeting：打招呼
- unknown：無法判斷

needs_human：
- true：需要人工介入（如確認檔期、客製設計、收到表單、改期取消）
- false：可自動回覆

請輸出純 JSON 陣列（不要其他文字）：
[
  {{"intent": "...", "needs_human": true/false, "confidence": 0.0-1.0}},
  ...
]

對話片段：
{items}"""


async def _classify_batch_llm(batch: list[dict[str, str]]) -> list[dict[str, Any]]:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("請安裝 anthropic：pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("請設定環境變數 ANTHROPIC_API_KEY")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    prompt = _build_llm_prompt(batch)

    response = await client.messages.create(
        model=LLM_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    # 處理 ```json ... ``` 包裝
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    results = json.loads(raw)

    # 保護：確保長度吻合，intent 合法
    out: list[dict[str, Any]] = []
    for item in results[:len(batch)]:
        intent = item.get("intent", "unknown")
        if intent not in VALID_INTENTS:
            intent = "unknown"
        out.append(
            {
                "intent":      intent,
                "needs_human": bool(item.get("needs_human", True)),
                "confidence":  float(item.get("confidence", 0.7)),
            }
        )
    # 若回傳筆數不足，補 unknown
    while len(out) < len(batch):
        out.append({"intent": "unknown", "needs_human": True, "confidence": 0.0})
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────

async def run(
    csv_path: Path,
    preset_csv: Path,
    skip_llm: bool,
    dry_run: bool,
    overwrite: bool,
) -> None:
    presets = load_preset_messages(preset_csv)
    print(f"載入 {len(presets)} 筆預設訊息")

    # 驗證 preset CSV 與 knowledge_base.STATIC_REPLIES 的 intent key 集合是否一致
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "../../Ahwoo_chatbot"))
        from knowledge_base import STATIC_REPLIES as _STATIC_REPLIES
        _preset_intents = set(presets.keys())
        _static_intents = set(_STATIC_REPLIES.keys())
        if _preset_intents != _static_intents:
            print("[WARNING] preset CSV 與 STATIC_REPLIES 不一致:")
            if _preset_intents - _static_intents:
                print(f"  只在 CSV: {_preset_intents - _static_intents}")
            if _static_intents - _preset_intents:
                print(f"  只在 KB:  {_static_intents - _preset_intents}")
    except ImportError:
        pass

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    # 確保必要欄位存在
    for col in ("gold_intent", "gold_needs_human", "reviewer", "review_status"):
        if col not in fieldnames:
            fieldnames.append(col)

    static_labeled: list[int] = []
    llm_queue: list[tuple[int, dict[str, str]]] = []
    skipped: list[int] = []

    # Layer 1：靜態比對
    for idx, row in enumerate(rows):
        has_label = bool(row.get("gold_intent", "").strip())
        if has_label and not overwrite:
            skipped.append(idx)
            continue

        observed = row.get("observed_reply", "") or ""
        result = match_reply(observed, presets)

        if result["matched"]:
            row["gold_intent"]     = result["intent"]
            row["gold_needs_human"] = "true" if result["needs_human"] else "false"
            row["reviewer"]        = f"auto:static:{result['title']}(conf={result['confidence']:.2f})"
            row["review_status"]   = "needs_review"
            static_labeled.append(idx)
        else:
            llm_queue.append((idx, row))

    print(f"靜態層命中：{len(static_labeled)} 筆 | 待 LLM：{len(llm_queue)} 筆 | 已有標注跳過：{len(skipped)} 筆")

    # Layer 2：LLM 分類
    llm_labeled = 0
    if not skip_llm and llm_queue:
        print(f"開始 LLM 分類（批次大小 {LLM_BATCH_SIZE}）...")
        for batch_start in range(0, len(llm_queue), LLM_BATCH_SIZE):
            batch_items = llm_queue[batch_start : batch_start + LLM_BATCH_SIZE]
            batch_rows = [item[1] for item in batch_items]
            batch_idxs = [item[0] for item in batch_items]

            try:
                results = await _classify_batch_llm(batch_rows)
            except Exception as exc:
                print(f"  [LLM 批次 {batch_start}] 失敗：{exc}")
                continue

            for (idx, _), res in zip(batch_items, results):
                rows[idx]["gold_intent"]      = res["intent"]
                rows[idx]["gold_needs_human"] = "true" if res["needs_human"] else "false"
                rows[idx]["reviewer"]         = f"auto:llm(conf={res['confidence']:.2f})"
                rows[idx]["review_status"]    = "needs_review"
                llm_labeled += 1

            done = min(batch_start + LLM_BATCH_SIZE, len(llm_queue))
            print(f"  LLM 進度：{done}/{len(llm_queue)}")

    print(f"\n標注結果：靜態 {len(static_labeled)} + LLM {llm_labeled} = {len(static_labeled) + llm_labeled} 筆")
    print(f"未標注：{len(llm_queue) - llm_labeled} 筆（跳過 LLM 或失敗）")

    if dry_run:
        print("\n[dry-run] 未寫入檔案")
        # 印出前 10 筆靜態命中結果
        print("\n前 10 筆靜態命中預覽：")
        for idx in static_labeled[:10]:
            row = rows[idx]
            print(
                f"  [{row['case_id'][:50]}]"
                f" intent={row['gold_intent']}"
                f" nh={row['gold_needs_human']}"
                f" reviewer={row['reviewer']}"
            )
        return

    # 寫回 CSV
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n已寫入：{csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="自動標注 annotation_queue.csv")
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=DEFAULT_CSV,
        help="annotation_queue.csv 路徑",
    )
    parser.add_argument(
        "--preset-csv",
        type=Path,
        default=DEFAULT_PRESET_CSV,
        help="預設訊息 CSV 路徑",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="跳過 LLM 層，只做靜態比對",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只顯示結果，不寫回 CSV",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆寫已有 gold_intent 的行",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            csv_path=args.csv_path,
            preset_csv=args.preset_csv,
            skip_llm=args.skip_llm,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
        )
    )


if __name__ == "__main__":
    main()
