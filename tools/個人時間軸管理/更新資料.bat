@echo off
cd /d "%~dp0scripts"

echo 手機重新匯出 location-history.json 並覆蓋到這個資料夾後，
echo 執行這支腳本即可重新產生地圖用的資料。
echo.

python convert.py

echo.
echo 完成。重新整理地圖網頁（或重開 啟動地圖.bat）就會看到最新資料。
pause
