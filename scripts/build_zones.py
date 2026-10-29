"""마을어장(마을어업) 구역을 해안 구역 단위로 변환 -> zones.geojson
사용: python build_zones.py <어장정보도 SHP 폴더> <출력 geojson>
"""
import glob
import json
import math
import sys

from shp_lite import read_dbf, read_polygons

SHPDIR, OUT = sys.argv[1], sys.argv[2]


def from_utmk(x, y):
    """EPSG:5179 (TM, lon0=127.5, lat0=38, k=0.9996, FE=1e6, FN=2e6) -> WGS84 위경도 (Snyder 역변환)."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0, lat0, lon0 = 0.9996, math.radians(38), math.radians(127.5)

    def M(p):
        return a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * p
                    - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * p)
                    + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * p)
                    - (35 * e2 ** 3 / 3072) * math.sin(6 * p))
    m = M(lat0) + (y - 2e6) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    N1 = a / math.sqrt(1 - e2 * math.sin(p1) ** 2)
    T1 = math.tan(p1) ** 2
    C1 = ep2 * math.cos(p1) ** 2
    R1 = a * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
    D = (x - 1e6) / (N1 * k0)
    lat = p1 - (N1 * math.tan(p1) / R1) * (D ** 2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 ** 2 - 9 * ep2) * D ** 4 / 24
                                           + (61 + 90 * T1 + 298 * C1 + 45 * T1 ** 2 - 252 * ep2 - 3 * C1 ** 2) * D ** 6 / 720)
    lon = lon0 + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
                  + (5 - 2 * C1 + 28 * T1 - 3 * C1 ** 2 + 8 * ep2 + 24 * T1 ** 2) * D ** 5 / 120) / math.cos(p1)
    return math.degrees(lat), math.degrees(lon)


# 마을 이름 -> 읍면동 (돌고래 가중치가 걸린 대정·안덕·구좌를 정확히 구분하는 것이 목적)
EMD_KEYS = [
    ("대정읍", ["하모", "상모", "동일", "일과", "영락", "무릉", "신도리", "가파", "마라"]),
    ("안덕면", ["사계", "화순", "대평", "형제섬"]),
    ("구좌읍", ["김녕", "월정", "행원", "한동", "평대", "하도", "종달", "동복"]),
    ("한경면", ["고산", "용수", "신창", "두모", "금등", "판포", "용당"]),
    ("한림읍", ["협재", "금능", "옹포", "한수", "수원", "비양도", "월령", "귀덕"]),
    ("애월읍", ["곽지", "금성", "애월", "고내", "신엄", "중엄", "구엄", "하귀"]),
    ("조천읍", ["함덕", "조천", "신촌", "북촌"]),
    ("우도면", ["조일", "천진", "서광", "오봉"]),
    ("남원읍", ["위미", "남원", "태흥", "신례", "하례", "지귀도"]),
    ("표선면", ["표선", "하천", "토산"]),
    ("성산읍", ["신천", "신풍", "삼달", "신산", "온평", "신양", "고성", "오조", "시흥", "수마포", "오정게"]),
    ("서귀포시 동지역", ["색달", "하예", "대포", "중문", "서건도", "강정", "법환", "범섬", "외돌개", "새섬", "자구리",
                    "보목", "토평", "하효"]),
    ("제주시 동지역", ["이호", "도두", "내도", "외도", "용담", "삼도", "화북", "삼양"]),
]


def emd_for(addr, sgg, lat):
    if "세화리" in addr:                      # 같은 이름: 제주시 세화(구좌) / 서귀포시 세화(표선)
        return "구좌읍" if "제주시" in sgg else "표선면"
    if "신흥리" in addr:                      # 제주시 신흥(조천) / 서귀포시 신흥(남원)
        return "조천읍" if "제주시" in sgg else "남원읍"
    for emd, keys in EMD_KEYS:
        if any(k in addr for k in keys):
            return emd
    return "기타"


def simplify(ring, max_pts=60):
    if len(ring) <= max_pts:
        return ring
    step = math.ceil(len(ring) / max_pts)
    out = ring[::step]
    if out[-1] != ring[-1]:
        out.append(ring[-1])
    return out


shp = glob.glob(SHPDIR + "/*.shp")[0]
base = shp[:-4]
_, rows = read_dbf(base + ".dbf")
idx = [i for i, r in enumerate(rows) if r["ctpv_nm"] == "제주특별자치도" and r["fids_se"] == "마을어업"]
polys = read_polygons(shp, base + ".shx", idx)

feats, seen, skipped = [], set(), {"추자면(제외)": 0, "중복": 0, "빈 도형": 0}
for i in idx:
    r = rows[i]
    lat_c, lon_c = float(r["ycdnt"]), float(r["xcdnt"])
    if lat_c > 33.8:                          # 추자도 일대 소도서는 본섬 지도에서 제외
        skipped["추자면(제외)"] += 1
        continue
    key = (r["addr"].strip(), round(lat_c, 4), round(lon_c, 4))
    if key in seen:
        skipped["중복"] += 1
        continue
    seen.add(key)
    if not polys[i]:
        skipped["빈 도형"] += 1
        continue
    rings = []
    for ring in polys[i]:
        ll = [from_utmk(x, y) for x, y in ring]
        rings.append([[round(lo, 5), round(la, 5)] for la, lo in simplify(ll)])
    rings.sort(key=len, reverse=True)
    emd = emd_for(r["addr"], r["sgg_nm"], lat_c)
    feats.append({"type": "Feature",
                  "properties": {"zone_id": len(feats), "name": r["addr"].strip(), "sgg": r["sgg_nm"].replace("제주특별자치도 ", ""),
                                 "emd": emd, "lat": round(lat_c, 5), "lon": round(lon_c, 5),
                                 "area_ha": float(r["area"]), "license": r["lcns_no"]},
                  "geometry": {"type": "Polygon", "coordinates": rings}})

json.dump({"type": "FeatureCollection", "features": feats}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print(len(feats), "zones", skipped)
from collections import Counter
print(Counter(f["properties"]["emd"] for f in feats))
print([f["properties"]["name"] for f in feats if f["properties"]["emd"] == "기타"])
