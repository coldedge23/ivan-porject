# 密碼管理學習 App

> ⚠️ **這是學習用專案，不是日常使用的密碼管理工具。**
> 目的是學習「怎麼做 APP」+「怎麼做加密」，操作時請一律用**假的測試帳密**，不要放真實密碼。
> 如果之後想要一個真的能安心每天用的密碼管理工具，建議直接用 [Bitwarden](https://bitwarden.com/)（開源、可自架、已被大量資安稽核驗證），不要拿這個學習專案取代它。

## 專案目標
學習 Flutter APP 開發 + 加密概念，做出一個「看得懂原理」的密碼管理 APP。

## 技術棧
- **框架**：Flutter（跨平台，Android/iOS 共用一份程式碼）
- **本機儲存**：sqflite / Hive（依階段需求選用）
- **加密**：`encrypt` 套件（AES-256-GCM）+ Argon2id 金鑰衍生
- **雲端同步（後期）**：Firebase Firestore（`my-teaching-tools` 專案，獨立 collection，不與學生資料混用）

## 學習階段

- [x] **Phase 0：環境建置** — 安裝 Flutter SDK、設定模擬器，跑出「Hello World」
- [ ] **Phase 1：CRUD 骨架**（不含加密）— 帳密的新增/查看/編輯/刪除，資料先明文存本機資料庫，目的是熟悉 Flutter 畫面與資料流
- [ ] **Phase 2：基本加密** — 學明文/密文/金鑰的概念，用 `encrypt` 套件把資料加密後再存
- [ ] **Phase 3：主密碼機制** — 學金鑰衍生（Argon2/PBKDF2），做出「輸入主密碼才能解鎖」的功能
- [ ] **Phase 4（選配）：雲端同步** — 串 Firebase，只上傳密文，體會「零知識」架構

## 目前進度
Phase 0 完成 ✅ — Flutter SDK + Android Studio + 模擬器都已安裝並跑出 Hello World。
Phase 1 準備開始 — 帳密 CRUD 骨架。

### 環境備忘
- Flutter SDK：`C:\flutter`（不在 GDrive 同步範圍內）
- Android SDK：`%LOCALAPPDATA%\Android\sdk`
- 模擬器：`Pixel_Test`（Android 14）
- ⚠️ 專案路徑含中文字元，Windows 上會導致 Gradle 建置失敗，已在 `android/gradle.properties` 加上 `android.overridePathCheck=true` 繞過此限制

## 安全性提醒（自己看，也給未來的自己看）
- 密碼學的 bug 通常「看起來正常運作」，不會像一般 bug 一樣馬上出錯，所以很難自己抓出問題
- 這個專案的加密邏輯**只用來學習**，沒有經過資安稽核，不要信任它保護真實資料
- 真正要用的密碼管理，交給 Bitwarden / KeePass 這種被大量驗證過的工具
