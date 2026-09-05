"""
把 Google Takeout 匯出的時間軸原始檔（location-history.json）
轉成依「年-月」拆分的精簡 GeoJSON，供網頁地圖載入。

用法：
    python convert.py

輸入：
  ../location-history.json
  ../data/place_names.json（選用，由 geocode_places.py 產生的地點名稱快取）

注意：網頁上的「修正名稱」與「釘選」不在這裡處理。那兩個是呈現層的設定，
存在 data/place_name_overrides.json 與 data/pinned_places.json，由 index.html
在畫面上直接套用，改了不需要重跑這支腳本。
  ../data/excluded_visits.json（選用，網頁上「隱藏這筆」存的排除清單）
輸出：
  ../data/YYYY-MM.geojson（一個月一個檔案，月/日視圖用）
  ../data/YYYY.geojson（一年一個檔案，年視圖叢集用）
  ../data/index.json（年份/月份清單）
  ../data/search_index.json（地點搜尋索引：每個地點名稱 + 座標 + 出現過的月份）
  ../data/daily_stats.json（月曆熱力圖用：每天的移動距離與停留點筆數）
  ../data/commutes.json（通勤分析用：住家↔公司之間每一趟的耗時、距離、交通方式）
  ../data/coverage.json（足跡覆蓋用：去過哪些縣市/國家、各去過幾個地點）
"""
import bisect
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from jsonio import load_json, save_json_atomic

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "location-history.json"
OUTPUT_DIR = BASE_DIR / "data"
PLACE_NAMES_FILE = OUTPUT_DIR / "place_names.json"
EXCLUDED_FILE = OUTPUT_DIR / "excluded_visits.json"

GEO_RE = re.compile(r"geo:(-?\d+\.\d+),(-?\d+\.\d+)")

# Google 已經分類好的常用地點，自動標示，不用手動釘選
AUTO_PIN_TYPES = {"Home", "Work", "Inferred Work", "Aliased Location"}


def load_place_names():
    names = load_json(PLACE_NAMES_FILE, {})
    if not isinstance(names, dict):
        print(f"  警告：{PLACE_NAMES_FILE.name} 格式不對，這次當成沒有快取處理")
        return {}
    return names


def load_state(path, default, is_valid, describe):
    """讀取網頁存下來的狀態檔（覆寫/排除/釘選）。

    這些檔案是使用者自己的編輯成果，不能因為混進一個壞值就讓整個轉換掛掉、
    連地圖都生不出來。壞掉的項目跳過並明講跳了幾筆，其餘照常套用。
    """
    data = load_json(path, default)
    if type(data) is not type(default):
        print(f"  警告：{path.name} 的內容不是{describe}，這次略過整個檔案")
        return default

    if isinstance(data, dict):
        good = {k: v for k, v in data.items() if is_valid((k, v))}
        dropped = len(data) - len(good)
    else:
        good = [e for e in data if is_valid(e)]
        dropped = len(data) - len(good)

    if dropped:
        print(f"  警告：{path.name} 有 {dropped} 筆格式不對的項目，已略過")
    return good


def parse_geo(geo_str):
    m = GEO_RE.match(geo_str)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return [lon, lat]  # GeoJSON 座標順序是 [經度, 緯度]


def parse_time(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def month_key(dt):
    local = dt.astimezone()  # 轉成系統時區（台灣執行即為 UTC+8）
    return f"{local.year:04d}-{local.month:02d}"


def day_key(dt):
    local = dt.astimezone()
    return f"{local.year:04d}-{local.month:02d}-{local.day:02d}"


# 壞掉的 endTime（例如遠在未來）不該讓一筆記錄被塞進上百個月份的檔案，設上限擋住
MAX_SPAN_MONTHS = 24
MAX_SPAN_DAYS = 400


def month_keys_between(start_dt, end_dt):
    """回傳這個區間跨過的所有「年-月」。

    跨月的記錄要同時放進每個月的檔案，否則切到下個月就看不到那筆還在進行中的停留
    （例如跨年夜 23:30 待到隔天 01:30，選 1 月會整筆消失）。
    """
    a, b = start_dt.astimezone(), end_dt.astimezone()
    if b < a:
        return [month_key(start_dt)]
    keys, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month) and len(keys) < MAX_SPAN_MONTHS:
        keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return keys


