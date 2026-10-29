"""제주 해안 지킴이 지도 - 점수 계산과 데이터 처리 (UI 없음, 테스트 가능)."""
import base64
import hashlib
import time
import json
import math
import re

import pandas as pd

# 쓰레기 종류별 위해성 가중치 (순위 척도: Wilcox 외 2016, Marine Policy - 버려진 어구가 해양생물 위협 1위)
HAZARD = {"fishing_gear": 3, "plastic": 2, "styrofoam": 2, "seaweed": 1, "other": 1}
LABEL = {"fishing_gear": "폐어구·로프·낚싯줄", "plastic": "플라스틱", "styrofoam": "스티로폼",
         "seaweed": "해조류(괭생이모자반 등)", "other": "기타"}

# 돌고래 가중치 (2025 해양생물보호구역 지정 + 2026 보도)
DOLPHIN = {"대정읍": (1.0, "2025 해양생물보호구역(신도리)"),
           "안덕면": (0.5, "2026.2 사계리항 새끼 폐사 목격 보도"),
           "구좌읍": (0.5, "2026.7 월정리 폐어구 걸림 개체 보도")}

FISHERY_W = 1.5      # 마을어장 500m 이내
WINTER_NW_W = 1.2    # 겨울 북서계절풍: 북·서쪽 해안 가중
ATTACH_M = 1000      # 기존 지점에서 이 거리 안이면 같은 지점으로 묶음
EMD_LIST = ["구좌읍", "조천읍", "삼양동", "화북동", "건입동", "이호동", "애월읍", "한림읍", "한경면", "대정읍",
            "안덕면", "중문동", "서귀포시 동지역", "남원읍", "표선면", "성산읍", "기타"]
SOURCE_LABEL = {"public": "공공 조사(2021)", "record": "기관·언론 기록(2025~26)", "report": "시민 제보"}


def default_weights():
    """가중치 묶음. 민감도 분석에서 이 값을 바꿔 가며 순위를 다시 계산한다."""
    return {"hazard": dict(HAZARD), "dolphin_scale": 1.0, "fishery": FISHERY_W, "winter": WINTER_NW_W}


def dolphin_weight(emd, w=None):
    scale = (w or default_weights())["dolphin_scale"]
    return DOLPHIN.get(emd, (0.0, ""))[0] * scale


def season_weight(coast_side, winter_on, w=None):
    return (w or default_weights())["winter"] if winter_on and coast_side in ("북", "서") else 1.0


def sensitivity(emd, near_fishery, coast_side, winter_on, w=None):
    """민감도 = (1+돌고래) × 마을어장 × 계절"""
    w = w or default_weights()
    return ((1 + dolphin_weight(emd, w)) * (w["fishery"] if near_fishery else 1.0)
            * season_weight(coast_side, winter_on, w))


def risk_index(hazard, emd, near_fishery, coast_side, winter_on, w=None):
    """위험 지수 = 평균 위해성 × 민감도. 무게 추정 없이 계산."""
    if hazard is None or pd.isna(hazard):
        return float("nan")
    return round(hazard * sensitivity(emd, near_fishery, coast_side, winter_on, w), 2)


def public_hazard(row, w=None):
    """공공 조사 지점의 평균 위해성을 종류별 개수로 다시 계산 (가중치가 바뀌어도 반영되게)."""
    hz = (w or default_weights())["hazard"]
    cnt = {k: row.get(f"{k}_cnt") for k in ("fishing_gear", "plastic", "styrofoam", "other")}
    if any(v is None or pd.isna(v) for v in cnt.values()):
        return float("nan")
    tot = sum(cnt.values())
    return sum(cnt[k] * hz[k] for k in cnt) / tot if tot else float("nan")


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_point(points, lat, lon):
    d = points.apply(lambda r: haversine_m(lat, lon, r.lat, r.lon), axis=1)
    i = d.idxmin()
    return points.loc[i], float(d.loc[i])


