export type Risk = 'low' | 'medium' | 'high'

export interface Finding {
  id: string
  kind: string
  label: string
  original: string
  replacement: string
  start: number
  end: number
  risk: Risk
  accepted: boolean
}

export interface DocumentStats {
  characters: number
  paragraphs: number
  images: number
  findings: number
}

export interface DocumentData {
  id: string
  filename: string
  source_type: 'markdown' | 'docx' | 'pdf'
  status: 'ready' | 'processed'
  original_content: string
  processed_content: string
  stats: DocumentStats
  findings: Finding[]
  warnings: string[]
  assets: Array<{
    filename: string
    local_path: string
    status: 'pending' | 'uploaded' | 'failed'
    url: string
    provider: string
    error: string
  }>
}

export interface ConfigStatus {
  official_ai_ready: boolean
  user_ai_allowed: boolean
  cos_ready: boolean
  picgo_configured: boolean
  mock_mode: boolean
  app_public_url: string
  frontend_public_url: string
  deployment_configured: boolean
  app_secret_configured: boolean
}

export interface AiSettings {
  baseUrl: string
  apiKey: string
  model: string
}
