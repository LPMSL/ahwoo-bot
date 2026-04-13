# 部署審查報告 — 嗷嗚工作室 LINE Chatbot

## 問題清單

### ❌ 嚴重問題

**1. Google 憑證載入方式在 Render 上會失敗**
- `config.py:25`：`GOOGLE_CREDENTIALS_PATH` 預設讀本地檔案路徑 `credentials/google_service_account.json`
- `render.yaml` 沒有設定此路徑，也沒有 `GOOGLE_CREDENTIALS_JSON`（環境變數方案）
- 上線後 Sheets 記錄功能會直接拋錯，但不會中斷 LINE 回覆（因為 `log_conversation` 有 try/except）
- **修法**：在 `config.py` 新增 `GOOGLE_CREDENTIALS_JSON` 讀取邏輯，並加入 `render.yaml`

**2. `.env.example` 不存在**
- `README_部署指南.md:69` 的 `cp .env.example .env` 指令會失敗
- 新人無法得知需要哪些環境變數
- **修法**：建立 `.env.example`

---

### ⚠️ 風險問題

**3. Render Free 冷啟動 vs LINE Webhook Timeout**
- Render Free 閒置後冷啟動約 15–50 秒
- LINE Webhook 要求 1 秒內回傳 HTTP 200，否則重送；最終超時約 30 秒
- 目前架構：`/webhook/line` 先回 `{"status": "ok"}` 再用 `background_tasks` 處理 → HTTP 200 會即時回應 ✅
- **但問題是**：Render Free 冷啟動期間，整個服務還沒起來，LINE 的請求根本進不來 → 這筆訊息會被 LINE 標記為 Webhook 失敗，**不會重送給顧客**
- **修法**：升級 Render Starter（$7/月）或改用不冷啟動的平台

**4. 對話歷史 in-memory，重啟後清空**
- `main.py:51`：`conversation_history` 是 Python dict，存在記憶體
- 每次 Render 部署或重啟，所有進行中的對話歷史歸零
- 顧客再傳訊息，Bot 會當成新對話處理
- **修法**：短期用 Redis 或 Google Sheets 存歷史；長期考慮資料庫

**5. 單 Worker**
- `render.yaml` start command 無 `--workers` 設定，預設單 process
- 同時有多筆訊息進來（例如 LINE 廣播觸發大量回覆）時，會排隊等待
- FastAPI 是 async，能處理並發，但受限於 Python GIL 和單 process，Anthropic API 延遲時會卡住
- **修法**：`uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2`

---

### 📋 小缺失

**6. `CLAUDE_MODEL` hardcode 用舊版名稱**
- `render.yaml:21`：`claude-haiku-4-5-20251001`
- 建議改為 `claude-haiku-4-5`（自動跟最新 patch）或確認版本名稱是否正確

**7. README 未提 Secret Files 的 Render 操作路徑**
- Google 憑證上傳步驟描述模糊，實際操作位置是 Render Dashboard → Service → Secret Files

---

## 部署方案比較

| 方案 | 費用/月 | 冷啟動 | Asia Latency | 持久 Volume | 建議 |
|------|---------|--------|--------------|-------------|------|
| **Render Free** | $0 | 15–50s ❌ | 無亞洲節點 | ❌ | 開發測試用 |
| **Render Starter** | $7 | 無 ✅ | 無亞洲節點 | ❌ | 現階段最省事 ✅ |
| **Fly.io** | $0–$5 | 無（min=1）✅ | 有亞洲節點（NRT/SIN）✅ | 有 ✅ | 長期推薦 |
| **Cloud Run（GCP）** | $0–$3 | 有（min=0）/ 無（min=1）| 有亞洲節點 ✅ | ❌ | 流量低時最省 |

### 推薦路線

**短期（立即可用）**：升級 Render Starter（$7/月）
- 改動最少，只需在 Render Dashboard 切換方案
- 先修 Google 憑證問題

**中期（1–2 個月後）**：遷移至 Fly.io
- 有日本節點（NRT），LINE 訊息 latency 明顯較低
- 支援 persistent volume → 可解決對話歷史問題
- 免費額度：3 shared-cpu-1x + 3GB storage，超出約 $1–3/月

---

## 立即修復清單（優先順序）

1. **建立 `.env.example`** — 5 分鐘
2. **修 `config.py` 支援 `GOOGLE_CREDENTIALS_JSON` 環境變數** — 30 分鐘
3. **更新 `render.yaml` 加入 `GOOGLE_CREDENTIALS_JSON`** — 5 分鐘
4. **升級 Render Starter** — 2 分鐘（在 Render Dashboard 操作）
5. **`render.yaml` start command 加 `--workers 2`** — 5 分鐘
