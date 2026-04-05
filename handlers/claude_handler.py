"""
claude_handler.py — Claude API 意圖辨識 + 品牌語氣回覆生成
使用 claude-haiku 達到速度與成本平衡（每次呼叫約 $0.001 USD）
"""

import json
import logging
from anthropic import AsyncAnthropic

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from knowledge_base import (
    BRAND_VOICE_SYSTEM_PROMPT, INTENTS, INTENT_KEYWORDS,
    STATIC_REPLIES, USE_STATIC_REPLY
)

logger = logging.getLogger(__name__)
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


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

    # Step 1: 快速關鍵字前置篩選（節省 API 費用）
    quick_intent = _quick_keyword_check(user_message)
    if quick_intent and quick_intent in USE_STATIC_REPLY:
        return {
            "intent":        quick_intent,
            "needs_human":   False,
            "auto_reply":    STATIC_REPLIES[quick_intent],
            "priority":      INTENTS[quick_intent]["priority"],
            "reason":        f"關鍵字快速匹配：{INTENTS[quick_intent]['zh']}",
            "confidence":    0.95,
            "used_static":   True,
        }

    # Step 2: 超過輪數閾值 → 轉人工
    from config import HUMAN_TURN_THRESHOLD
    if total_turns >= HUMAN_TURN_THRESHOLD:
        return {
            "intent":        "other",
            "needs_human":   True,
            "auto_reply":    "感謝你的訊息！我們會盡快回覆你 .ᐟ",
            "priority":      "high",
            "reason":        f"對話已達 {total_turns} 輪，自動轉人工處理",
            "confidence":    1.0,
            "used_static":   False,
        }

    # Step 3: 呼叫 Claude 做完整語意分析 + 回覆生成
    result = await _call_claude(user_message, conversation_history)
    return result


# ── Claude API 呼叫 ─────────────────────────────────────────────────────────

async def _call_claude(user_message: str, history: list[dict]) -> dict:
    """呼叫 Claude API，一次完成意圖分類 + 回覆生成"""

    # 格式化歷史對話（最多保留最近 10 輪）
    history_text = ""
    if history:
        recent = history[-10:]
        history_text = "\n".join(
            f"{'顧客' if h['role']=='user' else 'Yvette'}: {h['content']}"
            for h in recent
        )

    # 意圖清單提示
    intent_list = "\n".join(
        f"- {k}: {v['zh']} {'（自動）' if v['auto'] else '（需人工）'}"
        for k, v in INTENTS.items()
    )

    user_prompt = f"""請分析以下顧客訊息並以 JSON 格式回覆。

【近期對話記錄】
{history_text if history_text else "（無歷史）"}

【顧客最新訊息】
{user_message}

【可選意圖清單】
{intent_list}

請輸出以下 JSON（只輸出 JSON，不要其他文字）：
{{
  "intent": "<從上方清單選一個>",
  "needs_human": <true/false>,
  "confidence": <0.0-1.0>,
  "priority": "<low/normal/high/urgent>",
  "reason": "<15字內說明判斷依據>",
  "auto_reply": "<用 Yvette 語氣寫回覆，needs_human=true 時寫「感謝你的訊息！我們會盡快回覆你 .ᐟ」>"
}}

回覆規則：
1. 語氣完全模仿 Yvette（用.ᐟ、♡、😊，不用句號）
2. 訊息簡潔，最多5行
3. needs_human=true 的情況：pre_form_filled、form_submitted、payment_received、custom_design、change_reschedule、complaint
4. 若訊息含「後五碼」「轉帳後」代表顧客已付款，needs_human=true，intent=payment_received
5. 若訊息含完整蛋糕表單欄位（LINE名稱、取貨日期、蛋糕口味）代表顧客填完整單，needs_human=true，intent=form_submitted
6. 若訊息含「預約項目」+「預約日期」代表顧客填完預篩選表單，needs_human=true，intent=pre_form_filled
   → auto_reply 固定回：「收到.ᐟ 我們確認好檔期後會再傳詳細表單給你 請稍待片刻😊」
7. 顧客主動說「想訂」「如何訂」「索取表單」→ needs_human=false，intent=request_form，傳預篩選表單
8. 顧客詢問具體價格金額 → 不要捏造數字，回覆：「價格依口味、尺寸和客製程度不同 歡迎填寫預約資訊後再提供報價😊」
9. 外燴詢問含任何金額/規模問題 → 不要捏造，引導填外燴資訊表"""

    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=BRAND_VOICE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}]
        )

        raw = response.content[0].text.strip()

        # 處理 Claude 有時包在 ```json ... ``` 裡的情況
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)

        # 安全預設值
        result.setdefault("intent",      "other")
        result.setdefault("needs_human", True)
        result.setdefault("confidence",  0.7)
        result.setdefault("priority",    "normal")
        result.setdefault("reason",      "Claude 分析")
        result.setdefault("auto_reply",  "感謝你的訊息！我們會盡快回覆你 .ᐟ")
        result["used_static"] = False

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Claude JSON 解析失敗: {e}\n原始輸出: {raw}")
        return _fallback_response("JSON 解析失敗")
    except Exception as e:
        logger.error(f"Claude API 錯誤: {e}")
        return _fallback_response(str(e))


# ── 工具函數 ────────────────────────────────────────────────────────────────

def _quick_keyword_check(text: str) -> str | None:
    """關鍵字快速比對，命中靜態回覆才回傳意圖"""
    text_lower = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k.lower() in text_lower for k in keywords):
            return intent
    return None


def _fallback_response(reason: str) -> dict:
    """API 出錯時的保底回應"""
    return {
        "intent":      "other",
        "needs_human": True,
        "auto_reply":  "感謝你的訊息！我們會盡快回覆你 .ᐟ",
        "priority":    "normal",
        "reason":      f"fallback：{reason}",
        "confidence":  0.0,
        "used_static": False,
    }
