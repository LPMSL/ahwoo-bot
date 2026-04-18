from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path.home() / "Documents/projects/Ahwoo-project"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Ahwoo_plan" / "eval_datasets"
DEFAULT_SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB", "LINE對話記錄")
DEFAULT_RAW_ROOT = Path.home() / "Documents/projects/data/raw/ahwoo_oa_chat_raw"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
RAW_EXPECTED_HEADER = ["傳送者類型", "傳送者名稱", "傳送日期", "傳送時間", "內容"]
RAW_MEDIA_MESSAGES = {"照片已傳送", "貼圖已傳送", "影片已傳送", "檔案已傳送"}

SHEET_HEADERS = {
    "時間戳記",
    "日期",
    "星期",
    "小時",
    "用戶ID",
    "顯示名稱",
    "用戶訊息",
    "意圖分類",
    "意圖說明",
    "自動回覆",
    "回覆內容",
    "需要人工",
    "優先等級",
    "判斷依據",
    "信心值",
    "對話輪數",
    "靜態回覆",
    "Telegram通知",
}

DATE_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S")
from privacy_utils import stable_alias, mask_message


@dataclass
class RowRecord:
    timestamp: datetime
    user_id: str
    display_name: str
    user_message: str
    intent: str
    intent_zh: str
    auto_reply: str
    needs_human: bool
    priority: str
    reason: str
    confidence: float
    total_turns: int
    used_static: bool


@dataclass
class RawMessage:
    sender_type: str
    sender_name: str
    timestamp: datetime
    content: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="從 Ahwoo LINE OA 對話紀錄建立匿名化評測資料集",
    )
    parser.add_argument(
        "--source",
        choices=("csv", "sheets", "raw-folder"),
        default="csv",
        help="資料來源，預設為 csv；也可直接讀 Google Sheets 或原始對話資料夾",
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="Google Sheets 匯出的 CSV 路徑",
    )
    parser.add_argument(
        "--sheet-id",
        default=os.getenv("GOOGLE_SHEET_ID"),
        help="Google Sheets 文件 ID，未指定時讀取環境變數 GOOGLE_SHEET_ID",
    )
    parser.add_argument(
        "--sheet-tab",
        default=DEFAULT_SHEET_TAB,
        help="Google Sheets 分頁名稱，預設讀 GOOGLE_SHEET_TAB 或 LINE對話記錄",
    )
    parser.add_argument(
        "--credentials-path",
        type=Path,
        default=Path(os.getenv("GOOGLE_CREDENTIALS_PATH", "Ahwoo_chatbot/credentials/google_service_account.json")),
        help="service account JSON 路徑",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="輸出資料夾，預設為 Ahwoo_plan/eval_datasets",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help="原始對話 CSV 資料夾路徑，給 --source raw-folder 使用",
    )
    parser.add_argument(
        "--single-per-intent",
        type=int,
        default=20,
        help="每個 intent 最多抽樣幾筆 single-turn case",
    )
    parser.add_argument(
        "--multi-per-intent",
        type=int,
        default=8,
        help="每個 intent 最多抽樣幾段 multi-turn case",
    )
    parser.add_argument(
        "--min-multi-turns",
        type=int,
        default=3,
        help="multi-turn case 至少要有幾輪 user→bot 紀錄",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="隨機抽樣 seed",
    )
    parser.add_argument(
        "--context-window",
        type=int,
        default=5,
        help="每個 single-turn 案例附帶的前 N 輪對話上下文（user+bot），預設 5",
    )
    return parser.parse_args()


