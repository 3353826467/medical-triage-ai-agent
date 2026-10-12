const BASE = import.meta.env.VITE_API_BASE || '/api/v1'

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const err = await resp.json()
      detail = err.detail || detail
    } catch {
      /* 忽略解析失败 */
    }
    throw new Error(detail)
  }
  return resp.json()
}

/** 一次性返回（同步）对话 */
export function chat(payload) {
  return request('/chat', { method: 'POST', body: JSON.stringify(payload) })
}

/**
 * SSE 流式对话。
 * EventSource 不支持 POST，因此用 fetch + ReadableStream 手动解析 SSE 帧。
 *
 * @param {object} payload
 * @param {{onMeta?:Function,onDelta?:Function,onDone?:Function,onError?:Function}} handlers
 * @param {AbortSignal} [signal]
 */
export async function chatStream(payload, handlers = {}, signal) {
  let resp
  try {
    resp = await fetch(`${BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (err) {
    handlers.onError?.(err)
    return
  }

  if (!resp.ok || !resp.body) {
    handlers.onError?.(new Error(`HTTP ${resp.status}`))
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE 以空行分隔事件
      let sep
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)

        let event = 'message'
        const dataLines = []
        for (const line of raw.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
        }
        if (!dataLines.length) continue

        const text = dataLines.join('\n')
        // delta 是纯文本片段；meta / done 是 JSON 对象
        let parsed = text
        if (event !== 'delta') {
          try {
            parsed = JSON.parse(text)
          } catch {
            /* 解析失败则按纯文本处理 */
          }
        }

        if (event === 'meta') handlers.onMeta?.(parsed)
        else if (event === 'delta') handlers.onDelta?.(parsed)
        else if (event === 'done') handlers.onDone?.(parsed)
      }
    }
  } catch (err) {
    if (err?.name !== 'AbortError') handlers.onError?.(err)
  }
}

/** 报告解读（文本） */
export function interpretReport(reportText, profile = {}, sessionId = '') {
  return request('/report/interpret', {
    method: 'POST',
    body: JSON.stringify({ report_text: reportText, profile, session_id: sessionId }),
  })
}

/** 报告解读（文件上传） */
export async function uploadReport(file) {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(`${BASE}/report/upload`, { method: 'POST', body: form })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const err = await resp.json()
      detail = err.detail || detail
    } catch {
      /* 忽略 */
    }
    throw new Error(detail)
  }
  return resp.json()
}

/** 常见问题列表 */
export function listFaq(q = '', limit = 20) {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  params.set('limit', String(limit))
  return request(`/faq?${params.toString()}`)
}

/** 服务健康状态 */
export function health() {
  return request('/health')
}

/** 运行后端自省 */
export function runtime() {
  return request('/runtime')
}
