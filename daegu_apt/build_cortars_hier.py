# -*- coding: utf-8 -*-
"""Naver 지역 계층 API로 대구 전체 구·군 → 법정동 cortarNo를 권위있게 수집.
뷰포트 샘플링이 아니라 공식 행정 계층이라 누락이 없다.
결과: daegu_cortars.json  {구명: [{cortarNo,name,centerLat,centerLon}, ...]}
"""
import json
import time
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

DAEGU_CNO = '2700000000'  # 대구광역시
TARGET_GU = {'중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군'}

JS = """async ([cno, headers]) => {
  const url = `https://new.land.naver.com/api/regions/list?cortarNo=${cno}`;
  try {
    const r = await fetch(url, {headers, credentials:'include'});
    if(!r.ok) return {status:r.status};
    const j = await r.json();
    return {status:200, list: j.regionList || j.list || []};
  } catch(e){ return {status:-1, error:String(e)}; }
}"""


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, locale='ko-KR',
                            viewport={'width': 1280, 'height': 800})
        ctx.route('**/*', lambda r: r.abort()
                  if r.request.resource_type in ('image', 'media', 'font')
                  else r.continue_())
        page = ctx.new_page()
        auth = {}

        def on_req(rq):
            if 'new.land.naver.com/api/' in rq.url and 'authorization' not in auth:
                h = rq.headers
                if h.get('authorization'):
                    for k in ('authorization', 'accept', 'accept-language'):
                        if h.get(k):
                            auth[k] = h[k]
        page.on('request', on_req)
        page.goto('https://new.land.naver.com/complexes?ms=35.86,128.6,12&a=APT&b=A1&e=RETAIL',
                  wait_until='networkidle', timeout=25000)
        time.sleep(1.0)
        if not auth:
            print('[오류] auth 헤더 미확보'); b.close(); return

        def fetch(cno):
            for _ in range(3):
                res = page.evaluate(JS, [cno, auth])
                if res.get('status') == 429:
                    time.sleep(30); continue
                return res.get('list', []) if res.get('status') == 200 else []
            return []

        result = {}
        gus = fetch(DAEGU_CNO)
        print(f'대구 하위 구·군 {len(gus)}개')
        for gu in gus:
            name = gu.get('cortarName', '')
            if name not in TARGET_GU:
                continue
            dongs = fetch(gu['cortarNo'])
            entries = []
            for d in dongs:
                # 법정동에 하위(리)가 있으면 그 하위까지, 없으면 자신
                children = fetch(d['cortarNo'])
                leaves = children if children else [d]
                for lf in leaves:
                    entries.append({
                        'cortarNo':  lf['cortarNo'],
                        'name':      lf.get('cortarName', ''),
                        'centerLat': lf.get('centerLat'),
                        'centerLon': lf.get('centerLon'),
                    })
                time.sleep(0.1)
            result[name] = entries
            print(f'  {name}: 법정동 {len(entries)}개')
        b.close()

    with open('daegu_cortars.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    total = sum(len(v) for v in result.values())
    print(f'\n저장 완료 → daegu_cortars.json (총 {total}개 법정동)')


if __name__ == '__main__':
    main()
