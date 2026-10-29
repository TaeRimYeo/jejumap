"""Day 1: merge monitoring CSV + beach API + 마을어장 SHP into beaches.csv"""
import sys, json, math, glob
import pandas as pd
from shp_lite import read_dbf, read_polygons, to_utmk, dist_to_rings

MON = sys.argv[1]; SHPDIR = sys.argv[2]; BEACH = sys.argv[3]; OUT = sys.argv[4]
YEAR = 2021  # only year all 3 stations were surveyed

# ---------- 1. monitoring stations ----------
d = pd.read_csv(MON, encoding="utf-8-sig")
d = d[d["측정 연도"] == YEAR]
GEAR_SUB = ["그물", "낚싯줄", "밧줄", "통발", "가짜미끼", "부표", "어상자", "양식용"]
def cat(r):
    big, mid, sub = r["쓰레기 유형 대분류"], str(r["쓰레기 유형 중분류"]), str(r["쓰레기 유형 소분류"])
    txt = mid + " " + sub
    if big in ("플라스틱", "외국기인") and any(k in txt for k in GEAR_SUB): return "fishing_gear"
    if big == "플라스틱" and mid == "발포형": return "styrofoam"
    if big in ("플라스틱", "외국기인"): return "plastic"
    return "other"
d["cat"] = d.apply(cat, axis=1)
cnt = d.pivot_table(index="정점명", columns="cat", values="개수", aggfunc="sum", fill_value=0)
# weight is repeated per (station, round, material) -> dedupe then average over rounds
w = (d.groupby(["정점명", "측정 차수", "쓰레기 유형 대분류"])["무게"].first()
       .groupby(["정점명", "측정 차수"]).sum().groupby("정점명").mean())
loc = d.groupby("정점명")[["위도", "경도"]].first()
HAZ = {"fishing_gear": 3, "plastic": 2, "styrofoam": 2, "other": 1}
st = []
for name in cnt.index:
    c = {k: int(cnt.loc[name].get(k, 0)) for k in HAZ}
    tot = sum(c.values())
    st.append(dict(name=name, type="모니터링정점", lat=loc.loc[name, "위도"], lon=loc.loc[name, "경도"],
                   data_year=YEAR, total_items=tot, avg_kg_per_survey=round(w[name], 1),
                   **{f"{k}_cnt": v for k, v in c.items()},
                   fishing_gear_share=round(c["fishing_gear"]/tot, 3) if tot else None,
                   hazard_index=round(sum(c[k]*HAZ[k] for k in HAZ)/tot, 2) if tot else None,
                   source="제주특별자치도_해양쓰레기 모니터링 데이터_20221130"))

# ---------- 2. beaches ----------
bc = json.load(open(BEACH, encoding="utf-8"))
be = [dict(name=b["sta_nm"], type="해수욕장", lat=b["lat"], lon=b["lon"],
           source="해양수산부_해수욕장정보 서비스(API, 2026-10-28 조회)") for b in bc]

df = pd.DataFrame(st + be)

# 읍면동 (manual, well-known locations)
EMD = {"제주 사계리": ("서귀포시", "안덕면"), "제주 김녕리": ("제주시", "구좌읍"), "제주 위미": ("서귀포시", "남원읍"),
       "신양섭지코지": ("서귀포시", "성산읍"), "중문색달": ("서귀포시", "중문동"), "표선해비치": ("서귀포시", "표선면"),
       "화순금모래": ("서귀포시", "안덕면"), "곽지과물": ("제주시", "애월읍"), "금능으뜸원": ("제주시", "한림읍"),
       "김녕성세기": ("제주시", "구좌읍"), "삼양검은모래": ("제주시", "삼양동"), "이호테우": ("제주시", "이호동"),
       "함덕서우봉": ("제주시", "조천읍"), "협재": ("제주시", "한림읍")}
df["sgg"] = df.name.map(lambda n: EMD[n][0]); df["emd"] = df.name.map(lambda n: EMD[n][1])

# coast side from island centre (for winter NW-monsoon weight later)
def side(lat, lon):
    ang = math.degrees(math.atan2(lat-33.38, (lon-126.55)*math.cos(math.radians(33.4)))) % 360
    return ["동", "북", "서", "남"][int(((ang+45) % 360)//90)]
df["coast_side"] = [side(a, o) for a, o in zip(df.lat, df.lon)]

# ---------- 3. 마을어장 (village fishery) ----------
shp = glob.glob(SHPDIR + "/*.shp")[0]; base = shp[:-4]
_, rows = read_dbf(base + ".dbf")
idx = [i for i, r in enumerate(rows) if r["ctpv_nm"] == "제주특별자치도" and r["fids_se"] == "마을어업"]
polys = read_polygons(shp, base + ".shx", idx)
dist, near = [], []
for a, o in zip(df.lat, df.lon):
    x, y = to_utmk(a, o)
    best = min(((dist_to_rings(x, y, polys[i]), i) for i in idx if polys[i]), key=lambda t: t[0])
    dist.append(round(best[0])); near.append(rows[best[1]]["addr"])
df["village_fishery_dist_m"] = dist; df["village_fishery_near"] = near
df["village_fishery"] = df.village_fishery_dist_m <= 500

# ---------- 4. dolphin weight (2025 보호구역 + 2026 보도) ----------
DOL = {"대정읍": (1.0, "2025 해양생물보호구역(신도리)"),
       "안덕면": (0.5, "2026.2 사계리항 새끼 폐사 목격 보도"),
       "구좌읍": (0.5, "2026.7 월정리 폐어구 걸림 개체 보도")}
df["dolphin_weight"] = df.emd.map(lambda e: DOL.get(e, (0.0, ""))[0])
df["dolphin_basis"] = df.emd.map(lambda e: DOL.get(e, (0.0, ""))[1])

# ---------- 5. base risk score (season weight applied in app) ----------
df["risk_score"] = (df.avg_kg_per_survey * df.hazard_index * (1 + df.dolphin_weight)
                    * df.village_fishery.map({True: 1.5, False: 1.0})).round(1)
df["has_debris_data"] = df.total_items.notna()

cols = ["name", "type", "sgg", "emd", "lat", "lon", "coast_side", "has_debris_data", "data_year", "total_items",
        "avg_kg_per_survey", "fishing_gear_cnt", "plastic_cnt", "styrofoam_cnt", "other_cnt", "fishing_gear_share",
        "hazard_index", "village_fishery", "village_fishery_dist_m", "village_fishery_near", "dolphin_weight",
        "dolphin_basis", "risk_score", "source"]
df[cols].to_csv(OUT, index=False, encoding="utf-8-sig")
print(df[cols].to_string())
