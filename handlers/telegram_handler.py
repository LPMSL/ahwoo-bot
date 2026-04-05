"""
telegram_handler.py — 人工介入通知系統
當 Claude 判斷需要人工處理時，透過 Telegram 通知 Yvette
包含：顧客名稱、訊息內容、意圖類別、優先等級、LINE 直連連結
"""

import logging
from telegram import Bot
from telegram.constants import ParseMode

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

# 優先等級 Emoji 對應
PRIORITY_EMOJI = {
    "low":    "🔵",
    "normal": "🟡",
    "high":   "🟠",
    "urgent": "🔴",
}

# 意圖中文對應
INTENT_ZH = {
    "pre_form_filled":   "📝 顧客已填回預約項目＋日期（待確認檔期）",
    "form_submitted":    "📋 顧客已填寫完整蛋糕表單",
    "payment_received":  "💰 顧客已付款",
    "custom_design":     "🎨 客製設計需求",
    "change_reschedule": "📅 要求改期/取消",
    "complaint":         "😤 顧客抱怨",
    "date_inquiry":      "📆 詢問檔期",
    "other":             "❓ 其他需確認",
}


async def notify_human(
    user_id:       str,
    display_name:  str,
    message:       str,
    intent:        str,
    priority:      str,
    reason:        str,
    total_turns:   int,
) -> bool:
    """
    發送 Telegram 通知給 Yvette
    回傳 True 成功 / False 失敗
    """
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        emoji = PRIORITY_EMOJI.get(priority, "🟡")
        intent_text = INTENT_ZH.get(intent, f"意圖：{intent}")
        turns_warning = f"\n⚠️ 已對話 {total_turns} 輪" if total_turns >= 10 else ""

        # 截斷過長訊息
        msg_preview = message[:300] + "…" if len(message) > 300 else message

        text = (
            f"{emoji} *需要人工回覆*\n"
            f"{'─' * 28}\n"
            f"👤 *顧客：* {_escape(display_name)}\n"
            f"🏷️ *類別：* {_escape(intent_text)}\n"
            f"💬 *訊息：*\n{_escape(msg_preview)}\n"
            f"{'─' * 28}\n"
            f"🔍 *判斷依據：* {_escape(reason)}{turns_warning}\n\n"
            f"👉 [前往 LINE OA 回覆](https://manager.line.biz/)"
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
    """
    預篩選表單回填通知（最高頻觸發點）
    顧客填完「預約項目＋日期」後通知 Yvette 確認檔期
    """
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        text = (
            f"📝 *預約資訊已收到 \\— 請確認檔期* \\!\n"
            f"{'─' * 28}\n"
            f"👤 *顧客：* {_escape(display_name)}\n\n"
            f"```\n{message[:300]}\n```\n\n"
            f"✅ 系統已自動回覆顧客稍待\n"
            f"👉 確認好檔期後請至 LINE OA 傳完整表單\n"
            f"[前往 LINE OA](https://manager.line.biz/)"
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
    """表單提交專用通知（格式化清晰）"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        text = (
            f"📋 *新訂購表單* \\!\n"
            f"{'─' * 28}\n"
            f"👤 *顧客：* {_escape(display_name)}\n\n"
            f"```\n{form_content[:800]}\n```\n\n"
            f"👉 [前往 LINE OA 確認](https://manager.line.biz/)"
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
    display_name:  str,
    message:       str,
) -> bool:
    """付款通知（高優先）"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        text = (
            f"💰 *收到付款通知* \\!\n"
            f"{'─' * 28}\n"
            f"👤 *顧客：* {_escape(display_name)}\n\n"
            f"```\n{message[:400]}\n```\n\n"
            f"👉 [前往 LINE OA 確認](https://manager.line.biz/)"
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
    """
    逾時未回覆警報（每小時背景掃描觸發）
    列出所有等待超過 4 小時的對話
    """
    if not conversations:
        return True
    try:
        bot   = Bot(token=TELEGRAM_BOT_TOKEN)
        count = len(conversations)

        lines = [f"⏰ *{_escape(str(count))} 個對話等待人工回覆超過 4 小時*\n{'─' * 28}"]
        for c in conversations[:10]:   # 最多顯示 10 筆
            emoji    = PRIORITY_EMOJI.get(c["priority"], "🟡")
            hrs      = c["waiting_hours"]
            name     = _escape(c["display_name"])
            intent   = _escape(c.get("intent_zh", ""))
            msg_prev = _escape(c["message"][:80] + ("…" if len(c["message"]) > 80 else ""))
            lines.append(
                f"{emoji} *{name}* \\— 等待 {_escape(str(hrs))} 小時\n"
                f"   {intent}\n"
                f"   _{msg_prev}_"
            )

        lines.append(f"{'─' * 28}\n👉 [前往 LINE OA 回覆](https://manager\\.line\\.biz/)")
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


async def send_daily_summary(stats: dict) -> bool:
    """每日統計摘要（可選：設定定時任務呼叫）"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        text = (
            f"📊 *昨日 LINE OA 統計*\n"
            f"{'─' * 28}\n"
            f"💬 總訊息數：{stats.get('total_messages', 0)}\n"
            f"👥 活躍對話：{stats.get('active_conversations', 0)}\n"
            f"🤖 自動回覆：{stats.get('auto_replies', 0)}\n"
            f"🙋 轉人工：{stats.get('human_handoffs', 0)}\n"
            f"📋 收到表單：{stats.get('forms_received', 0)}\n"
            f"💰 收到付款：{stats.get('payments_received', 0)}\n"
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
