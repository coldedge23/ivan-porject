"""本機小型伺服器：在原本的靜態檔案伺服器功能上，多加三個 API，
讓網頁地圖上的「修正名稱」「隱藏這筆」「釘選」按鈕可以直接把結果寫回本機檔案，
不用手動下載、手動搬檔案。

只監聽 localhost，不會被外部連線存取。

用法：
    python server.py            # 預設 port 8000
    python server.py 8080       # 指定 port

寫入的檔案：
  ../data/place_name_overrides.json   { placeId: "手動修正的名稱" }
  ../data/excluded_visits.json        [ { "placeId": ..., "startTime": ... }, ... ]
  ../data/pinned_places.json          [ placeId, ... ]（手動釘選的常用地點）

「隱藏這筆」會改變統計數字，收到之後自動重跑 convert.py。
「修正名稱」與「釘選」只是呈現層的設定，不重跑——前端會直接載入那兩個檔案套用，
所以按下去是即時生效的。

三件跟資料完整性有關的事：
  1. 整段「讀檔 → 改 → 寫回 → 重跑轉換」由 WRITE_LOCK 序列化。這是
     ThreadingHTTPServer，開兩個分頁同時改就會有兩條執行緒交錯；沒有鎖的話
     兩邊都讀到同一份原始內容、各自加上自己的修改再蓋回去，其中一筆會消失，
     而且兩邊都會收到成功。
  2. 所有寫入都經過 jsonio.save_json_atomic（暫存檔 + 原子換名），
     不會留下寫到一半的半截 JSON。
  3. 每個欄位都先驗證型別與長度才落地。之前沒驗證，送出 {"placeId": []}
     會把 [[]] 寫進 pinned_places.json，之後每次 convert.py 都會掛掉，
     得手動去修檔案才能救回來。
"""
import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jsonio import load_json, save_json_atomic

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OVERRIDES_FILE = DATA_DIR / "place_name_overrides.json"
EXCLUDED_FILE = DATA_DIR / "excluded_visits.json"
PINNED_FILE = DATA_DIR / "pinned_places.json"
CONVERT_SCRIPT = Path(__file__).resolve().parent / "convert.py"

# 「讀檔 → 改 → 寫回 → 重跑 convert.py」整段必須是一個交易，不能只鎖寫檔那一行
WRITE_LOCK = threading.Lock()

MAX_BODY_BYTES = 64 * 1024
MAX_ID_LEN = 200
MAX_NAME_LEN = 200

SERVER_PORT = 8000  # main() 會覆寫；Host 標頭檢查要用

# 靜態檔案只開放地圖真正需要的東西。原本是把整個專案資料夾開出去，
# 連 location-history.json（28 MB 原始足跡）和 scripts/ 都能直接抓。
# 這不是防外部連線（本來就只聽 localhost），而是萬一有腳本在同源底下執行，
# 能拿到的東西少一點。
ALLOWED_GET_PATHS = {"/", "/index.html", "/favicon.ico"}
ALLOWED_GET_PREFIXES = ("/data/",)
ALLOWED_GET_SUFFIXES = (".json", ".geojson")


class BadRequest(Exception):
    """送來的內容有問題，回 400 且不改動任何檔案。"""


def require_str(body, field, max_len=MAX_ID_LEN, allow_empty=False):
    value = body.get(field)
    if not isinstance(value, str):
        raise BadRequest(f"{field} 必須是字串")
    value = value.strip()
    if not value and not allow_empty:
        raise BadRequest(f"{field} 不能是空字串")
    if len(value) > max_len:
        raise BadRequest(f"{field} 太長（上限 {max_len} 字）")
    return value


def require_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        raise BadRequest(f"{field} 必須是 true 或 false")
    return value


def load_overrides():
    data = load_json(OVERRIDES_FILE, {})
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise BadRequest(f"{OVERRIDES_FILE.name} 的內容格式不對，請先修好這個檔案")
    return data


