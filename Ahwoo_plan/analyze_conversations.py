from __future__ import annotations

import ast
import csv
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


# 這支腳本只允許寫入 Ahwoo_plan 目錄
OUTPUT_DIR = Path.home() / "Documents/projects/Ahwoo-project/Ahwoo_plan"
CSV_ROOT = Path.home() / "Documents/projects/data/raw/ahwoo_oa_chat_raw"
KNOWLEDGE_BASE_PATH = Path.home() / "Documents/projects/Ahwoo-project/knowledge_base.py"
HTML_DASHBOARD_PATH = Path.home() / "Documents/projects/Ahwoo-project/LINE_OA_分析儀表板.html"
SUMMARY_PATH = OUTPUT_DIR / "summary.md"
DASHBOARD_DIFF_PATH = OUTPUT_DIR / "dashboard_diff.md"

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "big5", "cp950")
EXPECTED_HEADER = ["傳送者類型", "傳送者名稱", "傳送日期", "傳送時間", "內容"]
MEDIA_MESSAGES = {"照片已傳送", "貼圖已傳送", "影片已傳送", "檔案已傳送"}
SHORT_MESSAGE_MAX_LENGTH = 2
ACK_TOKENS = (
    "謝謝您",
    "謝謝你",
    "不好意思",
    "沒關係",
    "不用了",
    "thankyou",
    "thanks",
    "thank",
    "好的",
    "收到",
    "了解",
    "瞭解",
    "謝謝",
    "感謝",
    "抱歉",
    "okay",
    "可以",
    "是的",
    "嗯嗯",
    "恩恩",
    "okk",
    "ok",
    "好喔",
    "好哦",
    "好",
)

MANUAL_PATTERN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("日期 / 名額確認", re.compile(r"(今天|明天|後天|週[一二三四五六日天]|星期[一二三四五六日天]|禮拜[一二三四五六日天]|\d{1,2}[/-]\d{1,2}|名額|時間|時段|可以訂|可訂|還有嗎|有空嗎|預約)")),
    ("價格 / 報價詢問", re.compile(r"(多少|價錢|價格|費用|報價|怎麼算|幾[元塊])")),
    ("品項 / 客製需求", re.compile(r"(口味|尺寸|造型|客製|客製化|圖案|字樣|文字|蛋糕|甜點|餅乾|餐盒|外燴|加購|修改|更改)")),
    ("取貨 / 配送", re.compile(r"(自取|面交|宅配|寄送|配送|運費|到貨|取貨|寄到|地址)")),
    ("付款 / 訂單處理", re.compile(r"(付款|匯款|轉帳|訂金|尾款|下單|訂單|取消|改單|收據|發票)")),
    ("成分 / 保存 / 過敏", re.compile(r"(成分|原料|葷|素|蛋奶|奶蛋|過敏|堅果|酒精|保存|冷藏|冷凍)")),
    ("致謝 / 確認回覆", re.compile(r"^(好的|好喔|好哦|好|收到|了解|瞭解|謝謝|thanks|ok|okk|okay|可以|沒關係|不用了)$", re.I)),
]


@dataclass
class Message:
    sender_type: str
    sender_name: str
    timestamp: datetime
    content: str


def read_text_with_fallback(path: Path, encodings: Iterable[str]) -> tuple[str | None, str | None]:
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding), encoding
        except Exception:
            continue
    return None, None


def read_csv_rows(path: Path) -> tuple[list[list[str]] | None, str | None]:
    for encoding in CSV_ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.reader(handle)), encoding
        except Exception:
            continue
    return None, None


def parse_timestamp(date_str: str, time_str: str) -> datetime | None:
    value = f"{date_str.strip()} {time_str.strip()}"
    try:
        return datetime.strptime(value, "%Y/%m/%d %H:%M:%S")
    except Exception:
        return None


def normalize_text(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text(text))


def is_media_message(text: str) -> bool:
    return (text or "").strip() in MEDIA_MESSAGES


def is_short_message(text: str) -> bool:
    compact = re.sub(r"\s+", "", (text or "").strip())
    return len(compact) <= SHORT_MESSAGE_MAX_LENGTH


def extract_chinese_bigrams(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text or "")
    bigrams: list[str] = []
    for chunk in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(chunk) < 2:
            continue
        for index in range(len(chunk) - 1):
            bigrams.append(chunk[index:index + 2])
    return bigrams


def format_number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return f"{value:,}"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.{digits}f}"


def format_percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.00%"
    return f"{(numerator / denominator * 100):.2f}%"


