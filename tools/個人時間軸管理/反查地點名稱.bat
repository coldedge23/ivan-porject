@echo off
cd /d "%~dp0scripts"

echo 這支腳本會把停留點的座標反查成實際地址/店家名稱。
echo 只查快取裡還沒有的地點，重複執行很安全，不會重查已有的。
echo.
echo 第一次執行如果地點很多，會需要一段時間（每秒最多查 1 筆，
echo 例如 1800 個地點大約要 30 分鐘），請耐心等待，不要關視窗。
echo.
pause

python geocode_places.py

echo.
echo 完成。接著執行 更新資料.bat（或直接跑 convert.py）把地點名稱套進地圖資料。
pause
