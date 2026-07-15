# -*- coding: utf-8 -*-
"""우주항공청 사업공고 수집 스크립트 (GitHub Actions에서 자동 실행)"""
import json, re, sys
import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.kasa.go.kr/bbs/BBSMSTR_000000000018.do"
BASE = "https://www.kasa.go.kr"
MAX_ITEMS = 10
DATE_RE = re.compile(r"(\d{4})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})")

def norm_href(href: str) -> str:
    if not href or href == "#" or href.lower().startswith("javascript"):
        return LIST_URL
    if href.startswith("http"):
        return href
    return BASE + (href if href.startswith("/") else "/" + href)

def find_date(el) -> str:
    node = el
    for _ in range(4):  # 부모 방향으로 최대 4단계 탐색
        if node is None:
            break
        m = DATE_RE.search(node.get_text(" ", strip=True))
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        node = node.parent
    return ""

def main():
    res = requests.get(
        LIST_URL, timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (KASILog feed bot)"},
    )
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items, seen = [], set()

    # 1차: nttId 파라미터를 가진 게시글 링크
    for a in soup.select('a[href*="nttId"]'):
        title = re.sub(r"\s+", " ", a.get_text(strip=True))
        if len(title) < 4 or title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "date": find_date(a), "href": norm_href(a.get("href", ""))})
        if len(items) >= MAX_ITEMS:
            break

    # 2차: 날짜가 있는 표(tr) 행에서 추출
    if not items:
        for tr in soup.select("tr"):
            a = tr.find("a")
            if not a:
                continue
            m = DATE_RE.search(tr.get_text(" ", strip=True))
            if not m:
                continue
            title = re.sub(r"\s+", " ", a.get_text(strip=True))
            if len(title) < 4 or title in seen:
                continue
            seen.add(title)
            items.append({
                "title": title,
                "date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                "href": norm_href(a.get("href", "")),
            })
            if len(items) >= MAX_ITEMS:
                break

    if not items:
        print("공고를 찾지 못했습니다 — 게시판 구조가 바뀌었을 수 있습니다.", file=sys.stderr)
        sys.exit(1)

    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    out = {"updated": datetime.now(kst).strftime("%Y-%m-%d %H:%M"), "items": items}
    with open("kasa_feed.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"공고 {len(items)}건 저장 완료")

if __name__ == "__main__":
    main()
