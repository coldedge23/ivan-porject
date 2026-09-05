"""
把 Google Takeout 匯出的時間軸原始檔（location-history.json）
轉成依「年-月」拆分的精簡 GeoJSON，供網頁地圖載入。

用法：
    python convert.py

輸入：
  ../location-history.json
  ../data/place_names.json（選用，由 geocode_places.py 產生的地點名稱快取）
  ../data/place_name_overrides.json（選用，網頁上「修正名稱」存的人工覆寫，優先權最高）
  ../data/excluded_visits.json（選用，網頁上「隱藏這筆」存的排除清單）
  ../data/pinned_places.json（選用，網頁上「釘選此地點」存的常用地點清單）
輸出：
  ../data/YYYY-MM.geojson（一個月一個檔案，月/日視圖用）
  ../data/YYYY.geojson（一年一個檔案，年視圖叢集用）
  ../data/index.json（年份/月份清單）
  ../data/search_index.json（地點搜尋索引：每個地點名稱 + 座標 + 出現過的月份）
  ../data/daily_stats.json（月曆熱力圖用：每天的移動距離與停留點筆數）
  ../data/commutes.json（通勤分析用：住家↔公司之間每一趟的耗時、距離、交通方式）
  ../data/coverage.json（足跡覆蓋用：去過哪些縣市/國家、各去過幾個地點）
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "location-history.json"
OUTPUT_DIR = BASE_DIR / "data"
PLACE_NAMES_FILE = OUTPUT_DIR / "place_names.json"
OVERRIDES_FILE = OUTPUT_DIR / "place_name_overrides.json"
EXCLUDED_FILE = OUTPUT_DIR / "excluded_visits.json"
PINNED_FILE = OUTPUT_DIR / "pinned_places.json"

GEO_RE = re.compile(r"geo:(-?\d+\.\d+),(-?\d+\.\d+)")

# Google 已經分類好的常用地點，自動標示，不用手動釘選
AUTO_PIN_TYPES = {"Home", "Work", "Inferred Work", "Aliased Location"}


def load_json_if_exists(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def load_place_names():
    return load_json_if_exists(PLACE_NAMES_FILE, {})


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


def visit_to_feature(seg, place_names, overrides, pinned_manual):
    visit = seg["visit"]
    top = visit.get("topCandidate", {})
    coords = parse_geo(top.get("placeLocation", ""))
    if coords is None:
        return None
    place_id = top.get("placeID")
    place_name = place_names.get(place_id, {}).get("name") if place_id else None
    if place_id and place_id in overrides:
        place_name = overrides[place_id]  # 人工覆寫優先權最高

    semantic_type = top.get("semanticType")
    if semantic_type in AUTO_PIN_TYPES:
        pin_source = "auto"
    elif place_id and place_id in pinned_manual:
        pin_source = "manual"
    else:
        pin_source = None

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
        },
    }


def activity_to_feature(seg):
    act = seg["activity"]
    start = parse_geo(act.get("start", ""))
    end = parse_geo(act.get("end", ""))
    if start is None or end is None:
        return None
    top = act.get("topCandidate", {})
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [start, end]},
        "properties": {
            "type": "activity",
            "startTime": seg["startTime"],
            "endTime": seg["endTime"],
            "activityType": top.get("type"),
            "distanceMeters": act.get("distanceMeters"),
        },
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

        y = entry["byYear"].setdefault(year, {"visits": 0, "minutes": 0.0, "placeIds": set()})
        y["visits"] += 1
        y["minutes"] += minutes
        y["placeIds"].add(p["placeId"])

        lon, lat = f["geometry"]["coordinates"]
        ps = entry["placeStats"].setdefault(p["placeId"], {
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
            "byYear": {
                y: {"visits": v["visits"], "minutes": round(v["minutes"]), "places": len(v["placeIds"])}
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
            for adt, a in activities:
                if adt < t0:
                    continue
                if adt > t1:
                    break
                move_min += (parse_time(a["properties"]["endTime"]) - adt).total_seconds() / 60
                d = float(a["properties"].get("distanceMeters") or 0)
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
    print(f"讀取 {INPUT_FILE} ...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        segments = json.load(f)
    print(f"共 {len(segments)} 筆記錄，開始轉換...")

    place_names = load_place_names()
    if place_names:
        print(f"已載入 {len(place_names)} 個地點名稱快取（{PLACE_NAMES_FILE.name}）")
    else:
        print(f"沒有找到地點名稱快取，停留點會只顯示類型（住家/公司等）。可先執行 geocode_places.py 產生快取。")

    overrides = load_json_if_exists(OVERRIDES_FILE, {})
    if overrides:
        print(f"已載入 {len(overrides)} 筆人工覆寫地點名稱（{OVERRIDES_FILE.name}）")

    excluded_list = load_json_if_exists(EXCLUDED_FILE, [])
    excluded_keys = {(e["placeId"], e["startTime"]) for e in excluded_list}
    if excluded_keys:
        print(f"已載入 {len(excluded_keys)} 筆隱藏記錄（{EXCLUDED_FILE.name}）")

    pinned_manual = set(load_json_if_exists(PINNED_FILE, []))
    if pinned_manual:
        print(f"已載入 {len(pinned_manual)} 個手動釘選的常用地點（{PINNED_FILE.name}）")

    by_month = defaultdict(list)
    skipped = 0
    excluded_count = 0
    search_places = {}  # placeId -> {"name":..., "lat":..., "lon":..., "months": set()}
    daily = defaultdict(lambda: {"m": 0.0, "v": 0})  # 日期 -> 移動距離(公尺) / 停留點筆數

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
            feature = visit_to_feature(seg, place_names, overrides, pinned_manual)
        elif "activity" in seg:
            feature = activity_to_feature(seg)
        elif "timelinePath" in seg:
            feature = timeline_path_to_feature(seg)
        # timelineMemory 類型目前用途不明，先略過

        if feature is None:
            skipped += 1
            continue

        mkey = month_key(dt)
        by_month[mkey].append(feature)

        dkey = day_key(dt)
        if feature["properties"]["type"] == "activity":
            daily[dkey]["m"] += float(feature["properties"].get("distanceMeters") or 0)
        elif feature["properties"]["type"] == "visit":
            daily[dkey]["v"] += 1

        if feature["properties"]["type"] == "visit":
            props = feature["properties"]
            name = props.get("placeName") or props.get("semanticType")
            place_id = props.get("placeId")
            if place_id and name:
                lon, lat = feature["geometry"]["coordinates"]
                entry = search_places.setdefault(
                    place_id, {"name": name, "lat": lat, "lon": lon, "months": set()}
                )
                entry["name"] = name  # 用最新一筆的名稱（覆寫/新查到的名稱會蓋掉舊的）
                entry["months"].add(mkey)

    OUTPUT_DIR.mkdir(exist_ok=True)
    months = sorted(by_month.keys())

    by_year = defaultdict(list)
    for month, features in by_month.items():
        year = month[:4]
        by_year[year].extend(features)
    years = sorted(by_year.keys())

    for month in months:
        out_path = OUTPUT_DIR / f"{month}.geojson"
        geojson = {"type": "FeatureCollection", "features": by_month[month]}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        print(f"  {month}.geojson: {len(by_month[month])} 筆")

    for year in years:
        out_path = OUTPUT_DIR / f"{year}.geojson"
        geojson = {"type": "FeatureCollection", "features": by_year[year]}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        print(f"  {year}.geojson: {len(by_year[year])} 筆（年彙整）")

    index = {
        "years": years,
        "months": months,
        "generatedAt": datetime.now().isoformat(),
    }
    with open(OUTPUT_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

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
    with open(OUTPUT_DIR / "search_index.json", "w", encoding="utf-8") as f:
        json.dump(search_index, f, ensure_ascii=False)
    print(f"搜尋索引：{len(search_index)} 個不重複地點")

    daily_stats = {
        d: {"m": round(v["m"]), "v": v["v"]}
        for d, v in sorted(daily.items())
    }
    with open(OUTPUT_DIR / "daily_stats.json", "w", encoding="utf-8") as f:
        json.dump(daily_stats, f, ensure_ascii=False)
    print(f"每日統計：{len(daily_stats)} 天")

    all_features = [f for feats in by_month.values() for f in feats]
    commutes = build_commutes(all_features)
    with open(OUTPUT_DIR / "commutes.json", "w", encoding="utf-8") as f:
        json.dump(commutes, f, ensure_ascii=False)
    print(f"通勤趟次：{len(commutes)} 趟")

    coverage = build_coverage(all_features, place_names)
    with open(OUTPUT_DIR / "coverage.json", "w", encoding="utf-8") as f:
        json.dump(coverage, f, ensure_ascii=False)
    print(f"足跡覆蓋：{len(coverage['regions'])} 個縣市/國家")

    print(f"完成。共 {len(years)} 年、{len(months)} 個月份，略過 {skipped} 筆無法解析的記錄，隱藏 {excluded_count} 筆記錄。")
    print(f"輸出目錄：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
