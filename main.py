"""
main.py — FastAPI 主程式
LINE Messaging API Webhook 接收點
整合 Claude / Telegram / Google Sheets
"""

import asyncio
import logging
import hashlib
import hmac
import base64
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient, AsyncMessagingApi, Configuration,
    ReplyMessageRequest, TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, FollowEvent,
)
from linebot.v3.exceptions import InvalidSignatureError

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from config import (
    LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN,
    PORT, LOG_LEVEL
)
from knowledge_base import INTENTS
from handlers.claude_handler  import analyze_message
from handlers.telegram_handler import (
    notify_human, notify_pre_form_filled,
    notify_form_submitted, notify_payment_received,
    notify_unanswered_alert,
)
from handlers.sheets_handler import log_conversation, get_unanswered_conversations
from handlers.session_handler import get_turns, increment_turns, get_history, append_history


# ── 日誌設定 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── LINE SDK 初始化 ─────────────────────────────────────────────────────────
line_config     = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
line_api_client = AsyncApiClient(configuration=line_config)
line_api        = AsyncMessagingApi(api_client=line_api_client)
parser          = WebhookParser(LINE_CHANNEL_SECRET)


# ── 逾時警報背景掃描 ──────────────────────────────────────────────────────────
ALERT_INTERVAL_HOURS = 1   # 每小時掃描一次

async def _unanswered_alert_loop():
    """每小時掃描 Google Sheets，對逾時未回覆的對話發送 Telegram 警報"""
    await asyncio.sleep(60)   # 啟動後等 1 分鐘再開始第一次掃描
    while True:
        try:
            conversations = await get_unanswered_conversations(hours_threshold=4)
            if conversations:
                await notify_unanswered_alert(conversations)
                logger.info(f"逾時警報掃描完成：{len(conversations)} 個對話待回覆")
            else:
                logger.debug("逾時警報掃描：無待回覆對話")
        except Exception as e:
            logger.error(f"逾時警報掃描失敗: {e}")
        await asyncio.sleep(ALERT_INTERVAL_HOURS * 3600)


# ── FastAPI App ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🐺 嗷嗚工作室 Chatbot 啟動！")
    alert_task = asyncio.create_task(_unanswered_alert_loop())
    yield
    alert_task.cancel()
    logger.info("Chatbot 關閉")

app = FastAPI(title="嗷嗚工作室 LINE Chatbot", lifespan=lifespan)


# ── 健康檢查（Render 用）────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "ahwoo-chatbot"}


# ── LINE Webhook 主入口 ─────────────────────────────────────────────────────
@app.post("/webhook/line")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    """接收 LINE 所有事件的 Webhook endpoint"""

    body      = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    # 驗證簽名
    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        logger.warning("LINE 簽名驗證失敗")
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        # 新顧客加入（Follow 事件）
        if isinstance(event, FollowEvent):
            background_tasks.add_task(_handle_follow, event)

        # 文字訊息
        elif isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            background_tasks.add_task(_handle_text_message, event)

    return JSONResponse(content={"status": "ok"})


# ── 事件處理：Follow ─────────────────────────────────────────────────────────
async def _handle_follow(event: FollowEvent):
    """新顧客加入時傳送歡迎訊息"""
    try:
        welcome = (
            "嗷嗚工作室 𝐚𝐡𝐰𝐨𝐨𝐝𝐞𝐬𝐬𝐞𝐫𝐭. 🐺\n"
            "—\n"
            "客製蛋糕｜外燴甜點桌｜專門店。\n"
            "—\n"
            "點擊下方選單預約 .ᐟ.ᐟ\n"
            "有相關訂購問題都可以詢問🥞✨。\n"
            "—\n"
            "訂購前請詳閱訂購指南。"
        )
        await line_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome)],
            )
        )
    except Exception as e:
        logger.error(f"Follow 事件處理失敗: {e}")


# ── 事件處理：Text Message ───────────────────────────────────────────────────
async def _handle_text_message(event: MessageEvent):
    """
    核心流程：
    1. 取得顧客資訊
    2. 用 Claude 分析意圖
    3. 自動回覆 LINE
    4. 若需人工 → Telegram 通知
    5. 全程寫入 Google Sheets
    """
    user_id      = event.source.user_id
    reply_token  = event.reply_token
    message_text = event.message.text.strip()

    # 取得顯示名稱
    display_name = await _get_display_name(user_id)

    # 從 Redis 取得輪數與歷史
    total_turns = await increment_turns(user_id)
    history     = await get_history(user_id)

    logger.info(f"[{display_name}] 輪{total_turns}: {message_text[:60]}")

    # ── Claude 分析 ──────────────────────────────────────────────────────
    analysis = await analyze_message(
        user_message=message_text,
        conversation_history=history,
        total_turns=total_turns,
    )

    intent       = analysis["intent"]
    needs_human  = analysis["needs_human"]
    auto_reply   = analysis["auto_reply"]
    priority     = analysis["priority"]
    reason       = analysis["reason"]
    confidence   = analysis["confidence"]
    used_static  = analysis["used_static"]
    intent_zh    = INTENTS.get(intent, {}).get("zh", intent)

    # ── 更新對話歷史到 Redis ──────────────────────────────────────────────
    await append_history(user_id, message_text, auto_reply)

    # ── 自動回覆 LINE ─────────────────────────────────────────────────────
    reply_sent = False
    try:
        await line_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=auto_reply)],
            )
        )
        reply_sent = True
        logger.info(f"LINE 回覆已送出 → {display_name}: {auto_reply[:50]}")
    except Exception as e:
        logger.error(f"LINE 回覆失敗: {e}")

    # ── Telegram 通知（需人工時）─────────────────────────────────────────
    telegram_ok = False
    if needs_human:
        # 特殊意圖用專屬通知格式
        if intent == "pre_form_filled":
            telegram_ok = await notify_pre_form_filled(display_name, message_text)
        elif intent == "form_submitted":
            telegram_ok = await notify_form_submitted(display_name, message_text)
        elif intent == "payment_received":
            telegram_ok = await notify_payment_received(display_name, message_text)
        else:
            telegram_ok = await notify_human(
                user_id=user_id,
                display_name=display_name,
                message=message_text,
                intent=intent,
                priority=priority,
                reason=reason,
                total_turns=total_turns,
            )

    # ── Google Sheets 記錄 ────────────────────────────────────────────────
    await log_conversation(
        user_id=user_id,
        display_name=display_name,
        message=message_text,
        intent=intent,
        intent_zh=intent_zh,
        auto_reply=auto_reply if reply_sent else None,
        needs_human=needs_human,
        priority=priority,
        reason=reason,
        confidence=confidence,
        total_turns=total_turns,
        used_static=used_static,
        telegram_ok=telegram_ok,
    )


# ── 工具：取得 LINE 顯示名稱 ──────────────────────────────────────────────────
async def _get_display_name(user_id: str) -> str:
    try:
        profile = await line_api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return user_id[:8]


# ── 程式入口 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