def parse_bool(value: str) -> bool:
    return str(value).strip() in {"是", "TRUE", "True", "true", "1"}


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def parse_timestamp(raw: str) -> datetime | None:
    text = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def load_rows_from_csv(path: Path) -> list[RowRecord]:
    if not path.exists():
        raise FileNotFoundError(f"找不到輸入檔案: {path}")

    encodings = ("utf-8-sig", "utf-8", "cp950", "big5")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise ValueError("CSV 沒有標題列")
                missing = SHEET_HEADERS.difference(reader.fieldnames)
                if missing:
                    missing_text = ", ".join(sorted(missing))
                    raise ValueError(f"CSV 缺少欄位: {missing_text}")

                rows: list[RowRecord] = []
                for raw in reader:
                    timestamp = parse_timestamp(raw.get("時間戳記", ""))
                    if timestamp is None:
                        continue

                    user_id = (raw.get("用戶ID") or "").strip()
                    user_message = (raw.get("用戶訊息") or "").strip()
                    if not user_id or not user_message:
                        continue

                    rows.append(
                        RowRecord(
                            timestamp=timestamp,
                            user_id=user_id,
                            display_name=(raw.get("顯示名稱") or "").strip() or "顧客",
                            user_message=user_message,
                            intent=(raw.get("意圖分類") or "").strip() or "unknown",
                            intent_zh=(raw.get("意圖說明") or "").strip() or "未知",
                            auto_reply=(raw.get("回覆內容") or "").strip(),
                            needs_human=parse_bool(raw.get("需要人工", "")),
                            priority=(raw.get("優先等級") or "").strip() or "normal",
                            reason=(raw.get("判斷依據") or "").strip(),
                            confidence=parse_float(raw.get("信心值", ""), default=0.0),
                            total_turns=parse_int(raw.get("對話輪數", ""), default=0),
                            used_static=parse_bool(raw.get("靜態回覆", "")),
                        )
                    )
                return sorted(rows, key=lambda item: (item.user_id, item.timestamp))
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"讀取 CSV 失敗: {last_error}")


def parse_raw_timestamp(date_str: str, time_str: str) -> datetime | None:
    value = f"{date_str.strip()} {time_str.strip()}"
    try:
        return datetime.strptime(value, "%Y/%m/%d %H:%M:%S")
    except Exception:
        return None


def is_raw_media_message(text: str) -> bool:
    return (text or "").strip() in RAW_MEDIA_MESSAGES


def read_raw_csv_rows(path: Path) -> list[list[str]] | None:
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.reader(handle))
        except Exception:
            continue
    return None


def parse_raw_conversation(path: Path) -> tuple[str, str, list[RawMessage]]:
    rows = read_raw_csv_rows(path)
    if not rows or len(rows) < 5:
        return "", "", []
    header = rows[3]
    if header[:5] != RAW_EXPECTED_HEADER:
        return "", "", []

    user_id = path.stem.split("_", 1)[0]
    display_name = path.stem.rsplit("_", 1)[-1]
    messages: list[RawMessage] = []
    for raw_row in rows[4:]:
        if len(raw_row) < 5:
            continue
        sender_type, sender_name, send_date, send_time, content = raw_row[:5]
        sender_type = sender_type.strip()
        if sender_type not in {"Account", "User"}:
            continue
        timestamp = parse_raw_timestamp(send_date, send_time)
        if timestamp is None:
            continue
        message_text = (content or "").strip()
        if not message_text:
            continue
        messages.append(
            RawMessage(
                sender_type=sender_type,
                sender_name=sender_name.strip(),
                timestamp=timestamp,
                content=message_text,
            )
        )
        if sender_type == "User" and sender_name.strip():
            display_name = sender_name.strip()

    return user_id, display_name, sorted(messages, key=lambda item: item.timestamp)


def derive_rows_from_raw_folder(raw_root: Path) -> list[RowRecord]:
    if not raw_root.exists():
        raise FileNotFoundError(f"找不到原始資料夾: {raw_root}")

    rows: list[RowRecord] = []
    for csv_path in sorted(raw_root.glob("*.csv")):
        user_id, display_name, messages = parse_raw_conversation(csv_path)
        if not user_id or not messages:
            continue

        next_account_lookup: dict[int, str] = {}
        next_account_message: RawMessage | None = None
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.sender_type == "Account":
                next_account_message = message
            elif message.sender_type == "User":
                next_account_lookup[index] = next_account_message.content if next_account_message else ""

        turn_count = 0
        for index, message in enumerate(messages):
            if message.sender_type != "User" or is_raw_media_message(message.content):
                continue

            turn_count += 1
            auto_reply = next_account_lookup.get(index, "")
            rows.append(
                RowRecord(
                    timestamp=message.timestamp,
                    user_id=user_id,
                    display_name=display_name or "顧客",
                    user_message=message.content,
                    intent="unknown",
                    intent_zh="待標註",
                    auto_reply=auto_reply,
                    needs_human=False,
                    priority="unknown",
                    reason=f"raw_file:{csv_path.name}",
                    confidence=0.0,
                    total_turns=turn_count,
                    used_static=False,
                )
            )

    return sorted(rows, key=lambda item: (item.user_id, item.timestamp))


