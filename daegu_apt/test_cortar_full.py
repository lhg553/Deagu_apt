# -*- coding: utf-8 -*-
"""
api/cortars 전체 응답 구조 확인 + 수성구 전체 동 cortarNo 수집 테스트.
rate limit 회피 위해 세션 후 딜레이 길게.
"""
import json
import time
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# 수성구 대표 격자 포인트 (현재 코드의 0.015°×0.018° 스텝)
# 범어동 중심부터 시작
SUSEONG_CENTERS = [
    (35.800, 128.590), (35.800, 128.608), (35.800, 128.626),
    (35.815, 128.590), (35.815, 128.608), (35.815, 128.626),
    (35.830, 128.590), (35.830, 128.608), (35.830, 128.626),
    (35.845, 128.600), (35.845, 128.618), (35.845, 128.636),
    (35.860, 128.600), (35.860, 128.618), (35.860, 128.636),
    (35.875, 128.610), (35.875, 128.628), (35.875, 128.646),
    # 시지 방향
    (35.800, 128.680), (35.800, 128.698), (35.800, 128.716),
    (35.815, 128.680), (35.815, 128.698), (35.815, 128.716),
]


def main():
    collected = {}  # cortarNo → cortarName

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()

        # 세션 워밍업 (페이지 방문)
        print('[1] 세션 워밍업...')
        try:
            page.goto(
                'https://new.land.naver.com/?ms=35.858,128.627,15&a=APT&b=A1&e=RETAIL',
                wait_until='networkidle', timeout=30000
            )
        except Exception:
            pass
        time.sleep(3)  # 충분히 대기

        # 2) api/cortars 전체 응답 확인 (1개만)
        print('\n[2] api/cortars 전체 응답 구조:')
        try:
            r = page.request.get(
                'https://new.land.naver.com/api/cortars?zoom=15&centerLat=35.858&centerLon=128.627',
                headers={'Referer': 'https://new.land.naver.com/'},
            )
            if r.status == 200:
                d = r.json()
                print(json.dumps(d, ensure_ascii=False, indent=2)[:2000])
            else:
                print(f'HTTP {r.status}: {r.text()[:300]}')
        except Exception as e:
            print(f'ERR: {e}')
        time.sleep(2)

        # 3) 구 레벨 cortarNo로 하위 동 목록 탐색
        print('\n[3] 수성구(2726000000) 하위 동 목록 탐색:')
        try:
            r = page.request.get(
                'https://new.land.naver.com/api/cortars?cortarNo=2726000000',
                headers={'Referer': 'https://new.land.naver.com/'},
            )
            print(f'  HTTP {r.status}: {r.text()[:500]}')
        except Exception as e:
            print(f'  ERR: {e}')
        time.sleep(2)

        # 4) 수성구 격자 포인트들로 cortarNo 수집
        print('\n[4] 수성구 격자 → cortarNo 수집:')
        for lat, lon in SUSEONG_CENTERS:
            try:
                r = page.request.get(
                    f'https://new.land.naver.com/api/cortars?zoom=15&centerLat={lat}&centerLon={lon}',
                    headers={'Referer': 'https://new.land.naver.com/'},
                )
                if r.status == 200:
                    d = r.json()
                    # cortarNo 필드 탐색
                    cno = d.get('cortarNo') or d.get('sectorNo') or d.get('cortarNo')
                    cname = d.get('cortarName') or d.get('sectorName') or ''
                    if cno and cno not in collected:
                        collected[cno] = cname
                        print(f'  NEW: {cno} {cname}')
                elif r.status == 429:
                    print(f'  ({lat},{lon}): 429 rate limit - 5초 대기...')
                    time.sleep(5)
            except Exception as ex:
                print(f'  ({lat},{lon}): ERR {ex}')
            time.sleep(0.8)  # 요청 간 딜레이

        browser.close()

    print(f'\n수집된 cortarNo: {len(collected)}개')
    for cno, cname in sorted(collected.items()):
        print(f'  {cno}: {cname}')


if __name__ == '__main__':
    main()
