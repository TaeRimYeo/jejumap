"""Streamlit 무료 앱이 잠들지 않게 실제 브라우저로 한 번 열어 둔다 (잠들어 있으면 깨우기 버튼을 누름)."""
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jeju-coast-map.streamlit.app/"

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.goto(URL, timeout=120_000)
    page.wait_for_timeout(15_000)
    btn = page.get_by_role("button", name="Yes, get this app back up!")
    if btn.count():
        print("잠들어 있어 깨우는 중")
        btn.first.click()
        page.wait_for_timeout(90_000)
    else:
        page.wait_for_timeout(30_000)       # 세션을 잠시 유지해 '사용 중'으로 잡히게
    print("완료:", page.title())
    b.close()
