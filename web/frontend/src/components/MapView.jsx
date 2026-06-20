import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import L from 'leaflet'
import 'leaflet.markercluster'

function priceColor(price) {
  if (!price) return '#9ca3af'
  if (price <= 15000) return '#22c55e'
  if (price <= 30000) return '#84cc16'
  if (price <= 50000) return '#f59e0b'
  if (price <= 80000) return '#f97316'
  return '#ef4444'
}

function formatPrice(won) {
  if (!won) return '-'
  if (won >= 10000) return `${(won / 10000).toFixed(1)}억`
  return `${won.toLocaleString()}만`
}

const MapView = forwardRef(function MapView({ apartments }, ref) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const clusterRef = useRef(null)
  const markersRef = useRef({}) // { 단지코드: circleMarker }

  // 외부에서 호출 가능한 메서드 노출
  useImperativeHandle(ref, () => ({
    flyTo(apt) {
      const lat = apt['위도']
      const lng = apt['경도']
      if (!lat || !lng || !mapRef.current) return

      const marker = markersRef.current[apt['단지코드']]
      if (marker && clusterRef.current) {
        // 클러스터에 묶여 있어도 펼쳐서 팝업 오픈
        clusterRef.current.zoomToShowLayer(marker, () => {
          setTimeout(() => marker.openPopup(), 100)
        })
      } else {
        mapRef.current.flyTo([lat, lng], 16, { duration: 0.8 })
      }
    },
  }))

  // 지도 초기화 (1회)
  useEffect(() => {
    if (mapRef.current) return

    mapRef.current = L.map(containerRef.current, { zoomControl: true }).setView(
      [35.871, 128.601],
      12
    )

    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      {
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OSM</a> © <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
      }
    ).addTo(mapRef.current)

    const legend = L.control({ position: 'bottomleft' })
    legend.onAdd = () => {
      const div = L.DomUtil.create('div', '')
      div.style.cssText =
        'background:#fff;padding:8px 12px;border-radius:8px;font-size:12px;box-shadow:0 1px 4px rgba(0,0,0,.2);line-height:1.8'
      div.innerHTML = [
        '<b>매매 최저가</b>',
        '<span style="color:#22c55e">●</span> ~1.5억',
        '<span style="color:#84cc16">●</span> ~3억',
        '<span style="color:#f59e0b">●</span> ~5억',
        '<span style="color:#f97316">●</span> ~8억',
        '<span style="color:#ef4444">●</span> 8억↑',
        '<span style="color:#9ca3af">●</span> 매물없음',
      ].join('<br>')
      return div
    }
    legend.addTo(mapRef.current)
  }, [])

  // 마커 갱신
  useEffect(() => {
    if (!mapRef.current) return

    if (clusterRef.current) {
      mapRef.current.removeLayer(clusterRef.current)
    }
    markersRef.current = {}

    const cluster = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 50,
      spiderfyOnMaxZoom: true,
    })

    apartments.forEach((apt) => {
      const lat = apt['위도']
      const lng = apt['경도']
      if (!lat || !lng) return

      const marker = L.circleMarker([lat, lng], {
        radius: 7,
        fillColor: priceColor(apt['매매_최저(만원)']),
        color: '#ffffff',
        weight: 1.5,
        opacity: 1,
        fillOpacity: 0.85,
      })

      const low = apt['매매_최저(만원)']
      const high = apt['매매_최고(만원)']
      const priceStr = low && high ? `${formatPrice(low)} ~ ${formatPrice(high)}` : '매물없음'

      marker.bindPopup(
        `<div style="min-width:200px;font-size:13px;line-height:1.7">
          <b style="font-size:14px">${apt['단지명'] || ''}</b><br>
          <span style="color:#6b7280">${apt['지역(구)'] || ''} ${apt['지역(동)'] || ''}</span><br>
          <hr style="margin:6px 0;border-color:#e5e7eb">
          🏗 ${apt['건축년월'] || '-'} &nbsp;·&nbsp; ${apt['총세대수'] || '-'}세대<br>
          💰 매매 ${priceStr}<br>
          📐 ${apt['전용평형(평)'] || '-'}평<br>
          ${apt['근처지하철'] ? `🚇 ${apt['근처지하철']} <span style="color:#6b7280">(도보 ${apt['지하철직선도보(분)']}분)</span><br>` : ''}
          ${apt['근처초등학교'] ? `🏫 ${apt['근처초등학교']} <span style="color:#6b7280">${apt['초등학교직선거리(m/분)'] || ''}</span>` : ''}
        </div>`,
        { maxWidth: 280 }
      )

      if (apt['단지코드']) {
        markersRef.current[apt['단지코드']] = marker
      }
      cluster.addLayer(marker)
    })

    clusterRef.current = cluster
    mapRef.current.addLayer(cluster)
  }, [apartments])

  return <div ref={containerRef} style={{ height: '100%', width: '100%' }} />
})

export default MapView
