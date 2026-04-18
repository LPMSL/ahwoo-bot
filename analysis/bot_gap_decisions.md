# Bot Gap 決策文件 — 嗷嗚工作室

## 資料來源
- `summary.md`（4,594 對話、34,009 則文字訊息分析）
- T2 完成後的 `knowledge_base.py`（9 個靜態意圖）
- T3 測試結果（34/34 通過）

---

## 決策一：靜態回覆擴充（T4 執行）

### 現狀
T2 後 `USE_STATIC_REPLY` 有 9 個意圖。以下意圖仍呼叫 Claude API，但答案是固定的：

| 意圖 | 頻率 | 決策 |
|------|------|------|
| `size_inquiry` | 中 | ✅ 改靜態回覆（尺寸固定） |
| `flavor_inquiry` | 中 | ✅ 改靜態回覆（口味固定） |
| `addons_inquiry` | 低 | ✅ 改靜態回覆（配件固定） |
| `price_inquiry` | 高 | ⚠️ **暫留 Claude**（見下方說明） |

**price_inquiry 特殊說明：**
目前 `BRAND_VOICE_SYSTEM_PROMPT` 和 `knowledge_base.py` 皆無實際價格資料。Claude 無法正確回答，回覆品質不可靠。
→ **需要 Yvette 提供各尺寸定價** 後才能寫靜態回覆或加入 System Prompt。

---

## 決策二：System Prompt 調整（T4 執行）

### 現狀問題
1. System Prompt 無定價資訊 → Claude 無法回答價格問題
2. 無明確指示「不要自創價格」→ Claude 可能幻覺
3. 邊緣案例處理不清：顧客問「外燴大概幾人起跳」Claude 可能自創數字

### T4 修改方向
- 加入「**不要編造價格**」明確指令
- 加入「外燴報價需填表，不要給任何具體數字」規則
- 簡化 System Prompt 中重複的表單文字（已在 `_call_claude` prompt 裡重複）

---

## 決策三：跨對話記憶

### 現狀
`conversation_history` 是 in-memory dict，每次 Render 重啟後清空。

### 評估
| 方案 | 成本 | 複雜度 | 效益 |
|------|------|--------|------|
| 維持 in-memory | 0 | 無 | 單次對話記憶正常 |
| Redis | $10+/月 | 中 | 跨重啟保留記憶 |
| 讀 Google Sheets 歷史 | 0 | 高 | 有延遲，Sheets API 限速 |

### 決策
**維持 in-memory。** 理由：
1. 大多數顧客對話在一次 session 內完成
2. Render Starter 重啟頻率低（每次 deploy 才重啟）
3. 引入 Redis 增加架構複雜度與費用，邊際效益低

未來擴充點：若 Render 頻繁重啟或對話跨天，改用 Sheets 歷史讀取最後 5 則。

---

## 決策四：HUMAN_TURN_THRESHOLD

### 現狀
`config.py` 預設 15 輪轉人工。

### 決策
**改為 10 輪。** 理由：
- 資料顯示真實對話中位數回覆時間 972 分鐘（~16 小時）
- 若對話超過 10 輪仍未解決，人工介入比自動回覆更有效
- 10 輪足以完成完整下單流程（問詢 → 填表 → 付款確認）

---

## 決策五：意圖關鍵字排序（已在 T3 測試中執行）

**已完成：**
- `pre_form_filled` / `form_submitted` / `payment_received` 移至最前
- `catering_inquiry` 移至 `price_inquiry` 之前
- `delivery_inquiry` 新增 "可以送" / "送嗎" / "有送"
- `date_inquiry` 新增 "幾號有"
- `_quick_keyword_check` 改為 `k.lower() in text_lower`（修正大寫關鍵字 bug）

---

## T4 待執行清單

1. `knowledge_base.py`
   - [ ] 新增 `size_inquiry` 靜態回覆
   - [ ] 新增 `flavor_inquiry` 靜態回覆
   - [ ] 新增 `addons_inquiry` 靜態回覆
   - [ ] `USE_STATIC_REPLY` 加入以上 3 個
   - [ ] `BRAND_VOICE_SYSTEM_PROMPT` 加入「不編造價格」規則

2. `claude_handler.py`
   - [ ] `_call_claude` prompt 加入外燴/價格邊緣案例規則

3. `config.py`
   - [ ] `HUMAN_TURN_THRESHOLD` 預設改為 10

---

## 待確認（需 Yvette 提供）

- 各尺寸蛋糕定價（4吋 / 6吋 / 8吋）
- 外燴甜點桌起跳人數與大概報價範圍
- 是否有季節性口味需要定期更新的機制
