"""JSON 讀寫的共用工具。

原本三支腳本各自用 `open(path, "w")` 直接覆寫，那會先把檔案截斷再慢慢寫，
中間如果有人（網頁的 fetch、另一支腳本）剛好去讀，就會拿到寫到一半的半截 JSON；
寫到一半當掉更會直接留下壞檔。這裡統一改成「寫暫存檔 → 原子換名」。
"""
import json
import os
import tempfile
from pathlib import Path


def load_json(path, default):
    """讀 JSON，檔案不存在就回傳預設值。"""
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json_atomic(path, data, indent=None, fsync=True, skip_if_unchanged=False):
    """先寫進同目錄的暫存檔，再用 os.replace 換名。

    os.replace 在同一個磁碟區上是原子操作：讀取端要嘛看到舊的完整內容，
    要嘛看到新的完整內容，不會讀到中間狀態。暫存檔刻意放在目標檔案的同一個
    目錄，跨磁碟區的 replace 不保證原子性。

    fsync 只多保證一件事：斷電或當機之後檔案內容仍在。它跟原子性無關，
    而且在 Google 雲端硬碟同步資料夾上很貴——實測整批 191 個檔案會從 18 秒
    變成 32 秒。所以：
      fsync=True （預設）給不可重生的資料——使用者手動改的覆寫/釘選/排除清單，
                 以及跑了好幾小時才查回來的地點名稱快取
      fsync=False 給 convert.py 產生的衍生檔案——當機了重跑一次就有，
                 不值得為它付這個代價

    skip_if_unchanged：內容跟現有檔案一模一樣就不寫，回傳 False。
    改一個地點名稱通常只影響一兩個月檔，另外一百多個檔案內容根本沒變；
    在 Google 雲端硬碟上，省下的不只是寫入時間，還有整批重新上傳同步。

    回傳值：True 代表真的寫了，False 代表內容沒變所以跳過。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=indent)

    if skip_if_unchanged and path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except (OSError, UnicodeDecodeError):
            pass  # 讀不出來就當成有變，照常重寫

    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True
