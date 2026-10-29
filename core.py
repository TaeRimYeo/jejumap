"""제주 해안 지킴이 지도 - 점수 계산과 데이터 처리 (UI 없음, 테스트 가능)."""
import base64
import hashlib
import time
import json
import math
import re

import pandas as pd

# 쓰레기 종류별 위해성 가중치
HAZARD = {"fishing_gear": 3, "plastic": 2, "styrofoam": 2, "seaweed": 1, "other": 1}
LABEL = {"fishing_gear": "폐어구·로프·낚싯줄", "plastic": "플라스틱", "styrofoam": "스티로폼",
         "seaweed": "해조류(괭생이모자반 등)", "other": "기타"}

# 돌고래 가중치 (2025 해양생물보호구역 지정 + 2026 보도)
DOLPHIN = {"대정읍": (1.0, "2025 해양생물보호구역(신도리)"),
           "안덕면": (0.5, "2026.2 사계리항 새끼 폐사 목격 보도"),
           "구좌읍": (0.5, "2026.7 월정리 폐어구 걸림 개체 보도")}

FISHERY_W = 1.5      # 마을어장 500m 이내
WINTER_NW_W = 1.2    # 겨울 북서계절풍: 북·서쪽 해안 가중
EMD_LIST = ["구좌읍", "조천읍", "삼양동", "이호동", "애월읍", "한림읍", "한경면", "대정읍", "안덕면",
            "중문동", "서귀포시 동지역", "남원읍", "표선면", "성산읍", "기타"]


def dolphin_weight(emd):
    return DOLPHIN.get(emd, (0.0, ""))[0]


def season_weight(coast_side, winter_on):
    return WINTER_NW_W if winter_on and coast_side in ("북", "서") else 1.0


def sensitivity(emd, near_fishery, coast_side, winter_on):
    """민감도 = (1+돌고래) × 마을어장 × 계절"""
    return (1 + dolphin_weight(emd)) * (FISHERY_W if near_fishery else 1.0) * season_weight(coast_side, winter_on)


def risk_index(hazard, emd, near_fishery, coast_side, winter_on):
    """위험 지수 = 평균 위해성(1~3) × 민감도. 무게 추정 없이 계산."""
    if hazard is None or pd.isna(hazard):
        return float("nan")
    return round(hazard * sensitivity(emd, near_fishery, coast_side, winter_on), 2)


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


def build_table(beaches, reports, winter_on):
    """지점별 위험 지수와 근거 수.
    평균 위해성 = (공공 조사 위해성 1건 + 제보별 위해성) 의 평균
    근거 수   = 공공 조사(1) + 제보 건수"""
    t = beaches.copy().reset_index(drop=True)
    t["hz_sum"] = t["hazard_index"].fillna(0.0)
    t["public_evidence"] = t["hazard_index"].notna().astype(int)
    t["report_count"] = 0
    extra = []
    for rep in reports:
        h = HAZARD[rep["category"]]
        if rep.get("attach_to") is not None and rep["attach_to"] in t.index:
            t.loc[rep["attach_to"], "report_count"] += 1
            t.loc[rep["attach_to"], "hz_sum"] += h
        else:
            extra.append(dict(name=rep["place"], type="시민제보", emd=rep["emd"], lat=rep["lat"], lon=rep["lon"],
                              coast_side=rep["coast_side"], has_debris_data=False, village_fishery=rep["near_fishery"],
                              dolphin_weight=dolphin_weight(rep["emd"]),
                              dolphin_basis=DOLPHIN.get(rep["emd"], (0, ""))[1],
                              hz_sum=float(h), public_evidence=0, report_count=1))
    if extra:
        t = pd.concat([t, pd.DataFrame(extra)], ignore_index=True)
    t["evidence"] = t["public_evidence"] + t["report_count"]
    t["avg_hazard"] = (t["hz_sum"] / t["evidence"]).where(t["evidence"] > 0)
    t["risk_index"] = [risk_index(r.avg_hazard, r.emd, r.village_fishery, r.coast_side, winter_on)
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
