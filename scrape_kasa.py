# -*- coding: utf-8 -*-
"""우주항공청 사업공고 수집 스크립트 v5 (GitHub Actions에서 자동 실행)
   - 사업·과제(R&D) 공고만 선별 (아래 키워드 목록으로 조정 가능)
   - 각 공고의 실제 상세 페이지 링크 추출
"""
import json, re, sys, time
import urllib.parse
import requests
from bs4 import BeautifulSoup

TARGET = "https://www.kasa.go.kr/bbs/BBSMSTR_000000000018.do"
VIEW_URL = "https://www.kasa.go.kr/bbs/BBSMSTR_000000000018/view.do?nttId="
BASE = "https://www.kasa.go.kr"
MAX_ITEMS = 10

# ★ 공고 선별 키워드 — 필요 시 이 목록만 수정하세요
INCLUDE_KW = ["사업", "과제", "R&D", "연구", "공모", "수요조사"]   # 하나라도 포함돼야 표시
EXCLUDE_KW = ["발주계획", "월력", "자동판매기", "관리위탁", "청사", "임대"]  # 하나라도 포함되면 제외

DATE_RE = re.compile(r"(\d{4})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})")
NTT_RE = re.compile(r"B\d{10,14}[A-Za-z][A-Za-z0-9]{2,10}")   # 게시글 ID (예: B000000003292Sg7fX7)
META_WORDS = ("작성자", "조회수", "첨부파일", "공지", "새글", "번호", "제목", "등록일")

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

def wanted(title: str) -> bool:
    if any(k in title for k in EXCLUDE_KW):
        return False
    return any(k in title for k in INCLUDE_KW)

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

def row_link(row) -> str:
    """행에서 게시글 ID를 찾아 실제 상세 페이지 주소를 만든다"""
    m = NTT_RE.search(str(row))
    if m:
        return VIEW_URL + m.group(0)
    for a in row.find_all("a"):
        href = a.get("href", "")
        if "nttId" in href and "FileDown" not in href:
            return href if href.startswith("http") else BASE + (href if href.startswith("/") else "/" + href)
    return TARGET

def parse(html: str):
    soup = BeautifulSoup(html, "html.parser")
    for sel in ("header", "footer", "nav", "script", "style"):
        for t in soup.find_all(sel):
            t.decompose()

    items, seen, skipped = [], [], []

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
        title = ""
        for s in row.stripped_strings:
            s = re.sub(r"\s+", " ", s).strip()
            if len(s) <= len(title): continue
            if s in META_WORDS: continue
            if DATE_RE.search(s) and len(s) <= 14: continue
            if re.fullmatch(r"[\d,]+", s): continue
            if "다운로드" in s or s.lower().endswith((".hwp", ".hwpx", ".pdf", ".xlsx", ".zip", ".docx")): continue
            title = s
        if len(title) < 8 or title in seen:
            continue
        seen.append(title)
        if not wanted(title):
            skipped.append(title)
            continue
        items.append({
            "title": title,
            "date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
            "href": row_link(row),
        })

    if skipped:
        print(f"[진단] 키워드 필터로 제외된 공고 {len(skipped)}건:")
        for s in skipped[:6]:
            print("    ×", s[:45])
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
        print("  -", it["date"], it["title"][:45], "→", it["href"][:70])

if __name__ == "__main__":
    main()
