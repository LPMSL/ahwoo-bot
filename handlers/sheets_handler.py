"""
sheets_handler.py — Google Sheets 對話記錄
每筆訊息自動寫入 Google Sheet，欄位設計可直接套用 Looker Studio 儀表板
"""

import logging
import traceback
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_PATH, GOOGLE_CREDENTIALS_JSON, GOOGLE_SHEET_TAB

logger = logging.getLogger(__name__)

# 台灣時區 UTC+8
TW_TZ = timezone(timedelta(hours=8))

# Google Sheets API 權限範圍
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Google Sheet 欄位標題（第一列）
SHEET_HEADERS = [
    "時間戳記",          # A - datetime
    "日期",              # B - date only
    "星期",              # C - weekday
    "小時",              # D - hour (0-23)
    "用戶ID",            # E - LINE user_id
    "顯示名稱",          # F - display_name
    "用戶訊息",          # G - message content
    "意圖分類",          # H - intent
    "意圖說明",          # I - intent zh
    "自動回覆",          # J - auto reply sent
    "回覆內容",          # K - reply content
    "需要人工",          # L - needs_human (TRUE/FALSE)
    "優先等級",          # M - priority
    "判斷依據",          # N - reason
    "信心值",            # O - confidence (0-1)
    "對話輪數",          # P - turn count
    "靜態回覆",          # Q - used_static (TRUE/FALSE)
    "Telegram通知",      # R - telegram_notified
]


def _get_sheet():
    """初始化並回傳 Google Sheet worksheet
    優先使用環境變數 GOOGLE_CREDENTIALS_JSON（Render 雲端），
    fallback 至本地檔案 GOOGLE_CREDENTIALS_PATH（本地開發）。
    """
    if GOOGLE_CREDENTIALS_JSON:
        creds = Credentials.from_service_account_info(
            json.loads(GOOGLE_CREDENTIALS_JSON), scopes=SCOPES
        )
    else:
        creds = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
        )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)

    # 如果 tab 不存在就建立
    try:
        ws = sh.worksheet(GOOGLE_SHEET_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=GOOGLE_SHEET_TAB, rows=10000, cols=20)
        ws.append_row(SHEET_HEADERS, value_input_option="RAW")
        # 凍結標題列 + 設定基本格式
        ws.freeze(rows=1)
        logger.info(f"Google Sheet tab 已建立：{GOOGLE_SHEET_TAB}")

    return ws