def build_credentials(credentials_path: Path):
    from google.oauth2.service_account import Credentials

    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        return Credentials.from_service_account_info(json.loads(credentials_json), scopes=SCOPES)
    if not credentials_path.exists():
        raise FileNotFoundError(f"找不到 credentials 檔案: {credentials_path}")
    return Credentials.from_service_account_file(credentials_path, scopes=SCOPES)


def load_rows_from_sheets(sheet_id: str, sheet_tab: str, credentials_path: Path) -> list[RowRecord]:
    import gspread

    if not sheet_id:
        raise ValueError("使用 --source sheets 時需要提供 --sheet-id 或設定 GOOGLE_SHEET_ID")

    creds = build_credentials(credentials_path)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(sheet_id).worksheet(sheet_tab)
    records = worksheet.get_all_records()

    rows: list[RowRecord] = []
    for raw in records:
        timestamp = parse_timestamp(str(raw.get("時間戳記", "")))
        if timestamp is None:
            continue

        user_id = str(raw.get("用戶ID", "")).strip()
        user_message = str(raw.get("用戶訊息", "")).strip()
        if not user_id or not user_message:
            continue

        rows.append(
            RowRecord(
                timestamp=timestamp,
                user_id=user_id,
                display_name=str(raw.get("顯示名稱", "")).strip() or "顧客",
                user_message=user_message,
                intent=str(raw.get("意圖分類", "")).strip() or "unknown",
                intent_zh=str(raw.get("意圖說明", "")).strip() or "未知",
                auto_reply=str(raw.get("回覆內容", "")).strip(),
                needs_human=parse_bool(str(raw.get("需要人工", ""))),
                priority=str(raw.get("優先等級", "")).strip() or "normal",
                reason=str(raw.get("判斷依據", "")).strip(),
                confidence=parse_float(str(raw.get("信心值", "")), default=0.0),
                total_turns=parse_int(str(raw.get("對話輪數", "")), default=0),
                used_static=parse_bool(str(raw.get("靜態回覆", ""))),
            )
        )

    return sorted(rows, key=lambda item: (item.user_id, item.timestamp))




def anonymize_row(row: RowRecord) -> dict[str, Any]:
    user_alias = stable_alias("user", row.user_id)
    conversation_alias = stable_alias("conv", row.user_id)
    display_alias = stable_alias("name", row.display_name)
    return {
        "conversation_id": conversation_alias,
        "user_alias": user_alias,
        "display_name_alias": display_alias,
        "timestamp": row.timestamp.isoformat(sep=" "),
        "user_message": mask_message(row.user_message),
        "observed_reply": mask_message(row.auto_reply),
        "intent": row.intent,
        "intent_zh": row.intent_zh,
        "needs_human": row.needs_human,
        "priority": row.priority,
        "reason": row.reason,
        "confidence": row.confidence,
        "total_turns": row.total_turns,
        "used_static": row.used_static,
    }


def build_single_turn_dataset(rows: list[RowRecord], per_intent: int, seed: int) -> list[dict[str, Any]]:
    by_intent: dict[str, list[RowRecord]] = defaultdict(list)
    for row in rows:
        by_intent[row.intent].append(row)

    rng = random.Random(seed)
    dataset: list[dict[str, Any]] = []

    for intent in sorted(by_intent):
        candidates = by_intent[intent][:]
        rng.shuffle(candidates)
        for row in candidates[:per_intent]:
            item = anonymize_row(row)
            item["case_type"] = "single_turn"
            item["evaluation_prompt"] = "檢查意圖、是否應轉人工、回覆是否符合品牌語氣與安全規則"
            dataset.append(item)

    dataset.sort(key=lambda item: (item["intent"], item["timestamp"]))
    return dataset


