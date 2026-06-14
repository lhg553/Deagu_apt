"""
MOLIT API 응답 태그명 확인용 스크립트
"""
import os
import requests
import xml.etree.ElementTree as ET
from pathlib import Path


def load_env():
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        return
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


load_env()
api_key = os.environ.get('MOLIT_API_KEY', '')
API_URL = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'

url = (f'{API_URL}?serviceKey={api_key}'
       f'&LAWD_CD=27260&DEAL_YMD=202504'
       f'&numOfRows=3&pageNo=1')

r = requests.get(url, timeout=20)
print(f'HTTP {r.status_code}')

root = ET.fromstring(r.content)

# 전체 구조 출력
items = root.findall('.//item')
print(f'항목 수: {len(items)}')

if items:
    print('\n=== 첫 번째 item 태그 목록 ===')
    for child in items[0]:
        print(f'  <{child.tag}>: "{child.text}"')

# API 사용량 확인
print('\n=== API 사용량 ===')
url_quota = (f'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
             f'?serviceKey={api_key}&LAWD_CD=27260&DEAL_YMD=202504&numOfRows=1&pageNo=1')
r2 = requests.get(url_quota, timeout=20)
# 응답 헤더에서 사용량 정보 확인
for h, v in r2.headers.items():
    if any(k in h.lower() for k in ('limit', 'remain', 'quota', 'rate', 'count')):
        print(f'  {h}: {v}')
print('  (사용량은 data.go.kr 마이페이지 → 개발계정에서 확인 가능)')
