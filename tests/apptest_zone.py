"""?zone= 마을 앞바다 화면 점검 (GitHub Actions에서 실행)."""
from streamlit.testing.v1 import AppTest

def run(q):
    at = AppTest.from_file("../app.py", default_timeout=120)
    for k, v in q.items():
        at.query_params[k] = v
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at

at = run({"zone": "평대리"})
md = " ".join(m.value for m in at.markdown)
assert "우리 마을 앞바다 · 평대리" in md, md[:300]
codes = [c.value for c in at.code]
assert any("평대리 앞바다" in c for c in codes), codes
print(next(c for c in codes if "평대리 앞바다" in c))
ms = next(m for m in at.multiselect if m.key == "v_patrol_wild")
ms.set_value(["흰물떼새"]).run()
btn = next(b for b in at.button if "이상 없어요" in b.label)
btn.click().run()
assert not at.exception, [e.value for e in at.exception]
succ = [s.value for s in at.success]
print("patrol ok:", succ[:3])
assert any("흰물떼새" in v for v in succ), succ
assert any("최근 관찰한 생물: 흰물떼새" in c.value for c in at.code), [c.value for c in at.code]
# 다른 탭(리포트 표·민감도 화면)도 오류 없이
at.query_params["zone"] = "사계리"
at.run()
assert not at.exception, [e.value for e in at.exception]

at = run({"zone": "비양도 지선 #2"})
assert "우리 마을 앞바다 · 비양도" in " ".join(m.value for m in at.markdown)
at = run({"zone": "없는마을"})
assert any("찾지 못했어요" in i.value for i in at.info)
at = run({})
assert not any("우리 마을 앞바다 ·" in m.value for m in at.markdown)
sel = next(s for s in at.selectbox if s.key == "view_zone")
sel.set_value("이호동 지선").run()
assert not at.exception, [e.value for e in at.exception]
print("select ->", dict(at.query_params))
print("ALL OK")
