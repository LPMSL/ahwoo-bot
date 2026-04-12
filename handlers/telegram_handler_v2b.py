"""
telegram_handler_v2b.py — 版本 B「標籤分類」格式（備用）
切換方式：將此檔改名為 telegram_handler.py 取代現有版本

格式範例：
  🔴【緊急】改期/取消
  👤 王大明  ·  第3輪
  ─────────────────
  我想改訂單，之前約的6月要取消
  ─────────────────
  👉 LINE OA
"""

import logging
from telegram import Bot
from telegram.constants import ParseMode

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

# ── 優先等級標籤 ─────────────────────────────────────────────────────────────
PRIORITY_LABEL = {
    "low":    "🔵【一般】",
    "normal": "🟡【一般】",
    "high":   "🟠【高優先】",
    "urgent": "🔴【緊急】",
}

# ── 分類標籤 ─────────────────────────────────────────────────────────────────
INTENT_LABEL = {
    "pre_form_filled":   "待確認檔期",
    "form_submitted":    "新表單",
    "payment_received":  "付款通知",
    "custom_design":     "客製設計",
    "change_reschedule": "改期／取消",
    "complaint":         "顧客抱怨",
    "price_inquiry":     "詢問報價",
    "other":             "待確認",
}

LINE_OA_URL = "https://manager.line.biz/"


async def notify_human(
    user_id:       str,
    display_name:  str,
    message:       str,
    intent:        str,
    priority:      str,
    reason:        str,
    system_status: str | None,
    total_turns:   int,
) -> bool:
    """一般需人工通知 — 版本 B 標籤分類格式"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        p_label   = PRIORITY_LABEL.get(priority, "🟡【一般】")
        i_label   = INTENT_LABEL.get(intent, intent)
        msg_prev  = message[:300] + "…" if len(message) > 300 else message
        turns_tag = f"  ·  第{total_turns}輪" if total_turns > 1 else ""

        text = (
            f"{_escape(p_label)}{_escape(i_label)}\n"
            f"👤 {_escape(display_name)}{_escape(turns_tag)}\n"
            f"{'─' * 20}\n"
            f"{_escape(msg_prev)}\n"
            f"{'─' * 20}\n"
            f"[👉 LINE OA]({LINE_OA_URL})"
        )

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        logger.info(f"Telegram 通知已送出 → {display_name} ({intent})")
        return True

    except Exception as e:
        logger.error(f"Telegram 通知失敗: {e}")
        return False


async def notify_pre_form_filled(
    display_name: str,
    message: str,
) -> bool:
    """預篩選表單回填通知 — 版本 B"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        msg_prev = message[:300] + "…" if len(message) > 300 else message

        text = (
            f"🟠【高優先】待確認檔期\n"
            f"👤 {_escape(display_name)}\n"
            f"{'─' * 20}\n"
            f"{_escape(msg_prev)}\n"
            f"{'─' * 20}\n"
            f"✅ Bot 已回「稍待確認」\n"
            f"[👉 LINE OA 傳完整表單]({LINE_OA_URL})"
        )

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error(f"Telegram 預篩選通知失敗: {e}")
        return False


async def notify_form_submitted(
    display_name: str,
    form_content: str,
) -> bool:
    """完整表單提交通知 — 版本 B"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        text = (
            f"🟠【高優先】新表單\n"
            f"👤 {_escape(display_name)}\n"
            f"{'─' * 20}\n"
            f"{_escape(form_content[:600])}\n"
            f"{'─' * 20}\n"
            f"[👉 LINE OA 確認]({LINE_OA_URL})"
        )

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error(f"Telegram 表單通知失敗: {e}")
        return False


async def notify_payment_received(
    display_name: str,
    message: str,
) -> bool:
    """付款通知 — 版本 B"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        msg_prev = message[:300] + "…" if len(message) > 300 else message

        text = (
            f"🟠【高優先】付款通知\n"
            f"👤 {_escape(display_name)}\n"
            f"{'─' * 20}\n"
            f"{_escape(msg_prev)}\n"
            f"{'─' * 20}\n"
            f"[👉 LINE OA 確認]({LINE_OA_URL})"
        )

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error(f"Telegram 付款通知失敗: {e}")
        return False


async def notify_unanswered_alert(conversations: list) -> bool:
    """逾時未回覆警報 — 版本 B"""
    if not conversations:
        return True
    try:
        bot   = Bot(token=TELEGRAM_BOT_TOKEN)
        count = len(conversations)

        lines = [f"⏰【逾時警報】{_escape(str(count))} 個對話等待超過 4 小時\n{'─' * 20}"]
        for c in conversations[:10]:
            hrs     = c["waiting_hours"]
            name    = _escape(c["display_name"])
            i_label = _escape(INTENT_LABEL.get(c.get("intent", "other"), "待確認"))
            msg_p   = _escape(c["message"][:60] + ("…" if len(c["message"]) > 60 else ""))
            p       = c.get("priority", "normal")
            p_e     = {"low": "🔵", "normal": "🟡", "high": "🟠", "urgent": "🔴"}.get(p, "🟡")
            lines.append(f"{p_e} {name} — {i_label}（{_escape(str(hrs))}h）\n   「{msg_p}」")

        lines.append(f"{'─' * 20}\n[👉 LINE OA 回覆]({LINE_OA_URL})")
        text = "\n".join(lines)

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error(f"逾時警報發送失敗: {e}")
        return False


async def notify_api_failure(error_msg: str) -> bool:
    """系統異常通知"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        status = _escape(_summarize_system_status(error_msg))
        text = (
            f"⚠️【系統異常】\n"
            f"{'─' * 20}\n"
            f"{status}\n"
            f"{'─' * 20}\n"
            f"所有訊息仍會轉人工處理"
        )
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error(f"API 失敗通知發送失敗: {e}")
        return False


async def send_daily_summary(stats: dict) -> bool:
    """每日統計摘要"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        text = (
            f"📊 昨日 LINE OA 統計\n"
            f"{'─' * 20}\n"
            f"💬 總訊息：{stats.get('total_messages', 0)}\n"
            f"🤖 自動回覆：{stats.get('auto_replies', 0)}\n"
            f"🙋 轉人工：{stats.get('human_handoffs', 0)}\n"
            f"📋 收到表單：{stats.get('forms_received', 0)}\n"
            f"💰 收到付款：{stats.get('payments_received', 0)}"
        )
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return True
    except Exception as e:
        logger.error(f"每日統計通知失敗: {e}")
        return False


def _escape(text: str) -> str:
    """Escape MarkdownV2 特殊字元"""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def _summarize_system_status(raw_error: str) -> str:
    error_text = (raw_error or "").lower()
    if "credit balance is too low" in error_text:
        return "Anthropic 點數不足"
    if "rate limit" in error_text:
        return "請求過多，請稍後"
    if "timeout" in error_text:
        return "API 逾時"
    trimmed = raw_error.strip().replace("\n", " ")
    return trimmed[:80] + "…" if len(trimmed) > 80 else trimmed