def coast_side(lat, lon):
    ang = math.degrees(math.atan2(lat - 33.38, (lon - 126.55) * math.cos(math.radians(33.4)))) % 360
    return ["동", "북", "서", "남"][int(((ang + 45) % 360) // 90)]


def load_records(path):
    """기관·언론 정화 기록 CSV -> 근거 목록."""
    try:
        r = pd.read_csv(path, encoding="utf-8-sig")
    except OSError:
        return []
    return r.to_dict("records")


def _as_bool(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        return v.strip().lower() == "true"
    return bool(v)


def _evidence_items(beaches, reports, records):
    """모든 근거를 (출처, 종류, 위치) 형태로 통일."""
    items = []
    for rec in records or []:
        items.append(dict(source="record", category=rec["category"], place=rec["place"], emd=rec["emd"],
                          lat=rec.get("lat"), lon=rec.get("lon"), attach_name=rec.get("attach_to_name"),
                          near_fishery=_as_bool(rec.get("near_fishery"))))
    for rep in reports or []:
        items.append(dict(source="report", category=rep["category"], place=rep["place"], emd=rep["emd"],
                          lat=rep["lat"], lon=rep["lon"], attach_idx=rep.get("attach_to"),
                          near_fishery=rep.get("near_fishery")))
    return items


def build_table(beaches, reports, winter_on, records=None, w=None):
    """지점별 위험 지수와 근거 수.
    평균 위해성 = (공공 조사 1건 + 기관 기록 + 시민 제보) 각 근거 위해성의 평균
    근거 수    = 공공 조사 + 기관 기록 + 시민 제보 건수"""
    w = w or default_weights()
    hz = w["hazard"]
    t = beaches.copy().reset_index(drop=True)
    t["public_evidence"] = t["hazard_index"].notna().astype(int)
    t["hz_sum"] = [public_hazard(r, w) if p else 0.0 for r, p in zip(t.to_dict("records"), t.public_evidence)]
    t["record_count"] = 0
    t["report_count"] = 0
    for it in _evidence_items(beaches, reports, records):
        idx = None
        if it.get("attach_idx") is not None and it["attach_idx"] in t.index:
            idx = it["attach_idx"]
        elif isinstance(it.get("attach_name"), str) and (t.name == it["attach_name"]).any():
            idx = t.index[t.name == it["attach_name"]][0]
        elif pd.notna(it.get("lat")):
            near, dist = nearest_point(t, it["lat"], it["lon"])
            if dist <= ATTACH_M:
                idx = near.name
        col = "record_count" if it["source"] == "record" else "report_count"
        if idx is not None:
            t.loc[idx, col] += 1
            t.loc[idx, "hz_sum"] += hz[it["category"]]
        else:
            near, _ = nearest_point(beaches, it["lat"], it["lon"])
            fishery = it["near_fishery"] if it["near_fishery"] is not None else True  # 제주 해안 대부분 마을어장
            row = dict(name=it["place"], type="기관 기록" if it["source"] == "record" else "시민제보",
                       emd=it["emd"], lat=it["lat"], lon=it["lon"], coast_side=coast_side(it["lat"], it["lon"]),
                       has_debris_data=False, village_fishery=fishery,
                       dolphin_weight=DOLPHIN.get(it["emd"], (0.0, ""))[0],
                       dolphin_basis=DOLPHIN.get(it["emd"], (0, ""))[1],
                       public_evidence=0, hz_sum=float(hz[it["category"]]), record_count=0, report_count=0)
            row[col] = 1
            t = pd.concat([t, pd.DataFrame([row])], ignore_index=True)
    t["evidence"] = t["public_evidence"] + t["record_count"] + t["report_count"]
    t["avg_hazard"] = (t["hz_sum"] / t["evidence"]).where(t["evidence"] > 0)
    t["risk_index"] = [risk_index(r.avg_hazard, r.emd, r.village_fishery, r.coast_side, winter_on, w)
                       for r in t.itertuples()]
    return t


def priority(table, n=5):
    """위험 지수 높은 순, 같으면 근거 많은 순."""
    return table[table.risk_index.notna()].sort_values(["risk_index", "evidence"], ascending=False).head(n)


def rank_compare(beaches):
    """개수 기준 순위 vs 위험 지수 순위 (공공데이터 측정 지점만)."""
    m = beaches[beaches.has_debris_data].copy()
    m["위험 지수"] = [risk_index(r.hazard_index, r.emd, r.village_fishery, r.coast_side, False)
                  for r in m.itertuples()]
    m["개수 순위"] = m.total_items.rank(ascending=False, method="min").astype(int)
    m["위험 지수 순위"] = m["위험 지수"].rank(ascending=False, method="min").astype(int)
    out = m[["name", "total_items", "fishing_gear_share", "hazard_index", "위험 지수", "개수 순위", "위험 지수 순위"]]
    out = out.rename(columns={"name": "지점", "total_items": "쓰레기 개수", "fishing_gear_share": "폐어구 비율",
                              "hazard_index": "평균 위해성"})
    out["쓰레기 개수"] = out["쓰레기 개수"].astype(int)
    out["폐어구 비율"] = (out["폐어구 비율"] * 100).round(1).astype(str) + "%"
    return out.sort_values("위험 지수 순위")


# ---------- 민감도 분석 ----------
def _spearman(a, b):
    """두 순위 목록의 스피어만 순위상관 (동점은 평균 순위)."""
    ra, rb = pd.Series(a).rank(), pd.Series(b).rank()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(ra.corr(rb))


def scenario_grid():
    """가중치를 기본값 주변에서 넓게 흔든 조합들."""
    grid = []
    for fg in (2, 3, 4, 5):
        for pl in (1.5, 2, 2.5):
            for ds in (0.0, 0.5, 1.0, 1.5):
                for fi in (1.0, 1.25, 1.5, 2.0):
                    if pl >= fg:
                        continue          # '폐어구가 가장 위험'이라는 전제는 유지
                    w = default_weights()
                    w["hazard"].update(fishing_gear=fg, plastic=pl, styrofoam=pl)
                    w.update(dolphin_scale=ds, fishery=fi)
                    grid.append(w)
    return grid


def robustness(beaches, reports, records, winter_on, top_k=3):
    """여러 가중치 조합에서 순위가 얼마나 유지되는지."""
    base = build_table(beaches, reports, winter_on, records)
    base = base[base.risk_index.notna()]
    names = list(base.sort_values("risk_index", ascending=False).name)
    base_rank = base.set_index("name").risk_index.rank(ascending=False, method="min")
    ranks, rhos = {n: [] for n in names}, []
    grid = scenario_grid()
    for w in grid:
        t = build_table(beaches, reports, winter_on, records, w)
        t = t[t.risk_index.notna()].set_index("name")
        r = t.risk_index.rank(ascending=False, method="min")
        for n in names:
            ranks[n].append(int(r[n]))
        rhos.append(_spearman(base_rank[names], r[names]))
    rows = []
    for n in names:
        rs = ranks[n]
        rows.append({"지점": n, "기본 순위": int(base_rank[n]),
                     f"상위 {top_k} 유지율": f"{sum(x <= top_k for x in rs) / len(rs) * 100:.0f}%",
                     "최고 순위": min(rs), "최저 순위": max(rs),
                     "순위 중앙값": float(pd.Series(rs).median())})
    out = pd.DataFrame(rows).sort_values("기본 순위")
    rho = pd.Series(rhos).dropna()
    return out, {"scenarios": len(grid), "rho_mean": float(rho.mean()), "rho_min": float(rho.min())}


def factor_overlap(table):
    """요소 간 중복 점검: 각 요소가 지점을 얼마나 구분하는지와 요소 간 상관."""
    m = table[table.risk_index.notna()].copy()
    f = pd.DataFrame({"평균 위해성": m.avg_hazard.astype(float),
                      "돌고래 가중치": m.dolphin_weight.astype(float),
                      "마을어장 인접": m.village_fishery.astype(float)})
    info = []
    for c in f.columns:
        info.append({"요소": c, "서로 다른 값 수": int(f[c].nunique()),
                     "최솟값": round(f[c].min(), 2), "최댓값": round(f[c].max(), 2),
                     "판정": "구분력 없음 (모든 지점 같음)" if f[c].nunique() <= 1 else
                             ("구분력 약함" if f[c].value_counts(normalize=True).max() >= 0.85 else "구분력 있음")})
    corr = f.loc[:, f.nunique() > 1].corr().round(2)
    return pd.DataFrame(info), corr, len(m)


# ---------- 비전 AI 분류 (Gemini REST, 학습 없음) ----------
PROMPT = ("이 사진은 제주 해안의 쓰레기 사진이다. 가장 많이 보이는 쓰레기 종류를 "
          "fishing_gear(폐어구·그물·로프·낚싯줄·부표·통발), plastic, styrofoam, seaweed, other 중 하나로 고르고, "
          "쓰레기가 아니면 category를 other로 하라. "
          'JSON 한 줄로만 답하라: {"category":"...","reason":"한 문장"}')


def parse_vision_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("AI 응답에서 JSON을 찾지 못했어요")
    d = json.loads(m.group(0))
    cat = d.get("category", "other")
    if cat not in HAZARD:
        cat = "other"
    return {"category": cat, "reason": d.get("reason", "")}


# ---------- 무료 한도 보호 ----------
# Google 무료 등급 한도보다 훨씬 낮게 잡은 자체 상한. 넘으면 API를 아예 부르지 않는다.
SAFE_PER_MINUTE = 5
# 2026.10 기준 이 키에서 동작 확인한 모델 (gemini-2.5-flash는 신규 사용자에게 종료됨)
DEFAULT_MODEL = "gemini-flash-lite-latest"
SAFE_PER_DAY = 100


class QuotaGuard:
    """호출 기록을 파일에 남겨 앱을 껐다 켜도 하루 상한이 유지되게 한다. 같은 사진은 다시 부르지 않는다."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("calls", [])
        self.d.setdefault("cache", {})

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False)

    def _recent(self, now, seconds):
        return [t for t in self.d["calls"] if now - t < seconds]

    def status(self, now):
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        day = [t for t in self.d["calls"] if time.strftime("%Y-%m-%d", time.localtime(t)) == today]
        return {"today": len(day), "last_minute": len(self._recent(now, 60)),
                "day_left": max(0, SAFE_PER_DAY - len(day))}

    def check(self, now):
        st = self.status(now)
        if st["today"] >= SAFE_PER_DAY:
            return f"오늘 AI 호출 {SAFE_PER_DAY}회 상한에 도달했어요. 내일 다시 쓸 수 있어요."
        if st["last_minute"] >= SAFE_PER_MINUTE:
            return f"1분에 {SAFE_PER_MINUTE}회까지만 호출해요. 잠시 후 다시 눌러주세요."
        return None

    def cached(self, h):
        return self.d["cache"].get(h)

    def record(self, now, h, result):
        self.d["calls"] = self._recent(now, 2 * 86400) + [now]
        self.d["cache"][h] = result
        self._save()


def classify_guarded(image_bytes, mime, api_key, guard, model=None, now=None, call=None):
    """캐시 -> 상한 확인 -> 호출. 반환: (결과, 메시지). 결과가 None이면 호출하지 않았거나 실패."""
    now = time.time() if now is None else now
    h = hashlib.sha256(image_bytes).hexdigest()
    hit = guard.cached(h)
    if hit:
        return hit, "같은 사진이라 저장된 결과를 썼어요 (호출 안 함)."
    blocked = guard.check(now)
    if blocked:
        return None, blocked
    try:
        res = (call or classify_with_gemini)(image_bytes, mime, api_key, model)
    except Exception as e:
        msg = str(e)
        if "429" in msg:
            return None, "Google 무료 한도에 걸렸어요. 직접 골라서 진행해주세요."
        return None, f"AI 분류 실패: {msg[:120]}"
    guard.record(now, h, res)
    return res, None


def classify_with_gemini(image_bytes, mime, api_key, model=None, timeout=30):
    import requests
    model = model or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"parts": [{"text": PROMPT},
                                    {"inline_data": {"mime_type": mime,
                                                     "data": base64.b64encode(image_bytes).decode()}}]}],
            "generationConfig": {"maxOutputTokens": 400}}
    r = requests.post(url, headers={"x-goog-api-key": api_key}, json=body, timeout=timeout)
    if not r.ok:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text
        raise RuntimeError(f"{r.status_code} {msg[:200]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts)
    return parse_vision_json(text)
