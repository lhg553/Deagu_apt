# -*- coding: utf-8 -*-
"""
남구 cortarNo 방식 단지 목록 vs 기존 격자 방식(엑셀) 비교.
Phase 1+2만 실행 (Phase 3 매물상세 없음 → 빠름).
"""
import json, time, pandas as pd
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

OLD_XLS = '남구_부동산_20260612_112446.xlsx'


def collect_seen():
    """남구 cortarNo 3개 × 2거래유형 순회 → seen dict 반환."""
    with open('daegu_cortars.json', encoding='utf-8') as f:
        cortars_data = json.load(f)

    cortars = [(x['cortarNo'], x['centerLat'], x['centerLon'], x['name'])
               for x in cortars_data['남구']]

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
                elif mid:
                    for k, v in cx.items():
                        if k not in seen[mid] or not seen[mid][k]:
                            seen[mid][k] = v
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800})
        page = ctx.new_page()
        page.on('response', on_resp)

        for trade, label in [('A1', '매매'), ('B1', '전세')]:
            for cno, lat, lon, name in cortars:
                try:
                    page.goto(
                        f'https://new.land.naver.com/complexes?cortarNo={cno}&ms={lat},{lon},15'
                        f'&a=APT&b={trade}&e=RETAIL',
                        wait_until='networkidle', timeout=25000
                    )
                except Exception:
                    pass
                time.sleep(1.5)
            print(f'  {label}: {len(seen)}개 누적')

        browser.close()
    return seen


def main():
    import os
    from shapely.geometry import shape, Point
    with open('daegu_boundaries.json', encoding='utf-8') as f:
        polys = {k: shape(v) for k, v in json.load(f).items()}
    poly = polys.get('남구')

    print('[1] cortarNo 방식으로 남구 단지 수집...')
    t = time.time()
    seen = collect_seen()
    print(f'    수집: {len(seen)}개 (폴리곤 필터 전), {time.time()-t:.0f}초')

    # 폴리곤 필터
    _BUF = 0.0005
    filtered = {
        cid: cx for cid, cx in seen.items()
        if poly and poly.buffer(_BUF).contains(
            Point(float(cx.get('longitude', 0)), float(cx.get('latitude', 0)))
        )
    }
    new_names = {cx.get('complexName', '') for cx in filtered.values()}
    print(f'    폴리곤 필터 후: {len(filtered)}개\n')

    # 기존 엑셀 로드
    old_df = pd.read_excel(OLD_XLS, sheet_name='호가_단지요약')
    old_names = set(old_df['단지명'].unique())
    print(f'[2] 기존 격자방식 단지 수: {len(old_names)}개')
    print(f'    cortarNo 방식 단지 수: {len(new_names)}개\n')

    # 차이 분석
    only_old = sorted(old_names - new_names)
    only_new = sorted(new_names - old_names)

    # 폴리곤으로 걸러진 단지 목록
    seen_names = {cx.get('complexName', '') for cx in seen.values()}
    filtered_out = {cid: cx for cid, cx in seen.items()
                    if not (poly and poly.buffer(_BUF).contains(
                        Point(float(cx.get('longitude', 0)), float(cx.get('latitude', 0)))))}

    print(f'=== 폴리곤이 걸러낸 단지 ({len(filtered_out)}개) ===')
    for cx in sorted(filtered_out.values(), key=lambda x: x.get('complexName', '')):
        print(f'  {cx.get("complexName","")}  lat={cx.get("latitude")}, lon={cx.get("longitude")}')

    print(f'\n=== 기존에만 있는 단지 ({len(only_old)}개) — seen 여부 확인 ===')
    for n in only_old:
        row = old_df[old_df['단지명'] == n].iloc[0]
        in_seen = n in seen_names
        status = '★ seen에 있음 → 폴리곤이 걸러냄' if in_seen else '✗ seen에도 없음 → cortarNo 미수집'
        print(f'  {n}  (매매={row["매매_매물수"]}, 전세={row["전세_매물수"]})  [{status}]')
        if in_seen:
            cx = next(cx for cx in seen.values() if cx.get('complexName') == n)
            print(f'      → lat={cx.get("latitude")}, lon={cx.get("longitude")}')

    print(f'\n=== cortarNo 방식에만 있는 단지 ({len(only_new)}개) ===')
    for n in only_new:
        cx = next(cx for cx in filtered.values() if cx.get('complexName') == n)
        print(f'  {n}  (dealCount={cx.get("dealCount",0)}, leaseCount={cx.get("leaseCount",0)})')


if __name__ == '__main__':
    main()
