"""Streamlit 무료 앱이 잠들지 않게 실제 브라우저로 열어 두고(잠들어 있으면 깨우기 버튼을 누름),
앱이 오류 화면을 띄우는지도 검사한다. 오류가 보이면 실패로 끝나 GitHub Actions에 빨간 표시가 남는다."""
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jeju-coast-map.streamlit.app/"
ERROR_WORDS = ("Traceback", "This app has encountered an error", "KeyError", "TypeError", "ValueError")


def app_text(page):
    texts = []
    for f in page.frames:
        try:
            texts.append(f.inner_text("body", timeout=5_000))
        except Exception:
            pass
    return "\n".join(texts)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1400, "height": 1000})
    page.goto(URL, timeout=120_000)
    page.wait_for_timeout(15_000)
    btn = page.get_by_role("button", name="Yes, get this app back up!")
    if btn.count():
        print("잠들어 있어 깨우는 중")
        btn.first.click()
        page.wait_for_timeout(120_000)
    else:
        page.wait_for_timeout(30_000)
    text = app_text(page)
    found = [w for w in ERROR_WORDS if w in text]
    ok = "제주 해안 지킴이 지도" in text
    print("앱 화면 확인:", "정상" if ok and not found else f"이상 (오류 단어 {found}, 제목 보임 {ok})")
    print(text[:600])
    b.close()
    sys.exit(1 if found or not ok else 0)
