# -*- coding: utf-8 -*-
"""
대구 각 구의 cortarNo 목록 탐색 + single-markers cortarNo 방식 동작 확인.
"""
import json
import time
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# 대구 구별 divisionNo
DAEGU_DIVISIONS = {
    '중구':   '2711000000',
    '동구':   '2714000000',
    '서구':   '2717000000',
    '남구':   '2720000000',
    '북구':   '2723000000',
    '수성구': '2726000000',
    '달서구': '2729000000',
    '달성군': '2771000000',
}

# 수성구 범어동 (테스트용)
TEST_CORTAR = '2726010100'
TEST_CENTER = (35.85554, 128.622025)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()

        # 1) 세션 워밍업
        print('[1] 세션 워밍업...')
        try:
            page.goto(
                'https://new.land.naver.com/?ms=35.858,128.627,15&a=APT&b=A1&e=RETAIL',
                wait_until='networkidle', timeout=30000
            )
        except Exception:
            pass
        time.sleep(2)

        # 2) 각 구의 동 목록 탐색
        print('\n[2] 구별 동 목록 (api/cortars) 탐색...')
        for gu, div_no in DAEGU_DIVISIONS.items():
            # 구 레벨 cortarNo
            try:
                r = page.request.get(
                    f'https://new.land.naver.com/api/cortars?cortarNo={div_no}',
                    headers={'Referer': 'https://new.land.naver.com/'},
                )
                if r.status == 200:
                    d = r.json()
                    print(f'  {gu} ({div_no}): {json.dumps(d, ensure_ascii=False)[:200]}')
                else:
                    print(f'  {gu}: HTTP {r.status}')
            except Exception as e:
                print(f'  {gu}: ERR {e}')
            time.sleep(0.3)

        # 3) 동 목록을 반환하는 엔드포인트 탐색
        print('\n[3] 수성구 하위 동 목록 API 탐색...')
        candidates = [
            f'https://new.land.naver.com/api/regions/list?cortarNo=2726000000',
            f'https://new.land.naver.com/api/cortars/list?cortarNo=2726000000',
            f'https://new.land.naver.com/api/regions?cortarNo=2726000000&cortarType=sec',
            f'https://new.land.naver.com/api/cortars?cortarNo=2726000000&cortarType=sec',
            f'https://new.land.naver.com/api/regions/sub?cortarNo=2726000000',
        ]
        for url in candidates:
            try:
                r = page.request.get(url, headers={'Referer': 'https://new.land.naver.com/'})
                try:
                    d = r.json()
                    preview = json.dumps(d, ensure_ascii=False)[:300]
                except Exception:
                    preview = r.text()[:200]
                print(f'  HTTP {r.status} | {url.split("?")[1][:60]}')
                print(f'    {preview[:200]}')
            except Exception as ex:
                print(f'  ERR | {str(ex)[:80]}')
            time.sleep(0.4)

        # 4) single-markers cortarNo 방식으로 단지 목록 수집 테스트
        print(f'\n[4] single-markers cortarNo={TEST_CORTAR} 직접 호출 테스트...')
        lat, lon = TEST_CENTER
        markers_url = (
            f'https://new.land.naver.com/api/complexes/single-markers/2.0'
            f'?cortarNo={TEST_CORTAR}'
            f'&zoom=15&priceType=RETAIL'
            f'&markerId=&markerType=&selectedComplexNo=&selectedComplexBuildingNo='
            f'&fakeComplexMarker=&realEstateType=APT'
            f'&tradeType=A1&tag=%3A%3A%3A%3A%3A%3A%3A%3A'
            f'&rentPriceMin=0&rentPriceMax=900000'
            f'&priceMin=0&priceMax=900000'
            f'&areaMin=0&areaMax=900'
            f'&oldBuildYear=&recentlyBuildYear=&minHouseHoldCount=&maxHouseHoldCount='
            f'&showArticle=false&sameAddressGroup=false&minMaintenanceCost=&maxMaintenanceCost='
            f'&directions='
        )
        for trade in ['A1', 'B1']:
            url = markers_url.replace('tradeType=A1', f'tradeType={trade}')
            try:
                r = page.request.get(url, headers={
                    'Accept': 'application/json, text/plain, */*',
                    'Referer': f'https://new.land.naver.com/complexes?cortarNo={TEST_CORTAR}&a=APT&b={trade}&e=RETAIL',
                })
                if r.status == 200:
                    items = r.json()
                    if isinstance(items, list):
                        names = [x.get('complexName','?') for x in items[:5]]
                        print(f'  tradeType={trade}: {len(items)}개 단지')
                        print(f'    샘플: {names}')
                    else:
                        print(f'  tradeType={trade}: HTTP {r.status} {str(items)[:200]}')
                else:
                    print(f'  tradeType={trade}: HTTP {r.status} {r.text()[:200]}')
            except Exception as ex:
                print(f'  tradeType={trade}: ERR {ex}')
            time.sleep(0.5)

        browser.close()

    print('\n완료.')


if __name__ == '__main__':
    main()
