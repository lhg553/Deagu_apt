import { useCallback, useEffect, useRef, useState } from 'react'
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
  const [apartments, setApartments] = useState([])
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef(null)

  // 구 목록 + 모델 목록 초기 로드
  useEffect(() => {
    fetch('/api/districts').then((r) => r.json()).then(setDistricts)
    fetch('/api/models').then((r) => r.json()).then(setModels)
  }, [])

  // 필터 변경 시 아파트 데이터 재로드 (debounce 300ms)
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
      .then((data) => {
        setApartments(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchApartments(filters), 300)
  }, [filters, fetchApartments])

  function handleFilterChange(newFilters) {
    setFilters(newFilters)
  }

  return (
    <div className="layout">
      {/* 헤더 */}
      <header className="header">
        <span className="header-title">🏢 대구 아파트 분석</span>
        <span className="header-sub">
          {loading ? '로딩 중...' : `${apartments.length.toLocaleString()}개 단지`}
        </span>
      </header>

      {/* 본문 3컬럼 */}
      <div className="body">
        {/* 왼쪽: 필터 */}
        <FilterBar
          districts={districts}
          filters={filters}
          onChange={handleFilterChange}
          total={apartments.length}
        />

        {/* 가운데: 지도 */}
        <main className="map-area">
          <MapView apartments={apartments} />
        </main>

        {/* 오른쪽: 채팅 */}
        <ChatPanel district={filters.district} models={models} />
      </div>
    </div>
  )
}
