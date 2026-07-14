import type { ConfigStatus, DocumentData } from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '请求失败，请稍后重试。' }))
    throw new Error(body.detail ?? '请求失败，请稍后重试。')
  }
  return response.json() as Promise<T>
}

export function getConfigStatus(): Promise<ConfigStatus> {
  return request('/api/config/status')
}

export function createDemo(): Promise<DocumentData> {
  return request('/api/documents/demo', { method: 'POST' })
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
): Promise<DocumentData> {
  return request(`/api/documents/${id}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ finding_ids: findingIds, improve_structure: improveStructure }),
  })
}

export async function downloadExport(id: string, format: 'markdown' | 'docx' | 'pdf'): Promise<void> {
  const response = await fetch(`${API_BASE}/api/documents/${id}/export/${format}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '导出失败，请稍后重试。' }))
    throw new Error(body.detail ?? '导出失败，请稍后重试。')
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const filename = match ? decodeURIComponent(match[1]) : `draft-to-blog.${format}`
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

