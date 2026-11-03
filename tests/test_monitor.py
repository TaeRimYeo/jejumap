"""주민·시민단체 모니터링 CSV 가져오기 점검."""
import datetime, io, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
import core

B = os.path.join(os.path.dirname(__file__), "..")
beaches = pd.read_csv(os.path.join(B, "beaches.csv"), encoding="utf-8-sig")
zones = json.load(open(os.path.join(B, "zones.geojson"), encoding="utf-8"))["features"]
csv = """날짜,마을,위도,경도,쓰레기,종류,관찰한 생물,단체,메모
2026-11-01,평대리,,,없음,,흰물떼새 3마리,주민 모니터링단,평대사구 010-1234-5678
2026.10.30,,33.4975,126.4518,있음,플라스틱,갈매기,시민단체,이호 사구
2026-10-29,색달동,,,,폐그물,,주민,
2026-10-29,없는마을,,,없음,,,주민,
bad,평대리,,,없음,,,주민,
2026-10-29,새우마을,,,없음,,새우,주민,
"""
df = pd.read_csv(io.StringIO(csv), dtype=str)
p, r, s = core.parse_monitoring(df, beaches, zones)
assert [x["zone"] for x in p] == ["평대리 지선"], p
assert p[0]["wildlife"] == ["흰물떼새"] and "010" not in p[0]["by"], p[0]
assert [x["zone"] for x in r] == ["이호동 지선", "색달동지선"] and r[1]["category"] == "fishing_gear", r
assert len(s) == 3, s
p2, r2, _ = core.parse_monitoring(df, beaches, zones)
assert [x["_id"] for x in p + r] == [x["_id"] for x in p2 + r2]       # 같은 파일 → 같은 id
tp, tr, ts = core.parse_monitoring(pd.read_csv(io.StringIO(core.MONITOR_TEMPLATE), dtype=str), beaches, zones)
assert not tp and not tr, "양식의 예시 행은 들어가면 안 됨"
W = core.wildlife_by_zone(p, datetime.date(2026, 11, 4), reports=r)
assert set(W) == {"평대리 지선", "이호동 지선"}, W
t = core.apply_wildlife(core.build_table(beaches, r, False, [], today=datetime.date(2026, 11, 4)), zones, W)
assert (t.wildlife != "").any()
print("MONITOR OK")

# ---- 비 온 뒤 하천 하구 ----
T = datetime.date(2026, 11, 4)
rs = core.rain_summary({"2026-11-02": 20, "2026-11-03": 15, "2026-11-04": 0, "2026-11-05": 5}, T)
assert rs == {"past3": 35, "tomorrow": 5, "triggered": True}, rs
assert core.rain_summary(None, T) is None
t = core.build_table(beaches, [], False, [], today=T)
cov = core.zone_coverage(t, zones, today=T)
rv = core.river_patrol(zones, cov, {"북부(제주시)": rs, "남부(서귀포)": None})
assert all(rv["하구 해안 구역"] != ""), rv
assert set(rv[rv["순찰"] != "평소"]["강수 지역"]) == {"북부(제주시)"}
assert rv.iloc[0]["순찰"] != "평소"                      # 순찰 필요한 곳이 먼저
assert (core.river_patrol(zones, cov, {}, force=True)["순찰"] != "평소").all()
b = core.briefing_text(t, cov, "제주시 동지역", T, rivers=rv)
assert "하천 하구 순찰" in b and "한천" in b, b
live = core.fetch_rain(33.5, 126.53)
print("live rain:", core.rain_summary(live, datetime.date.today()) if live else "받아오지 못함")
print("RIVER OK")
