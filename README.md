# Chronodrive Dashcam

為 Tesla 行車紀錄器影片嵌入時間戳記、合併多鏡頭畫面，並匯出為影片剪輯 — 完全在瀏覽器中運行，無需安裝任何軟體。

**[線上使用 → chronodrive.tinyomnibus.me](https://chronodrive.tinyomnibus.me)**

Fork 自 [TDashcam Studio](https://github.com/DeaglePC/TDashcamStudio)，大幅改版後以 Chronodrive Dashcam 重新發佈。

---

## 功能特色

### 多鏡頭預覽與剪輯
- 支援 Tesla 六鏡頭視角：前視、後視、左側、右側、左柱、右柱
- 時間軸剪輯工具，可選擇片段起迄時間
- 事件標記與日曆快速篩選

### 匯出選項
- **時間戳記** — 左下角嵌入時間，DejaVu Sans Bold 字型，白字黑色描邊
- **行車狀態** — 顯示車速、方向燈、檔位等 Tesla SEI metadata
- **背景音樂** — 可選擇加入背景音樂
- **色彩調整** — 飽和度、對比、亮度滑桿
- **Logo 浮水印** — 自動嵌入（永遠啟用）
- **Grid 匯出背景** — 多鏡頭拼接畫面使用背景底圖，鏡頭間 6px 間距

### 分享
- 一鍵上傳匯出影片，自動產生分享連結
- 影片託管於 Cloudflare R2，24 小時後自動刪除
- 100MB 大小限制

### 國際化
- 繁體中文 / English 雙語切換
- 自動偵測瀏覽器語系

### 深色模式
- 淺色 / 深色主題切換，CSS Variables 驅動

---

## 快速開始

### 使用線上版

直接前往 **[chronodrive.tinyomnibus.me](https://chronodrive.tinyomnibus.me)**，選擇 Tesla USB 中的 TeslaCam 資料夾即可。

### 本地開發

```bash
git clone https://github.com/go-skyline/chronodrive-dashcam.git
cd chronodrive-dashcam
```

專案為純靜態前端，開啟 `src/index.html` 或使用任意靜態伺服器：

```bash
npx serve src
```

### 部署

專案部署於 Cloudflare Pages，推送至 `main` 分支即自動部署。

分享功能需要設定 Cloudflare R2 bucket（`chronodrive-shares`）作為後端儲存。

---

## 技術架構

| 層級 | 技術 |
|------|------|
| 前端 | 原生 HTML / CSS / JS，單檔架構（無框架） |
| 圖示 | [Lucide Icons](https://lucide.dev) (CDN) |
| 日曆 | [flatpickr](https://flatpickr.js.org) (CDN) |
| Metadata 解析 | protobuf.js（Tesla SEI） |
| 字型 / 音檔 | Cloudflare R2 CDN |
| 分享後端 | Cloudflare Pages Functions + R2 |
| 部署 | Cloudflare Pages |

### 匯出路徑

瀏覽器版使用 **Canvas + MediaRecorder** 進行影片合成與匯出，完全在客戶端運行，不需要伺服器。

---

## 授權

本專案基於 [TDashcam Studio](https://github.com/DeaglePC/TDashcamStudio) 開發，採用 [GNU AGPL-3.0](LICENSE) 授權。