async def log_conversation(
    user_id:      str,
    display_name: str,
    message:      str,
    intent:       str,
    intent_zh:    str,
    auto_reply:   str | None,
    needs_human:  bool,
    priority:     str,
    reason:       str,
    confidence:   float,
    total_turns:  int,
    used_static:  bool,
    telegram_ok:  bool,
) -> bool:
    """
    寫入一列對話記錄到 Google Sheet
    設計為 async 但 gspread 是同步庫 → 用 try/except 包裹即可
    """
    try:
        now_tw = datetime.now(TW_TZ)

        weekday_zh = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"][now_tw.weekday()]

        row = [
            now_tw.strftime("%Y/%m/%d %H:%M:%S"),  # 時間戳記
            now_tw.strftime("%Y/%m/%d"),            # 日期
            weekday_zh,                              # 星期
            now_tw.hour,                             # 小時
            user_id,                                 # 用戶ID
            display_name,                            # 顯示名稱
            message[:500],                           # 用戶訊息（截斷）
            intent,                                  # 意圖分類
            intent_zh,                               # 意圖說明
            "是" if auto_reply else "否",            # 自動回覆
            (auto_reply or "")[:300],                # 回覆內容（截斷）
            "是" if needs_human else "否",           # 需要人工
            priority,                                # 優先等級
            reason,                                  # 判斷依據
            round(confidence, 2),                    # 信心值
            total_turns,                             # 對話輪數
            "是" if used_static else "否",           # 靜態回覆
            "是" if telegram_ok else "否",           # Telegram通知
        ]

        ws = _get_sheet()
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Google Sheets 記錄成功：{display_name} / {intent}")
        return True

    except Exception as e:
        logger.error(f"Google Sheets 寫入失敗: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return False


async def get_unanswered_conversations(hours_threshold: int = 4) -> list:
    """
    掃描 Sheets，找出逾時未獲人工回覆的對話
    條件：
    - 有 needs_human=是 的訊息
    - 該用戶最後一則訊息距今超過 hours_threshold 小時（表示 Yvette 尚未回應且顧客仍在等待）
    - 距今不超過 48 小時（避免重複舊警報）
    回傳：[{user_id, display_name, message, intent_zh, priority, waiting_hours}, ...]
    """
    try:
        ws       = _get_sheet()
        all_rows = ws.get_all_records()
        now_tw   = datetime.now(TW_TZ)

        # 依 user_id 分組：記錄最新 needs_human 訊息 與 最新任意訊息
        latest_needs_human: dict = {}
        latest_any:         dict = {}

        for row in all_rows:
            uid  = row.get("用戶ID", "")
            ts_s = row.get("時間戳記", "")
            if not uid or not ts_s:
                continue
            try:
                ts = datetime.strptime(ts_s, "%Y/%m/%d %H:%M:%S").replace(tzinfo=TW_TZ)
            except ValueError:
                continue

            # 更新最新任意訊息
            if uid not in latest_any or ts > latest_any[uid]["ts"]:
                latest_any[uid] = {"ts": ts}

            # 更新最新 needs_human 訊息
            if row.get("需要人工") == "是":
                if uid not in latest_needs_human or ts > latest_needs_human[uid]["ts"]:
                    latest_needs_human[uid] = {
                        "ts":          ts,
                        "display_name": row.get("顯示名稱", uid),
                        "message":     row.get("用戶訊息", ""),
                        "intent_zh":   row.get("意圖說明", ""),
                        "priority":    row.get("優先等級", "normal"),
                    }

        alerts = []
        for uid, nh in latest_needs_human.items():
            waiting_secs = (now_tw - nh["ts"]).total_seconds()
            waiting_hrs  = waiting_secs / 3600

            # 逾時窗口：4–48 小時
            if not (hours_threshold <= waiting_hrs <= 48):
                continue

            # 如果顧客在 needs_human 之後又傳了新訊息，表示對話仍在進行，跳過
            latest = latest_any.get(uid, {}).get("ts", nh["ts"])
            if latest > nh["ts"]:
                continue

            alerts.append({
                "user_id":      uid,
                "display_name": nh["display_name"],
                "message":      nh["message"],
                "intent_zh":    nh["intent_zh"],
                "priority":     nh["priority"],
                "waiting_hours": round(waiting_hrs, 1),
            })

        # 依等待時間降冪排列（最久未回的排最前）
        alerts.sort(key=lambda x: x["waiting_hours"], reverse=True)
        return alerts

    except Exception as e:
        logger.error(f"get_unanswered_conversations 失敗: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return []


async def get_daily_stats(date_str: str | None = None) -> dict:
    """
    查詢指定日期的統計數字（給每日摘要用）
    date_str 格式：'2026/03/20'，None 表示今天
    """
    try:
        ws = _get_sheet()
        all_rows = ws.get_all_records()

        if not date_str:
            date_str = datetime.now(TW_TZ).strftime("%Y/%m/%d")

        day_rows = [r for r in all_rows if r.get("日期") == date_str]

        return {
            "total_messages":        len(day_rows),
            "active_conversations":  len(set(r.get("用戶ID","") for r in day_rows)),
            "auto_replies":          sum(1 for r in day_rows if r.get("自動回覆") == "是"),
            "human_handoffs":        sum(1 for r in day_rows if r.get("需要人工") == "是"),
            "forms_received":        sum(1 for r in day_rows if r.get("意圖分類") == "form_submitted"),
            "payments_received":     sum(1 for r in day_rows if r.get("意圖分類") == "payment_received"),
        }

    except Exception as e:
        logger.error(f"Google Sheets 查詢失敗: {e}")
        return {}
