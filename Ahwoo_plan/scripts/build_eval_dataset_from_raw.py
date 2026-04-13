from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_RAW_ROOT = Path("/Users/linstev/Documents/projects/data/raw/ahwoo_oa_chat_raw")
DEFAULT_OUTPUT_DIR = Path("/Users/linstev/Documents/projects/Ahwoo-project/Ahwoo_plan/eval_datasets/raw_eval")
EXPECTED_HEADER = ["傳送者類型", "傳送者名稱", "傳送日期", "傳送時間", "內容"]
MEDIA_MESSAGES = {"照片已傳送", "貼圖已傳送", "影片已傳送", "檔案已傳送"}
from privacy_utils import stable_alias, mask_message


@dataclass
class Turn:
    conversation_id: str
    user_alias: str
    display_name_alias: str
    timestamp: str
    user_message: str
    observed_reply: str
    total_turns: int
    source_file: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="從 Ahwoo 原始對話 CSV 建立匿名化評測資料集")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--single-count", type=int, default=200)
    parser.add_argument("--multi-count", type=int, default=80)
    parser.add_argument("--min-multi-turns", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int, default=0, help="0 表示直到最後一個檔案")
    parser.add_argument("--skip-slow-seconds", type=float, default=3.0)
    return parser.parse_args()


def parse_timestamp(date_str: str, time_str: str) -> datetime | None:
    try:
        return datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%Y/%m/%d %H:%M:%S")
    except Exception:
        return None


def read_csv_rows(path: Path) -> list[list[str]] | None:
    try:
        raw_bytes = path.read_bytes()
    except Exception:
        return None

    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = raw_bytes.decode(encoding)
            return list(csv.reader(io.StringIO(text)))
        except Exception:
            continue
    return None



def parse_conversation(path: Path) -> tuple[str, str, list[tuple[str, datetime, str]]]:
    rows = read_csv_rows(path)
    if not rows or len(rows) < 5 or rows[3][:5] != EXPECTED_HEADER:
        return "", "", []

    user_id = path.stem.split("_", 1)[0]
    display_name = path.stem.rsplit("_", 1)[-1]
    messages: list[tuple[str, datetime, str]] = []

    for raw_row in rows[4:]:
        if len(raw_row) < 5:
            continue
        sender_type, sender_name, send_date, send_time, content = raw_row[:5]
        sender_type = sender_type.strip()
        if sender_type not in {"Account", "User"}:
            continue
        timestamp = parse_timestamp(send_date, send_time)
        if timestamp is None:
            continue
        text = (content or "").strip()
        if not text:
            continue
        messages.append((sender_type, timestamp, text))
        if sender_type == "User" and sender_name.strip():
            display_name = sender_name.strip()

    messages.sort(key=lambda item: item[1])
    return user_id, display_name, messages


def build_turns(
    raw_root: Path,
    start_index: int,
    end_index: int,
    skip_slow_seconds: float,
) -> tuple[list[Turn], list[dict], int]:
    single_turns: list[Turn] = []
    multi_cases: list[dict] = []
    skipped_slow = 0

    all_files = sorted(raw_root.glob("*.csv"))
    csv_files = all_files[start_index:end_index or None]
    for index, path in enumerate(csv_files, start=1):
        started = time.perf_counter()
        user_id, display_name, messages = parse_conversation(path)
        elapsed = time.perf_counter() - started
        if elapsed > skip_slow_seconds:
            skipped_slow += 1
            print(f"[skip-slow] {path.name} {elapsed:.2f}s", flush=True)
            continue
        if not user_id or not messages:
            continue

        user_alias = stable_alias("user", user_id)
        conversation_id = stable_alias("conv", user_id)
        display_name_alias = stable_alias("name", display_name or user_id)

        next_account_reply = ""
        next_reply_lookup: dict[int, str] = {}
        for message_index in range(len(messages) - 1, -1, -1):
            sender_type, _timestamp, text = messages[message_index]
            if sender_type == "Account":
                next_account_reply = text
            else:
                next_reply_lookup[message_index] = next_account_reply

        transcript: list[dict] = []
        turn_count = 0
        for message_index, (sender_type, timestamp, text) in enumerate(messages):
            if sender_type == "User":
                if text in MEDIA_MESSAGES:
                    continue
                turn_count += 1
                observed_reply = next_reply_lookup.get(message_index, "")
                single_turns.append(
                    Turn(
                        conversation_id=conversation_id,
                        user_alias=user_alias,
                        display_name_alias=display_name_alias,
                        timestamp=timestamp.isoformat(sep=" "),
                        user_message=mask_message(text),
                        observed_reply=mask_message(observed_reply),
                        total_turns=turn_count,
                        source_file=path.name,
                    )
                )
                transcript.append(
                    {
                        "role": "user",
                        "timestamp": timestamp.isoformat(sep=" "),
                        "content": mask_message(text),
                    }
                )
                if observed_reply:
                    transcript.append(
                        {
                            "role": "assistant",
                            "timestamp": timestamp.isoformat(sep=" "),
                            "content": mask_message(observed_reply),
                        }
                    )

        if turn_count >= 3:
            multi_cases.append(
                {
                    "case_type": "multi_turn",
                    "conversation_id": conversation_id,
                    "user_alias": user_alias,
                    "display_name_alias": display_name_alias,
                    "turn_count": turn_count,
                    "start_time": transcript[0]["timestamp"] if transcript else "",
                    "end_time": transcript[-1]["timestamp"] if transcript else "",
                    "source_file": path.name,
                    "primary_intent": "unknown",
                    "observed_metrics": {
                        "needs_human_turns": 0,
                        "static_reply_turns": 0,
                        "max_total_turns": turn_count,
                    },
                    "transcript": transcript,
                    "evaluation_prompt": "重播整段真實對話，檢查上下文理解與回覆品質",
                }
            )

        if index % 500 == 0:
            print(f"[progress] {index}/{len(csv_files)} files", flush=True)

    return single_turns, multi_cases, skipped_slow


