"""
把停留點的座標反查成實際地址/地點名稱，存進 data/place_names.json 快取。

分兩步查詢：
  1. Nominatim 反查 → 基本地址（路名門牌），當作保底
  2. Overpass API 附近搜尋 → 找座標方圓內最近的「有名字地標」（店家/機構/景點等），
     找得到就優先用地標名稱蓋過純地址，找不到才維持地址

兩個都是 OpenStreetMap 生態的免費服務，不需要額外註冊或 API Key。
兩者都要求限速（Nominatim 每秒最多 1 次），這支腳本會照規矩自動限速，
且只查快取裡還沒有的地點，重複執行是安全的（不會浪費時間重查已有結果）。

用法：
    python geocode_places.py                # 查全部還沒查過的
    python geocode_places.py --limit 5      # 只查前 5 個沒查過的，測試用
    python geocode_places.py --limit 10 --refresh   # 強制重查已有快取的前 10 個（用來比較新舊查法效果）
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "location-history.json"
CACHE_FILE = BASE_DIR / "data" / "place_names.json"

GEO_RE = re.compile(r"geo:(-?\d+\.\d+),(-?\d+\.\d+)")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "ivan-porject-personal-timeline-map/1.0 (local personal use, non-commercial)"

LANDMARK_TAGS = ["amenity", "shop", "office", "tourism", "leisure", "craft"]
LANDMARK_RADIUS_M = 50

# Overpass 是免費公用服務，塞車時單一查詢可能卡很久。與其苦等，不如快速放棄、
# 讓那筆先用 Nominatim 的地址保底並標記起來，之後服務順暢時再用 --retry-failed 補查。
OVERPASS_SERVER_TIMEOUT = 6   # 給 Overpass 伺服器的查詢執行上限（秒）
OVERPASS_CLIENT_TIMEOUT = 8   # 我方等待回應的上限（含排隊時間）
OVERPASS_RETRIES = 0          # 塞車時重試只會拖慢整批，改成不重試

# 這些分類雖然有掛 name，但對「這是哪裡」沒什麼意義（廁所、停車格、垃圾桶等），
# 找地標時直接排除，避免把有意義的名稱（例如已經精準比對到的店名）蓋掉。
EXCLUDE_TAG_VALUES = {
    "toilets", "parking", "parking_space", "bicycle_parking", "waste_basket",
    "bench", "recycling", "vending_machine", "waste_disposal", "shelter",
    "fire_hydrant", "post_box", "telephone", "clock",
}


def parse_geo(geo_str):
    m = GEO_RE.match(geo_str)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def reverse_geocode(lat, lon):
    """Nominatim 反查，回傳基本地址（保底用）"""
    url = (
        f"{NOMINATIM_URL}?format=json&lat={lat}&lon={lon}"
        f"&zoom=18&addressdetails=1&accept-language=zh-TW"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    name = data.get("name") or ""
    address = data.get("address", {})
    road = address.get("road", "")
    house_number = address.get("house_number", "")
    display = data.get("display_name", "")
    short = name or f"{road}{house_number}".strip() or (display.split(",")[0] if display else "")
    return {"name": short, "displayName": display, "hadOwnName": bool(name)}


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def elem_latlon(el):
    if el.get("type") == "node":
        return el.get("lat"), el.get("lon")
    center = el.get("center")
    if center:
        return center.get("lat"), center.get("lon")
    return None, None


def find_nearby_landmark(lat, lon, radius=LANDMARK_RADIUS_M):
    """Overpass 附近搜尋，找方圓內最近的有名字地標，找不到回傳 None"""
    clauses = []
    for tag in LANDMARK_TAGS:
        clauses.append(f'node(around:{radius},{lat},{lon})["{tag}"]["name"];')
        clauses.append(f'way(around:{radius},{lat},{lon})["{tag}"]["name"];')
    query = f'[out:json][timeout:{OVERPASS_SERVER_TIMEOUT}];({"".join(clauses)});out center;'

    req = urllib.request.Request(
        OVERPASS_URL, data=query.encode("utf-8"), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=OVERPASS_CLIENT_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    best_name, best_dist = None, None
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        if any(tags.get(tag) in EXCLUDE_TAG_VALUES for tag in LANDMARK_TAGS):
            continue
        elat, elon = elem_latlon(el)
        if elat is None:
            continue
        dist = haversine_m(lat, lon, elat, elon)
        if best_dist is None or dist < best_dist:
            best_name, best_dist = name, dist

    return best_name


def find_nearby_landmark_with_retry(lat, lon, retries=OVERPASS_RETRIES):
    """Overpass 公共伺服器偶爾會逾時/塞車，失敗時重試幾次再放棄，
    避免把「查詢失敗」誤判成「真的沒有地標」。"""
    last_error = None
    for attempt in range(retries + 1):
        try:
            return find_nearby_landmark(lat, lon), None
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2)
    return None, last_error


def geocode_one(lat, lon, skip_landmark=False):
    result = reverse_geocode(lat, lon)
    time.sleep(1.1)  # Nominatim 限速

    if skip_landmark and not result["hadOwnName"]:
        # Overpass 不通時的降級模式：先用地址保底，標記起來之後用 --retry-failed 補查地標
        result["source"] = "address"
        result["landmarkQueryFailed"] = True
        return result

    if result["hadOwnName"]:
        # Nominatim 反查已經精準比對到具體名稱（座標就落在那個地點上），
        # 直接採用，不再讓地標搜尋去覆蓋——避免被方圓內剛好更近的無關地標蓋掉。
        result["source"] = "nominatim_name"
        return result

    landmark, error = find_nearby_landmark_with_retry(lat, lon)
    if error is not None:
        result["landmarkQueryFailed"] = True
    time.sleep(1.1)  # Overpass 限速（保守起見比照辦理）

    if landmark:
        result["name"] = landmark
        result["source"] = "landmark"
    else:
        result["source"] = "address"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="只查前 N 個地點（測試用）")
    parser.add_argument(
        "--refresh", action="store_true",
        help="強制重查，忽略現有快取（用來比較新舊查法效果，正式全量查詢不要加這個）",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="只重查上次「地標查詢失敗」（Overpass 逾時/塞車）的地點，不動其他已成功的快取",
    )
    parser.add_argument(
        "--no-landmark", action="store_true",
        help="跳過 Overpass 地標搜尋，只用 Nominatim 查地址（Overpass 掛掉時用；查過的會標記起來，之後可用 --retry-failed 補查地標）",
    )
    args = parser.parse_args()

    print(f"讀取 {INPUT_FILE} ...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        segments = json.load(f)

    places = {}  # placeId -> (lat, lon)
    for seg in segments:
        if "visit" not in seg:
            continue
        top = seg["visit"].get("topCandidate", {})
        pid = top.get("placeID")
        loc = parse_geo(top.get("placeLocation", ""))
        if pid and loc and pid not in places:
            places[pid] = loc

    cache = load_cache()
    if args.retry_failed:
        todo = [pid for pid in places if cache.get(pid, {}).get("landmarkQueryFailed")]
    elif args.refresh:
        todo = list(places.keys())
    else:
        # 沒有 source 欄位代表是還沒套用地標搜尋邏輯的舊資料（例如上次 --refresh 跑到一半中斷），
        # 當成沒查過一樣補查，這樣中斷後直接重跑（不用加 --refresh）就會自動接續。
        todo = [pid for pid in places if pid not in cache or "source" not in cache[pid]]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"共 {len(places)} 個不重複地點，本次要查 {len(todo)} 個。")

    if not todo:
        print("全部都已經有快取，不需要查詢。")
        return

    print(f"預估需要約 {len(todo) * 2.2:.0f} 秒（約 {len(todo) * 2.2 / 60:.1f} 分鐘，每個地點查 2 個服務）...")

    for i, pid in enumerate(todo, 1):
        lat, lon = places[pid]
        try:
            result = geocode_one(lat, lon, skip_landmark=args.no_landmark)
            cache[pid] = result
            tag = {"landmark": "地標", "nominatim_name": "反查店名", "address": "地址"}.get(result["source"], result["source"])
            if result.get("landmarkQueryFailed"):
                tag += "，地標查詢逾時"
            print(f"  [{i}/{len(todo)}] ({tag}) {result['name'] or '(無名稱)'}")
        except urllib.error.URLError as e:
            print(f"  [{i}/{len(todo)}] 查詢失敗，略過：{e}")
        except Exception as e:
            print(f"  [{i}/{len(todo)}] 發生錯誤，略過：{e}")

        if i % 5 == 0:
            save_cache(cache)  # 定期存檔，中途中斷也不會全部重查

    save_cache(cache)

    landmark_count = sum(1 for v in cache.values() if v.get("source") == "landmark")
    failed_count = sum(1 for v in cache.values() if v.get("landmarkQueryFailed"))
    print(f"完成。快取已存到 {CACHE_FILE}")
    print(f"目前快取共 {len(cache)} 筆，{landmark_count} 筆有地標名稱，{failed_count} 筆地標查詢曾逾時失敗（可用 --retry-failed 重查）。")


if __name__ == "__main__":
    main()
