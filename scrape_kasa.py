# -*- coding: utf-8 -*-
"""우주항공청 사업공고 수집 스크립트 v3 (GitHub Actions에서 자동 실행)
   - 직접 접속이 차단될 경우(해외 IP 차단) 중계 서비스를 경유해 수집
"""
import json, re, sys, time
import requests
from bs4 import BeautifulSoup

TARGET = "https://www.kasa.go.kr/bbs/BBSMSTR_000000000018.do"
BASE = "https://www.kasa.go.kr"
MAX_ITEMS = 10
DATE_RE = re.compile(r"(\d{4})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
}

# 접속 경로: ① 직접 → ② 중계 서비스들 (해외 IP 차단 우회)
import urllib.parse
q = urllib.parse.quote(TARGET, safe="")
ROUTES = [
    ("직접 접속", TARGET, 12),
    ("중계: allorigins", f"https://api.allorigins.win/raw?url={q}", 30),
    ("중계: codetabs",   f"https://api.codetabs.com/v1/proxy?quest={q}", 30),
    ("중계: corsproxy",  f"https://corsproxy.io/?url={q}", 30),
]

def norm_href(href: str) -> str:
    if not href or href == "#" or href.lower().startswith("javascript"):
        return TARGET
    if href.startswith("http"):
        return href
    return BASE + (href if href.startswith("/") else "/" + href)

def find_date(el) -> str:
    node = el
    for _ in range(4):
        if node is None:
            break
        m = DATE_RE.search(node.get_text(" ", strip=True))
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        node = node.parent
    return ""

def get_page():
    for name, url, tmo in ROUTES:
        try:
            res = requests.get(url, headers=HEADERS, timeout=tmo)
            ok = res.status_code == 200 and len(res.text) > 3000
            print(f"[진단] {name} → 상태 {res.status_code}, 본문 {len(res.text):,}자 "
                  f"{'✓ 사용' if ok else '✗ 건너뜀'}")
            if ok:
                return res.text
        except Exception as e:
            print(f"[진단] {name} 실패: {type(e).__name__}: {e}")
        time.sleep(1)
    print("[오류] 모든 경로 접속 실패", file=sys.stderr)
    sys.exit(1)

def parse(html: str):
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()

    def add(title, date, href):
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 4 or title in seen:
            return
        seen.add(title)
        items.append({"title": title, "date": date, "href": norm_href(href)})

    # 1차: nttId 링크
    for a in soup.select('a[href*="nttId"]'):
        add(a.get_text(strip=True), find_date(a), a.get("href", ""))
        if len(items) >= MAX_ITEMS: return items

    # 2차: 표(tr) 기반
    if not items:
        print("[진단] nttId 링크 없음 → 표(tr) 파서 시도")
        for tr in soup.select("tr"):
            a = tr.find("a")
            m = DATE_RE.search(tr.get_text(" ", strip=True))
            if not a or not m: continue
            add(a.get_text(strip=True),
                f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                a.get("href", ""))
            if len(items) >= MAX_ITEMS: break

    # 3차: 목록(li) 기반
    if not items:
        print("[진단] 표 파서 실패 → 목록(li) 파서 시도")
        for li_el in soup.select("li"):
            a = li_el.find("a")
            m = DATE_RE.search(li_el.get_text(" ", strip=True))
            if not a or not m: continue
            t = a.get_text(strip=True)
            if len(t) < 8: continue
            add(t, f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                a.get("href", ""))
            if len(items) >= MAX_ITEMS: break
    return items

def main():
    html = get_page()
    items = parse(html)
    if not items:
        snippet = re.sub(r"\s+", " ", html[:1500])
        print(f"[오류] 공고를 찾지 못했습니다. 페이지 앞부분:\n{snippet}", file=sys.stderr)
        sys.exit(1)

    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    out = {"updated": datetime.now(kst).strftime("%Y-%m-%d %H:%M"), "items": items}
    with open("kasa_feed.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[성공] 공고 {len(items)}건 저장:")
    for it in items[:5]:
        print("  -", it["date"], it["title"][:50])

if __name__ == "__main__":
    main()