def markdown_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def load_intent_keywords(path: Path) -> tuple[dict[str, list[str]], str]:
    if not path.exists():
        return {}, f"找不到檔案：{path}"

    text, encoding = read_text_with_fallback(path, ("utf-8", "utf-8-sig", "big5", "cp950"))
    if text is None:
        return {}, f"無法讀取檔案：{path}"

    try:
        tree = ast.parse(text)
    except Exception as exc:
        return {}, f"AST 解析失敗：{exc}"

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "INTENT_KEYWORDS":
                try:
                    value = ast.literal_eval(node.value)
                    return {
                        str(intent): [str(keyword) for keyword in keywords]
                        for intent, keywords in value.items()
                    }, f"已載入 INTENT_KEYWORDS（encoding={encoding}）"
                except Exception as exc:
                    return {}, f"INTENT_KEYWORDS 解析失敗：{exc}"

    return {}, "knowledge_base.py 中找不到 INTENT_KEYWORDS"


def extract_dashboard_metrics(path: Path) -> tuple[dict[str, str], list[str]]:
    notes: list[str] = []
    metrics: dict[str, str] = {}

    if not path.exists():
        notes.append(f"找不到檔案：{path}")
        return metrics, notes

    text, encoding = read_text_with_fallback(path, ("utf-8", "utf-8-sig", "big5", "cp950"))
    if text is None:
        notes.append(f"無法讀取檔案：{path}")
        return metrics, notes

    notes.append(f"已讀取 HTML（encoding={encoding}）")

    def capture(name: str, pattern: str, flags: int = 0) -> None:
        match = re.search(pattern, text, flags)
        if match:
            metrics[name] = match.group(1).strip()

    capture("頁首對話分析數", r">([\d,]+)\s*筆對話分析")
    capture("總對話數 KPI", r"總對話數.*?<div class=\"value\">([\d,]+)</div>", re.S)
    capture("漏斗有效詢問數", r"label:'有效詢問',\s*count:(\d+)")

    match_5 = re.search(r"delay:\s*\{[^}]*?dist:\s*\[([^\]]+)\]", text, re.S)
    if match_5:
        values = [part.strip() for part in match_5.group(1).split(",")]
        labels = ["<1hr", "1-4hr", "4-8hr", "8-24hr", ">24hr"]
        for label, value in zip(labels, values):
            metrics[f"回覆延遲 5桶 {label}"] = value

    match_9 = re.search(r"delayCounts:\s*\[([^\]]+)\]", text, re.S)
    if match_9:
        values = [part.strip() for part in match_9.group(1).split(",")]
        labels = ["<15min", "15-30min", "30-60min", "1-2hr", "2-4hr", "4-8hr", "8-24hr", "1-3天", ">3天"]
        for label, value in zip(labels, values):
            metrics[f"回覆延遲 9桶 {label}"] = value

    return metrics, notes


def match_intents(message_text: str, keyword_map: dict[str, list[str]]) -> set[str]:
    normalized = compact_text(message_text)
    matched: set[str] = set()
    for intent, keywords in keyword_map.items():
        for keyword in keywords:
            compact_keyword = compact_text(keyword)
            if compact_keyword and compact_keyword in normalized:
                matched.add(intent)
                break
    return matched


def bucket_counts(values: list[float], boundaries: list[float]) -> list[int]:
    counts = [0] * (len(boundaries) + 1)
    for value in values:
        for index, boundary in enumerate(boundaries):
            if value < boundary:
                counts[index] += 1
                break
        else:
            counts[-1] += 1
    return counts


def diff_status(dashboard_value: str | None, computed_value: str | None) -> tuple[str, str]:
    if dashboard_value in (None, "") or computed_value in (None, ""):
        return "N/A", "N/A"

    dash = dashboard_value.strip()
    comp = computed_value.strip()
    if dash == comp:
        return "0", "Match"

    dash_num = dash.replace(",", "")
    comp_num = comp.replace(",", "")
    try:
        if "." in dash_num or "." in comp_num:
            diff = float(comp_num) - float(dash_num)
            return f"{diff:+.2f}", "Match" if abs(diff) < 0.005 else "Mismatch"
        diff = int(comp_num) - int(dash_num)
        return f"{diff:+,}", "Match" if diff == 0 else "Mismatch"
    except Exception:
        return "N/A", "Mismatch" if dash != comp else "Match"


def categorize_gap_message(text: str) -> str:
    normalized = normalize_text(text)
    if is_short_message(text):
        return "短訊息 / 簡短回覆"
    if is_acknowledgement_message(text):
        return "致謝 / 確認回覆"
    for label, pattern in MANUAL_PATTERN_RULES:
        if pattern.search(normalized):
            return label
    return "其他未覆蓋需求"


