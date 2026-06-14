import sys; sys.stdout.reconfigure(encoding='utf-8')
import requests

HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://new.land.naver.com/',
}

urls = [
    'https://new.land.naver.com/api/complexes?cortarNo=27110&realEstateType=APT',
    'https://new.land.naver.com/api/complexes/search?keyword=달성파크푸르지오힐스테이트',
    'https://new.land.naver.com/api/search?query=달성파크푸르지오힐스테이트&type=complexes',
    'https://new.land.naver.com/api/search/complexes?keyword=달성파크',
    'https://new.land.naver.com/api/complexes/regionList?cortarNo=27110&realEstateType=APT',
]

for url in urls:
    r = requests.get(url, headers=HDR, timeout=10)
    ct = r.headers.get('content-type', '')[:50]
    print(f'--- {url[:75]}')
    print(f'status={r.status_code}  ct={ct}')
    print(r.text[:300])
    print()