def sample_single_turns(turns: list[Turn], count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    candidates = turns[:]
    rng.shuffle(candidates)
    selected = sorted(candidates[:count], key=lambda item: item.timestamp)
    result: list[dict] = []
    for turn in selected:
        item = asdict(turn)
        item["case_type"] = "single_turn"
        item["intent"] = "unknown"
        item["intent_zh"] = "待標註"
        item["needs_human"] = False
        item["priority"] = "unknown"
        item["reason"] = f"raw_file:{turn.source_file}"
        item["confidence"] = 0.0
        item["used_static"] = False
        item["evaluation_prompt"] = "檢查是否回答到客戶問題、語氣是否自然、是否有不該承諾的內容"
        result.append(item)
    return result


def sample_multi_turns(cases: list[dict], count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    candidates = cases[:]
    rng.shuffle(candidates)
    return sorted(candidates[:count], key=lambda item: item["start_time"])


def build_annotation_queue(single_cases: list[dict], multi_cases: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for case in single_cases:
        rows.append(
            {
                "case_id": f"single_turn::{case['conversation_id']}::{case['timestamp']}",
                "case_type": "single_turn",
                "conversation_id": case["conversation_id"],
                "timestamp": case["timestamp"],
                "sampled_intent": "unknown",
                "sampled_needs_human": "",
                "user_message": case["user_message"],
                "observed_reply": case["observed_reply"],
                "gold_intent": "",
                "gold_needs_human": "",
                "gold_reply_notes": "",
                "reviewer": "",
                "review_status": "pending",
            }
        )
    for case in multi_cases:
        rows.append(
            {
                "case_id": f"multi_turn::{case['conversation_id']}::{case['start_time']}",
                "case_type": "multi_turn",
                "conversation_id": case["conversation_id"],
                "timestamp": case["start_time"],
                "sampled_intent": "unknown",
                "sampled_needs_human": "",
                "user_message": case["transcript"][0]["content"] if case["transcript"] else "",
                "observed_reply": "",
                "gold_intent": "",
                "gold_needs_human": "",
                "gold_reply_notes": "",
                "reviewer": "",
                "review_status": "pending",
            }
        )
    return rows


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    single_turns, multi_cases_all, skipped_slow = build_turns(
        args.raw_root,
        args.start_index,
        args.end_index,
        args.skip_slow_seconds,
    )
    single_cases = sample_single_turns(single_turns, args.single_count, args.seed)
    multi_cases = sample_multi_turns(
        [case for case in multi_cases_all if case["turn_count"] >= args.min_multi_turns],
        args.multi_count,
        args.seed,
    )
    annotation_queue = build_annotation_queue(single_cases, multi_cases)

    summary = {
        "source": str(args.raw_root),
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "start_index": args.start_index,
        "end_index": args.end_index,
        "all_single_turns": len(single_turns),
        "all_multi_turn_candidates": len(multi_cases_all),
        "sampled_single_turns": len(single_cases),
        "sampled_multi_turns": len(multi_cases),
        "unique_conversations": len({turn.conversation_id for turn in single_turns}),
        "skipped_slow_files": skipped_slow,
    }

    write_json(args.output_dir / "dataset_summary.json", summary)
    write_json(args.output_dir / "single_turn_cases.json", single_cases)
    write_json(args.output_dir / "multi_turn_cases.json", multi_cases)
    write_csv(args.output_dir / "annotation_queue.csv", annotation_queue)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