def day_keys_between(start_dt, end_dt):
    """回傳這個區間跨過的所有日期（本地時區），供前端的單日篩選使用。"""
    a, b = start_dt.astimezone().date(), end_dt.astimezone().date()
    if b < a:
        return [day_key(start_dt)]
    out, cur = [], a
    while cur <= b and len(out) < MAX_SPAN_DAYS:
        out.append(f"{cur.year:04d}-{cur.month:02d}-{cur.day:02d}")
        cur += timedelta(days=1)
    return out


def collect_home_work_places(segments):
    """回傳「曾被 Google 判定為住家/公司」的 placeId 集合。

    同一個地點在不同次造訪可能被標成不同的 semanticType，所以這件事必須看
    整份資料彙總的結果。原本前端是取「該年遇到的第一筆」來判斷，但原始檔裡
    visit 並不是照時間排序的，第一筆是誰純粹看檔案順序，重新匯出就可能改變。
    """
    places = set()
    for seg in segments:
        if "visit" not in seg:
            continue
        top = seg["visit"].get("topCandidate", {})
        pid = top.get("placeID")
        if pid and top.get("semanticType") in HOME_TYPES | WORK_TYPES:
            places.add(pid)
    return places


def visit_to_feature(seg, place_names, home_work_places):
    """把一筆 visit 轉成 GeoJSON Feature。

    這裡放的是「原始事實」：Google 給的座標與 semanticType、反查回來的名稱。
    網頁上的人工修正（place_name_overrides.json）與手動釘選（pinned_places.json）
    刻意不烙進來——那是呈現層的東西，由前端在畫面上套用。

    這樣做的原因：名稱被寫進每一筆造訪記錄，所以改一個常去地點的名字會讓
    它出現過的每一個月檔都要重寫（實測改一個出現在 71 個月份的地點要重寫
    80 個檔案、耗時十幾秒），但改變的只有一個字串欄位，沒有任何數字不同。
    交給前端套用之後，改名不需要重跑轉換，而且只有一份真相。
    """
    visit = seg["visit"]
    top = visit.get("topCandidate", {})
    coords = parse_geo(top.get("placeLocation", ""))
    if coords is None:
        return None
    place_id = top.get("placeID")
    place_name = place_names.get(place_id, {}).get("name") if place_id else None

    semantic_type = top.get("semanticType")
    # pinSource 是「地圖上怎麼畫」（這裡只放 Google 判定的 auto，手動釘選由前端加）；
    # isHomeWork 是「這裡算不算住家/公司」，用於統計面板的排除條件。兩件事要分開。
    pin_source = "auto" if semantic_type in AUTO_PIN_TYPES else None
    is_home_work = bool(place_id) and place_id in home_work_places

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coords},
        "properties": {
            "type": "visit",
            "startTime": seg["startTime"],
            "endTime": seg["endTime"],
            "semanticType": semantic_type,
            "placeId": place_id,
            "placeName": place_name,
            "probability": top.get("probability"),
            "pinSource": pin_source,
            "isHomeWork": is_home_work,
        },
    }


def haversine_km(a, b):
    """兩點間的大圓距離（公里）。座標是 GeoJSON 的 [經度, 緯度]。"""
    (lon1, lat1), (lon2, lat2) = a, b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(x), math.sqrt(1 - x))


# Google 的原始資料裡有一批 distanceMeters 是壞的：宣稱移動一萬三千多公里，
# 但頭尾座標幾乎是同一點、時長只有幾分鐘。這種值會灌爆移動統計與月曆色階。
#
# 判準要兩個條件同時成立才算異常，只看其中一個都會誤判：
#   1. 宣稱距離遠大於頭尾直線距離 —— 直線距離是實際路徑長度的物理下限
#   2. 推算時速快到不可能
# 只看時速會誤刪真實航班（實測有一筆 2,144 km、時速 1,067 km/h 的長途飛行，
# 被 Google 標成 in subway，但它的直線距離就是 2,135 km，距離本身是對的）。
# 只看比值會誤刪繞圈折返的路線（走一圈回到原點，直線距離接近 0 是正常的）。
MAX_PLAUSIBLE_KMH = 1000
DISTANCE_RATIO_LIMIT = 3
DISTANCE_MARGIN_KM = 50

# 被判定為異常而剔除的距離筆數，轉換結束時回報
invalid_distances = []