def load_excluded():
    data = load_json(EXCLUDED_FILE, [])
    ok = isinstance(data, list) and all(
        isinstance(e, dict)
        and isinstance(e.get("placeId"), str)
        and isinstance(e.get("startTime"), str)
        for e in data
    )
    if not ok:
        raise BadRequest(f"{EXCLUDED_FILE.name} 的內容格式不對，請先修好這個檔案")
    return data


def load_pinned():
    data = load_json(PINNED_FILE, [])
    if not isinstance(data, list) or not all(isinstance(e, str) for e in data):
        raise BadRequest(f"{PINNED_FILE.name} 的內容格式不對，請先修好這個檔案")
    return data


def run_convert():
    subprocess.run(
        [sys.executable, str(CONVERT_SCRIPT)],
        check=True,
        cwd=str(CONVERT_SCRIPT.parent),
        capture_output=True,
    )


def op_override_name(body):
    place_id = require_str(body, "placeId")
    name = require_str(body, "name", max_len=MAX_NAME_LEN, allow_empty=True)
    overrides = load_overrides()
    if name:
        overrides[place_id] = name
    else:
        overrides.pop(place_id, None)  # 空字串代表取消覆寫
    save_json_atomic(OVERRIDES_FILE, overrides, indent=2)
    return {}


def op_exclude_visit(body):
    place_id = require_str(body, "placeId")
    start_time = require_str(body, "startTime")
    excluded = load_excluded()
    key = {"placeId": place_id, "startTime": start_time}
    if key not in excluded:
        excluded.append(key)
    save_json_atomic(EXCLUDED_FILE, excluded, indent=2)
    return {}


def op_set_pin(body):
    """由呼叫端指定「要變成什麼狀態」，不是盲目切換。

    原本是切換式的：先存檔再重跑 convert.py，重跑失敗回 500，使用者以為沒成功
    再按一次，就把已經存好的狀態又切回去。改成指定目標狀態之後，同一個請求
    重送幾次結果都一樣，重試是安全的。
    """
    place_id = require_str(body, "placeId")
    want_pinned = require_bool(body, "pinned")
    pinned = load_pinned()
    if want_pinned and place_id not in pinned:
        pinned.append(place_id)
    elif not want_pinned and place_id in pinned:
        pinned.remove(place_id)
    save_json_atomic(PINNED_FILE, pinned, indent=2)
    return {"pinned": want_pinned}