def build_multi_turn_dataset(
    rows: list[RowRecord],
    per_intent: int,
    min_turns: int,
    seed: int,
) -> list[dict[str, Any]]:
    by_user: dict[str, list[RowRecord]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)

    candidates_by_intent: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for user_id, convo_rows in by_user.items():
        ordered = sorted(convo_rows, key=lambda item: item.timestamp)
        if len(ordered) < min_turns:
            continue

        intent_counts: dict[str, int] = defaultdict(int)
        for row in ordered:
            intent_counts[row.intent] += 1
        primary_intent = max(
            intent_counts.items(),
            key=lambda item: (item[1], item[0]),
        )[0]

        transcript: list[dict[str, str]] = []
        observed_metrics = {
            "needs_human_turns": 0,
            "static_reply_turns": 0,
            "max_total_turns": 0,
        }
        for row in ordered:
            observed_metrics["needs_human_turns"] += int(row.needs_human)
            observed_metrics["static_reply_turns"] += int(row.used_static)
            observed_metrics["max_total_turns"] = max(observed_metrics["max_total_turns"], row.total_turns)
            transcript.append(
                {
                    "role": "user",
                    "content": mask_message(row.user_message),
                    "timestamp": row.timestamp.isoformat(sep=" "),
                    "intent": row.intent,
                    "needs_human": str(row.needs_human),
                }
            )
            if row.auto_reply:
                transcript.append(
                    {
                        "role": "assistant",
                        "content": mask_message(row.auto_reply),
                        "timestamp": row.timestamp.isoformat(sep=" "),
                    }
                )

        first = ordered[0]
        candidates_by_intent[primary_intent].append(
            {
                "case_type": "multi_turn",
                "conversation_id": stable_alias("conv", user_id),
                "user_alias": stable_alias("user", user_id),
                "display_name_alias": stable_alias("name", first.display_name),
                "primary_intent": primary_intent,
                "turn_count": len(ordered),
                "start_time": first.timestamp.isoformat(sep=" "),
                "end_time": ordered[-1].timestamp.isoformat(sep=" "),
                "observed_metrics": observed_metrics,
                "transcript": transcript,
                "evaluation_prompt": "重播整段對話，檢查上下文理解、轉人工時機與回覆一致性",
            }
        )

    rng = random.Random(seed)
    dataset: list[dict[str, Any]] = []
    for intent in sorted(candidates_by_intent):
        candidates = candidates_by_intent[intent][:]
        rng.shuffle(candidates)
        dataset.extend(candidates[:per_intent])

    dataset.sort(key=lambda item: (item["primary_intent"], item["start_time"]))
    return dataset


