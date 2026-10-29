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

import core

BASE = Path(__file__).parent
st.set_page_config(page_title="제주 해안 지킴이 지도", page_icon="🌊", layout="wide")

BLUE, ORANGE = "#1D4E9E", "#E8833A"


@st.cache_data
def load_trend():
    return pd.read_csv(BASE / "jeju_collection_trend.csv", encoding="utf-8-sig")


@st.cache_data
def load_beaches():
    return pd.read_csv(BASE / "beaches.csv", encoding="utf-8-sig")


def color_for(score):
    if score is None or pd.isna(score):
        return "#B8C2CC"          # 미측정
    if score >= 4.5:
        return "#D64545"          # 높음
    if score >= 3:
        return "#F0A030"          # 보통
    return "#3BA272"              # 낮음


beaches = load_beaches()
REPORTS_FILE = BASE / "reports.json"
if "reports" not in st.session_state:          # 앱을 껐다 켜도 제보 유지
    try:
        st.session_state.reports = json.loads(REPORTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.session_state.reports = []
if "stamps" not in st.session_state:
    st.session_state.stamps = set()

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
    st.markdown("**위험 지수**  \n= 평균 위해성 × (1+돌고래) × 마을어장 × 계절  \n**근거 수** = 공공 조사 + 제보 건수")
    st.caption("위해성: 폐어구 3 · 플라스틱/스티로폼 2 · 해조류/기타 1\n\n"
               "돌고래: 대정 1.0(2025 보호구역) · 안덕·구좌 0.5(2026 보도)")

table = core.build_table(beaches, st.session_state.reports, winter)

tab_map, tab_report, tab_list = st.tabs(["🗺️ 위험도 지도", "📸 쓰레기 제보", "📋 우선 수거 리포트"])

# ---------------- 1. 지도 ----------------
with tab_map:
    tr = load_trend()
    st.markdown("#### 제주 해양쓰레기 수거량, 5년 새 1.6배")
    p1 = tr[tr.연도.between(2014, 2018)]["제주 합계"].mean()
    p2 = tr[tr.연도.between(2019, 2023)]["제주 합계"].mean()
    peak = tr.loc[tr["제주 합계"].idxmax()]
    k1, k2, k3 = st.columns(3)
    k1.metric("연평균 수거량 (2019~2023)", f"{p2:,.0f}톤", f"{(p2 / p1 - 1) * 100:+.0f}% vs 2014~2018")
    k2.metric("최대 수거 연도", f"{int(peak.연도)}년", f"{peak['제주 합계']:,.0f}톤")
    k3.metric("전국 대비 제주 비중 (최대)", f"{tr['제주 비중(%)'].max():.1f}%")
    st.bar_chart(tr[tr.연도 >= 2009].set_index("연도")[["제주시", "서귀포시", "제주 기타"]],
                 color=["#1D4E9E", "#6FA8DC", "#B8C2CC"], height=240, y_label="수거량(톤)")
    st.caption("출처: 해양환경공단_해양쓰레기 조사_지역별_20231231 (연도별 수거량). "
               "치우는 양은 늘었지만, 어디부터 치울지 정하는 기준은 아직 없습니다.")
    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("지도 지점", len(table))
    c2.metric("공공데이터 측정 지점", int(table.public_evidence.sum()))
    c3.metric("시민 제보", len(st.session_state.reports))
    c4.metric("미측정 지점", int(table.risk_index.isna().sum()))

    m = folium.Map(location=[33.38, 126.55], zoom_start=10, tiles="OpenStreetMap")
    for r in table.itertuples():
        src = BLUE if r.report_count == 0 else ORANGE
        score = r.risk_index
        size = 7 if pd.isna(score) else min(24, 9 + 3 * r.evidence)
        tip = f"{r.name} · " + ("미측정 (제보 필요)" if pd.isna(score) else f"위험 지수 {score:.2f} · 근거 {r.evidence}건")
        pop = (f"<b>{r.name}</b> ({r.type})<br>"
               f"위험 지수: {'미측정' if pd.isna(score) else f'{score:.2f}'}<br>"
               f"평균 위해성: {'-' if pd.isna(r.avg_hazard) else f'{r.avg_hazard:.2f}'}<br>"
               f"근거: 공공 조사(2021) {r.public_evidence}건 · 시민 제보 {r.report_count}건<br>"
               f"마을어장 인접: {'예' if r.village_fishery else '아니오'}<br>"
               f"돌고래 가중치: {r.dolphin_weight}"
               + (f" ({r.dolphin_basis})" if isinstance(r.dolphin_basis, str) and r.dolphin_basis else ""))
        folium.CircleMarker([r.lat, r.lon], radius=size, color=src, weight=3,
                            fill=True, fill_color=color_for(score), fill_opacity=0.85,
                            tooltip=tip, popup=folium.Popup(pop, max_width=280)).add_to(m)
    st_folium(m, height=520, use_container_width=True, returned_objects=[])
    st.caption("● 채움색: 빨강 높음(4.5+) · 주황 보통(3~4.5) · 초록 낮음 · 회색 미측정　"
               "| 크기: 근거 수　| 테두리: 파랑 공공데이터(2021) · 주황 시민 제보 포함")

    st.markdown("#### 📊 현재 위험 순위 (공공데이터 + 시민 제보)")
    live = core.priority(table, n=len(table))
    live = live.assign(순위=range(1, len(live) + 1))[
        ["순위", "name", "emd", "risk_index", "public_evidence", "report_count", "evidence"]]
    live.columns = ["순위", "지점", "읍면동", "위험 지수", "공공 조사", "시민 제보", "근거 수"]
    st.dataframe(live, hide_index=True, use_container_width=True)
    st.caption(f"제보가 들어올 때마다 바뀝니다. 아직 근거가 없는 지점 {int(table.risk_index.isna().sum())}곳은 순위에서 빠져 있어요.")

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
            st.session_state.stamps.add(place)
            st.session_state.pop("ai", None)
            REPORTS_FILE.write_text(json.dumps(st.session_state.reports, ensure_ascii=False), encoding="utf-8")
            new = core.build_table(beaches, st.session_state.reports, winter)
            after = new[new.name == place].iloc[0]
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
        ["순위", "name", "emd", "risk_index", "avg_hazard", "evidence", "report_count", "village_fishery", "dolphin_basis"]]
    rep.columns = ["순위", "지점", "읍면동", "위험 지수", "평균 위해성", "근거 수", "제보 수", "마을어장 인접", "돌고래 근거"]
    rep["돌고래 근거"] = rep["돌고래 근거"].fillna("")
    st.caption("위험 지수가 같으면 근거가 많은 곳이 먼저입니다. 근거 1건인 지점은 현장 확인을 권장합니다.")
    st.dataframe(rep, hide_index=True, use_container_width=True)
    st.download_button("📥 지킴이 전달용 CSV 다운로드", rep.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"우선수거구역_{datetime.now():%Y%m%d}.csv", mime="text/csv")

    if st.session_state.reports:
        st.markdown("#### 제보 기록")
        st.dataframe(pd.DataFrame(st.session_state.reports)[["time", "place", "emd", "category", "ai"]],
                     hide_index=True, use_container_width=True)
