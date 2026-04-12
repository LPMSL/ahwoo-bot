"""
telegram_handler.py — 人工介入通知系統
v2.1：版本 A「行動優先」格式
第一行 = 要做什麼 ← 誰傳的，一眼看清楚
"""

import logging
from telegram import Bot
from telegram.constants import ParseMode

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LINE_OA_BASIC_ID

logger = logging.getLogger(__name__)

# ── 動作標籤（行動優先格式第一行用）────────────────────────────────────────
ACTION_LABEL = {
    "pre_form_filled":   "📝 確認檔期",
    "form_submitted":    "📋 新表單",
    "payment_received":  "💰 確認付款",
    "custom_design":     "🎨 客製設計",
    "change_reschedule": "🔴 改期／取消",
    "complaint":         "🔴 顧客抱怨",
    "price_inquiry":     "💬 詢問報價",
    "other":             "❓ 待確認",
}


def _line_chat_url(user_id: str) -> str:
    """產生 LINE OA Manager 直連特定顧客對話的 URL
    格式：https://manager.line.biz/account/{basicId}/chat/{userId}
    若未設定 LINE_OA_BASIC_ID，退回 LINE OA 首頁
    """
    if LINE_OA_BASIC_ID:
        return f"https://manager.line.biz/account/{LINE_OA_BASIC_ID}/chat/{user_id}"
    return "https://manager.line.biz/"


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
    """一般需人工通知 — 版本 A 行動優先格式"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        action = ACTION_LABEL.get(intent, f"❓ {intent}")
        msg_preview = message[:300] + "…" if len(message) > 300 else message
        turns_line = f"\n⚠️ 已對話 {total_turns} 輪" if total_turns >= 10 else ""
        chat_url = _line_chat_url(user_id)

        text = (
            f"{action} ← {_escape(display_name)}\n"
            f"{'─' * 20}\n"
            f"{_escape(msg_preview)}\n"
            f"{'─' * 20}"
            f"{turns_line}\n"
            f"[→ 前往對話]({chat_url})"
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
    user_id: str = "",
) -> bool:
    """預篩選表單回填通知 — 版本 A"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        msg_preview = message[:300] + "…" if len(message) > 300 else message
        chat_url = _line_chat_url(user_id)

        text = (
            f"📝 確認檔期 ← {_escape(display_name)}\n"
            f"{'─' * 20}\n"
            f"{_escape(msg_preview)}\n"
            f"{'─' * 20}\n"
            f"✅ Bot 已回「稍待確認」\n"
            f"[→ 前往對話傳完整表單]({chat_url})"
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
    user_id: str = "",
) -> bool:
    """完整表單提交通知 — 版本 A"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        chat_url = _line_chat_url(user_id)

        text = (
            f"📋 新表單 ← {_escape(display_name)}\n"
            f"{'─' * 20}\n"
            f"{_escape(form_content[:600])}\n"
            f"{'─' * 20}\n"
            f"[→ 前往對話確認]({chat_url})"
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
    user_id: str = "",
) -> bool:
    """付款通知 — 版本 A"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        msg_preview = message[:300] + "…" if len(message) > 300 else message
        chat_url = _line_chat_url(user_id)

        text = (
            f"💰 確認付款 ← {_escape(display_name)}\n"
            f"{'─' * 20}\n"
            f"{_escape(msg_preview)}\n"
            f"{'─' * 20}\n"
            f"[→ 前往對話確認]({chat_url})"
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
    """逾時未回覆警報 — 版本 A 緊湊列表"""
    if not conversations:
        return True
    try:
        bot   = Bot(token=TELEGRAM_BOT_TOKEN)
        count = len(conversations)

        lines = [f"⏰ {_escape(str(count))} 個對話等待超過 4 小時\n{'─' * 20}"]
        for c in conversations[:10]:
            hrs      = c["waiting_hours"]
            name     = _escape(c["display_name"])
            msg_prev = _escape(c["message"][:60] + ("…" if len(c["message"]) > 60 else ""))
            action   = ACTION_LABEL.get(c.get("intent", "other"), "❓")
            lines.append(f"{action} ← {name}（{_escape(str(hrs))} 小時）\n「{msg_prev}」")

        lines.append(f"{'─' * 20}\n[→ LINE OA 回覆]({LINE_OA_URL})")
        text = "\n".join(lines)

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        logger.info(f"逾時警報已送出：{count} 個對話")
        return True

    except Exception as e:
        logger.error(f"逾時警報發送失敗: {e}")
        return False


async def notify_api_failure(error_msg: str) -> bool:
    """系統異常通知（保留備用）"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        status = _escape(_summarize_system_status(error_msg))
        text = (
            f"⚠️ 系統異常\n"
            f"{'─' * 20}\n"
            f"{status}\n"
            f"{'─' * 20}\n"
            f"Bot 已切換為等待語模式，所有訊息仍會轉人工"
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
    """每日統計摘要（可選：設定定時任務呼叫）"""
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
    """將系統錯誤摘要成短句"""
    error_text = (raw_error or "").lower()
    if "credit balance is too low" in error_text:
        return "Anthropic 點數不足"
    if "rate limit" in error_text:
        return "請求過多，請稍後"
    if "timeout" in error_text:
        return "API 逾時"
    trimmed = raw_error.strip().replace("\n", " ")
    return trimmed[:80] + "…" if len(trimmed) > 80 else trimmed