def distance_is_implausible(claimed_m, start, end, start_time, end_time):
    if not claimed_m:
        return False
    claimed_km = float(claimed_m) / 1000
    straight_km = haversine_km(start, end)
    if claimed_km <= straight_km * DISTANCE_RATIO_LIMIT + DISTANCE_MARGIN_KM:
        return False
    hours = (parse_time(end_time) - parse_time(start_time)).total_seconds() / 3600
    if hours <= 0:
        return True  # 沒有時長可佐證，但距離已經跟直線距離差太多
    return claimed_km / hours > MAX_PLAUSIBLE_KMH


def activity_to_feature(seg):
    act = seg["activity"]
    start = parse_geo(act.get("start", ""))
    end = parse_geo(act.get("end", ""))
    if start is None or end is None:
        return None
    top = act.get("topCandidate", {})

    distance = act.get("distanceMeters")
    invalid = distance_is_implausible(
        distance, start, end, seg["startTime"], seg["endTime"]
    )
    if invalid:
        # 保留這段移動（起訖點是真的，地圖上還是要畫出來），只是距離不採計。
        # 不用直線距離頂替：那是估算值，會讓統計看起來精確但其實是掰的。
        invalid_distances.append((seg["startTime"][:10], float(distance) / 1000))
        distance = None

    props = {
        "type": "activity",
        "startTime": seg["startTime"],
        "endTime": seg["endTime"],
        "activityType": top.get("type"),
        "distanceMeters": distance,
    }
    if invalid:
        props["distanceInvalid"] = True
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [start, end]},
        "properties": props,
    }


def timeline_path_to_feature(seg):
    points = seg.get("timelinePath", [])
    coords = []
    for p in points:
        c = parse_geo(p.get("point", ""))
        if c is not None:
            coords.append(c)
    if len(coords) < 2:
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "type": "timelinePath",
            "startTime": seg["startTime"],
            "endTime": seg["endTime"],
        },
    }


TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市",
    "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣",
    "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣",
]

# OSM 的國名有時是簡體、或用 ; / 併列多種寫法，統一成繁體單一名稱
COUNTRY_ALIASES = {"中国": "中國", "韩国": "南韓", "泰国": "泰國", "日本国": "日本"}


def normalize_country(raw):
    name = raw
    for sep in (";", "/"):
        if sep in name:
            name = name.split(sep)[-1]
    name = name.strip()
    return COUNTRY_ALIASES.get(name, name)


def parse_region(display_name):
    """從 Nominatim 的完整地址字串解析出（國家, 縣市）。
    國外地點沒有可靠的次級行政區可解析，縣市就用國名代替。"""
    if not display_name:
        return None, None
    parts = [p.strip() for p in display_name.split(",")]
    country = normalize_country(parts[-1]) if parts else None
    if country != "臺灣":
        return country, country
    normalized = display_name.replace("台", "臺")
    for city in TAIWAN_CITIES:
        if city in normalized:
            return country, city
    return country, None


def build_coverage(all_features, place_names):
    """統計去過哪些縣市/國家，以及各自的地點數、造訪次數、停留時間、起訖日期。"""
    regions = {}
    for f in all_features:
        p = f["properties"]
        if p["type"] != "visit" or not p.get("placeId"):
            continue
        country, region = parse_region(place_names.get(p["placeId"], {}).get("displayName"))
        if not region:
            continue

        key = f"{country}|{region}"
        entry = regions.setdefault(key, {
            "country": country, "name": region,
            "placeIds": set(), "firstDate": None, "lastDate": None,
            "byYear": {}, "placeStats": {},
        })

        dt = parse_time(p["startTime"]).astimezone()
        date_str = f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        year = f"{dt.year:04d}"
        minutes = (parse_time(p["endTime"]) - parse_time(p["startTime"])).total_seconds() / 60

        entry["placeIds"].add(p["placeId"])
        if entry["firstDate"] is None or date_str < entry["firstDate"]:
            entry["firstDate"] = date_str
        if entry["lastDate"] is None or date_str > entry["lastDate"]:
            entry["lastDate"] = date_str

        y = entry["byYear"].setdefault(year, {
            "visits": 0, "minutes": 0.0, "placeIds": set(),
            "placeStats": {}, "first": None, "last": None,
        })
        y["visits"] += 1
        y["minutes"] += minutes
        y["placeIds"].add(p["placeId"])
        if y["first"] is None or date_str < y["first"]:
            y["first"] = date_str
        if y["last"] is None or date_str > y["last"]:
            y["last"] = date_str

        lon, lat = f["geometry"]["coordinates"]
        for stats in (entry["placeStats"], y["placeStats"]):
            ps = stats.setdefault(p["placeId"], {
                "placeId": p["placeId"],
                "name": p.get("placeName") or p.get("semanticType") or "未知地點",
                "lat": lat, "lon": lon, "visits": 0,
            })
            ps["visits"] += 1

    out = {}
    for key, e in regions.items():
        top_places = sorted(e["placeStats"].values(), key=lambda x: -x["visits"])[:5]
        out[key] = {
            "country": e["country"],
            "name": e["name"],
            "placeCount": len(e["placeIds"]),
            "firstDate": e["firstDate"],
            "lastDate": e["lastDate"],
            "topPlaces": top_places,
            # 每年也留一份自己的地點排行與起訖日期，前端選了年份之後，
            # 展開縣市看到的明細才會跟著那一年，不會上面篩年份、下面卻是全期間
            "byYear": {
                y: {
                    "visits": v["visits"],
                    "minutes": round(v["minutes"]),
                    "places": len(v["placeIds"]),
                    "firstDate": v["first"],
                    "lastDate": v["last"],
                    "topPlaces": sorted(
                        v["placeStats"].values(), key=lambda x: -x["visits"]
                    )[:5],
                }
                for y, v in sorted(e["byYear"].items())
            },
        }
    return {"regions": out, "taiwanCities": TAIWAN_CITIES}


