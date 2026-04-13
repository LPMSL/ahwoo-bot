# Render 環境變數設定指南

## GOOGLE_CREDENTIALS_JSON

### Step 1 — 取得 Service Account JSON 內容

在本機終端執行：

```bash
cat /path/to/credentials/google_service_account.json
```

複製輸出的完整 JSON（從 `{` 到最後的 `}`）。

---

### Step 2 — 到 Render Dashboard 新增環境變數

1. 前往 dashboard.render.com
2. 點擊 **ahwoo-chatbot** 服務
3. 左側選單點 **Environment**
4. 點 **Add Environment Variable**
5. 填入：
   - **Key**: `GOOGLE_CREDENTIALS_JSON`
   - **Value**: 貼上完整 JSON 內容
6. 點 **Save Changes**

Render 會自動重新部署。等部署完成後，到 **Logs** 確認沒有 Google Sheets 相關錯誤。

### 注意事項

- JSON 內容直接貼入，不需要加引號或轉義
- 現有的 `GOOGLE_CREDENTIALS_PATH` 可以留著（本地開發用），雲端會優先用 `GOOGLE_CREDENTIALS_JSON`

---

## 升級 Render Starter（選擇性）

**原因**：Free tier 有冷啟動（~15 秒），LINE Webhook timeout 為 30 秒，流量低時可能超時。

**方式**：
1. 服務頁面 → **Settings** → **Instance Type**
2. 選 **Starter**（$7/月）
3. **Save**

---

## 完整環境變數清單

| Key | 說明 | 來源 |
|-----|------|------|
| `LINE_CHANNEL_SECRET` | LINE Messaging API 密鑰 | LINE Developers Console |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE API Token | LINE Developers Console |
| `ANTHROPIC_API_KEY` | Claude API Key | console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram 通知目標 Chat ID | 用 @userinfobot 查詢 |
| `GOOGLE_SHEET_ID` | Google Sheet ID（URL 中的長字串） | Google Sheets URL |
| `GOOGLE_CREDENTIALS_JSON` | Service Account JSON 完整內容 | Google Cloud Console |
| `CLAUDE_MODEL` | `claude-haiku-4-5` | 已在 render.yaml 設定 |
| `LOG_LEVEL` | `info` | 已在 render.yaml 設定 |
| `HUMAN_TURN_THRESHOLD` | `10` | 已在 render.yaml 設定 |
