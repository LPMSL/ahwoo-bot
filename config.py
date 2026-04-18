"""
config.py — 環境變數集中管理
所有 Secret 透過 .env (本地) 或 Render Environment Variables (雲端) 注入
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── LINE Messaging API ──────────────────────────────────────────────────────
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_OA_ACCOUNT_ID        = os.getenv("LINE_OA_ACCOUNT_ID", "")  # LINE OA 帳號 ID（U 開頭），從 chat.line.biz/{這串}/chat/... 取得

# ── Anthropic Claude API（v2.0 已移除 Claude 呼叫，保留可選避免舊 env var 報錯）──
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")   # 不再必填
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "")         # 不再使用

# ── Telegram Bot ────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]   # Yvette 的 chat_id

# ── Google Sheets ───────────────────────────────────────────────────────────
GOOGLE_SHEET_ID           = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS_PATH   = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/google_service_account.json")
GOOGLE_CREDENTIALS_JSON   = os.getenv("GOOGLE_CREDENTIALS_JSON")   # Render 雲端部署用（JSON 字串）
GOOGLE_SHEET_TAB          = os.getenv("GOOGLE_SHEET_TAB", "LINE對話記錄")

# ── Upstash Redis ────────────────────────────────────────────────────────────
UPSTASH_REDIS_REST_URL   = os.environ["UPSTASH_REDIS_REST_URL"]
UPSTASH_REDIS_REST_TOKEN = os.environ["UPSTASH_REDIS_REST_TOKEN"]

# ── App Settings ─────────────────────────────────────────────────────────────
PORT              = int(os.getenv("PORT", 8000))
LOG_LEVEL         = os.getenv("LOG_LEVEL", "info")
HUMAN_TURN_THRESHOLD = int(os.getenv("HUMAN_TURN_THRESHOLD", "10"))  # 超過幾輪轉人工
