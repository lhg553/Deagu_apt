"""
미매칭 단지의 Naver 실거래 vs MOLIT 동일 동 데이터 비교
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import os, time, json, requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
API_KEY = os.getenv('MOLIT_API_KEY', '')
API_URL = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
DAEGU_LAWD = {'중구':'27110','동구':'27140','서구':'27170','남구':'27200',
              '북구':'27230','수성구':'27260','달서구':'27290','달성군':'27710'}

# 샘플: 미매칭 단지 중 첫 5개
df_un = pd.read_excel(os.path.join(BASE, 'complex_molit_map_review.xlsx'), sheet_name='미매칭')
targets = df_un[['단지코드','Naver단지명','구','동']].head(5).to_dict('records')

# ── Naver 실거래가 수집 (overview realPrice + 실거래 탭) ──────────────
naver_tx = {}

def on_resp(resp):
    for t in targets:
        cid = str(t['단지코드'])
        if f'complexes/overview/{cid}' in resp.url and resp.status == 200:
            try:
                d = resp.json()
                rp = d.get('realPrice') or {}
                if rp:
                    naver_tx[cid] = rp
            except: pass

print('Naver 실거래 조회 중...')
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent='Mozilla/5.0', locale='ko-KR', viewport={'width':1280,'height':800})
    page = ctx.new_page()
    page.on('response', on_resp)
    for t in targets:
        cid = str(t['단지코드'])
        try:
            page.goto(f'https://new.land.naver.com/complexes/{cid}', wait_until='networkidle', timeout=20000)
        except: pass
        time.sleep(0.5)
    browser.close()

# ── MOLIT 동일 구+동 데이터 수집 (최근 24개월) ──────────────────────
def prev_months(n):
    d = datetime.today().replace(day=1)
    r = []
    for _ in range(n):
        r.append(d.strftime('%Y%m'))
        d -= timedelta(days=1)
        d = d.replace(day=1)
    return r

def fetch_molit(lawd, ymd):
    url = f'{API_URL}?serviceKey={API_KEY}&LAWD_CD={lawd}&DEAL_YMD={ymd}&numOfRows=1000&pageNo=1'
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200: return []
        root = ET.fromstring(r.content)
        rows = []
        for item in root.findall('.//item'):
            def g(tag, _i=item):
                el = _i.find(tag)
                return el.text.strip() if el is not None and el.text else ''
            rows.append({'아파트명': g('aptNm'), '법정동': g('umdNm'),
                         '년': g('dealYear'), '월': g('dealMonth'), '일': g('dealDay'),
                         '금액': g('dealAmount').replace(',',''), '면적': g('excluUseAr'), '층': g('floor')})
        return rows
    except: return []

ymds = prev_months(24)

print('\n' + '='*70)
for t in targets:
    cid   = str(t['단지코드'])
    name  = t['Naver단지명']
    gu    = t['구']
    dong  = t['동']
    lawd  = DAEGU_LAWD.get(gu, '')

    print(f'\n[{name}] 단지코드={cid} / {gu} {dong}')

    # Naver 최근 실거래
    rp = naver_tx.get(cid)
    if rp:
        print(f'  Naver 최근 실거래: {rp.get("tradeYear")}.{rp.get("tradeMonth"):02d}.{rp.get("tradeDate")} '
              f'/ {rp.get("formattedPrice")} / {rp.get("exclusiveArea")}㎡ {rp.get("floor")}층')
    else:
        print('  Naver 최근 실거래: 없음')
        continue

    # MOLIT 동일 구+동 데이터에서 날짜+금액+면적 매칭 시도
    tx_year  = str(rp.get('tradeYear', ''))
    tx_month = str(rp.get('tradeMonth', ''))
    tx_day   = str(rp.get('tradeDate', '')).lstrip('0')
    tx_price = str(rp.get('dealPrice', ''))
    tx_area  = str(rp.get('exclusiveArea', ''))

    target_ymd = f'{tx_year}{int(tx_month):02d}'
    molit_rows = fetch_molit(lawd, target_ymd)
    same_dong  = [r for r in molit_rows if r['법정동'] == dong]

    print(f'  MOLIT {target_ymd} {dong} 거래: {len(same_dong)}건')

    # 날짜+금액+면적으로 매칭 시도
    matched = [r for r in same_dong
               if r['년'] == tx_year and r['월'].lstrip('0') == tx_month.lstrip('0')
               and r['일'].lstrip('0') == tx_day.lstrip('0')
               and r['금액'] == tx_price]

    if matched:
        print(f'  MOLIT 매칭 성공! → 아파트명: "{matched[0]["아파트명"]}"')
        print(f'    (Naver 단지명 "{name}" vs MOLIT 아파트명 "{matched[0]["아파트명"]}")')
    else:
        print(f'  MOLIT 매칭 실패 (날짜+금액 기준)')
        # 같은 날 같은 동 거래 목록
        same_day = [r for r in same_dong
                    if r['년'] == tx_year and r['월'].lstrip('0') == tx_month.lstrip('0')
                    and r['일'].lstrip('0') == tx_day.lstrip('0')]
        if same_day:
            print(f'  같은 날 같은 동 거래: {[r["아파트명"]+"("+r["금액"]+")" for r in same_day]}')
        else:
            print(f'  같은 날 같은 동 거래 없음')
            # 그 달 같은 동 아파트명 목록
            names = list({r["아파트명"] for r in same_dong})
            print(f'  그 달 같은 동 MOLIT 단지들: {names[:10]}')
