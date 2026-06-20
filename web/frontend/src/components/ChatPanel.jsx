import { useEffect, useRef, useState } from 'react'

function Message({ role, content }) {
  const isUser = role === 'user'
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 12,
      }}
    >
      <div
        style={{
          maxWidth: '85%',
          padding: '10px 14px',
          borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
          background: isUser ? '#3b82f6' : '#f3f4f6',
          color: isUser ? '#fff' : '#111827',
          fontSize: 13,
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {content}
      </div>
    </div>
  )
}

export default function ChatPanel({ district, models }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        '안녕하세요! 대구 아파트 데이터를 기반으로 질문에 답변드립니다.\n예) "수성구 5억 이하 단지 알려줘", "지하철 가까운 달서구 아파트는?"',
    },
  ])
  const [input, setInput] = useState('')
  const [model, setModel] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => {
    if (models.length && !model) setModel(models[0])
  }, [models])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const text = input.trim()
    if (!text || loading) return

    const history = messages
      .filter((m) => m.role !== 'assistant' || messages.indexOf(m) > 0)
      .map(({ role, content }) => ({ role, content }))

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)

    // 스트리밍 응답 자리 확보
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

    try {
      const controller = new AbortController()
      abortRef.current = controller

      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          model: model || 'qwen2.5:14b',
          district: district || null,
          history,
        }),
        signal: controller.signal,
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const data = JSON.parse(line.slice(6))
            if (data.error) {
              setMessages((prev) => {
                const copy = [...prev]
                copy[copy.length - 1] = {
                  role: 'assistant',
                  content: `오류: ${data.error}`,
                }
                return copy
              })
            } else if (data.content) {
              setMessages((prev) => {
                const copy = [...prev]
                copy[copy.length - 1] = {
                  ...copy[copy.length - 1],
                  content: copy[copy.length - 1].content + data.content,
                }
                return copy
              })
            }
          } catch {
            // JSON 파싱 오류 무시
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        setMessages((prev) => {
          const copy = [...prev]
          copy[copy.length - 1] = {
            role: 'assistant',
            content: 'Ollama 연결에 실패했습니다. 서버가 실행 중인지 확인하세요.',
          }
          return copy
        })
      }
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }

  function stop() {
    abortRef.current?.abort()
    setLoading(false)
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="chat-panel">
      {/* 모델 선택 */}
      <div className="chat-header">
        <span style={{ fontWeight: 600, fontSize: 14 }}>AI 분석</span>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          style={{
            fontSize: 12,
            border: '1px solid #d1d5db',
            borderRadius: 6,
            padding: '3px 6px',
            background: '#fff',
          }}
        >
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
          {!models.length && <option value="qwen2.5:14b">qwen2.5:14b</option>}
        </select>
      </div>

      {/* 메시지 목록 */}
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <Message key={i} role={msg.role} content={msg.content} />
        ))}
        {loading && (
          <div style={{ color: '#9ca3af', fontSize: 12, marginLeft: 4 }}>
            ●●● 생성 중...
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 입력창 */}
      <div className="chat-input-row">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={`질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)${district && district !== '전체' ? `\n현재 필터: ${district}` : ''}`}
          rows={2}
          disabled={loading}
          style={{
            flex: 1,
            resize: 'none',
            border: '1px solid #d1d5db',
            borderRadius: 10,
            padding: '8px 12px',
            fontSize: 13,
            fontFamily: 'inherit',
            outline: 'none',
          }}
        />
        <button
          onClick={loading ? stop : send}
          style={{
            padding: '0 16px',
            borderRadius: 10,
            border: 'none',
            background: loading ? '#ef4444' : '#3b82f6',
            color: '#fff',
            fontWeight: 600,
            fontSize: 13,
            cursor: 'pointer',
            alignSelf: 'stretch',
          }}
        >
          {loading ? '중지' : '전송'}
        </button>
      </div>
    </div>
  )
}