def is_acknowledgement_message(text: str) -> bool:
    simplified = re.sub(r"[^\u4e00-\u9fffa-z0-9]+", "", normalize_text(text))
    if not simplified:
        return False
    while simplified:
        for token in ACK_TOKENS:
            if simplified.startswith(token):
                simplified = simplified[len(token):]
                break
        else:
            return False
    return True


def build_summary_markdown(
    valid_conversations: int,
    empty_conversations: int,
    total_user_messages: int,
    total_user_text_messages: int,
    no_account_reply_conversations: int,
    reply_delays_minutes: list[float],
    reply_delay_distribution: list[tuple[str, int]],
    keyword_counter: Counter[str],
    matched_text_messages: int,
    unmatched_text_messages: int,
    gap_counter: Counter[str],
    short_gap_count: int,
    manual_pattern_counter: Counter[str],
    manual_pattern_examples: dict[str, Counter[str]],
) -> str:
    lines: list[str] = []
    lines.append("# Bot 缺口分析摘要")
    lines.append("")

    lines.append("## 基本統計")
    lines.append(f"- 有效對話數：{format_number(valid_conversations)}（含訊息的 CSV）")
    lines.append(f"- 空白對話數：{format_number(empty_conversations)}（加好友但未傳訊息）")
    lines.append(f"- 總 User 訊息數（含媒體）：{format_number(total_user_messages)}")
    lines.append(f"- 總 User 文字訊息數（排媒體）：{format_number(total_user_text_messages)}")
    lines.append(
        f"- 無 Account 回覆的對話數：{format_number(no_account_reply_conversations)}"
        f"（{format_percent(no_account_reply_conversations, valid_conversations)}）"
    )
    lines.append("")

    lines.append("## 回覆延遲分布（以 User 訊息後的下一則 Account 回覆計算）")
    lines.append("| 延遲區間 | 訊息數 | 比例 |")
    lines.append("| --- | ---: | ---: |")
    delay_denominator = total_user_messages
    for label, count in reply_delay_distribution:
        lines.append(f"| {label} | {count:,} | {format_percent(count, delay_denominator)} |")
    median_reply_minutes = statistics.median(reply_delays_minutes) if reply_delays_minutes else None
    median_display = f"{median_reply_minutes:.2f}" if median_reply_minutes is not None else "N/A"
    lines.append(f"| 中位數回覆時間（分鐘） | {median_display} | - |")
    lines.append("")

    lines.append("## Top 20 顧客訊息關鍵詞（僅 User 訊息）")
    for rank, (keyword, count) in enumerate(keyword_counter.most_common(20), start=1):
        lines.append(f"{rank}. {keyword}（{count:,} 次）")
    if not keyword_counter:
        lines.append("1. N/A（0 次）")
    lines.append("")

    lines.append("## Bot 意圖覆蓋率（排除媒體訊息後）")
    lines.append(f"- 可命中：{format_percent(matched_text_messages, total_user_text_messages)}")
    lines.append(f"- 無法命中（缺口）：{format_percent(unmatched_text_messages, total_user_text_messages)}")
    lines.append("")

    lines.append("## Top 10 Bot 缺口訊息（排除媒體訊息）")
    for rank, (message, count) in enumerate(gap_counter.most_common(10), start=1):
        lines.append(f"{rank}. {message}（{count:,} 次）")
    if not gap_counter:
        lines.append("1. N/A（0 次）")
    lines.append("")

    lines.append("## 需人工介入的高頻訊息模式")
    pattern_rank = 0
    for category, count in manual_pattern_counter.most_common():
        if count <= 0:
            continue
        if category == "其他未覆蓋需求":
            continue
        example = ""
        if category in manual_pattern_examples and manual_pattern_examples[category]:
            example = manual_pattern_examples[category].most_common(1)[0][0]
        pattern_rank += 1
        if category == "短訊息 / 簡短回覆":
            lines.append(
                f"- {category}：{count:,} 則，已納入覆蓋率統計，但依規則不列入 Top 10 缺口。"
            )
        elif example:
            lines.append(f"- {category}：{count:,} 則，例：「{example}」")
        else:
            lines.append(f"- {category}：{count:,} 則")
        if pattern_rank >= 5:
            break
    if not manual_pattern_counter:
        lines.append("- 無")
    elif short_gap_count > 0 and "短訊息 / 簡短回覆" not in manual_pattern_counter:
        lines.append(f"- 短訊息 / 簡短回覆：{short_gap_count:,} 則，已納入覆蓋率統計，但依規則不列入 Top 10 缺口。")
    elif pattern_rank == 0:
        lines.append("- 其他未覆蓋需求為主，暫無可穩定歸類的高頻模式。")

    return "\n".join(lines).strip() + "\n"


