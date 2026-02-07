# Chronodrive Dashcam - Fork 更新說明

本專案 fork 自 [TDashcam Studio](https://github.com/DeaglePC/TDashcamStudio)，以下為 fork 後的功能更新與改動摘要。

---

## 重新品牌

- 專案名稱：TDashcam Studio → **Chronodrive Dashcam**
- 線上版部署於 [chronodrive.tinyomnibus.me](https://chronodrive.tinyomnibus.me)
- 定位為**純瀏覽器 serverless 版本**（Cloudflare Pages），不再提供桌面版

---

## 新增功能

### 匯出增強
- **Logo 浮水印**：匯出影片右上角自動嵌入 Logo（永遠啟用）
- **背景音樂**：匯出時可選擇加入背景音樂（隨機選曲）
- **色彩調整**：匯出對話框新增飽和度（0\~200）、對比（50\~150）、亮度（50\~150）滑桿，可即時調整匯出影片色彩
- **匯出背景底圖**：Grid 匯出畫面背景改用 `space-bg.jpg` 取代純黑底色
- **格線間距**：Grid 匯出各鏡頭之間加入 6px 間距

### 時間戳改版
- 位置：右上角 → 左下角
- 字型：改用 DejaVu Sans Bold（透過 Cloudflare R2 CDN 載入）
- 樣式：去除黑底色塊，改為白字 + 黑色描邊，半透明圓角區塊

---

## UI 改版

### 色彩主題
- 紫色漸層主題 → **海軍藍 (#234C6A) + 金黃強調 (#f0c040)** 純色主題
- 所有 `linear-gradient` 漸層移除，全部改為純色
- 選擇資料夾按鈕改為黃底深色字
- 進度條、剪輯手把、視角按鈕 active 狀態統一使用黃色

### 圖示系統
- 所有 Emoji 圖示替換為 **Lucide Icons**（SVG icon library）
- 涵蓋 header 按鈕、事件類型標籤、GPS 位置、主題切換、下載按鈕等 21 處
- 透過 CDN 引入，動態元素使用 `lucide.createIcons()` 初始化

### 版面調整
- Sidebar 寬度：380px → 340px
- 廣告欄寬度：160px → 200px
- Sidebar header 與 Main header 統一高度（56px）
- 引導步驟改用 fieldset/legend + Lucide icon 卡片風格
- 移除右上角 GitHub 連結，改在 Footer 呈現

### Footer 重新設計
三行佈局：
1. **ChronoDrive | 為您的特斯拉行車紀錄輕鬆嵌入時間戳記** + GitHub icon
2. 關於我們 · 隱私權政策 · 服務條款
3. Based on chronodrive-dashcam GNU AGPL · © 2026 TinyOmnibus. Protected by reCAPTCHA.

---

## 語系改版

- 簡體中文 → **繁體中文 (zh-TW)**
- i18n key 從 `zh` 改名為 `zh-TW`
- 65+ 處內嵌簡體字串轉繁體（進度訊息、錯誤提示、按鈕文字等）
- 語言切換：繁中 ↔ 英文
- 自動偵測瀏覽器語系，向下相容舊 `localStorage` 值

---

## 匯出選項標籤

| 選項 | 中文 | English |
|------|------|---------|
| 時間戳章 | 時間戳章 | Timestamp |
| 行車狀態 | 行車狀態 | Driving Status |
| 背景音樂 | 背景音樂 | Background Music |
| 色彩調整 | 色彩調整 | Color Adjustment |

---

## 基礎設施

- 音檔與字型改由 **Cloudflare R2** CDN 託管，不再隨 `src/` 部署
  - 音檔：`https://audio.tinyomnibus.me/chronodrive/*`
  - 字型：`https://pub-007d01a7483d4a778c32807e257fedc8.r2.dev/fonts/*`
- Google AdSense 廣告整合（右側欄，動態插入避免窄螢幕報錯）
- 部署平台：Cloudflare Pages

---

## Bug 修正

- 匯出完成按鈕攝影機名稱未翻譯（直接顯示英文 key）→ 改用 i18n 對照
- 廣告 `availableWidth=0` 錯誤 → 動態插入 + try-catch 防護
- Video type tag 文字擠壓（移除 emoji 後中文無空格分隔）→ 改用 Lucide icon

---

## 技術棧

- **前端**：原生 HTML/CSS/JS（無框架），單檔架構
- **圖示**：Lucide Icons (CDN)
- **日曆**：flatpickr (CDN)
- **Protobuf**：protobuf.js（解析 Tesla SEI metadata）
- **CDN**：Cloudflare R2（音檔、字型）
- **部署**：Cloudflare Pages
- **授權**：GNU AGPL-3.0

---

## 授權

本專案基於 [TDashcam Studio](https://github.com/DeaglePC/TDashcamStudio) 開發，採用 [GNU AGPL-3.0](LICENSE) 授權。
