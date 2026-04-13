"""
test_bot_local.py — Bot 本地測試（不需要任何 API 金鑰）
測試範圍：
  1. 關鍵字快速匹配（_quick_keyword_check）
  2. 靜態回覆是否正確
  3. T2 新增意圖（acknowledgement / catering_inquiry / date_inquiry）
  4. Top 5 Bot 缺口訊息是否有被覆蓋

執行：python test_bot_local.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from knowledge_base import INTENTS, INTENT_KEYWORDS, STATIC_REPLIES, USE_STATIC_REPLY

# ── 複製 claude_handler 的關鍵字快速匹配邏輯（不 import 以避免需要 API KEY）
def _quick_keyword_check(text: str):
    text_lower = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k.lower() in text_lower for k in keywords):
            return intent
    return None

def simulate(user_message: str) -> dict:
    """模擬 analyze_message 的靜態回覆路徑"""
    intent = _quick_keyword_check(user_message)
    if intent and intent in USE_STATIC_REPLY:
        return {
            "matched": True,
            "intent": intent,
            "intent_zh": INTENTS[intent]["zh"],
            "needs_human": False,
            "auto_reply": STATIC_REPLIES.get(intent, "（無靜態回覆）"),
            "used_static": True,
        }
    elif intent:
        return {
            "matched": True,
            "intent": intent,
            "intent_zh": INTENTS[intent]["zh"],
            "needs_human": not INTENTS[intent]["auto"],
            "auto_reply": "→ 會呼叫 Claude API",
            "used_static": False,
        }
    else:
        return {
            "matched": False,
            "intent": "（未命中）",
            "intent_zh": "→ 會呼叫 Claude API",
            "needs_human": True,
            "auto_reply": "→ 會呼叫 Claude API",
            "used_static": False,
        }


# ── 測試案例 ─────────────────────────────────────────────────────────────────
TEST_CASES = [
    # 群組標題, (訊息, 預期意圖)
    ("🔴 T2 新增：Top 5 Bot 缺口訊息（致謝）", [
        ("好的謝謝",          "acknowledgement"),
        ("謝謝您",            "acknowledgement"),
        ("好的 謝謝",         "acknowledgement"),
        ("謝謝你",            "acknowledgement"),
        ("好的！",            "acknowledgement"),
        ("謝謝！",            "acknowledgement"),
        ("謝謝🙏",            "acknowledgement"),
        ("不好意思打擾",       "acknowledgement"),
        ("辛苦了",            "acknowledgement"),
        ("麻煩你了",          "acknowledgement"),
    ]),
    ("🔴 T2 新增：外燴詢問", [
        ("請問有外燴服務嗎",   "catering_inquiry"),
        ("婚禮甜點桌怎麼訂",   "catering_inquiry"),
        ("外燴大概多少錢",     "catering_inquiry"),
        ("活動甜點要幾桌",     "catering_inquiry"),
    ]),
    ("🟡 靜態回覆修復：檔期詢問（原本會呼叫 Claude）", [
        ("最快幾號可以訂",     "date_inquiry"),
        ("這個月還有名額嗎",   "date_inquiry"),
        ("有空檔嗎",           "date_inquiry"),
        ("下個月有空嗎",       "date_inquiry"),
        ("幾號有",             "date_inquiry"),
    ]),
    ("✅ 原有靜態回覆：宅配", [
        ("可以宅配嗎",         "delivery_inquiry"),
        ("台南可以送嗎",       "delivery_inquiry"),
        ("外縣市有送嗎",       "delivery_inquiry"),
    ]),
    ("✅ 原有靜態回覆：索取表單", [
        ("想訂蛋糕",           "request_form"),
        ("怎麼訂",             "request_form"),
        ("填表",               "request_form"),
    ]),
    ("✅ 原有靜態回覆：付款", [
        ("怎麼付款",           "payment_inquiry"),
        ("帳號是多少",         "payment_inquiry"),
        ("可以信用卡嗎",       "payment_inquiry"),
    ]),
    ("✅ 原有靜態回覆：地址/時間", [
        ("工作室在哪",         "pickup_location"),
        ("取貨時間幾點",       "pickup_time"),
    ]),
    ("🟠 需人工：填完預篩選表單", [
        ("預約項目（蛋糕）：4吋草莓\n預約日期：5/15", "pre_form_filled"),
        ("預約項目（外燴）：婚禮\n預約日期：6/1",     "pre_form_filled"),
    ]),
    ("🟠 需人工：客製設計", [
        ("想要人像蛋糕",       "custom_design"),
        ("可以畫Q版嗎",        "custom_design"),
    ]),
    ("🟢 T4 新增靜態：尺寸詢問", [
        ("幾吋比較好",         "size_inquiry"),
        ("4吋幾人份",          "size_inquiry"),
        ("有8吋嗎",            "size_inquiry"),
    ]),
    ("🟢 T4 新增靜態：口味詢問", [
        ("有什麼口味",         "flavor_inquiry"),
        ("有抹茶口味嗎",       "flavor_inquiry"),
        ("內餡可以選什麼",     "flavor_inquiry"),
    ]),
    ("🟢 T4 新增靜態：加購配件", [
        ("有蠟燭嗎",           "addons_inquiry"),
        ("盤叉怎麼加購",       "addons_inquiry"),
        ("可以加插牌嗎",       "addons_inquiry"),
    ]),
]


# ── 執行測試 ─────────────────────────────────────────────────────────────────
def run_tests():
    total = 0
    passed = 0
    failed = []

    for group_name, cases in TEST_CASES:
        print(f"\n{group_name}")
        print("─" * 60)

        for msg, expected_intent in cases:
            result = simulate(msg)
            actual_intent = result["intent"]
            ok = actual_intent == expected_intent
            total += 1
            if ok:
                passed += 1
                status = "✅"
            else:
                failed.append((msg, expected_intent, actual_intent))
                status = "❌"

            static_tag = " [靜態]" if result["used_static"] else " [Claude]"
            print(f"  {status} 「{msg}」→ {actual_intent}{static_tag}")
            if result["used_static"] and ok:
                # 印前 50 字的回覆預覽
                preview = result["auto_reply"][:50].replace("\n", "↵")
                print(f"     回覆預覽：{preview}")

    print("\n" + "═" * 60)
    print(f"結果：{passed}/{total} 通過")
    if failed:
        print("\n❌ 失敗案例：")
        for msg, expected, actual in failed:
            print(f"  「{msg}」 期望={expected}，實際={actual}")
    else:
        print("所有測試通過 ✅")

    # 額外：印出 USE_STATIC_REPLY 清單
    print(f"\n📋 USE_STATIC_REPLY（{len(USE_STATIC_REPLY)} 個意圖）：")
    for intent in sorted(USE_STATIC_REPLY):
        zh = INTENTS.get(intent, {}).get("zh", "?")
        print(f"  - {intent}（{zh}）")


if __name__ == "__main__":
    run_tests()