def build_dashboard_diff_markdown(rows: list[tuple[str, str, str, str, str]]) -> str:
    lines = [
        "# Dashboard Diff",
        "",
        "| Metric | Dashboard Value | Computed Value | Diff | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for metric, dashboard_value, computed_value, diff, status in rows:
        lines.append(
            f"| {markdown_escape(metric)} | {markdown_escape(dashboard_value)} | "
            f"{markdown_escape(computed_value)} | {markdown_escape(diff)} | {status} |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- 回覆延遲改以「每則 User 訊息 -> 同一對話中的下一則 Account 訊息」為計算粒度。",
            "- `summary.md` 使用 `<1 小時 / 1-4 小時 / 4-24 小時 / >24 小時 / 無回覆` 分布；本檔為了對照既有 HTML，仍保留舊版 `5桶 / 9桶` 指標名稱。",
            "- 因分桶切點與是否納入 `無回覆` 不同，`summary.md` 與 HTML 儀表板的回覆延遲數字不應直接視為同一口徑。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    intent_keywords, _knowledge_base_note = load_intent_keywords(KNOWLEDGE_BASE_PATH)
    dashboard_metrics, _html_notes = extract_dashboard_metrics(HTML_DASHBOARD_PATH)

    valid_conversations = 0
    empty_conversations = 0
    unreadable_files: list[str] = []

    total_user_messages = 0
    total_user_text_messages = 0
    no_account_reply_conversations = 0

    reply_delays_minutes: list[float] = []
    user_messages_without_reply = 0

    keyword_counter: Counter[str] = Counter()
    matched_text_messages = 0
    unmatched_text_messages = 0
    gap_counter: Counter[str] = Counter()
    short_gap_count = 0
    manual_pattern_counter: Counter[str] = Counter()
    manual_pattern_examples: dict[str, Counter[str]] = defaultdict(Counter)

    csv_files = sorted(CSV_ROOT.rglob("*.csv"))

    for index, csv_path in enumerate(csv_files, start=1):
        if index % 1000 == 0:
            print(f"[progress] {index}/{len(csv_files)} files processed")

        rows, _encoding = read_csv_rows(csv_path)
        if not rows or len(rows) < 4:
            unreadable_files.append(str(csv_path))
            continue

        header = rows[3]
        if header[:5] != EXPECTED_HEADER:
            unreadable_files.append(str(csv_path))
            continue

        if len(rows) == 4:
            empty_conversations += 1
            continue

        messages: list[Message] = []
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
            messages.append(
                Message(
                    sender_type=sender_type,
                    sender_name=sender_name.strip(),
                    timestamp=timestamp,
                    content=(content or "").strip(),
                )
            )

        if not messages:
            unreadable_files.append(str(csv_path))
            continue

        messages.sort(key=lambda item: item.timestamp)
        valid_conversations += 1

        has_user = any(message.sender_type == "User" for message in messages)
        has_account = any(message.sender_type == "Account" for message in messages)
        if has_user and not has_account:
            no_account_reply_conversations += 1

        next_account_time: datetime | None = None
        for message in reversed(messages):
            if message.sender_type == "Account":
                next_account_time = message.timestamp
                continue

            total_user_messages += 1
            if not is_media_message(message.content):
                for bigram in extract_chinese_bigrams(message.content):
                    keyword_counter[bigram] += 1

            if next_account_time is None:
                user_messages_without_reply += 1
            else:
                delta_minutes = (next_account_time - message.timestamp).total_seconds() / 60
                if delta_minutes >= 0:
                    reply_delays_minutes.append(delta_minutes)

            if is_media_message(message.content):
                continue

            total_user_text_messages += 1
            normalized_message = normalize_text(message.content)
            matched_intents = match_intents(message.content, intent_keywords) if intent_keywords else set()
            if matched_intents:
                matched_text_messages += 1
                continue

            unmatched_text_messages += 1
            category = categorize_gap_message(message.content)
            manual_pattern_counter[category] += 1
            if normalized_message:
                manual_pattern_examples[category][normalized_message] += 1

            if is_short_message(message.content):
                short_gap_count += 1
                continue

            if normalized_message:
                gap_counter[normalized_message] += 1

    reply_delay_distribution = [
        ("小於 1 小時", sum(1 for value in reply_delays_minutes if value < 60)),
        ("1-4 小時", sum(1 for value in reply_delays_minutes if 60 <= value < 240)),
        ("4-24 小時", sum(1 for value in reply_delays_minutes if 240 <= value < 1440)),
        ("大於 24 小時", sum(1 for value in reply_delays_minutes if value >= 1440)),
        ("無回覆", user_messages_without_reply),
    ]

    summary_markdown = build_summary_markdown(
        valid_conversations=valid_conversations,
        empty_conversations=empty_conversations,
        total_user_messages=total_user_messages,
        total_user_text_messages=total_user_text_messages,
        no_account_reply_conversations=no_account_reply_conversations,
        reply_delays_minutes=reply_delays_minutes,
        reply_delay_distribution=reply_delay_distribution,
        keyword_counter=keyword_counter,
        matched_text_messages=matched_text_messages,
        unmatched_text_messages=unmatched_text_messages,
        gap_counter=gap_counter,
        short_gap_count=short_gap_count,
        manual_pattern_counter=manual_pattern_counter,
        manual_pattern_examples=manual_pattern_examples,
    )

    delay_5_labels = ["<1hr", "1-4hr", "4-8hr", "8-24hr", ">24hr"]
    delay_5_counts = bucket_counts(reply_delays_minutes, [60, 240, 480, 1440])
    delay_9_labels = ["<15min", "15-30min", "30-60min", "1-2hr", "2-4hr", "4-8hr", "8-24hr", "1-3天", ">3天"]
    delay_9_counts = bucket_counts(reply_delays_minutes, [15, 30, 60, 120, 240, 480, 1440, 4320])

    comparison_map = {
        "頁首對話分析數": format_number(valid_conversations),
        "總對話數 KPI": format_number(valid_conversations),
        "漏斗有效詢問數": format_number(valid_conversations),
    }
    for label, count in zip(delay_5_labels, delay_5_counts):
        comparison_map[f"回覆延遲 5桶 {label}"] = format_number(count)
    for label, count in zip(delay_9_labels, delay_9_counts):
        comparison_map[f"回覆延遲 9桶 {label}"] = format_number(count)

    diff_rows: list[tuple[str, str, str, str, str]] = []
    for metric_name in comparison_map:
        dashboard_value = dashboard_metrics.get(metric_name, "N/A")
        computed_value = comparison_map[metric_name]
        diff, status = diff_status(
            None if dashboard_value == "N/A" else dashboard_value,
            None if computed_value == "N/A" else computed_value,
        )
        diff_rows.append((metric_name, dashboard_value, computed_value, diff, status))

    extra_rows = {
        "總 User 訊息數（含媒體）": format_number(total_user_messages),
        "總 User 文字訊息數（排媒體）": format_number(total_user_text_messages),
        "無 Account 回覆的對話數": format_number(no_account_reply_conversations),
        "Bot Coverage Rate (%)": format_percent(matched_text_messages, total_user_text_messages).replace("%", ""),
        "Bot Gap Rate (%)": format_percent(unmatched_text_messages, total_user_text_messages).replace("%", ""),
        "回覆延遲 小於 1 小時": format_number(reply_delay_distribution[0][1]),
        "回覆延遲 1-4 小時": format_number(reply_delay_distribution[1][1]),
        "回覆延遲 4-24 小時": format_number(reply_delay_distribution[2][1]),
        "回覆延遲 大於 24 小時": format_number(reply_delay_distribution[3][1]),
        "回覆延遲 無回覆": format_number(reply_delay_distribution[4][1]),
        "中位數回覆時間（分鐘）": format_number(statistics.median(reply_delays_minutes) if reply_delays_minutes else None),
    }
    for metric_name, computed_value in extra_rows.items():
        diff_rows.append((metric_name, "N/A", computed_value, "N/A", "N/A"))

    dashboard_diff_markdown = build_dashboard_diff_markdown(diff_rows)

    SUMMARY_PATH.write_text(summary_markdown, encoding="utf-8")
    DASHBOARD_DIFF_PATH.write_text(dashboard_diff_markdown, encoding="utf-8")

    summary_size = SUMMARY_PATH.stat().st_size if SUMMARY_PATH.exists() else 0
    dashboard_size = DASHBOARD_DIFF_PATH.stat().st_size if DASHBOARD_DIFF_PATH.exists() else 0

    print(f"[done] valid_conversations={valid_conversations:,}")
    print(f"[done] total_user_messages={total_user_messages:,}")
    print(f"[done] total_user_text_messages={total_user_text_messages:,}")
    print(f"[done] summary.md size={summary_size}")
    print(f"[done] dashboard_diff.md size={dashboard_size}")

    if summary_size <= 0 or dashboard_size <= 0:
        raise RuntimeError("輸出檔案為空，任務未完成")


if __name__ == "__main__":
    main()
