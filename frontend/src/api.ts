import type { ConfigStatus, CurrentUser, DocumentData } from './types'

const configuredApiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
const API_BASE = configuredApiBase || `${window.location.protocol}//${window.location.hostname}:8000`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...init })
  } catch {
    throw new Error('与服务器的连接已中断。文档可能处理时间过长，请稍后重试；若持续出现，请减少图片数量或检查网络。')
  }
  if (!response.ok) {
    const raw = await response.text()
    let detail = ''
    try {
      const body = JSON.parse(raw) as { detail?: string }
      detail = body.detail ?? ''
    } catch {
      // Nginx and other proxies may return an HTML error page.
    }
    if (!detail && response.status === 502) detail = '后端处理服务暂时不可用（HTTP 502），请稍后重试。'
    if (!detail && response.status === 504) detail = '文档处理超时（HTTP 504），请减少图片数量或稍后重试。'
    if (!detail && response.status === 413) detail = '上传文件被代理服务器拒绝（HTTP 413）。'
    throw new Error(detail || `服务器请求失败（HTTP ${response.status}）。`)
  }
  return response.json() as Promise<T>
}

export function getConfigStatus(): Promise<ConfigStatus> {
  return request('/api/config/status')
}

export function login(username: string, password: string): Promise<CurrentUser> {
  return request('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export function logout(): Promise<{ status: string }> {
  return request('/api/auth/logout', { method: 'POST' })
}

export function getCurrentUser(): Promise<CurrentUser> {
  return request('/api/users/me')
}

export function getAssetUrl(documentId: string, filename: string): string {
  return `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/assets/${encodeURIComponent(filename)}`
}

export function createDemo(): Promise<DocumentData> {
  return request('/api/documents/demo', { method: 'POST' })
}

export function getDocument(id: string): Promise<DocumentData> {
  return request(`/api/documents/${id}`)
}

export function getHistory(): Promise<DocumentData[]> {
  return request('/api/documents/history')
}

export function getAdminHistory(): Promise<DocumentData[]> {
  return request('/api/admin/documents')
}

export function analyzeDocument(file: File): Promise<DocumentData> {
  const data = new FormData()
  data.append('file', file)
  return request('/api/documents/analyze', { method: 'POST', body: data })
}

export function processDocument(
  id: string,
  findingIds: string[],
  improveStructure: boolean,
  aiConfig?: { baseUrl: string; apiKey: string; model: string },
): Promise<DocumentData> {
  const completeAiConfig = aiConfig?.baseUrl && aiConfig.apiKey && aiConfig.model
    ? { base_url: aiConfig.baseUrl, api_key: aiConfig.apiKey, model: aiConfig.model }
    : undefined
  return request(`/api/documents/${id}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-DTB-Async': 'true' },
    body: JSON.stringify({ finding_ids: findingIds, improve_structure: improveStructure, ai_config: completeAiConfig }),
  })
}

export async function downloadExport(id: string, format: 'markdown' | 'hexo' | 'hugo' | 'astro' | 'docx' | 'pdf'): Promise<void> {
  const response = await fetch(`${API_BASE}/api/documents/${id}/export/${format}`, { credentials: 'include' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '导出失败，请稍后重试。' }))
    throw new Error(body.detail ?? '导出失败，请稍后重试。')
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const fallbackName = `draft-to-blog.${fallbackExtension(format)}`
  const filename = match ? decodeURIComponent(match[1]) : fallbackName
  const blob = await response.blob()
  if (await saveWithFilePicker(blob, filename, response.headers.get('content-type') ?? undefined)) return
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function fallbackExtension(format: 'markdown' | 'hexo' | 'hugo' | 'astro' | 'docx' | 'pdf'): string {
  if (format === 'markdown') return 'md'
  if (format === 'docx' || format === 'pdf') return format
  return `${format}.md`
}

async function saveWithFilePicker(blob: Blob, filename: string, mimeType?: string): Promise<boolean> {
  const picker = (window as unknown as {
    showSaveFilePicker?: (options?: {
      suggestedName?: string
      types?: Array<{
        description: string
        accept: Record<string, string[]>
      }>
    }) => Promise<{
      createWritable: () => Promise<{
        write: (data: Blob) => Promise<void>
        close: () => Promise<void>
      }>
    }>
  }).showSaveFilePicker
  if (!picker) return false
  try {
    const handle = await picker({
      suggestedName: filename,
      types: [filePickerType(filename, mimeType)],
    })
    const writable = await handle.createWritable()
    await writable.write(blob)
    await writable.close()
    return true
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return true
    return false
  }
}

function filePickerType(filename: string, mimeType?: string): { description: string; accept: Record<string, string[]> } {
  const suffix = filename.toLowerCase().endsWith('.docx')
    ? '.docx'
    : filename.toLowerCase().endsWith('.pdf')
      ? '.pdf'
      : '.md'
  const type = mimeType?.split(';')[0] || (
    suffix === '.docx'
      ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      : suffix === '.pdf'
        ? 'application/pdf'
        : 'text/markdown'
  )
  return {
    description: suffix === '.md' ? 'Markdown 文件' : suffix === '.pdf' ? 'PDF 文件' : 'Word 文档',
    accept: { [type]: [suffix] },
  }
}

