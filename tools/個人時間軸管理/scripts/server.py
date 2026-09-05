"""
本機小型伺服器：在原本的靜態檔案伺服器功能上，多加兩個 API，
讓網頁地圖上的「修正名稱」「隱藏這筆」按鈕可以直接把結果寫回本機檔案，
不用手動下載、手動搬檔案。

只監聽 localhost，不會被外部連線存取。

用法：
    python server.py            # 預設 port 8000
    python server.py 8080       # 指定 port

寫入的檔案：
  ../data/place_name_overrides.json   { placeId: "手動修正的名稱" }
  ../data/excluded_visits.json        [ { "placeId": ..., "startTime": ... }, ... ]
  ../data/pinned_places.json          [ placeId, ... ]（手動釘選的常用地點）

收到修改後會自動重跑 convert.py，讓修改立刻反映到 GeoJSON 資料。
"""
import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OVERRIDES_FILE = DATA_DIR / "place_name_overrides.json"
EXCLUDED_FILE = DATA_DIR / "excluded_visits.json"
PINNED_FILE = DATA_DIR / "pinned_places.json"
CONVERT_SCRIPT = Path(__file__).resolve().parent / "convert.py"


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    DATA_DIR.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_convert():
    subprocess.run(
        [sys.executable, str(CONVERT_SCRIPT)],
        check=True,
        cwd=str(CONVERT_SCRIPT.parent),
        capture_output=True,
    )


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_POST(self):
        try:
            if self.path == "/api/override-name":
                body = self._read_json_body()
                place_id = body["placeId"]
                name = (body.get("name") or "").strip()
                overrides = load_json(OVERRIDES_FILE, {})
                if name:
                    overrides[place_id] = name
                else:
                    overrides.pop(place_id, None)  # 空字串代表取消覆寫
                save_json(OVERRIDES_FILE, overrides)
                run_convert()
                self._send_json(200, {"ok": True})

            elif self.path == "/api/exclude-visit":
                body = self._read_json_body()
                excluded = load_json(EXCLUDED_FILE, [])
                key = {"placeId": body["placeId"], "startTime": body["startTime"]}
                if key not in excluded:
                    excluded.append(key)
                save_json(EXCLUDED_FILE, excluded)
                run_convert()
                self._send_json(200, {"ok": True})

            elif self.path == "/api/toggle-pin":
                body = self._read_json_body()
                place_id = body["placeId"]
                pinned = load_json(PINNED_FILE, [])
                if place_id in pinned:
                    pinned.remove(place_id)
                    now_pinned = False
                else:
                    pinned.append(place_id)
                    now_pinned = True
                save_json(PINNED_FILE, pinned)
                run_convert()
                self._send_json(200, {"ok": True, "pinned": now_pinned})

            else:
                self._send_json(404, {"error": "not found"})
        except subprocess.CalledProcessError as e:
            self._send_json(500, {"error": f"convert.py 執行失敗：{e}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def log_message(self, format, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("localhost", port), Handler)
    print(f"伺服器啟動：http://localhost:{port}（只接受本機連線）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