def build_annotation_rows(
    single_turn_cases: list[dict[str, Any]],
    multi_turn_cases: list[dict[str, Any]],
    source_rows: list[RowRecord],
    context_window: int = 5,
) -> list[dict[str, Any]]:
    # 建立對話歷史查找表：以 conversation_id 分組並依時間戳排序，
    # 供每筆 single-turn 案例附上前 N 輪的對話脈絡，讓標注者有足夠上下文判斷意圖
    conv_history: dict[str, list[RowRecord]] = defaultdict(list)
    for r in source_rows:
        cid = stable_alias("conv", r.user_id)
        conv_history[cid].append(r)
    for cid in conv_history:
        conv_history[cid].sort(key=lambda r: r.timestamp)

    annotation_rows: list[dict[str, Any]] = []
    for case in single_turn_cases:
        # 找出同一對話中時間戳早於本案例的前 N 筆，組成上下文 JSON
        prior = [
            r for r in conv_history.get(case["conversation_id"], [])
            if r.timestamp.isoformat(sep=" ") < case["timestamp"]
        ]
        prior = prior[-context_window:]
        context_turns: list[dict[str, str]] = []
        for r in prior:
            context_turns.append({
                "role": "user",
                "content": mask_message(r.user_message),
                "ts": r.timestamp.isoformat(sep=" "),
            })
            if r.auto_reply:
                context_turns.append({
                    "role": "bot",
                    "content": mask_message(r.auto_reply),
                    "ts": r.timestamp.isoformat(sep=" "),
                })
        context_str = json.dumps(context_turns, ensure_ascii=False) if context_turns else ""

        annotation_rows.append(
            {
                "case_id": f"{case['case_type']}::{case['conversation_id']}::{case['timestamp']}",
                "case_type": case["case_type"],
                "conversation_id": case["conversation_id"],
                "timestamp": case["timestamp"],
                "sampled_intent": case["intent"],
                "sampled_needs_human": case["needs_human"],
                "user_message": case["user_message"],
                "observed_reply": case["observed_reply"],
                "context": context_str,
                "gold_intent": "",
                "gold_needs_human": "",
                "gold_reply_notes": "",
                "reviewer": "",
                "review_status": "pending",
            }
        )

    for case in multi_turn_cases:
        annotation_rows.append(
            {
                "case_id": f"{case['case_type']}::{case['conversation_id']}::{case['start_time']}",
                "case_type": case["case_type"],
                "conversation_id": case["conversation_id"],
                "timestamp": case["start_time"],
                "sampled_intent": case["primary_intent"],
                "sampled_needs_human": case["observed_metrics"]["needs_human_turns"] > 0,
                "user_message": case["transcript"][0]["content"] if case["transcript"] else "",
                "observed_reply": "",
                "context": "",
                "gold_intent": "",
                "gold_needs_human": "",
                "gold_reply_notes": "",
                "reviewer": "",
                "review_status": "pending",
            }
        )

    return annotation_rows


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_summary(
    source_path: Path,
    rows: list[RowRecord],
    single_turn_cases: list[dict[str, Any]],
    multi_turn_cases: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    intent_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        intent_counts[row.intent] += 1

    return {
        "source_csv": str(source_path),
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "total_rows": len(rows),
        "unique_users": len({row.user_id for row in rows}),
        "single_turn_cases": len(single_turn_cases),
        "multi_turn_cases": len(multi_turn_cases),
        "single_per_intent": args.single_per_intent,
        "multi_per_intent": args.multi_per_intent,
        "min_multi_turns": args.min_multi_turns,
        "intent_distribution": dict(sorted(intent_counts.items())),
    }


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    if args.source == "csv":
        if args.input_csv is None:
            raise SystemExit("使用 --source csv 時，請提供 --input-csv")
        rows = load_rows_from_csv(args.input_csv)
        source_label = args.input_csv
    elif args.source == "raw-folder":
        rows = derive_rows_from_raw_folder(args.raw_root)
        source_label = args.raw_root
    else:
        rows = load_rows_from_sheets(
            sheet_id=args.sheet_id,
            sheet_tab=args.sheet_tab,
            credentials_path=args.credentials_path,
        )
        source_label = Path(f"gsheet://{args.sheet_id}/{args.sheet_tab}")
    ensure_output_dir(args.output_dir)

    single_turn_cases = build_single_turn_dataset(
        rows=rows,
        per_intent=args.single_per_intent,
        seed=args.seed,
    )
    multi_turn_cases = build_multi_turn_dataset(
        rows=rows,
        per_intent=args.multi_per_intent,
        min_turns=args.min_multi_turns,
        seed=args.seed,
    )
    annotation_rows = build_annotation_rows(
        single_turn_cases,
        multi_turn_cases,
        source_rows=rows,
        context_window=args.context_window,
    )
    summary = build_summary(source_label, rows, single_turn_cases, multi_turn_cases, args)

    write_json(args.output_dir / "dataset_summary.json", summary)
    write_json(args.output_dir / "single_turn_cases.json", single_turn_cases)
    write_json(args.output_dir / "multi_turn_cases.json", multi_turn_cases)
    write_csv(args.output_dir / "annotation_queue.csv", annotation_rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
