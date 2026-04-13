"""共用隱私遮蔽工具，供 build_eval_dataset.py 和 build_eval_dataset_from_raw.py 使用"""
from __future__ import annotations

import hashlib
import re

PHONE_RE = re.compile(r"(?<!\d)(09\d{2})[-\s]?(\d{3})[-\s]?(\d{3})(?!\d)")
TRANSFER_RE = re.compile(r"(後五碼|末五碼|後 5 碼|末 5 碼)[:：]?\s*([A-Za-z0-9]{3,8})")
FIELD_PREFIXES = (
    "line名稱",
    "line name",
    "line id",
    "ig",
    "instagram",
    "帳號",
    "帳戶",
    "姓名",
    "電話",
    "地址",
    "取貨地點",
    "聯絡電話",
)
CITY_PREFIXES = (
    "台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市",
    "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣",
    "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
    "台東縣", "澎湖縣",
)


def stable_alias(prefix: str, raw_value: str) -> str:
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


def mask_message(text: str) -> str:
    masked = (text or "").strip()
    masked = PHONE_RE.sub(r"\1-***-***", masked)
    masked = TRANSFER_RE.sub(r"\1：<MASKED_TRANSFER_CODE>", masked)

    lines: list[str] = []
    for raw_line in re.split(r"(\r?\n)", masked):
        if raw_line in {"\n", "\r\n"}:
            lines.append(raw_line)
            continue

        normalized = raw_line.strip().lower()
        if any(normalized.startswith(prefix) for prefix in FIELD_PREFIXES):
            label = re.split(r"[:：]", raw_line, maxsplit=1)[0]
            lines.append(f"{label}：<MASKED>")
            continue
        if any(raw_line.strip().startswith(prefix) for prefix in CITY_PREFIXES):
            lines.append("<MASKED_ADDRESS>")
            continue
        lines.append(raw_line)

    return "".join(lines)
