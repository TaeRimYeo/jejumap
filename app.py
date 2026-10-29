"""제주 해안 지킴이 지도 (제주쓰담쓰담) - Streamlit 앱
실행:  streamlit run app.py
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import importlib

import core

core = importlib.reload(core)   # 배포 서버가 옛 core.py를 메모리에 들고 있지 않게

BASE = Path(__file__).parent
st.set_page_config(page_title="제주 해안 지킴이 지도", page_icon="🌊", layout="wide")

BLUE, TEAL, ORANGE = "#1D4E9E", "#1A9E8F", "#E8833A"


@st.cache_data
def load_trend():
    return pd.read_csv(BASE / "jeju_collection_trend.csv", encoding="utf-8-sig")


@st.cache_data
def load_beaches():
    return pd.read_csv(BASE / "beaches.csv", encoding="utf-8-sig")


@st.cache_data
def load_records_df():
    try:
        return pd.read_csv(BASE / "records.csv", encoding="utf-8-sig")
    except OSError:
        return pd.DataFrame()


@st.cache_data(show_spinner="가중치 조합 수백 개로 다시 계산 중... (처음 한 번만 걸려요)")
def cached_robustness(reports_json, cleanups_json, winter_on, today):
    return core.robustness(load_beaches(), json.loads(reports_json), load_records_df().to_dict("records"), winter_on,
                           today=today, cleanups=json.loads(cleanups_json))


@st.cache_data
def load_zones():
    try:
        return core.load_zones(BASE / "zones.geojson")
    except OSError:
        return []


ZONE_STYLE = {"확인 기록 없음": {"color": "#C0392B", "dashArray": "5 5", "fillOpacity": 0.10, "weight": 2},
              "오래전 확인": {"color": "#7E6BB0", "dashArray": "", "fillOpacity": 0.15, "weight": 2},
              "최근 확인": {"color": "#2E8B57", "dashArray": "", "fillOpacity": 0.20, "weight": 2}}

STALE, DONE = "#A99BC9", "#FFFFFF"


def color_for(score, status=""):
    if status == "수거 완료":
        return DONE               # 수거 완료 (흰색)
    if "재확인" in status:
        return STALE              # 오래된 근거 / 수거 후 미확인 · 재확인 필요 (회보라)
    if score is None or pd.isna(score):
        return "#B8C2CC"          # 확인 기록 없음
    if score >= 4.5:
        return "#D64545"          # 높음
    if score >= 3:
        return "#F0A030"          # 보통
    return "#3BA272"              # 낮음


beaches = load_beaches()
records_df = load_records_df()
records = records_df.to_dict("records")
REPORTS_FILE = BASE / "reports.json"
if "reports" not in st.session_state:          # 앱을 껐다 켜도 제보 유지
    try:
        st.session_state.reports = json.loads(REPORTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.session_state.reports = []
if "stamps" not in st.session_state:
    st.session_state.stamps = set()
CLEANUPS_FILE = BASE / "cleanups.json"
if "cleanups" not in st.session_state:         # 수거 완료 기록
    try:
        st.session_state.cleanups = json.loads(CLEANUPS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.session_state.cleanups = []


def save_cleanups():
    CLEANUPS_FILE.write_text(json.dumps(st.session_state.cleanups, ensure_ascii=False), encoding="utf-8")


PATROLS_FILE = BASE / "patrols.json"
if "patrols" not in st.session_state:          # 순찰 확인(이상 없음) 기록
    try:
        st.session_state.patrols = json.loads(PATROLS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.session_state.patrols = []


def save_patrols():
    PATROLS_FILE.write_text(json.dumps(st.session_state.patrols, ensure_ascii=False), encoding="utf-8")


TODAY = datetime.now().date()

# ---------------- 사이드바 ----------------
with st.sidebar:
    st.markdown("### 🌊 제주 해안 지킴이 지도")
    st.caption("쓰레기 양이 아니라 **생물에게 위험한 순서**로 수거 우선순위를 보여줍니다.")
    winter = st.toggle("겨울 북서계절풍 가중 (북·서 해안 ×1.2)", value=False)
    st.divider()
    try:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:              # secrets.toml 없음
        api_key = os.environ.get("GEMINI_API_KEY", "")
    guard = core.QuotaGuard(BASE / "ai_usage.json")
    us = guard.status(time.time())
    if api_key:
        st.markdown(f"🤖 AI 분류 **연결됨** · 오늘 {us['today']}/{core.SAFE_PER_DAY}회")
        st.progress(min(1.0, us["today"] / core.SAFE_PER_DAY))
        st.caption(f"무료 한도 보호: 분당 {core.SAFE_PER_MINUTE}회 · 하루 {core.SAFE_PER_DAY}회 상한, 같은 사진은 재호출 안 함")
    else:
        st.caption("AI 키가 없어요. 제보 화면에서 종류를 직접 고르면 됩니다.")
    st.divider()
    st.markdown("**현재 위험 지수**  \n= 보정 위해성 × (1+돌고래) × 마을어장 × 계절 × **최신성**  \n"
                "**보정 위해성** = (근거 위해성 합 + 2) ÷ (근거 수 + 1)  \n"
                "**근거 수** = 공공 조사 + 기관·언론 기록 + 시민 제보")
    st.caption(f"최신성: 근거가 오래될수록 가볍게 반영 (반감기 공공 조사 {core.HALF_LIFE_PUBLIC // 365}년, "
               f"기록·제보 {core.HALF_LIFE_EVENT}일). **수거 완료** 처리하면 그 전 근거는 빠집니다.")
    st.caption("근거가 1건뿐인 곳은 중간값(2)과 반반 섞어서, 제보 한 건으로 순위가 튀지 않게 합니다.")
    st.caption("위해성: 폐어구 3 · 플라스틱/스티로폼 2 · 해조류/기타 1 "
               "(버려진 어구 = 해양생물 위협 1위, Wilcox 외 2016)\n\n"
               "돌고래: 대정 1.0(2025 보호구역) · 안덕·구좌 0.5(2026 보도)")

table = core.build_table(beaches, st.session_state.reports, winter, records,
                         today=TODAY, cleanups=st.session_state.cleanups)

zones = load_zones()
cov = (core.zone_coverage(table, zones, winter, today=TODAY, cleanups=st.session_state.cleanups,
                          patrols=st.session_state.patrols) if zones else None)

tab_map, tab_report, tab_list, tab_check = st.tabs(
    ["🗺️ 위험도 지도", "📸 쓰레기 제보", "📋 우선 수거 리포트", "🔬 가중치 검증"])

# ---------------- 1. 지도 ----------------
with tab_map:
    tr = load_trend()
    st.markdown("#### 제주 해양쓰레기 수거량, 5년 새 1.6배")
    p1 = tr[tr.연도.between(2014, 2018)]["제주 합계"].mean()
    p2 = tr[tr.연도.between(2019, 2023)]["제주 합계"].mean()
    peak = tr.loc[tr["제주 합계"].idxmax()]
    k1, k2, k3 = st.columns(3)
    k1.metric("연평균 수거량 (2019–2023)", f"{p2:,.0f}톤", f"{(p2 / p1 - 1) * 100:+.0f}% vs 2014–2018")
    k2.metric("최대 수거 연도", f"{int(peak.연도)}년", f"{peak['제주 합계']:,.0f}톤")
    k3.metric("전국 대비 제주 비중 (최대)", f"{tr['제주 비중(%)'].max():.1f}%")
    st.bar_chart(tr[tr.연도 >= 2009].set_index("연도")[["제주시", "서귀포시", "제주 기타"]],
                 color=["#1D4E9E", "#6FA8DC", "#B8C2CC"], height=240, y_label="수거량(톤)")
    st.caption("출처: 해양환경공단_해양쓰레기 조사_지역별_20231231 (연도별 수거량). "
               "치우는 양은 늘었지만, 어디부터 치울지 정하는 기준은 아직 없습니다.")
    st.divider()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("지도 지점", len(table))
    c2.metric("최근 근거 지점", int((table.status == "최근 근거").sum()))
    c3.metric("재확인 필요", int(table.status.str.contains("재확인").sum()))
    c4.metric("수거 완료", int((table.status == "수거 완료").sum()))
    c5.metric("확인 기록 없음", int((table.status == core.NO_CHECK).sum()))
    st.caption(f"근거: 공공 조사(2021) {int(beaches.hazard_index.notna().sum())}곳 · 기관·언론 기록 {len(records)}건 · "
               f"시민 제보 {len(st.session_state.reports)}건 · 기준일 {TODAY:%Y-%m-%d}")

    if cov is not None:
        cs = core.coverage_summary(cov)
        st.markdown("#### 🕳️ 해안 확인 공백: 제보가 없는 곳은 '깨끗한 곳'이 아니라 '모르는 곳'")
        z1, z2, z3, z4 = st.columns(4)
        z1.metric("해안 구역 (마을어장 지선)", f"{cs['total']}곳")
        z2.metric(f"최근 {core.RECENT_CHECK_DAYS}일 안에 확인",
                  f"{cs['최근 확인']}곳 ({cs['최근 확인'] / cs['total'] * 100:.0f}%)")
        z3.metric("오래전 확인", f"{cs['오래전 확인']}곳")
        z4.metric("확인 기록 없음", f"{cs['확인 기록 없음']}곳")
        dall = cov[cov.dolphin >= 1.0]
        dz = dall[dall.state == "확인 기록 없음"]
        if len(dz):
            st.warning(f"돌고래 보호구역이 있는 **대정읍 해안 {len(dall)}개 구역 중 {len(dz)}곳이 확인 기록 없음**입니다. "
                       "위험 순위에 안 나오는 건 안전해서가 아니라 아무도 보지 않았기 때문입니다.")
        show_zones = st.toggle("지도에 해안 구역별 확인 상태 표시", value=True)
    else:
        show_zones = False

    m = folium.Map(location=[33.38, 126.55], zoom_start=10, tiles="OpenStreetMap")
    if show_zones:
        info = cov.set_index("zone_id")
        feats = []
        for f in zones:
            zi = info.loc[f["properties"]["zone_id"]]
            p = dict(f["properties"], state=zi.state, last_check=zi.last_check or "없음",
                     points=zi.points or "-")
            feats.append({**f, "properties": p})
        folium.GeoJson(
            {"type": "FeatureCollection", "features": feats}, name="해안 구역",
            style_function=lambda f: {**ZONE_STYLE[f["properties"]["state"]],
                                      "fillColor": ZONE_STYLE[f["properties"]["state"]]["color"]},
            tooltip=folium.GeoJsonTooltip(fields=["name", "emd", "state", "last_check", "points"],
                                          aliases=["구역", "읍면동", "상태", "마지막 확인", "확인한 지점"]),
        ).add_to(m)
    for r in table.itertuples():
        src = ORANGE if r.report_count else (TEAL if r.record_count else BLUE)
        score = r.risk_index
        size = 7 if pd.isna(score) else min(24, 9 + 3 * r.evidence)
        if r.status == "수거 완료":
            size, src = 10, "#3BA272"
        tip = f"{r.name} · " + (f"✅ 수거 완료 ({r.last_cleanup})" if r.status == "수거 완료" else
                                "확인 기록 없음 (제보 필요)" if pd.isna(score) else
                                f"위험 지수 {score:.2f} · 근거 {r.evidence}건 · {r.status}")
        pop = (f"<b>{r.name}</b> ({r.type})<br>"
               f"상태: <b>{r.status}</b>" + (f" (마지막 근거 {r.last_date})" if r.last_date else "")
               + (f"<br>마지막 수거 완료: {r.last_cleanup}" if r.last_cleanup else "") + "<br>"
               f"위험 지수: {'-' if pd.isna(score) else f'{score:.2f}'}"
               f"{'' if pd.isna(r.freshness) else f' (최신성 {r.freshness:.2f})'}<br>"
               f"보정 위해성: {'-' if pd.isna(r.adj_hazard) else f'{r.adj_hazard:.2f}'}"
               f" (원래 {'-' if pd.isna(r.avg_hazard) else f'{r.avg_hazard:.2f}'})<br>"
               f"근거: 공공 조사 {r.public_evidence} · 기관 기록 {r.record_count} · 시민 제보 {r.report_count}<br>"
               f"마을어장 인접: {'예' if r.village_fishery else '아니오'}<br>"
               f"돌고래 가중치: {r.dolphin_weight}"
               + (f" ({r.dolphin_basis})" if isinstance(r.dolphin_basis, str) and r.dolphin_basis else ""))
        folium.CircleMarker([r.lat, r.lon], radius=size, color=src, weight=3,
                            fill=True, fill_color=color_for(score, r.status), fill_opacity=0.85,
                            tooltip=tip, popup=folium.Popup(pop, max_width=280)).add_to(m)
    st_folium(m, height=520, use_container_width=True, returned_objects=[])
    st.caption("● 채움색: 빨강 높음(4.5+) · 주황 보통(3–4.5) · 초록 낮음 · **회보라 오래된 근거(재확인 필요)** · "
               "흰색 수거 완료 · 회색 확인 기록 없음　| 크기: 근거 수　"
               "| 테두리: 파랑 공공 조사 · 청록 기관·언론 기록 · 주황 시민 제보 포함")
    if show_zones:
        st.caption("▭ 해안 구역(마을어장 지선): **빨간 점선 = 확인 기록 없음** · 보라 = 오래전 확인"
                   f"({core.RECENT_CHECK_DAYS}일 넘음) · 초록 = 최근 확인. 확인 = 조사·기록·제보·수거 완료·순찰(이상 없음) 중 하나라도 있었던 날. "
                   "출처: 해양수산부 국립해양조사원 어장정보도(마을어업), 추자도 제외")

    st.markdown("#### 📊 현재 위험 순위 (공공 조사 + 기관 기록 + 시민 제보)")
    live = core.priority(table, n=len(table))
    live = live.assign(순위=range(1, len(live) + 1))[
        ["순위", "name", "emd", "risk_index", "status", "last_date", "freshness",
         "public_evidence", "record_count", "report_count", "evidence"]]
    live["freshness"] = live["freshness"].round(2)
    live.columns = ["순위", "지점", "읍면동", "위험 지수", "상태", "마지막 근거", "최신성",
                    "공공 조사", "기관 기록", "시민 제보", "근거 수"]
    st.dataframe(live, hide_index=True, use_container_width=True)
    st.caption("⚠️ 이 순위는 **근거가 있는 지점끼리만** 비교한 것입니다. 순위에 없는 해안은 안전한 곳이 아니라 확인되지 않은 곳이며, "
               "'📋 우선 수거 리포트' 탭의 확인 공백 구역 목록으로 따로 관리합니다.")
    st.caption("제보가 들어오면 올라가고, 시간이 지나거나 수거 완료 처리하면 내려갑니다. "
               "'재확인 필요'는 쓰레기가 없다는 뜻이 아니라 최근에 확인한 사람이 없다는 뜻이에요.")

    if len(records_df):
        st.markdown("#### 🗂️ 기관·언론 정화 기록 (2025–2026)")
        rv = records_df[["date", "place", "category", "amount_kg", "debris", "org", "source", "url", "note"]].copy()
        rv["category"] = rv["category"].map(core.LABEL)
        rv["amount_kg"] = rv["amount_kg"].map(lambda v: "" if pd.isna(v) else f"{v:,.0f}")
        rv.columns = ["날짜", "장소", "분류", "수거량(kg)", "쓰레기 내용", "주체", "출처", "링크", "비고"]
        st.dataframe(rv.fillna(""), hide_index=True, use_container_width=True,
                     column_config={"링크": st.column_config.LinkColumn("링크", display_text="기사")})
        st.caption("바다에 직접 가지 않아도 최신 현장을 반영하기 위해, 장소·날짜·쓰레기 종류가 확인되는 보도만 근거로 넣었습니다. "
                   "위치가 '근사'인 기록은 마을 중심 좌표를 썼습니다.")

    st.markdown("#### 공공데이터(2021)로 본 '개수' 기준 vs '위험 지수' 기준")
    st.dataframe(core.rank_compare(beaches), hide_index=True, use_container_width=True)
    st.caption("출처: 제주특별자치도_해양쓰레기 모니터링 데이터(해양환경공단, 2021년 조사). "
               "공식 조사 정점은 제주에 3곳뿐이라, 나머지 해안은 시민 제보로 채웁니다.")

# ---------------- 2. 제보 ----------------
with tab_report:
    st.markdown("#### 해변 쓰레기를 찍어 올려주세요")
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
        st.balloons()
    left, right = st.columns([1, 1])
    with left:
        photo = st.file_uploader("사진", type=["jpg", "jpeg", "png", "webp"])
        if photo:
            st.image(photo, use_container_width=True)

        opts = ["지도에서 직접 선택"] + list(beaches.name)
        where = st.selectbox("어디인가요?", opts, index=1)
        lat = lon = None
        if where == "지도에서 직접 선택":
            pm = folium.Map(location=[33.38, 126.55], zoom_start=10, tiles="OpenStreetMap")
            click = st_folium(pm, height=320, use_container_width=True, key="pick",
                              returned_objects=["last_clicked"])
            if click and click.get("last_clicked"):
                lat, lon = click["last_clicked"]["lat"], click["last_clicked"]["lng"]
                st.caption(f"선택한 위치: {lat:.5f}, {lon:.5f}")
        else:
            row = beaches[beaches.name == where].iloc[0]
            lat, lon = float(row.lat), float(row.lon)

    with right:
        ai = None
        if photo and api_key and st.button("🤖 AI로 종류 판별", use_container_width=True):
            with st.spinner("사진 분석 중..."):
                ai, msg = core.classify_guarded(photo.getvalue(), photo.type, api_key, guard)
            if ai:
                st.session_state.ai = ai
            if msg:                          # 상한·실패 시에도 수동 입력으로 계속
                (st.info if ai else st.warning)(msg)
        ai = st.session_state.get("ai")
        if ai:
            st.success(f"AI 판별: **{core.LABEL[ai['category']]}**  \n{ai['reason']}")

        cats = list(core.HAZARD)
        cat = st.radio("쓰레기 종류", cats, format_func=lambda c: core.LABEL[c],
                       index=cats.index(ai["category"]) if ai else 0)

        emd_default = None
        if lat is not None:
            near, dist = core.nearest_point(beaches, lat, lon)
            emd_default = near.emd if dist < 3000 else None
        emd = st.selectbox("읍면동", core.EMD_LIST,
                           index=core.EMD_LIST.index(emd_default) if emd_default in core.EMD_LIST else 0)

        if st.button("제보하기", type="primary", use_container_width=True, disabled=lat is None):
            near, dist = core.nearest_point(beaches, lat, lon)
            attach = int(near.name) if dist <= 1000 else None
            fishery = bool(near.village_fishery) if dist <= 1000 else True  # 제주 해안 대부분 마을어장
            place = near["name"] if attach is not None else f"제보 지점 ({emd})"
            st.session_state.reports.append(dict(
                time=datetime.now().strftime("%Y-%m-%d %H:%M"), place=place, lat=lat, lon=lon, emd=emd,
                category=cat, near_fishery=fishery, coast_side=core.coast_side(lat, lon),
                attach_to=attach, ai=bool(ai)))
            st.session_state.pop("ai", None)
            REPORTS_FILE.write_text(json.dumps(st.session_state.reports, ensure_ascii=False), encoding="utf-8")
            new = core.build_table(beaches, st.session_state.reports, winter, records,
                                   today=TODAY, cleanups=st.session_state.cleanups)
            after, _ = core.nearest_point(new, lat, lon)     # 이름이 '#2'로 바뀌어도 위치로 찾음
            place = after["name"]
            st.session_state.stamps.add(place)
            st.session_state.flash = (f"제보 완료! **{place}** 위험 지수 {after.risk_index:.2f} · "
                                      f"근거 {after.evidence}건  \n🏅 '{place}' 해안 스탬프를 받았어요.")
            st.rerun()                     # 지도·리포트에 바로 반영

    if st.session_state.stamps:
        st.markdown("#### 🏅 나의 해안 스탬프")
        st.write(" · ".join(sorted(st.session_state.stamps)))

# ---------------- 3. 리포트 ----------------
with tab_list:
    st.markdown("#### 우선 수거 구역 (바다환경지킴이·행정 전달용)")
    rep = core.priority(table, 5)
    rep = rep.assign(순위=range(1, len(rep) + 1))[
        ["순위", "name", "emd", "risk_index", "adj_hazard", "evidence", "record_count", "report_count",
         "village_fishery", "dolphin_basis"]]
    rep["adj_hazard"] = rep["adj_hazard"].round(2)
    rep.columns = ["순위", "지점", "읍면동", "위험 지수", "보정 위해성", "근거 수", "기관 기록", "제보 수",
                   "마을어장 인접", "돌고래 근거"]
    rep["돌고래 근거"] = rep["돌고래 근거"].fillna("")
    st.caption("위험 지수가 같으면 근거가 많은 곳이 먼저입니다. 근거 1건인 지점은 현장 확인을 권장합니다.")
    st.dataframe(rep, hide_index=True, use_container_width=True)
    st.download_button("📥 지킴이 전달용 CSV 다운로드", rep.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"우선수거구역_{datetime.now():%Y%m%d}.csv", mime="text/csv")

    st.divider()
    st.markdown("#### ✅ 수거 완료 처리")
    st.caption("지킴이가 수거를 마친 지점을 완료 처리하면, 그 전까지의 근거는 점수에서 빠지고 지도에 흰색으로 표시됩니다. "
               "이후 새 제보가 들어오면 다시 순위에 올라옵니다.")
    open_sites = list(core.priority(table, n=len(table)).name)
    if open_sites:
        cc1, cc2, cc3 = st.columns([2, 2, 1])
        site = cc1.selectbox("완료할 지점", open_sites, key="cleanup_site")
        who = cc2.text_input("처리자 / 메모 (선택)", key="cleanup_who", placeholder="예: 안덕면 바다환경지킴이 2명")
        cc3.write("")
        if cc3.button("수거 완료", type="primary", use_container_width=True):
            st.session_state.cleanups.append({"site": site, "date": TODAY.isoformat(), "by": who,
                                              "logged": datetime.now().strftime("%Y-%m-%d %H:%M")})
            save_cleanups()
            st.session_state.flash_clean = f"✅ **{site}** 수거 완료 처리됨. 지도와 순위에서 내려갔어요."
            st.rerun()
    if st.session_state.get("flash_clean"):
        st.success(st.session_state.pop("flash_clean"))
    if st.session_state.cleanups:
        log = pd.DataFrame(st.session_state.cleanups)[["date", "site", "by", "logged"]]
        log.columns = ["완료일", "지점", "처리자/메모", "기록 시각"]
        st.dataframe(log.iloc[::-1], hide_index=True, use_container_width=True)
        if st.button("↩️ 마지막 완료 처리 되돌리기"):
            st.session_state.cleanups.pop()
            save_cleanups()
            st.rerun()

    if cov is not None:
        st.divider()
        st.markdown("#### 🕳️ 확인 공백 구역 (한 번도 확인되지 않은 해안부터)")
        st.caption("제보·기록이 없는 구역은 깨끗한 게 아니라 **모르는 곳**입니다. 위험 순위에는 안 나오므로 따로 순찰 목록을 만듭니다. "
                   "순서: 확인 기록 없음 → 오래전 확인, 같은 상태 안에서는 민감도(돌고래·마을어장·겨울 북서풍) 높은 곳 먼저.")
        gap = cov[cov.state != "최근 확인"].head(15)
        gv = gap[["zone", "emd", "state", "sensitivity", "last_check", "points"]].copy()
        gv.insert(0, "순서", range(1, len(gv) + 1))
        gv.columns = ["순서", "해안 구역", "읍면동", "상태", "민감도", "마지막 확인", "근처 지점"]
        st.dataframe(gv, hide_index=True, use_container_width=True)
        full = cov[cov.state != "최근 확인"][["zone", "emd", "state", "sensitivity", "last_check", "lat", "lon"]]
        full.columns = ["해안 구역", "읍면동", "상태", "민감도", "마지막 확인", "위도", "경도"]
        st.download_button(f"📥 확인 공백 구역 전체 {len(full)}곳 CSV", full.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"확인공백구역_{datetime.now():%Y%m%d}.csv", mime="text/csv")

        st.markdown("##### 🧭 순찰 확인 기록 (쓰레기 이상 없음)")
        st.caption("순찰했는데 쓰레기가 거의 없었다면 여기서 기록하세요. 이 구역은 '최근 확인'으로 바뀌어 공백 목록에서 빠지고, "
                   f"{core.RECENT_CHECK_DAYS}일이 지나면 다시 공백 목록에 올라옵니다. "
                   "**쓰레기가 있었다면 '📸 쓰레기 제보' 탭에서 제보**해야 위험 순위에 반영됩니다.")
        todo = list(cov[cov.state != "최근 확인"].zone)
        if todo:
            pz1, pz2, pz3 = st.columns([2, 2, 1])
            pz = pz1.selectbox("순찰한 구역", todo, key="patrol_zone",
                               format_func=lambda z: f"{z} ({cov.set_index('zone').at[z, 'emd']})")
            pwho = pz2.text_input("순찰자 / 메모 (선택)", key="patrol_who", placeholder="예: 대정읍 지킴이, 해변 2km 도보")
            pz3.write("")
            if pz3.button("이상 없음 기록", use_container_width=True):
                st.session_state.patrols.append({"zone": pz, "date": TODAY.isoformat(), "by": pwho,
                                                 "logged": datetime.now().strftime("%Y-%m-%d %H:%M")})
                save_patrols()
                st.session_state.flash_patrol = f"🧭 **{pz}** 순찰 확인(이상 없음) 기록됨. 공백 목록에서 빠졌어요."
                st.rerun()
        if st.session_state.get("flash_patrol"):
            st.success(st.session_state.pop("flash_patrol"))
        if st.session_state.patrols:
            plog = pd.DataFrame(st.session_state.patrols)[["date", "zone", "by", "logged"]]
            plog.columns = ["순찰일", "해안 구역", "순찰자/메모", "기록 시각"]
            st.dataframe(plog.iloc[::-1], hide_index=True, use_container_width=True)
            if st.button("↩️ 마지막 순찰 기록 되돌리기"):
                st.session_state.patrols.pop()
                save_patrols()
                st.rerun()

    stale = table[table.status.str.contains("재확인")].sort_values("potential", ascending=False)
    if len(stale):
        st.divider()
        st.markdown("#### 🔎 재확인 권장 지점 (예전에 쓰레기가 확인된 곳)")
        sv = stale[["name", "emd", "status", "potential", "last_date", "last_cleanup"]].copy()
        sv.columns = ["지점", "읍면동", "상태", "원래 위험도", "마지막 근거", "마지막 수거"]
        st.dataframe(sv, hide_index=True, use_container_width=True)
        st.caption("예전에 쓰레기가 확인됐지만 최근 근거가 없는 곳입니다. 깨끗해졌는지, 아무도 안 가 봤는지 모르니 순찰로 확인하세요. "
                   "**원래 위험도**(시간 감쇠를 빼고 본 점수)가 높은 곳부터 가면 됩니다.")

    if st.session_state.reports:
        st.markdown("#### 제보 기록")
        st.dataframe(pd.DataFrame(st.session_state.reports)[["time", "place", "emd", "category", "ai"]],
                     hide_index=True, use_container_width=True)

# ---------------- 4. 가중치 검증 ----------------
with tab_check:
    st.markdown("#### 가중치를 바꿔도 순위가 유지될까?")
    st.caption("위해성 3·2·1은 측정값이 아니라 순위 척도입니다. 숫자를 바꿔 보며 결과가 얼마나 흔들리는지 직접 확인하세요.")
    a, b = st.columns(2)
    with a:
        fg = st.slider("폐어구·로프·낚싯줄", 1.0, 5.0, 3.0, 0.5)
        pl = st.slider("플라스틱·스티로폼", 1.0, 5.0, 2.0, 0.5)
        ot = st.slider("해조류·기타", 0.5, 3.0, 1.0, 0.5)
    with b:
        ds = st.slider("돌고래 가중치 배율 (0 = 돌고래 무시)", 0.0, 2.0, 1.0, 0.25)
        fi = st.slider("마을어장 인접 배율", 1.0, 2.0, core.FISHERY_W, 0.25)
        kk = st.slider("근거 수 보정 강도 (0 = 보정 없음)", 0.0, 3.0, core.PRIOR_K, 0.5)
        hl = st.slider("기록·제보 반감기 (일)", 30, 720, core.HALF_LIFE_EVENT, 30)
    w = core.default_weights()
    w["hazard"].update(fishing_gear=fg, plastic=pl, styrofoam=pl, seaweed=ot, other=ot)
    w.update(dolphin_scale=ds, fishery=fi, prior_k=kk, hl_event=hl)
    custom = core.build_table(beaches, st.session_state.reports, winter, records, w,
                              today=TODAY, cleanups=st.session_state.cleanups)
    base_t = table[table.risk_index.notna()].set_index("name")
    cus_t = custom[custom.risk_index.notna()].set_index("name")
    base_r = base_t.risk_index.rank(ascending=False, method="min").astype(int)
    cus_r = cus_t.risk_index.rank(ascending=False, method="min").astype(int)
    cmp = pd.DataFrame({"기본 순위": base_r, "바꾼 가중치 순위": cus_r, "바꾼 위험 지수": cus_t.risk_index})
    cmp["변화"] = (cmp["기본 순위"] - cmp["바꾼 가중치 순위"]).map(lambda d: "—" if d == 0 else (f"▲{d}" if d > 0 else f"▼{-d}"))
    st.dataframe(cmp.sort_values("바꾼 가중치 순위").reset_index(names="지점"), hide_index=True, use_container_width=True)
    if pl >= fg:
        st.warning("플라스틱이 폐어구보다 같거나 높게 설정됐어요. 연구 근거(버려진 어구 = 위협 1위)와 반대되는 가정입니다.")

    st.divider()
    st.markdown("#### 자동 민감도 분석")
    rb_args = (json.dumps(st.session_state.reports, ensure_ascii=False),
               json.dumps(st.session_state.cleanups, ensure_ascii=False), winter, TODAY.isoformat())
    if st.session_state.get("rb_args") != rb_args:
        st.caption("가중치 조합 수백 개로 순위를 다시 계산합니다. 제보·수거 기록이 바뀌면 다시 눌러 주세요.")
        if st.button("▶️ 민감도 분석 실행 (5–10초)", type="primary"):
            st.session_state.rb_result = cached_robustness(*rb_args)
            st.session_state.rb_args = rb_args
            st.rerun()
    if st.session_state.get("rb_args") == rb_args:
        rb, summ = st.session_state.rb_result
        m1, m2, m3 = st.columns(3)
        m1.metric("시험한 조합", f"{summ['scenarios']}개")
        m2.metric("기본 순위와 평균 순위상관", f"{summ['rho_mean']:.2f}")
        m3.metric("가장 다른 조합의 순위상관", f"{summ['rho_min']:.2f}")
        st.dataframe(rb, hide_index=True, use_container_width=True)
        st.caption("폐어구 2–5, 플라스틱·스티로폼 1.5–2.5, 돌고래 배율 0–1.5, 마을어장 1–2, 근거 수 보정 0·1, "
                   "기록·제보 반감기 90·180·365일을 조합해 다시 계산했습니다 (폐어구가 가장 위험하다는 전제는 유지). "
                   "순위상관은 1에 가까울수록 순위가 그대로라는 뜻입니다.")
        st.info("**읽는 법:** 상위 3 유지율이 100%인 지점은 가중치를 어떻게 바꿔도 우선 수거 대상입니다. "
                "유지율이 낮은 지점은 특정 요소에 순위가 기대는 곳입니다. 특히 근거가 오래된 지점은 **반감기를 몇 일로 "
                "잡느냐**에 따라 순위가 크게 바뀌므로, 위 반감기 슬라이더로 직접 확인해 보세요. "
                "공식을 숨기지 않고 어떤 요소가 순위를 만드는지 보여주는 화면입니다.")

    st.divider()
    st.markdown("#### 요소 간 중복 점검")
    info, corr, n = core.factor_overlap(table)
    st.dataframe(info, hide_index=True, use_container_width=True)
    if not corr.empty and corr.shape[0] > 1:
        st.caption(f"근거가 있는 {n}개 지점에서 요소 간 상관계수")
        st.dataframe(corr, use_container_width=True)
    st.caption("마을어장은 제주 해안 대부분에 있어 지점을 거의 구분하지 못합니다(구분력 약함). 그래서 순위를 정하는 힘은 "
               "주로 쓰레기 위해성과 돌고래 근거에서 나옵니다. 지점 수가 적어 상관계수는 참고용입니다.")
