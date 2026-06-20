export default function FilterBar({ districts, filters, onChange, total, search, onSearch }) {
  function set(key, value) {
    onChange({ ...filters, [key]: value })
  }

  return (
    <div className="filter-bar">
      <div className="filter-title">
        필터
        <span className="filter-count">{total.toLocaleString()}개 단지</span>
      </div>

      {/* 단지명 검색 */}
      <div className="filter-section">
        <label className="filter-label">단지명 검색</label>
        <input
          type="text"
          placeholder="단지명 입력..."
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="filter-input"
          style={{ width: '100%' }}
        />
        {search && (
          <button
            onClick={() => onSearch('')}
            style={{
              marginTop: 4,
              fontSize: 11,
              color: '#6b7280',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 0,
            }}
          >
            ✕ 검색 초기화
          </button>
        )}
      </div>

      {/* 구 선택 */}
      <div className="filter-section">
        <label className="filter-label">지역 (구)</label>
        <select
          value={filters.district}
          onChange={(e) => set('district', e.target.value)}
          className="filter-select"
        >
          {districts.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      {/* 매매가 범위 */}
      <div className="filter-section">
        <label className="filter-label">매매가 (만원)</label>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            type="number"
            placeholder="최소"
            value={filters.minPrice}
            onChange={(e) => set('minPrice', e.target.value)}
            className="filter-input"
            step={1000}
          />
          <span style={{ color: '#9ca3af', fontSize: 12 }}>~</span>
          <input
            type="number"
            placeholder="최대"
            value={filters.maxPrice}
            onChange={(e) => set('maxPrice', e.target.value)}
            className="filter-input"
            step={1000}
          />
        </div>
        <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
          {[
            { label: '5억↓', max: 50000 },
            { label: '3억↓', max: 30000 },
            { label: '2억↓', max: 20000 },
          ].map(({ label, max }) => (
            <button
              key={label}
              onClick={() => onChange({ ...filters, minPrice: '', maxPrice: max })}
              className="quick-btn"
              style={{
                background: filters.maxPrice === max ? '#3b82f6' : '#f3f4f6',
                color: filters.maxPrice === max ? '#fff' : '#374151',
              }}
            >
              {label}
            </button>
          ))}
          <button
            onClick={() => onChange({ ...filters, minPrice: '', maxPrice: '' })}
            className="quick-btn"
            style={{ background: '#f3f4f6', color: '#374151' }}
          >
            전체
          </button>
        </div>
      </div>

      {/* 평형 범위 */}
      <div className="filter-section">
        <label className="filter-label">전용평형 (평)</label>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            type="number"
            placeholder="최소"
            value={filters.minSize}
            onChange={(e) => set('minSize', e.target.value)}
            className="filter-input"
            step={5}
          />
          <span style={{ color: '#9ca3af', fontSize: 12 }}>~</span>
          <input
            type="number"
            placeholder="최대"
            value={filters.maxSize}
            onChange={(e) => set('maxSize', e.target.value)}
            className="filter-input"
            step={5}
          />
        </div>
        <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
          {[
            { label: '20평대', min: 20, max: 29 },
            { label: '30평대', min: 30, max: 39 },
            { label: '40평↑', min: 40, max: '' },
          ].map(({ label, min, max }) => (
            <button
              key={label}
              onClick={() => onChange({ ...filters, minSize: min, maxSize: max })}
              className="quick-btn"
              style={{ background: '#f3f4f6', color: '#374151' }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* 전체 초기화 */}
      <button
        onClick={() => {
          onChange({
            district: '전체',
            minPrice: '',
            maxPrice: '',
            minSize: '',
            maxSize: '',
          })
          onSearch('')
        }}
        style={{
          width: '100%',
          padding: '8px',
          marginTop: 8,
          border: '1px solid #e5e7eb',
          borderRadius: 8,
          background: '#fff',
          color: '#6b7280',
          fontSize: 13,
          cursor: 'pointer',
        }}
      >
        전체 초기화
      </button>
    </div>
  )
}