HOME_TYPES = {"Home"}
WORK_TYPES = {"Work", "Inferred Work"}
MAX_COMMUTE_MINUTES = 300  # 超過 5 小時就不算通勤（多半是中間去了別的地方）


def commute_kind(feature):
    st = feature["properties"].get("semanticType")
    if st in HOME_TYPES:
        return "H"
    if st in WORK_TYPES:
        return "W"
    return None


def build_commutes(all_features):
    """從時序排列的停留點裡找出住家↔公司的移動，算出每一趟的耗時、距離、交通方式。

    門到門耗時 = 離開起點到抵達終點的總時間（含中途停留，這是實際體感）
    純移動時間 = 中間所有移動段落的時間加總（不含中途停留）
    """
    visits, activities = [], []
    for f in all_features:
        dt = parse_time(f["properties"]["startTime"])
        if f["properties"]["type"] == "visit":
            visits.append((dt, f))
        elif f["properties"]["type"] == "activity":
            activities.append((dt, f))
    visits.sort(key=lambda x: x[0])
    activities.sort(key=lambda x: x[0])
    activity_starts = [dt for dt, _ in activities]
    # 往前回頭找多遠才夠：最長的一段移動有多長，就回頭多久，
    # 這樣「在 t0 之前出發、延續進通勤時段」的段落一定找得到
    max_activity_span = max(
        (parse_time(a["properties"]["endTime"]) - dt for dt, a in activities),
        default=timedelta(0),
    )

    trips = []
    for i, (_, v) in enumerate(visits):
        kind = commute_kind(v)
        if kind is None:
            continue
        # 往後找下一個住家或公司（中間的其他地點視為順路停留）
        for _, nxt in visits[i + 1:]:
            nkind = commute_kind(nxt)
            if nkind is None:
                continue
            if nkind == kind:
                break  # 回到同一種地點，不是通勤
            t0 = parse_time(v["properties"]["endTime"])
            t1 = parse_time(nxt["properties"]["startTime"])
            total_min = (t1 - t0).total_seconds() / 60
            if not 0 < total_min < MAX_COMMUTE_MINUTES:
                break

            move_min, dist_m = 0.0, 0.0
            by_mode = defaultdict(float)
            # 取所有跟 [t0, t1] 有重疊的移動段落，並且只計入落在區間內的部分。
            # 原本是用「起始時刻有沒有落在區間內」判斷，會有兩個方向的錯：
            # 在 t0 之前出發、但一路開到通勤時段的段落被整段漏掉；在 t1 之前
            # 出發、卻延續到抵達之後的段落被整段算進來（實測可以做出「門到門
            # 30 分鐘、純移動 60 分鐘」這種不可能的結果）。
            hi = bisect.bisect_left(activity_starts, t1)
            lo = bisect.bisect_left(activity_starts, t0 - max_activity_span)
            for adt, a in activities[lo:hi]:
                a_end = parse_time(a["properties"]["endTime"])
                overlap_start = max(adt, t0)
                overlap_end = min(a_end, t1)
                overlap_min = (overlap_end - overlap_start).total_seconds() / 60
                if overlap_min <= 0:
                    continue
                move_min += overlap_min

                # 距離只知道整段的總和，不知道是怎麼分布的，所以部分重疊時
                # 按時間比例分攤——這是估算值，完整落在區間內的則是精確值。
                total_min_a = (a_end - adt).total_seconds() / 60
                share = 1.0 if total_min_a <= 0 else min(1.0, overlap_min / total_min_a)
                d = float(a["properties"].get("distanceMeters") or 0) * share
                dist_m += d
                by_mode[a["properties"].get("activityType") or "unknown"] += d

            local_t0 = t0.astimezone()
            trips.append({
                "date": f"{local_t0.year:04d}-{local_t0.month:02d}-{local_t0.day:02d}",
                "dir": "toWork" if kind == "H" else "toHome",
                "departHour": local_t0.hour,
                "totalMin": round(total_min),
                "moveMin": round(move_min),
                "km": round(dist_m / 1000, 1),
                # 以距離最長的段落當作這趟的主要交通方式
                "mode": max(by_mode, key=by_mode.get) if by_mode else None,
            })
            break

    return trips


