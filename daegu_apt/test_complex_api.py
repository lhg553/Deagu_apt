"""
COMPLEX_URL 응답 구조 확인용 테스트 스크립트.
Phase 1 지도 순회로 세션을 먼저 워밍업한 뒤 COMPLEX_URL 호출.
"""
import json
import time
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

MARKERS_URL = 'https://new.land.naver.com/api/complexes/single-markers/2.0'
COMPLEX_URL = 'https://new.land.naver.com/api/complexes/{}?sameAddressGroup=false'

# 수성구 중심점
CENTERS = [(35.858, 128.627), (35.851, 128.672)]
SAMPLE_SIZE = 3  # 작은/중간/큰 각 1개


def fetch_sample_complex_data():
    seen = {}

    def on_resp(resp):
        if 'single-markers' not in resp.url or resp.status != 200:
            return
        try:
            items = resp.json()
            if not isinstance(items, list):
                return
            for cx in items:
                mid = cx.get('markerId', '')
                if mid and mid not in seen:
                    seen[mid] = cx
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()
        page.on('response', on_resp)

        # Phase 1 방식 그대로: 지도 탐색으로 세션 워밍업 + 마커 수집
        print('세션 워밍업 중 (지도 순회)...')
        for lat, lon in CENTERS:
            try:
                page.goto(
                    f'https://new.land.naver.com/?ms={lat},{lon},15&a=APT&b=A1&e=RETAIL',
                    wait_until='networkidle', timeout=25000
                )
            except Exception:
                pass
            time.sleep(2.5)

        print(f'마커 수집: {len(seen)}개 단지')
        if not seen:
            print('[오류] 단지가 없습니다.')
            browser.close()
            return

        # dealCount 기준 작은/중간/큰 샘플
        sorted_cids = sorted(seen.keys(),
                             key=lambda c: seen[c].get('dealCount', 0) or 0)
        n = len(sorted_cids)
        if n >= 3:
            samples = [sorted_cids[0], sorted_cids[n // 2], sorted_cids[-1]]
        else:
            samples = sorted_cids[:SAMPLE_SIZE]

        print(f'\n샘플 단지:')
        for cid in samples:
            cx = seen[cid]
            print(f'  {cx.get("complexName", "?")} | dealCount={cx.get("dealCount", "?")} | cid={cid}')

        print('\n' + '=' * 60)
        print('COMPLEX_URL 응답 구조 확인')
        print('=' * 60)

        for cid in samples:
            cx = seen[cid]
            name = cx.get('complexName', cid)
            deal_count = cx.get('dealCount', '?')

            # 429 시 세션 리프레시 후 재시도 (무제한)
            retry = 0
            while True:
                r = page.request.get(
                    COMPLEX_URL.format(cid),
                    headers={
                        'Accept': 'application/json, text/plain, */*',
                        'Referer': f'https://new.land.naver.com/complexes/{cid}?a=APT&b=A1',
                    }
                )
                if r.status != 429:
                    break
                retry += 1
                wait = min(60 * retry, 120)
                print(f'\n[{name}] 429 → 지도 탐색 후 {wait}초 대기 (시도 {retry})...')
                try:
                    page.goto(
                        'https://new.land.naver.com/?ms=35.858,128.627,15&a=APT&b=A1&e=RETAIL',
                        wait_until='networkidle', timeout=25000
                    )
                    time.sleep(3)
                except Exception:
                    pass
                time.sleep(wait)

            print(f'\n[{name}] dealCount={deal_count} | HTTP {r.status}')

            if r.status == 200:
                data = r.json()
                print('-- 평형/가격 관련 키 탐색 --')
                _find_keys(data)
                print('-- raw JSON (앞 3000자) --')
                raw = json.dumps(data, ensure_ascii=False, indent=2)
                print(raw[:3000])
                if len(raw) > 3000:
                    print(f'... (총 {len(raw)}자 잘림)')
            else:
                print(f'  → 오류 {r.status}')

            time.sleep(0.5)

        browser.close()


def _find_keys(data, prefix='', depth=0):
    """평형/면적/가격 관련 키를 재귀 탐색."""
    if depth > 5:
        return
    keywords = ('pyoeng', 'area', 'price', 'deal', 'type', 'size',
                 'space', 'floor', 'count', 'list', 'detail')
    if isinstance(data, dict):
        for k, v in data.items():
            full_key = f'{prefix}.{k}' if prefix else str(k)
            if any(kw in str(k).lower() for kw in keywords):
                if isinstance(v, (dict, list)):
                    preview = f'[{type(v).__name__} len={len(v)}]'
                else:
                    preview = str(v)[:120]
                print(f'  {full_key}: {preview}')
            _find_keys(v, full_key, depth + 1)
    elif isinstance(data, list) and data:
        _find_keys(data[0], f'{prefix}[0]', depth + 1)


if __name__ == '__main__':
    fetch_sample_complex_data()
