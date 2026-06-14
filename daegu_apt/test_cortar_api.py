# -*- coding: utf-8 -*-
"""
네이버 부동산 cortarNo(법정동) 기반 단지 목록 API 탐색 스크립트.
수성구 범어1동(cortarNo=2726010100)을 방문하면서
어떤 API 콜이 발생하는지 캡처한다.
"""
import json
import time
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# 수성구 범어1동 cortarNo (법정동 10자리)
CORTAR_NO = '2726010100'

found = {}  # url → (status, data_preview)


def on_resp(resp):
    url = resp.url
    if 'land.naver.com' not in url:
        return
    if resp.status != 200:
        return
    # complex / region 관련 API만 캡처
    if not any(k in url for k in ('complex', 'region', 'cortar', 'article')):
        return
    try:
        ct = resp.headers.get('content-type', '')
        if 'json' not in ct:
            return
        data = resp.json()
        if isinstance(data, list):
            length = len(data)
            preview = json.dumps(data[0], ensure_ascii=False)[:300] if data else '[]'
        elif isinstance(data, dict):
            length = len(data)
            preview = json.dumps(data, ensure_ascii=False)[:300]
        else:
            return
        short_url = url[:200]
        found[short_url] = (resp.status, length, preview)
    except Exception:
        pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()
        page.on('response', on_resp)

        # 1) 메인 지도 먼저 방문해서 쿠키/세션 세팅
        print('[1] 메인 페이지 방문...')
        try:
            page.goto(
                'https://new.land.naver.com/?ms=35.858,128.627,15&a=APT&b=A1&e=RETAIL',
                wait_until='networkidle', timeout=30000
            )
        except Exception as e:
            print(f'    (timeout 무시) {e}')
        time.sleep(2)

        # 2) cortarNo 기반 URL로 이동
        print(f'[2] cortarNo={CORTAR_NO} (범어1동) 방문...')
        try:
            page.goto(
                f'https://new.land.naver.com/complexes?cortarNo={CORTAR_NO}'
                f'&ms=35.858,128.659,15&a=APT&b=A1&e=RETAIL',
                wait_until='networkidle', timeout=30000
            )
        except Exception as e:
            print(f'    (timeout 무시) {e}')
        time.sleep(3)

        # 3) 직접 API 호출 시도 (알려진 패턴들)
        print('[3] 직접 API 호출 탐색...')
        candidates = [
            f'https://new.land.naver.com/api/regions/complexes?cortarNo={CORTAR_NO}&realEstateType=APT&tradeType=A1',
            f'https://new.land.naver.com/api/regions/complexes?cortarNo={CORTAR_NO}&realEstateType=APT',
            f'https://new.land.naver.com/api/complexes?cortarNo={CORTAR_NO}&realEstateType=APT&tradeType=A1',
            f'https://new.land.naver.com/api/complexes/list?cortarNo={CORTAR_NO}',
            f'https://new.land.naver.com/api/regions/{CORTAR_NO}/complexes?realEstateType=APT',
        ]
        for url in candidates:
            try:
                r = page.request.get(url, headers={
                    'Accept': 'application/json, text/plain, */*',
                    'Referer': f'https://new.land.naver.com/complexes?cortarNo={CORTAR_NO}&a=APT&b=A1',
                })
                try:
                    data = r.json()
                    if isinstance(data, list):
                        length = len(data)
                        preview = json.dumps(data[0], ensure_ascii=False)[:300] if data else '[]'
                    else:
                        length = len(data) if isinstance(data, dict) else '?'
                        preview = json.dumps(data, ensure_ascii=False)[:300]
                    found[url[:200]] = (r.status, length, preview)
                except Exception:
                    found[url[:200]] = (r.status, '?', r.text()[:200])
            except Exception as ex:
                found[url[:200]] = ('ERR', 0, str(ex)[:100])
            time.sleep(0.5)

        browser.close()

    print('\n' + '=' * 80)
    print('캡처된 API 콜:')
    print('=' * 80)
    for url, (status, length, preview) in sorted(found.items()):
        print(f'\n[HTTP {status}] items={length}')
        print(f'  URL: {url}')
        print(f'  PREVIEW: {preview[:300]}')


if __name__ == '__main__':
    main()
