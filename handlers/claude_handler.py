from __future__ import annotations

"""
claude_handler.py — 純關鍵字分類 + 靜態回覆
v2.0：移除 Claude API，改為純靜態回覆模式
- 命中 USE_STATIC_REPLY → 回傳 LINE OA 預設訊息
- pre_form_filled → 固定 Ack + 轉人工
- 其他一切 → 固定等待語 + 轉人工
"""

import logging

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import HUMAN_TURN_THRESHOLD
from knowledge_base import INTENTS, INTENT_KEYWORDS, STATIC_REPLIES, USE_STATIC_REPLY

logger = logging.getLogger(__name__)

# ── 固定回覆常數 ─────────────────────────────────────────────────────────────
WAITING_MESSAGE = "感謝你的訊息 .ᐟ 我們確認後會盡快回覆你😊"
PRE_FORM_ACK    = "收到.ᐟ 我們確認好檔期後會再傳詳細表單給你 請稍待片刻😊"


# ── 主要分析函數 ────────────────────────────────────────────────────────────

async def analyze_message(
    user_message: str,
    conversation_history: list[dict],
    total_turns: int,
) -> dict:
    """
    輸入：用戶訊息 + 歷史對話 + 輪數
    輸出：{
        intent, needs_human, auto_reply, priority,
        reason, confidence, used_static
    }
    """

    # Step 1: 超過輪數閾值 → 直接轉人工
    if total_turns >= HUMAN_TURN_THRESHOLD:
        return {
            "intent":      "other",
            "needs_human": True,
            "auto_reply":  WAITING_MESSAGE,
            "priority":    "high",
            "reason":      f"已達 {total_turns} 輪，自動轉人工",
            "confidence":  1.0,
            "used_static": False,
        }

    # Step 2: 關鍵字快篩
    intent = _quick_keyword_check(user_message)

    # Step 3: 命中靜態回覆意圖 → 回傳 LINE OA 預設訊息
    if intent in USE_STATIC_REPLY:
        return {
            "intent":      intent,
            "needs_human": False,
            "auto_reply":  STATIC_REPLIES[intent],
            "priority":    INTENTS[intent]["priority"],
            "reason":      "static_reply",
            "confidence":  1.0,
            "used_static": True,
        }

    # Step 4: 顧客填回預篩選表單 → Ack + 人工
    if intent == "pre_form_filled":
        return {
            "intent":      "pre_form_filled",
            "needs_human": True,
            "auto_reply":  PRE_FORM_ACK,
            "priority":    "high",
            "reason":      "顧客已填回預約資訊",
            "confidence":  1.0,
            "used_static": True,
        }

    # Step 5: 其他一切（price_inquiry, custom_design, unknown...）→ 等待語 + 人工
    priority = INTENTS.get(intent, {}).get("priority", "normal")
    return {
        "intent":      intent or "other",
        "needs_human": True,
        "auto_reply":  WAITING_MESSAGE,
        "priority":    priority,
        "reason":      "no_preset_reply",
        "confidence":  1.0,
        "used_static": False,
    }


# ── 工具函數 ────────────────────────────────────────────────────────────────

def _quick_keyword_check(text: str) -> str | None:
    """關鍵字快速比對，回傳第一個命中的意圖"""
    text_lower = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k.lower() in text_lower for k in keywords):
            return intent
    return None
