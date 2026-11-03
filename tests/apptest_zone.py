"""?zone= 마을 앞바다 화면 점검 (GitHub Actions에서 실행)."""
from streamlit.testing.v1 import AppTest

def run(q):
    at = AppTest.from_file("app.py", default_timeout=120)
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
btn = next(b for b in at.button if "이상 없어요" in b.label)
btn.click().run()
assert not at.exception, [e.value for e in at.exception]
print("patrol ok:", [s.value for s in at.success][:2])

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
