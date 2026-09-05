@echo off

cd /d "%~dp0"



start "Timeline Server" cmd /k python scripts\server.py 8000

timeout /t 2 /nobreak >nul

start "" http://localhost:8000



echo 伺服器已在另一個視窗啟動，瀏覽器應該也自動開啟了。

echo 如果沒開，請手動輸入網址 http://localhost:8000

echo 這個視窗可以直接關閉。

pause

