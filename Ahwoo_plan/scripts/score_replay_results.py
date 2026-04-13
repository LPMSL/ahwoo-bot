from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("/Users/linstev/Documents/projects/Ahwoo-project")
DEFAULT_DATASET_DIR = PROJECT_ROOT / "Ahwoo_plan" / "eval_datasets"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="評分 Ahwoo 離線重播結果並輸出報表")
    parser.add_argument(
        "--replay-results",
        type=Path,
        default=DEFAULT_DATASET_DIR / "replay_results.json",
        help="replay_eval_dataset.py 產出的 JSON",
    )
    parser.add_argument(
        "--annotation-csv",
        type=Path,
        default=DEFAULT_DATASET_DIR / "annotation_queue.csv",
        help="人工標註 CSV，可選；存在且有 gold_* 時會優先採用",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_DATASET_DIR / "replay_report.md",
        help="Markdown 報表輸出路徑",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_annotations(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            row["case_id"]: row
            for row in reader
            if any((row.get("gold_intent"), row.get("gold_needs_human"), row.get("gold_reply_notes")))
        }


def truthy(value: str) -> bool | None:
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"true", "1", "yes", "是"}:
        return True
    if text in {"false", "0", "no", "否"}:
        return False
    return None


def get_case_id(
    result: dict[str, Any],
    parent_case_type: str | None = None,
    parent_start_time: str | None = None,
    conversation_id: str | None = None,
) -> str:
    case_type = parent_case_type or result["case_type"]
    timestamp = result.get("timestamp") or parent_start_time or ""
    convo_id = conversation_id or result["conversation_id"]
    return f"{case_type}::{convo_id}::{timestamp}"


def flatten_results(payload: dict[str, Any], annotations: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []

    for result in payload.get("single_results", []):
        case_id = get_case_id(result)
        flat.append(make_flat_row(result, case_id, annotations.get(case_id)))

    for convo in payload.get("multi_results", []):
        for turn in convo.get("turn_results", []):
            case_id = get_case_id(
                turn,
                parent_case_type="multi_turn",
                parent_start_time=turn.get("timestamp"),
                conversation_id=convo.get("conversation_id"),
            )
            flat.append(
                make_flat_row(
                    turn,
                    case_id,
                    annotations.get(case_id),
                    primary_intent=convo.get("primary_intent"),
                    case_type="multi_turn",
                    conversation_id=convo.get("conversation_id"),
                )
            )

    return flat


def make_flat_row(
    result: dict[str, Any],
    case_id: str,
    annotation: dict[str, str] | None,
    primary_intent: str | None = None,
    case_type: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    observed = result.get("observed", {})
    prediction = result.get("prediction", {})

    gold_intent = annotation.get("gold_intent", "").strip() if annotation else ""
    gold_needs_human = truthy(annotation.get("gold_needs_human", "")) if annotation else None
    target_intent = gold_intent or observed.get("intent") or primary_intent or "unknown"
    target_needs_human = gold_needs_human if gold_needs_human is not None else observed.get("needs_human")

    return {
        "case_id": case_id,
        "case_type": case_type or result["case_type"],
        "conversation_id": conversation_id or result["conversation_id"],
        "timestamp": result.get("timestamp", ""),
        "input": result.get("input", ""),
        "target_intent": target_intent,
        "target_needs_human": target_needs_human,
        "predicted_intent": prediction.get("intent"),
        "predicted_needs_human": prediction.get("needs_human"),
        "predicted_reply": prediction.get("auto_reply", ""),
        "observed_reply": observed.get("reply", ""),
        "rule_flags": result.get("rule_flags", []),
        "intent_match": prediction.get("intent") == target_intent,
        "needs_human_match": prediction.get("needs_human") == target_needs_human,
        "reply_exact_match": prediction.get("auto_reply", "") == observed.get("reply", ""),
        "gold_reply_notes": annotation.get("gold_reply_notes", "").strip() if annotation else "",
        "reviewer": annotation.get("reviewer", "").strip() if annotation else "",
    }


def build_markdown(flat_rows: list[dict[str, Any]], runner: str) -> str:
    total = len(flat_rows)
    intent_match = sum(1 for row in flat_rows if row["intent_match"])
    human_match = sum(1 for row in flat_rows if row["needs_human_match"])
    reply_match = sum(1 for row in flat_rows if row["reply_exact_match"])
    flagged = [row for row in flat_rows if row["rule_flags"]]
    mismatches = [row for row in flat_rows if not row["intent_match"] or not row["needs_human_match"]]

    per_intent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in flat_rows:
        per_intent[row["target_intent"]].append(row)

    lines: list[str] = []
    lines.append("# Ahwoo Replay Report")
    lines.append("")
    lines.append(f"- runner: `{runner}`")
    lines.append(f"- total turns: **{total}**")
    lines.append(f"- intent match rate: **{ratio(intent_match, total)}**")
    lines.append(f"- needs_human match rate: **{ratio(human_match, total)}**")
    lines.append(f"- reply exact match rate: **{ratio(reply_match, total)}**")
    lines.append(f"- flagged turns: **{len(flagged)}**")
    lines.append("")

    lines.append("## Per Intent")
    lines.append("")
    lines.append("| intent | turns | intent match | needs_human match | flagged |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for intent in sorted(per_intent):
        rows = per_intent[intent]
        lines.append(
            f"| {intent} | {len(rows)} | {ratio(sum(1 for row in rows if row['intent_match']), len(rows))} | "
            f"{ratio(sum(1 for row in rows if row['needs_human_match']), len(rows))} | "
            f"{sum(1 for row in rows if row['rule_flags'])} |"
        )
    lines.append("")

    flag_counter = Counter(flag for row in flagged for flag in row["rule_flags"])
    lines.append("## Rule Flags")
    lines.append("")
    if flag_counter:
        for flag, count in flag_counter.most_common():
            lines.append(f"- `{flag}`: {count}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Top Mismatches")
    lines.append("")
    if mismatches:
        for row in mismatches[:20]:
            lines.append(f"### {row['case_id']}")
            lines.append(f"- input: {row['input']}")
            lines.append(f"- target intent: `{row['target_intent']}`")
            lines.append(f"- predicted intent: `{row['predicted_intent']}`")
            lines.append(f"- target needs_human: `{row['target_needs_human']}`")
            lines.append(f"- predicted needs_human: `{row['predicted_needs_human']}`")
            if row["gold_reply_notes"]:
                lines.append(f"- gold reply notes: {row['gold_reply_notes']}")
            lines.append(f"- predicted reply: {row['predicted_reply']}")
            lines.append("")
    else:
        lines.append("- no mismatches")
        lines.append("")

    lines.append("## Flagged Replies")
    lines.append("")
    if flagged:
        for row in flagged[:20]:
            lines.append(f"### {row['case_id']}")
            lines.append(f"- flags: {', '.join(row['rule_flags'])}")
            lines.append(f"- input: {row['input']}")
            lines.append(f"- predicted reply: {row['predicted_reply']}")
            lines.append("")
    else:
        lines.append("- no rule flags")
        lines.append("")

    return "\n".join(lines)


def ratio(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{numerator / denominator * 100:.1f}%"


def main() -> None:
    args = parse_args()
    payload = read_json(args.replay_results)
    annotations = load_annotations(args.annotation_csv)
    flat_rows = flatten_results(payload, annotations)
    report = build_markdown(flat_rows, runner=payload.get("runner", "unknown"))

    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