def main():
    invalid_distances.clear()
    print(f"讀取 {INPUT_FILE} ...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        segments = json.load(f)
    print(f"共 {len(segments)} 筆記錄，開始轉換...")

    place_names = load_place_names()
    if place_names:
        print(f"已載入 {len(place_names)} 個地點名稱快取（{PLACE_NAMES_FILE.name}）")
    else:
        print(f"沒有找到地點名稱快取，停留點會只顯示類型（住家/公司等）。可先執行 geocode_places.py 產生快取。")

    excluded_list = load_state(
        EXCLUDED_FILE, [],
        lambda e: isinstance(e, dict) and isinstance(e.get("placeId"), str)
        and isinstance(e.get("startTime"), str),
        "陣列",
    )
    excluded_keys = {(e["placeId"], e["startTime"]) for e in excluded_list}
    if excluded_keys:
        print(f"已載入 {len(excluded_keys)} 筆隱藏記錄（{EXCLUDED_FILE.name}）")

    home_work_places = collect_home_work_places(segments)
    print(f"住家/公司地點：{len(home_work_places)} 個（依整份資料的 semanticType 彙總）")

    by_month = defaultdict(list)
    by_year = defaultdict(list)
    all_features = []  # 每筆只放一次，給通勤/覆蓋統計用（月檔會有跨月重複）
    skipped = 0
    excluded_count = 0
    search_places = {}  # placeId -> {"name":..., "lat":..., "lon":..., "months": set()}
    # 日期 -> 移動距離(公尺) / 停留點筆數 / 軌跡筆數
    daily = defaultdict(lambda: {"m": 0.0, "v": 0, "p": 0})

    for seg in segments:
        try:
            dt = parse_time(seg["startTime"])
        except (KeyError, ValueError):
            skipped += 1
            continue

        if "visit" in seg:
            top = seg["visit"].get("topCandidate", {})
            key = (top.get("placeID"), seg.get("startTime"))
            if key in excluded_keys:
                excluded_count += 1
                continue

        feature = None
        if "visit" in seg:
            feature = visit_to_feature(seg, place_names, home_work_places)
        elif "activity" in seg:
            feature = activity_to_feature(seg)
        elif "timelinePath" in seg:
            feature = timeline_path_to_feature(seg)
        # timelineMemory 類型目前用途不明，先略過

        if feature is None:
            skipped += 1
            continue

        props = feature["properties"]
        all_features.append(feature)

        end_dt = parse_time(props["endTime"])
        mkeys = month_keys_between(dt, end_dt)
        dkeys = day_keys_between(dt, end_dt)

        if len(mkeys) > 1:
            # 跨月的記錄會被放進每個月的檔案；homeMonth 標出它原本屬於哪個月，
            # 讓做加總的面板不會把同一筆算兩次
            props["homeMonth"] = mkeys[0]
        if len(dkeys) > 1:
            props["spanDates"] = dkeys  # 前端的單日篩選要靠這個才看得到跨日的停留

        for mk in mkeys:
            by_month[mk].append(feature)
        for yk in dict.fromkeys(mk[:4] for mk in mkeys):
            by_year[yk].append(feature)

        # 筆數算在「這筆記錄涵蓋到的每一天」，跟地圖的單日篩選看到的內容一致
        # （跨夜的停留在兩天都看得到，月曆的數字也要跟著算兩天）。
        # 距離只算在起始日：移動段落本來就短，硬要按比例切分只會生出估算值。
        for dk in dkeys:
            if props["type"] == "visit":
                daily[dk]["v"] += 1
            elif props["type"] == "timelinePath":
                daily[dk]["p"] += 1
            else:
                daily[dk]  # activity：確保這天存在，距離另外算
        if props["type"] == "activity":
            daily[dkeys[0]]["m"] += float(props.get("distanceMeters") or 0)

        if props["type"] == "visit":
            name = props.get("placeName") or props.get("semanticType")
            place_id = props.get("placeId")
            if place_id and name:
                lon, lat = feature["geometry"]["coordinates"]
                entry = search_places.setdefault(
                    place_id, {"name": name, "lat": lat, "lon": lon, "months": set()}
                )
                entry["name"] = name  # 用最新一筆的名稱（覆寫/新查到的名稱會蓋掉舊的）
                entry["months"].update(mkeys)

    OUTPUT_DIR.mkdir(exist_ok=True)
    written = 0  # 內容沒變的檔案會被跳過，這裡統計實際寫了幾個
    months = sorted(by_month.keys())
    years = sorted(by_year.keys())

    for month in months:
        out_path = OUTPUT_DIR / f"{month}.geojson"
        geojson = {"type": "FeatureCollection", "features": by_month[month]}
        written += save_json_atomic(out_path, geojson, fsync=False, skip_if_unchanged=True)
        print(f"  {month}.geojson: {len(by_month[month])} 筆")

    for year in years:
        out_path = OUTPUT_DIR / f"{year}.geojson"
        geojson = {"type": "FeatureCollection", "features": by_year[year]}
        written += save_json_atomic(out_path, geojson, fsync=False, skip_if_unchanged=True)
        print(f"  {year}.geojson: {len(by_year[year])} 筆（年彙整）")

    index = {
        "years": years,
        "months": months,
        "generatedAt": datetime.now().isoformat(),
    }
    written += save_json_atomic(OUTPUT_DIR / "index.json", index, indent=2, fsync=False, skip_if_unchanged=True)

    search_index = [
        {
            "placeId": pid,
            "name": entry["name"],
            "lat": entry["lat"],
            "lon": entry["lon"],
            "months": sorted(entry["months"]),
        }
        for pid, entry in search_places.items()
    ]
    written += save_json_atomic(OUTPUT_DIR / "search_index.json", search_index, fsync=False, skip_if_unchanged=True)
    print(f"搜尋索引：{len(search_index)} 個不重複地點")

    daily_stats = {
        d: {"m": round(v["m"]), "v": v["v"], "p": v["p"]}
        for d, v in sorted(daily.items())
    }
    written += save_json_atomic(OUTPUT_DIR / "daily_stats.json", daily_stats, fsync=False, skip_if_unchanged=True)
    print(f"每日統計：{len(daily_stats)} 天")

    commutes = build_commutes(all_features)
    written += save_json_atomic(OUTPUT_DIR / "commutes.json", commutes, fsync=False, skip_if_unchanged=True)
    print(f"通勤趟次：{len(commutes)} 趟")

    coverage = build_coverage(all_features, place_names)
    written += save_json_atomic(OUTPUT_DIR / "coverage.json", coverage, fsync=False, skip_if_unchanged=True)
    print(f"足跡覆蓋：{len(coverage['regions'])} 個縣市/國家")

    if invalid_distances:
        total_km = sum(km for _, km in invalid_distances)
        print(
            f"距離異常：剔除 {len(invalid_distances)} 筆不合理的移動距離"
            f"（合計 {total_km:,.0f} km，這些段落仍會畫在地圖上，只是不計入距離統計）"
        )
        for date, km in sorted(invalid_distances)[:5]:
            print(f"    {date}  宣稱 {km:,.0f} km")
        if len(invalid_distances) > 5:
            print(f"    ...另外 {len(invalid_distances) - 5} 筆")

    print(f"完成。共 {len(years)} 年、{len(months)} 個月份，略過 {skipped} 筆無法解析的記錄，隱藏 {excluded_count} 筆記錄。")
    print(f"實際寫入 {written} 個檔案（內容沒變的已跳過）")
    print(f"輸出目錄：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
