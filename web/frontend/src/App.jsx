import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ChatPanel from './components/ChatPanel'
import FilterBar from './components/FilterBar'
import MapView from './components/MapView'

const DEFAULT_FILTERS = {
  district: '전체',
  minPrice: '',
  maxPrice: '',
  minSize: '',
  maxSize: '',
}

export default function App() {
  const [districts, setDistricts] = useState(['전체'])
  const [models, setModels] = useState([])
  const [apartments, setApartments] = useState([])   // 필터 적용된 목록
  const [allApartments, setAllApartments] = useState([]) // 전체 목록 (AI 이름 조회용)
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef(null)
  const mapRef = useRef(null)

  // 초기 로드
  useEffect(() => {
    fetch('/api/districts').then((r) => r.json()).then(setDistricts)
    fetch('/api/models').then((r) => r.json()).then(setModels)
    // 전체 목록은 필터 없이 1회만 로드 (AI 단지명 클릭용)
    fetch('/api/apartments').then((r) => r.json()).then(setAllApartments)
  }, [])

  // 필터 변경 시 아파트 재로드 (debounce)
  const fetchApartments = useCallback((f) => {
    const params = new URLSearchParams()
    if (f.district && f.district !== '전체') params.set('district', f.district)
    if (f.minPrice) params.set('min_price', f.minPrice)
    if (f.maxPrice) params.set('max_price', f.maxPrice)
    if (f.minSize) params.set('min_size', f.minSize)
    if (f.maxSize) params.set('max_size', f.maxSize)

    setLoading(true)
    fetch(`/api/apartments?${params}`)
      .then((r) => r.json())
      .then((data) => { setApartments(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchApartments(filters), 300)
  }, [filters, fetchApartments])

  // 검색어로 지도 마커 추가 필터링 (클라이언트 사이드)
  const displayedApartments = useMemo(() => {
    if (!search.trim()) return apartments
    const q = search.trim()
    return apartments.filter((a) =>
      (a['단지명'] || '').includes(q)
    )
  }, [apartments, search])

  // AI가 언급한 단지명 클릭 → 지도 이동
  function handleApartmentSelect(apt) {
    // allApartments 기준으로 좌표를 찾아야 필터 밖 단지도 이동 가능
    const target = allApartments.find((a) => a['단지코드'] === apt['단지코드']) || apt
    mapRef.current?.flyTo(target)
  }

  const displayCount = displayedApartments.length

  return (
    <div className="layout">
      <header className="header">
        <span className="header-title">🏢 대구 아파트 분석</span>
        <span className="header-sub">
          {loading
            ? '로딩 중...'
            : search
            ? `검색 결과 ${displayCount.toLocaleString()}개`
            : `${displayCount.toLocaleString()}개 단지`}
        </span>
      </header>

      <div className="body">
        <FilterBar
          districts={districts}
          filters={filters}
          onChange={setFilters}
          total={displayCount}
          search={search}
          onSearch={setSearch}
        />

        <main className="map-area">
          <MapView ref={mapRef} apartments={displayedApartments} />
        </main>

        <ChatPanel
          district={filters.district}
          models={models}
          allApartments={allApartments}
          onApartmentSelect={handleApartmentSelect}
        />
      </div>
    </div>
  )
}
