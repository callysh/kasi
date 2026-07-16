# -*- coding: utf-8 -*-
"""우주항공청 사업공고 수집 스크립트 v4 (GitHub Actions에서 자동 실행)
   - 직접 접속 차단 시 중계 서비스 경유
   - 태그 구조와 무관한 '행 단위' 파서 (날짜 + 작성자 표식으로 행을 찾고 제목 추출)
"""
import json, re, sys, time
import urllib.parse
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

q = urllib.parse.quote(TARGET, safe="")
ROUTES = [
    ("직접 접속", TARGET, 12),
    ("중계: allorigins", f"https://api.allorigins.win/raw?url={q}", 40),
    ("중계: codetabs",   f"https://api.codetabs.com/v1/proxy?quest={q}", 40),
    ("중계: corsproxy",  f"https://corsproxy.io/?url={q}", 40),
]

META_WORDS = ("작성자", "조회수", "첨부파일", "공지", "새글", "번호", "제목", "등록일")

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
            print(f"[진단] {name} 실패: {type(e).__name__}")
        time.sleep(1)
    print("[오류] 모든 경로 접속 실패", file=sys.stderr)
    sys.exit(1)

def pick_link(container):
    """행 안에서 상세보기로 보이는 링크를 찾되, 확실치 않으면 목록 주소 사용"""
    for a in container.find_all("a"):
        href = a.get("href", "")
        if not href or href == "#" or href.lower().startswith("javascript"):
            continue
        if "FileDown" in href or "Download" in href:   # 첨부파일 링크 제외
            continue
        if "nttId" in href or "view" in href.lower():
            if href.startswith("http"):
                return href
            return BASE + (href if href.startswith("/") else "/" + href)
    return TARGET

def parse(html: str):
    soup = BeautifulSoup(html, "html.parser")
    # 헤더/푸터/내비 제거 (본문만 남기기)
    for sel in ("header", "footer", "nav", "script", "style"):
        for t in soup.find_all(sel):
            t.decompose()

    items, seen = [], []

    # 1차: nttId 링크 방식 (있으면 가장 정확)
    for a in soup.select('a[href*="nttId"]'):
        title = re.sub(r"\s+", " ", a.get_text(strip=True))
        if len(title) < 8 or title in seen:
            continue
        node = a
        date = ""
        for _ in range(4):
            if node is None: break
            m = DATE_RE.search(node.get_text(" ", strip=True))
            if m:
                date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                break
            node = node.parent
        seen.append(title)
        href = a.get("href", "")
        href = href if href.startswith("http") else BASE + (href if href.startswith("/") else "/" + href)
        items.append({"title": title, "date": date, "href": href})

    # 2차: 행 단위 파서 — 날짜 문자열에서 출발해 '작성자/조회' 표식이 있는
    #       가장 가까운 조상(=게시글 한 행)을 찾고, 그 안의 가장 긴 텍스트를 제목으로
    if not items:
        print("[진단] nttId 링크 없음 → 행 단위 파서 사용")
        for el in soup.find_all(string=DATE_RE):
            m = DATE_RE.search(str(el))
            if not m:
                continue
            node = el.parent
            row = None
            for _ in range(7):
                if node is None:
                    break
                t = node.get_text(" ", strip=True)
                if ("작성자" in t or "조회" in t) and len(t) > 25:
                    row = node
                    break
                node = node.parent
            if row is None:
                continue
            # 제목 후보: 행 안에서 가장 긴 텍스트 (메타 정보·파일명·숫자 제외)
            title = ""
            for s in row.stripped_strings:
                s = re.sub(r"\s+", " ", s).strip()
                if len(s) <= len(title):
                    continue
                if s in META_WORDS:
                    continue
                if DATE_RE.search(s) and len(s) <= 14:
                    continue
                if re.fullmatch(r"[\d,]+", s):
                    continue
                low = s.lower()
                if "다운로드" in s or low.endswith((".hwp", ".hwpx", ".pdf", ".xlsx", ".zip", ".docx")):
                    continue
                title = s
            if len(title) < 8 or title in seen:
                continue
            seen.append(title)
            items.append({
                "title": title,
                "date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                "href": pick_link(row),
            })

    # 최신순 정렬 후 상위 N건
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:MAX_ITEMS]

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
