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
- [x] **Phase 1：CRUD 骨架**（不含加密）— 帳密的新增/查看/編輯/刪除，資料先明文存本機資料庫，目的是熟悉 Flutter 畫面與資料流
- [x] **Phase 2：基本加密** — 學明文/密文/金鑰的概念，用 `encrypt` 套件把密碼欄位加密後再存（AES-256-GCM，隨機 IV）
- [x] **Phase 3：主密碼機制** — 用 Argon2id 從主密碼 + 隨機鹽值現算金鑰，金鑰只存在記憶體、不落地儲存，做出「輸入主密碼才能解鎖」的功能
- [ ] **Phase 4（選配）：雲端同步** — 串 Firebase，只上傳密文，體會「零知識」架構

## 目前進度
Phase 0～3 全部完成 ✅ — 完整的「設定主密碼 → 解鎖 → CRUD → 鎖定 → 重新解鎖」流程都測試通過。
Phase 4（雲端同步）是選配，之後想做再說。

### 檔案結構
- `lib/models/password_entry.dart` — 資料模型
- `lib/services/entry_storage.dart` — Hive 存取邏輯，存取時透過 CryptoService 加解密密碼欄位
- `lib/services/crypto_service.dart` — 實際加解密（AES-256-GCM），金鑰只存在記憶體
- `lib/services/master_password_service.dart` — 主密碼設定/驗證，Argon2id 金鑰衍生
- `lib/screens/home_screen.dart` — 帳號列表（新增/查看/刪除/鎖定）
- `lib/screens/edit_entry_screen.dart` — 新增/編輯表單
- `lib/screens/setup_master_password_screen.dart` — 首次使用設定主密碼
- `lib/screens/unlock_screen.dart` — 輸入主密碼解鎖

### 加密設計摘要（給未來的自己複習用）
- 金鑰不是隨機產生後存起來，而是每次用「主密碼 + 隨機鹽值」透過 Argon2id 現算出來，算完就丟，只存在記憶體
- 驗證主密碼對不對的方法：用算出來的金鑰去解密一組事先加密好的固定字串（verifier），解得開又對得上 = 密碼正確；解不開或 GCM 驗證失敗 = 密碼錯誤
- 忘記主密碼 = 資料真的救不回來，這是刻意的設計（沒有人能繞過主密碼拿到金鑰）

### 環境備忘
- Flutter SDK：`C:\flutter`（不在 GDrive 同步範圍內）
- Android SDK：`%LOCALAPPDATA%\Android\sdk`
- 模擬器：`Pixel_Test`（Android 14）
- ⚠️ **專案路徑含中文字元，Windows 上會導致多個建置工具出問題**（不只 Gradle，`flutter analyze`、native assets 建置也都會壞）：
  - `android/gradle.properties` 加了 `android.overridePathCheck=true` 繞過 Gradle 的路徑檢查
  - **關鍵解法**：實際下指令（`flutter run` 等）要透過 ASCII 捷徑路徑 `C:\dev\password_manager_learning`，而不是直接用 GDrive 的中文路徑 `G:\我的雲端硬碟\ivan-porject\tools\密碼管理學習`。這個捷徑是用 `mklink /J`（NTFS 目錄接合點）建立的，兩邊指向同一份實體檔案，GDrive 那邊還是會正常同步，只是「動作」要在 `C:\dev\` 這邊下
  - 如果重灌電腦或換電腦，記得要重新建立這個捷徑：
    ```
    mklink /J "C:\dev\password_manager_learning" "G:\我的雲端硬碟\ivan-porject\tools\密碼管理學習"
    ```

## 安全性提醒（自己看，也給未來的自己看）
- 密碼學的 bug 通常「看起來正常運作」，不會像一般 bug 一樣馬上出錯，所以很難自己抓出問題
- 這個專案的加密邏輯**只用來學習**，沒有經過資安稽核，不要信任它保護真實資料
- 真正要用的密碼管理，交給 Bitwarden / KeePass 這種被大量驗證過的工具
