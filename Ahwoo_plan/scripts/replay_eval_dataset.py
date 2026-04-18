from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# preset_messages 在同一個 scripts/ 目錄
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from preset_messages import (
    DEFAULT_PRESET_CSV,
    load_preset_messages,
    match_reply,
)

PROJECT_ROOT = Path.home() / "Documents/projects/Ahwoo-project"
DEFAULT_DATASET_DIR = PROJECT_ROOT / "Ahwoo_plan" / "eval_datasets"
DEFAULT_SLICE = "raw_eval_slice2"
PRICE_RE = re.compile(r"(?<![A-Za-z])(?:\d{2,5})(?:元|塊|NT|NT\$)?")

# 模組層級快取，避免重複載入 preset CSV
_PRESETS: list[dict] | None = None


def _get_presets(preset_csv: Path) -> list[dict]:
    global _PRESETS
    if _PRESETS is None:
        try:
            _PRESETS = load_preset_messages(preset_csv)
        except Exception:
            _PRESETS = []
    return _PRESETS


def _resolve_dataset_dir(dataset_dir: Path, slice_name: str) -> Path:
    """
    路徑解析優先順序：
    1. dataset_dir 下直接有 single_turn_cases.json → 使用 dataset_dir
    2. dataset_dir / slice_name 下有 → 使用該子目錄
    3. 其他情況 → 回傳 dataset_dir / slice_name（讓後續 read_json 拋出明確錯誤）
    """
    if (dataset_dir / "single_turn_cases.json").exists():
        return dataset_dir
    candidate = dataset_dir / slice_name
    return candidate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="離線重播 Ahwoo 評測資料集")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="eval_datasets 根目錄（含各 slice 子目錄）",
    )
    parser.add_argument(
        "--slice",
        default=DEFAULT_SLICE,
        help=f"資料集子目錄名稱，預設 {DEFAULT_SLICE!r}",
    )
    parser.add_argument(
        "--dataset-type",
        choices=("single", "multi", "both"),
        default="both",
        help="要重播的資料集種類",
    )
    parser.add_argument(
        "--runner",
        choices=("current_bot", "observed"),
        default="observed",
        help="observed 直接回放 production 結果，current_bot 重新呼叫 analyze_message",
    )
    parser.add_argument(
        "--history-source",
        choices=("predicted", "observed"),
        default="predicted",
        help="multi-turn 重播時，後續歷史要接前一輪預測回覆還是原 production 回覆",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_DATASET_DIR / "replay_results.json",
        help="重播結果輸出檔案",
    )
    parser.add_argument(
        "--preset-csv",
        type=Path,
        default=DEFAULT_PRESET_CSV,
        help="LINE OA 預設訊息 CSV 路徑（用於偵測 used_static）",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"找不到檔案: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_cases(dataset_dir: Path, dataset_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    single_cases: list[dict[str, Any]] = []
    multi_cases: list[dict[str, Any]] = []

    if dataset_type in {"single", "both"}:
        single_cases = read_json(dataset_dir / "single_turn_cases.json")
    if dataset_type in {"multi", "both"}:
        multi_cases = read_json(dataset_dir / "multi_turn_cases.json")
    return single_cases, multi_cases


def default_env() -> None:
    # current bot 的 config.py 會強制讀這些 env；離線 replay 時除了 API key 以外可先補空值避免 import 失敗
    defaults = {
        "LINE_CHANNEL_SECRET": "offline-replay",
        "LINE_CHANNEL_ACCESS_TOKEN": "offline-replay",
        "TELEGRAM_BOT_TOKEN": "offline-replay",
        "TELEGRAM_CHAT_ID": "offline-replay",
        "GOOGLE_SHEET_ID": "offline-replay",
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "offline-replay"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)

    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


async def call_current_bot(
    user_message: str,
    conversation_history: list[dict[str, str]],
    total_turns: int,
) -> dict[str, Any]:
    default_env()
    from Ahwoo_chatbot.handlers.claude_handler import analyze_message

    result = await analyze_message(
        user_message=user_message,
        conversation_history=conversation_history,
        total_turns=total_turns,
    )
    EXPECTED_KEYS = {"intent", "needs_human", "auto_reply", "priority", "reason", "confidence", "used_static"}
    assert set(result.keys()) >= EXPECTED_KEYS, \
        f"analyze_message 回傳缺少 key: {EXPECTED_KEYS - set(result.keys())}"
    return result


def call_observed(
    case: dict[str, Any],
    preset_csv: Path = DEFAULT_PRESET_CSV,
) -> dict[str, Any]:
    presets = _get_presets(preset_csv)
    observed_reply = case.get("observed_reply", "")
    preset_match = match_reply(observed_reply, presets) if presets else {"matched": False}

    used_static = preset_match["matched"] or bool(case.get("used_static", False))
    preset_title = preset_match.get("title", "") if preset_match["matched"] else ""

    return {
        "intent": case.get("intent") or case.get("primary_intent") or "unknown",
        "needs_human": case.get("needs_human", False),
        "auto_reply": observed_reply,
        "priority": case.get("priority", "normal"),
        "reason": "observed_baseline",
        "confidence": case.get("confidence", 1.0),
        "used_static": used_static,
        "preset_title": preset_title,
    }


def detect_rule_flags(reply: str) -> list[str]:
    flags: list[str] = []
    text = (reply or "").strip()
    if not text:
        flags.append("empty_reply")
        return flags

    if len(text.splitlines()) > 5:
        flags.append("too_many_lines")
    if "。" in text:
        flags.append("contains_full_stop")
    if PRICE_RE.search(text) and "報價" not in text and "價格依" not in text:
        flags.append("possible_fabricated_price")
    return flags


async def replay_single_case(
    case: dict[str, Any],
    runner: str,
    preset_csv: Path = DEFAULT_PRESET_CSV,
) -> dict[str, Any]:
    if runner == "observed":
        prediction = call_observed(case, preset_csv=preset_csv)
    else:
        prediction = await call_current_bot(
            user_message=case["user_message"],
            conversation_history=[],
            total_turns=int(case.get("total_turns", 1) or 1),
        )

    return {
        "case_type": "single_turn",
        "conversation_id": case["conversation_id"],
        "timestamp": case["timestamp"],
        "input": case["user_message"],
        "observed": {
            "intent": case.get("intent"),
            "needs_human": case.get("needs_human"),
            "reply": case.get("observed_reply"),
        },
        "prediction": prediction,
        "rule_flags": detect_rule_flags(prediction.get("auto_reply", "")),
        "matches": {
            "intent": prediction.get("intent") == case.get("intent"),
            "needs_human": prediction.get("needs_human") == case.get("needs_human"),
            "reply_exact": prediction.get("auto_reply", "") == case.get("observed_reply", ""),
        },
    }


async def replay_multi_case(
    case: dict[str, Any],
    runner: str,
    history_source: str,
    preset_csv: Path = DEFAULT_PRESET_CSV,
) -> dict[str, Any]:
    transcript = case.get("transcript", [])
    history: list[dict[str, str]] = []
    total_turns = 0
    turn_results: list[dict[str, Any]] = []

    current_user_message: str | None = None
    current_observed_reply: str = ""
    current_intent: str | None = None
    current_needs_human: bool | None = None
    current_timestamp: str | None = None

    async def flush_turn() -> None:
        nonlocal history
        nonlocal total_turns
        nonlocal current_user_message
        nonlocal current_observed_reply
        nonlocal current_intent
        nonlocal current_needs_human
        nonlocal current_timestamp

        if current_user_message is None:
            return

        total_turns += 1
        if runner == "observed":
            # 偵測此回覆是否為預設訊息
            presets = _get_presets(preset_csv)
            pm = match_reply(current_observed_reply, presets) if presets else {"matched": False}
            prediction = {
                "intent": current_intent,
                "needs_human": current_needs_human,
                "auto_reply": current_observed_reply,
                "priority": "normal",
                "reason": "observed_baseline",
                "confidence": 1.0,
                "used_static": pm["matched"],
                "preset_title": pm.get("title", "") if pm["matched"] else "",
            }
        else:
            prediction = await call_current_bot(
                user_message=current_user_message,
                conversation_history=history,
                total_turns=total_turns,
            )

        turn_results.append(
            {
                "turn_index": total_turns,
                "timestamp": current_timestamp,
                "input": current_user_message,
                "observed": {
                    "intent": current_intent,
                    "needs_human": current_needs_human,
                    "reply": current_observed_reply,
                },
                "prediction": prediction,
                "rule_flags": detect_rule_flags(prediction.get("auto_reply", "")),
                "matches": {
                    "intent": prediction.get("intent") == current_intent,
                    "needs_human": prediction.get("needs_human") == current_needs_human,
                    "reply_exact": prediction.get("auto_reply", "") == current_observed_reply,
                },
            }
        )

        next_reply = (
            prediction.get("auto_reply", "")
            if history_source == "predicted"
            else current_observed_reply
        )
        history = history + [
            {"role": "user", "content": current_user_message},
            {"role": "assistant", "content": next_reply},
        ]

        current_user_message = None
        current_observed_reply = ""
        current_intent = None
        current_needs_human = None
        current_timestamp = None

    for entry in transcript:
        role = entry.get("role")
        if role == "user":
            await flush_turn()
            current_user_message = entry.get("content", "")
            current_intent = entry.get("intent")
            current_needs_human = str(entry.get("needs_human", "")).lower() == "true"
            current_timestamp = entry.get("timestamp")
        elif role == "assistant":
            current_observed_reply = entry.get("content", "")
    await flush_turn()

    return {
        "case_type": "multi_turn",
        "conversation_id": case["conversation_id"],
        "primary_intent": case.get("primary_intent"),
        "history_source": history_source,
        "turn_count": len(turn_results),
        "turn_results": turn_results,
    }


def summarize_results(single_results: list[dict[str, Any]], multi_results: list[dict[str, Any]]) -> dict[str, Any]:
    single_total = len(single_results)
    multi_turn_total = sum(result["turn_count"] for result in multi_results)
    all_turns = single_results + [turn for convo in multi_results for turn in convo["turn_results"]]

    return {
        "single_cases": single_total,
        "multi_conversations": len(multi_results),
        "multi_turns": multi_turn_total,
        "turn_level": {
            "intent_match_rate": rate(all_turns, "intent"),
            "needs_human_match_rate": rate(all_turns, "needs_human"),
            "reply_exact_rate": rate(all_turns, "reply_exact"),
            "flagged_turns": sum(1 for turn in all_turns if turn.get("rule_flags")),
        },
    }


def rate(results: list[dict[str, Any]], key: str) -> float:
    if not results:
        return 0.0
    matched = sum(1 for result in results if result.get("matches", {}).get(key))
    return round(matched / len(results), 4)


async def main() -> None:
    args = parse_args()

    # 解析正確的資料集目錄（修正 multi-turn 路徑 bug）
    resolved_dir = _resolve_dataset_dir(args.dataset_dir, args.slice)
    print(f"Dataset dir: {resolved_dir}")

    single_cases, multi_cases = load_cases(resolved_dir, args.dataset_type)
    print(f"Loaded: {len(single_cases)} single-turn, {len(multi_cases)} multi-turn cases")

    single_results: list[dict[str, Any]] = []
    for case in single_cases:
        single_results.append(
            await replay_single_case(case, runner=args.runner, preset_csv=args.preset_csv)
        )

    multi_results: list[dict[str, Any]] = []
    for case in multi_cases:
        multi_results.append(
            await replay_multi_case(
                case,
                runner=args.runner,
                history_source=args.history_source,
                preset_csv=args.preset_csv,
            )
        )

    payload = {
        "runner": args.runner,
        "dataset_dir": str(resolved_dir),
        "slice": args.slice,
        "summary": summarize_results(single_results, multi_results),
        "single_results": single_results,
        "multi_results": multi_results,
    }

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
