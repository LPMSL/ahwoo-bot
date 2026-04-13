# 嗷嗚工作室 LINE Chatbot — 部署指南
## 架構總覽

```
LINE 顧客訊息
     │
     ▼
LINE Messaging API
     │
     ▼
FastAPI Webhook（Render 托管）
     │
     ├──► Claude Haiku  →  意圖辨識 + Yvette 語氣回覆
     │         │
     │         ▼
     │    LINE 自動回覆
     │
     ├──► Telegram Bot  →  需人工時通知 Yvette
     │
     └──► Google Sheets →  完整對話記錄（可接 Looker Studio）
```

---

## Step 1 — 準備 API Keys（5 個）

### 1-1 LINE Messaging API
1. 前往 https://developers.line.biz/
2. 建立 Provider → 建立 Messaging API Channel
3. Basic settings → 複製 **Channel Secret**
4. Messaging API → Issue **Channel Access Token（長期）**

### 1-2 Anthropic Claude API
1. 前往 https://console.anthropic.com/
2. API Keys → Create Key
3. 複製 `sk-ant-...` 開頭的金鑰

### 1-3 Telegram Bot
```bash
# 1. 在 Telegram 搜尋 @BotFather
# 2. 傳送 /newbot，取得 BOT_TOKEN（格式：123456:ABCxxx）

# 3. 取得你自己的 chat_id：
#    搜尋 @userinfobot，傳送任意訊息，它會回覆你的 ID
```

### 1-4 Google Sheets Service Account
1. 前往 https://console.cloud.google.com/
2. 建立新專案（或用既有的）
3. 啟用 **Google Sheets API** 和 **Google Drive API**
4. IAM & Admin → Service Accounts → 建立新帳戶
5. 下載 JSON 金鑰 → 存為 `credentials/google_service_account.json`
6. 建立 Google Sheet → 複製 URL 中的 Sheet ID
   - URL 格式：`https://docs.google.com/spreadsheets/d/**[SHEET_ID]**/edit`
7. 把 Sheet 共享給 Service Account 的 Email（編輯者權限）

---

## Step 2 — 本地測試

```bash
# 複製專案
cd ahwoo_chatbot

# 安裝套件
pip install -r requirements.txt

# 建立 .env
cp .env.example .env
# 用文字編輯器填入所有 Key

# 確認 Google 憑證放好
ls credentials/google_service_account.json

# 啟動本地伺服器
uvicorn main:app --reload --port 8000

# 用 ngrok 建立臨時公開 URL 來測試 LINE Webhook
ngrok http 8000
# 複製 https://xxxx.ngrok.io 這個 URL
```

---

## Step 3 — 部署到 Render（免費方案）

```bash
# 1. 將專案推到 GitHub
git init
git add .
git commit -m "init ahwoo chatbot"
git remote add origin https://github.com/YOUR_USERNAME/ahwoo-chatbot.git
git push -u origin main

# 2. 前往 https://render.com/
# 3. New → Web Service → 選你的 GitHub repo
# 4. 設定：
#    - Runtime: Python 3
#    - Build Command: pip install -r requirements.txt
#    - Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
# 5. Environment Variables（逐一填入）：
#    LINE_CHANNEL_SECRET
#    LINE_CHANNEL_ACCESS_TOKEN
#    ANTHROPIC_API_KEY
#    TELEGRAM_BOT_TOKEN
#    TELEGRAM_CHAT_ID
#    GOOGLE_SHEET_ID

# 6. 關於 Google 憑證 JSON：
#    方案 A：把 JSON 內容貼到環境變數 GOOGLE_CREDENTIALS_JSON
#    方案 B：用 Render 的 Secret Files 功能上傳 JSON 檔
```

---

## Step 4 — 設定 LINE Webhook URL

1. 前往 LINE Developers Console
2. Messaging API → Webhook settings
3. Webhook URL 填入：`https://your-app.onrender.com/webhook/line`
4. 點 Verify → 應顯示 Success
5. 開啟 **Use webhook**

---

## 檔案結構

```
ahwoo_chatbot/
├── main.py                    # FastAPI 主程式 + LINE Webhook
├── config.py                  # 環境變數管理
├── knowledge_base.py          # 品牌語氣 + 回覆知識庫
├── requirements.txt           # Python 套件
├── render.yaml                # Render 部署設定
├── .env.example               # 環境變數範本
├── handlers/
│   ├── claude_handler.py      # Claude API 意圖辨識 + 回覆生成
│   ├── telegram_handler.py    # Telegram 人工介入通知
│   └── sheets_handler.py      # Google Sheets 對話記錄
└── credentials/
    └── google_service_account.json  # Google 憑證（不要 commit 進 git！）
```

---

## Google Sheet 欄位說明

| 欄位 | 說明 | Looker Studio 用途 |
|------|------|-------------------|
| 時間戳記 | 完整時間 | 時間軸分析 |
| 日期 | 僅日期 | 日維度 |
| 星期 | 週一~週日 | 星期分布 |
| 小時 | 0-23 | 時段熱力圖 |
| 用戶ID | LINE user_id | 唯一識別 |
| 顯示名稱 | LINE 暱稱 | 顧客識別 |
| 用戶訊息 | 訊息內容 | 內容分析 |
| 意圖分類 | 英文代碼 | 分類篩選 |
| 意圖說明 | 中文說明 | 顯示用 |
| 自動回覆 | 是/否 | 自動化率 |
| 回覆內容 | 回覆文字 | 品質審查 |
| 需要人工 | 是/否 | 人工率 |
| 優先等級 | low/normal/high/urgent | 緊急度 |
| 判斷依據 | Claude 說明 | 除錯 |
| 信心值 | 0-1 | 準確度監控 |
| 對話輪數 | 數字 | 甜蜜輪數分析 |
| 靜態回覆 | 是/否 | API 費用監控 |
| Telegram通知 | 是/否 | 通知成功率 |

---

## 費用估算

| 項目 | 費用 | 備註 |
|------|------|------|
| Render Free | $0/月 | 免費方案，閒置會 sleep（約 15 秒冷啟動） |
| Render Starter | $7/月 | 不 sleep，推薦用這個 |
| Claude Haiku | ~$0.001/次 | 靜態回覆不計費，每月約 $1-3 USD |
| Telegram Bot | $0 | 完全免費 |
| Google Sheets | $0 | 免費（在配額內） |
| **總計** | **$7-10/月** | |

---

## 常見問題

**Q: LINE Webhook 一直 timeout？**
A: Render Free 方案有冷啟動問題，請升級 Starter 方案，或每 14 分鐘 ping 一次 /health

**Q: Claude 回覆語氣不對？**
A: 修改 `knowledge_base.py` 中的 `BRAND_VOICE_SYSTEM_PROMPT`，加入更多範例訊息

**Q: Google Sheets 寫入失敗？**
A: 確認 Service Account Email 有該 Sheet 的編輯者權限

**Q: Telegram 收不到通知？**
A: 先傳一則訊息給你的 Bot（需要先啟動對話），再確認 TELEGRAM_CHAT_ID 正確

---

*由 LP Motion Science Lab 分析 + Claude 開發*
