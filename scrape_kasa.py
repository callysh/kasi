# -*- coding: utf-8 -*-
"""우주항공청 사업공고 수집 스크립트 v7.1 (GitHub Actions에서 자동 실행)
   - 사업·과제(R&D) 공고만 선별 (아래 키워드 목록으로 조정 가능)
   - 각 공고의 실제 상세 페이지 링크 추출 + 링크 보강ㆍ이전 링크 보존
   - 중계 경로 5종 × 3회 반복 재시도 (일시적 중계 장애 대응)
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
# kind: html(원본 HTML) / aojson(allorigins JSON 포장) / text(jina 텍스트 변환)
ROUTES = [
    ("직접 접속",            TARGET,                                              12, "html"),
    ("중계: allorigins raw", f"https://api.allorigins.win/raw?url={q}",           40, "html"),
    ("중계: allorigins get", f"https://api.allorigins.win/get?url={q}",           40, "aojson"),
    ("중계: codetabs",       f"https://api.codetabs.com/v1/proxy?quest={q}",      40, "html"),
    ("중계: corsproxy",      f"https://corsproxy.io/?url={q}",                    40, "html"),
    ("중계: jina reader",    f"https://r.jina.ai/{TARGET}",                       50, "text"),
]
RETRY_PASSES = 3        # 전체 경로를 몇 바퀴 재시도할지
RETRY_WAIT = 25         # 바퀴 사이 대기(초)

def wanted(title: str) -> bool:
    if any(k in title for k in EXCLUDE_KW):
        return False
    return any(k in title for k in INCLUDE_KW)

def get_page():
    for attempt in range(1, RETRY_PASSES + 1):
        for name, url, tmo, kind in ROUTES:
            try:
                res = requests.get(url, headers=HEADERS, timeout=tmo)
                body = res.text
                if kind == "aojson" and res.status_code == 200:
                    try:
                        body = res.json().get("contents") or ""
                    except Exception:
                        body = ""
                ok = res.status_code == 200 and len(body) > 3000
                print(f"[진단] {attempt}차 {name} → 상태 {res.status_code}, 본문 {len(body):,}자 "
                      f"{'✓ 사용' if ok else '✗ 건너뜀'}")
                if ok:
                    return body, ("text" if kind == "text" else "html")
            except Exception as e:
                print(f"[진단] {attempt}차 {name} 실패: {type(e).__name__}")
            time.sleep(1)
        if attempt < RETRY_PASSES:
            print(f"[진단] 전 경로 실패 — {RETRY_WAIT}초 후 {attempt + 1}차 재시도")
            time.sleep(RETRY_WAIT)
    print("[오류] 모든 경로 접속 실패 (총 %d바퀴)" % RETRY_PASSES, file=sys.stderr)
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

def parse_text(text: str):
    """jina 등 텍스트 변환 결과 파서"""
    items, seen = [], set()
    # 1) 마크다운 링크에 nttId가 있으면 가장 정확
    for m in re.finditer(r"\[([^\]]{8,120})\]\((https?://[^\)]*nttId[^\)]*)\)", text):
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        if title in seen or not wanted(title):
            continue
        # 링크 주변 200자에서 날짜 탐색
        around = text[max(0, m.start() - 100): m.end() + 200]
        dm = DATE_RE.search(around)
        date = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""
        seen.add(title)
        items.append({"title": title, "date": date, "href": m.group(2)})
    if items:
        items.sort(key=lambda x: x["date"], reverse=True)
        return items[:MAX_ITEMS]
    # 2) 날짜 줄에서 출발해 인접한 긴 줄을 제목으로
    lines = [re.sub(r"[\*#|`\[\]]", " ", ln).strip() for ln in text.splitlines()]
    for i, ln in enumerate(lines):
        m = DATE_RE.search(ln)
        if not m or len(ln) > 40:
            continue
        title = ""
        for back in range(1, 6):
            if i - back < 0:
                break
            cand = re.sub(r"\s+", " ", lines[i - back]).strip()
            if len(cand) < 10 or any(w in cand for w in META_WORDS):
                continue
            if DATE_RE.search(cand) or re.fullmatch(r"[\d,\s]+", cand):
                continue
            if len(cand) > len(title):
                title = cand
        if len(title) < 8 or title in seen or not wanted(title):
            continue
        seen.add(title)
        items.append({
            "title": title,
            "date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
            "href": TARGET,
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:MAX_ITEMS]

def merge_previous_links(items):
    """이전 kasa_feed.json에서 확보했던 상세 링크(nttId)를 제목 기준으로 보존"""
    try:
        with open("kasa_feed.json", encoding="utf-8") as f:
            prev = json.load(f)
        prev_map = {p.get("title"): p.get("href") for p in prev.get("items", [])
                    if "nttId" in str(p.get("href", ""))}
        kept = 0
        for it in items:
            if "nttId" not in it["href"] and it["title"] in prev_map:
                it["href"] = prev_map[it["title"]]
                kept += 1
        if kept:
            print(f"[진단] 이전 데이터에서 상세 링크 {kept}건 보존")
    except Exception:
        pass
    return items

def enrich_links(items):
    """상세 링크가 없는 공고가 있으면 HTML 경로로 재시도해 링크만 보강 (3바퀴)"""
    if all("nttId" in it["href"] for it in items):
        return items
    print("[진단] 상세 링크 누락 → HTML 경로로 링크 보강 시도")
    for attempt in range(1, RETRY_PASSES + 1):
        for name, url, tmo, kind in ROUTES:
            if kind == "text":
                continue
            try:
                res = requests.get(url, headers=HEADERS, timeout=tmo)
                body = res.text
                if kind == "aojson" and res.status_code == 200:
                    try:
                        body = res.json().get("contents") or ""
                    except Exception:
                        body = ""
                ok = res.status_code == 200 and len(body) > 3000
                print(f"[진단] 보강 {attempt}차 {name} → 상태 {res.status_code}, 본문 {len(body):,}자 "
                      f"{'✓' if ok else '✗'}")
                if not ok:
                    continue
                link_map = {p["title"]: p["href"] for p in parse(body) if "nttId" in p["href"]}
                hit = 0
                for it in items:
                    if "nttId" not in it["href"] and it["title"] in link_map:
                        it["href"] = link_map[it["title"]]
                        hit += 1
                if hit:
                    print(f"[진단] 링크 보강 성공: {hit}건 ({name})")
                    return items
            except Exception as e:
                print(f"[진단] 보강 {attempt}차 {name} 실패: {type(e).__name__}")
            time.sleep(1)
        if attempt < RETRY_PASSES:
            print(f"[진단] 보강 실패 — {RETRY_WAIT}초 후 재시도")
            time.sleep(RETRY_WAIT)
    print("[진단] 링크 보강 실패 — 목록 주소 유지 (다음 자동 실행에서 재시도)")
    return items

def main():
    html, kind = get_page()
    items = parse_text(html) if kind == "text" else parse(html)
    items = merge_previous_links(items)
    items = enrich_links(items)
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