# needs_rebuild：這個修改會不會改變統計數字。
#   修正名稱、釘選 → 只是呈現層的標籤與樣式，geojson 裡一個數字都不會變，
#      前端載入 place_name_overrides.json / pinned_places.json 直接套用即可。
#      （實測：改一個出現在 71 個月份的地點，重建會重寫 80 個檔案、十幾秒，
#        但改變的只有一個字串欄位。那個重建完全沒有必要。）
#   隱藏這筆 → 該筆記錄會從所有計算裡消失，通勤配對、每日統計、足跡覆蓋
#      的數字都會變（實測 5 個檔案），非重建不可。
ROUTES = {
    "/api/override-name": (op_override_name, False),
    "/api/exclude-visit": (op_exclude_visit, True),
    "/api/toggle-pin": (op_set_pin, False),
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def _local_origins(self):
        return {
            f"http://localhost:{SERVER_PORT}",
            f"http://127.0.0.1:{SERVER_PORT}",
        }

    def _check_browser_origin(self):
        """擋掉別的網頁跨站來打這幾個會寫檔的 API。

        只聽 localhost 不代表安全：使用者瀏覽器裡的任何一個分頁都連得到
        127.0.0.1，而 Content-Type: text/plain 的 POST 屬於 CORS 安全列表，
        不會觸發 preflight，就算對方讀不到回應，寫入也已經發生了。

        - Content-Type 必須是 application/json：text/plain 那條路就此堵死
        - Origin 有帶就必須完全吻合：瀏覽器發跨站 POST 一定會帶 Origin，
          所以「沒帶 Origin」代表不是瀏覽器跨站請求（curl、腳本），放行
        - Host 必須是 localhost：擋 DNS rebinding，攻擊者把自己的網域指到
          127.0.0.1 時，瀏覽器送出的 Host 會是那個網域而不是 localhost
        """
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise BadRequest("Content-Type 必須是 application/json")

        origin = self.headers.get("Origin")
        if origin is not None and origin not in self._local_origins():
            raise BadRequest(f"不接受來自 {origin} 的請求")

        host = (self.headers.get("Host") or "").strip().lower()
        hostname = host.rsplit(":", 1)[0] if ":" in host else host
        if hostname not in ("localhost", "127.0.0.1"):
            raise BadRequest(f"不接受 Host 為 {host} 的請求")

    # 這兩個是使用者還沒做過任何修正時就不存在的檔案。回 404 會在瀏覽器
    # 主控台留下紅字，看起來像壞掉，其實只是「還沒有任何覆寫」。
    EMPTY_DEFAULTS = {
        "/data/place_name_overrides.json": {},
        "/data/pinned_places.json": [],
    }

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]

        if path in self.EMPTY_DEFAULTS and not (BASE_DIR / path.lstrip("/")).exists():
            self._send_json(200, self.EMPTY_DEFAULTS[path])
            return

        allowed = (
            path in ALLOWED_GET_PATHS
            or (path.startswith(ALLOWED_GET_PREFIXES)
                and path.endswith(ALLOWED_GET_SUFFIXES))
        )
        if not allowed:
            self.send_error(404, "File not found")
            return
        super().do_GET()

    def do_HEAD(self):
        self.do_GET()

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise BadRequest("Content-Length 不是數字")
        if length < 0:
            raise BadRequest("Content-Length 不合法")
        if length > MAX_BODY_BYTES:
            raise BadRequest(f"request body 太大（上限 {MAX_BODY_BYTES} bytes）")

        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BadRequest("request body 不是合法的 JSON")
        if not isinstance(body, dict):
            raise BadRequest("request body 必須是 JSON 物件")
        return body

    def do_POST(self):
        route = ROUTES.get(self.path)
        if route is None:
            self._send_json(404, {"error": "not found"})
            return
        handler, needs_rebuild = route

        # 先檢查來源與 body。驗證失敗回 400，這時還沒碰過任何檔案。
        try:
            self._check_browser_origin()
            body = self._read_json_body()
        except BadRequest as e:
            self._send_json(400, {"error": str(e), "saved": False})
            return

        # 整段交易序列化：同時間只有一個請求在改檔案 + 重跑轉換
        with WRITE_LOCK:
            try:
                payload = handler(body)
            except BadRequest as e:
                self._send_json(400, {"error": str(e), "saved": False})
                return
            except Exception as e:
                self._send_json(500, {"error": f"存檔失敗：{e}", "saved": False})
                return

            if not needs_rebuild:
                self._send_json(200, {"ok": True, "saved": True, "rebuilt": False, **payload})
                return

            # 到這裡修改已經確實寫進檔案。之後若重跑失敗，要講清楚是「存好了但
            # 重建失敗」，否則使用者會以為整件事沒發生而重按，把狀態改回去。
            try:
                run_convert()
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or b"").decode("utf-8", "replace").strip()
                self._send_json(500, {
                    "saved": True,
                    "error": f"修改已經存檔，但重新產生地圖資料失敗：{stderr or e}",
                })
                return
            except Exception as e:
                self._send_json(500, {
                    "saved": True,
                    "error": f"修改已經存檔，但重新產生地圖資料失敗：{e}",
                })
                return

        self._send_json(200, {"ok": True, "saved": True, "rebuilt": True, **payload})

    def log_message(self, format, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main():
    global SERVER_PORT
    SERVER_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    port = SERVER_PORT
    server = ThreadingHTTPServer(("localhost", port), Handler)
    print(f"伺服器啟動：http://localhost:{port}（只接受本機連線）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
