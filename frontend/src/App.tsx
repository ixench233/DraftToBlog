import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Cloud,
  Download,
  FileInput,
  FileText,
  KeyRound,
  LoaderCircle,
  Moon,
  PanelRight,
  RotateCcw,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  UploadCloud,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  analyzeDocument,
  createDemo,
  downloadExport,
  getConfigStatus,
  getAssetUrl,
  processDocument,
} from './api'
import type { AiSettings, ConfigStatus, DocumentData } from './types'

type Theme = 'light' | 'dark'
type PreviewMode = 'original' | 'processed'

const acceptedExtensions = ['.pdf', '.docx', '.md', '.markdown']
const steps = ['导入文档', '整理内容', '隐私检查', '导出发布']

function initialTheme(): Theme {
  const saved = localStorage.getItem('dtb-theme')
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [documentData, setDocumentData] = useState<DocumentData | null>(null)
  const [config, setConfig] = useState<ConfigStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('dtb-theme', theme)
  }, [theme])

  useEffect(() => {
    getConfigStatus().then(setConfig).catch(() => setConfig(null))
  }, [])

  async function handleFile(file: File) {
    const extension = `.${file.name.split('.').pop()?.toLowerCase()}`
    if (!acceptedExtensions.includes(extension)) {
      setError('请选择 PDF、DOCX 或 Markdown 文件。')
      return
    }
    setError('')
    setLoading(true)
    try {
      setDocumentData(await analyzeDocument(file))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '文件解析失败。')
    } finally {
      setLoading(false)
    }
  }

  async function handleDemo() {
    setError('')
    setLoading(true)
    try {
      setDocumentData(await createDemo())
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '演示文档加载失败。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <Header
        theme={theme}
        config={config}
        onThemeChange={() => setTheme(theme === 'light' ? 'dark' : 'light')}
        onOpenSettings={() => setSettingsOpen(true)}
        onReset={documentData ? () => setDocumentData(null) : undefined}
      />
      <main id="main-content">
        {documentData ? (
          <Workspace
            data={documentData}
            error={error}
            onChange={setDocumentData}
            onError={setError}
          />
        ) : (
          <Landing
            loading={loading}
            error={error}
            config={config}
            onFile={handleFile}
            onDemo={handleDemo}
          />
        )}
      </main>
      <div className="sr-live" aria-live="polite">{loading ? '正在处理文档' : error}</div>
      {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} config={config} />}
    </div>
  )
}

interface HeaderProps {
  theme: Theme
  config: ConfigStatus | null
  onThemeChange: () => void
  onOpenSettings: () => void
  onReset?: () => void
}

function Header({ theme, config, onThemeChange, onOpenSettings, onReset }: HeaderProps) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <button className="brand" type="button" onClick={onReset} aria-label="DraftToBlog 首页">
          <span className="brand-mark" aria-hidden="true"><FileText size={20} /></span>
          <span>DraftToBlog</span>
          <span className="brand-beta">BETA</span>
        </button>
        <div className="topbar-actions">
          <div className={`service-status ${config?.mock_mode ? 'is-pending' : 'is-ready'}`}>
            <span className="status-dot" aria-hidden="true" />
            {config?.mock_mode ? '基础模式' : '服务已就绪'}
          </div>
          {onReset && (
            <button className="button button-ghost header-text-button" type="button" onClick={onReset}>
              <RotateCcw size={17} /> 新建任务
            </button>
          )}
          <button className="icon-button" type="button" onClick={onOpenSettings} aria-label="打开 API 设置">
            <Settings size={19} />
          </button>
          <button className="icon-button" type="button" onClick={onThemeChange} aria-label={`切换为${theme === 'light' ? '暗黑' : '明亮'}主题`}>
            {theme === 'light' ? <Moon size={19} /> : <Sun size={19} />}
          </button>
        </div>
      </div>
    </header>
  )
}

interface LandingProps {
  loading: boolean
  error: string
  config: ConfigStatus | null
  onFile: (file: File) => void
  onDemo: () => void
}

function Landing({ loading, error, config, onFile, onDemo }: LandingProps) {
  return (
    <div className="landing-page">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <div className="eyebrow"><Sparkles size={16} /> 让工作沉淀真正成为内容资产</div>
          <h1 id="hero-title">从内部草稿到<br /><span>可公开的好文章</span></h1>
          <p className="hero-lead">导入 PDF、Word 或 Markdown，自动整理结构、发现敏感信息，并输出你需要的发布格式。</p>
          <div className="value-list">
            <ValueItem icon={<FileInput size={19} />} title="多格式解析" detail="PDF · DOCX · Markdown" />
            <ValueItem icon={<ShieldCheck size={19} />} title="发布前检查" detail="隐私风险逐项确认" />
            <ValueItem icon={<Cloud size={19} />} title="图片可用" detail="PicGo + 腾讯云 COS" />
          </div>
        </div>
        <UploadCard loading={loading} error={error} onFile={onFile} onDemo={onDemo} />
      </section>
      <section className="trust-strip" aria-label="处理流程说明">
        <span><ShieldCheck size={17} /> 默认任务自动过期清理</span>
        <span><CheckCircle2 size={17} /> 每一处修改都由你确认</span>
        <span><KeyRound size={17} /> API Key 不写入应用日志</span>
        <span className="config-summary">AI {config?.official_ai_ready ? '已配置' : '待配置'} · COS {config?.cos_ready ? '已配置' : '待配置'}</span>
      </section>
    </div>
  )
}

function ValueItem({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return (
    <div className="value-item">
      <span className="value-icon" aria-hidden="true">{icon}</span>
      <span><strong>{title}</strong><small>{detail}</small></span>
    </div>
  )
}

interface UploadCardProps {
  loading: boolean
  error: string
  onFile: (file: File) => void
  onDemo: () => void
}

function UploadCard({ loading, error, onFile, onDemo }: UploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function select(files: FileList | null) {
    const file = files?.[0]
    if (file) onFile(file)
  }

  return (
    <div className="upload-card">
      <div className="upload-card-head">
        <div><span className="step-kicker">第一步</span><h2>导入一份草稿</h2></div>
        <span className="secure-label"><ShieldCheck size={15} /> 安全处理</span>
      </div>
      <div
        className={`dropzone ${dragging ? 'is-dragging' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => { event.preventDefault(); setDragging(false) }}
        onDrop={(event) => { event.preventDefault(); setDragging(false); select(event.dataTransfer.files) }}
      >
        <span className="dropzone-icon" aria-hidden="true"><UploadCloud size={30} /></span>
        <h3>拖放文件到这里</h3>
        <p>或从电脑中选择一份文档</p>
        <button className="button button-primary" type="button" disabled={loading} onClick={() => inputRef.current?.click()}>
          {loading ? <LoaderCircle className="spin" size={18} /> : <UploadCloud size={18} />}
          {loading ? '正在解析…' : '选择文件'}
        </button>
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept=".pdf,.docx,.md,.markdown"
          onChange={(event) => select(event.target.files)}
        />
        <span className="file-hint">支持 PDF、DOCX、Markdown · 不限制文件大小</span>
      </div>
      {error && <div className="inline-error" role="alert"><AlertCircle size={17} />{error}</div>}
      <div className="demo-row">
        <span>暂时没有文件？</span>
        <button className="text-button" type="button" disabled={loading} onClick={onDemo}>使用安全演示文档 <ArrowRight size={16} /></button>
      </div>
    </div>
  )
}

interface WorkspaceProps {
  data: DocumentData
  error: string
  onChange: (data: DocumentData) => void
  onError: (message: string) => void
}

function Workspace({ data, error, onChange, onError }: WorkspaceProps) {
  const [selectedFindings, setSelectedFindings] = useState(() => new Set(data.findings.map((item) => item.id)))
  const [improveStructure, setImproveStructure] = useState(true)
  const [previewMode, setPreviewMode] = useState<PreviewMode>(data.status === 'processed' ? 'processed' : 'original')
  const [processing, setProcessing] = useState(false)
  const [exporting, setExporting] = useState<string | null>(null)

  async function runProcess() {
    setProcessing(true)
    onError('')
    try {
      const savedAiConfig = sessionStorage.getItem('dtb-ai-settings')
      const aiConfig = savedAiConfig ? JSON.parse(savedAiConfig) as AiSettings : undefined
      const result = await processDocument(data.id, [...selectedFindings], improveStructure, aiConfig)
      onChange(result)
      setPreviewMode('processed')
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : '处理失败，请重试。')
    } finally {
      setProcessing(false)
    }
  }

  async function runExport(format: 'markdown' | 'docx' | 'pdf') {
    setExporting(format)
    onError('')
    try {
      await downloadExport(data.id, format)
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : '导出失败，请重试。')
    } finally {
      setExporting(null)
    }
  }

  function toggleFinding(id: string) {
    setSelectedFindings((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const currentStep = data.status === 'processed' ? 3 : 2
  const preview = previewMode === 'original' ? data.original_content : data.processed_content

  return (
    <div className="workspace-page">
      <section className="workflow-header">
        <div className="document-title-row">
          <div>
            <span className="step-kicker">当前任务</span>
            <h1>{data.filename}</h1>
          </div>
          <span className={`file-type type-${data.source_type}`}>{data.source_type.toUpperCase()}</span>
        </div>
        <ol className="stepper" aria-label="文档处理进度">
          {steps.map((step, index) => (
            <li key={step} className={index < currentStep ? 'is-complete' : index === currentStep ? 'is-current' : ''}>
              <span className="step-number" aria-hidden="true">{index < currentStep ? <Check size={15} /> : index + 1}</span>
              <span>{step}</span>
              {index < steps.length - 1 && <ChevronRight className="step-chevron" size={16} aria-hidden="true" />}
            </li>
          ))}
        </ol>
      </section>

      {data.warnings.length > 0 && (
        <div className="warning-banner" role="status">
          <AlertCircle size={18} />
          <div><strong>导入检查提醒</strong>{data.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>
        </div>
      )}

      {error && <div className="workspace-error" role="alert"><AlertCircle size={18} />{error}</div>}

      <section className="stats-grid" aria-label="文档统计">
        <StatCard label="字符" value={data.stats.characters.toLocaleString()} />
        <StatCard label="段落" value={data.stats.paragraphs.toString()} />
        <StatCard label="图片" value={data.stats.images.toString()} />
        <StatCard label="风险项" value={data.stats.findings.toString()} emphasized={data.stats.findings > 0} />
      </section>

      <section className="workbench">
        <div className="preview-panel panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker"><FileText size={15} /> 文档预览</span>
              <h2>内容与修改结果</h2>
            </div>
            <div className="segmented" role="group" aria-label="预览版本">
              <button type="button" className={previewMode === 'original' ? 'is-active' : ''} onClick={() => setPreviewMode('original')}>原文</button>
              <button type="button" className={previewMode === 'processed' ? 'is-active' : ''} onClick={() => setPreviewMode('processed')} disabled={data.status !== 'processed'}>整理后</button>
            </div>
          </div>
          <article className="document-preview" aria-label={`${previewMode === 'original' ? '原始' : '整理后'}文档内容`}>
            {preview.split('\n').map((line, index) => <PreviewLine key={`${index}-${line.slice(0, 8)}`} line={line} />)}
            {data.assets.length > 0 && (
              <section className="document-images" aria-label="文档图片">
                <h3>文档图片</h3>
                <div className="document-image-grid">
                  {data.assets.map((asset) => (
                    <figure key={asset.filename}>
                      <img
                        src={asset.url || getAssetUrl(data.id, asset.filename)}
                        alt={asset.filename}
                        loading="lazy"
                      />
                      <figcaption>
                        {asset.filename}
                        {asset.status === 'uploaded' && <span>已上传</span>}
                        {asset.status === 'failed' && <span className="image-failed">上传失败</span>}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              </section>
            )}
          </article>
        </div>

        <aside className="control-panel panel" aria-label="处理选项">
          <div className="panel-header">
            <div><span className="panel-kicker"><PanelRight size={15} /> 处理面板</span><h2>发布前整理</h2></div>
          </div>
          <label className="option-card">
            <input type="checkbox" checked={improveStructure} onChange={(event) => setImproveStructure(event.target.checked)} />
            <span className="check-control" aria-hidden="true"><Check size={14} /></span>
            <span><strong>AI 内容优化</strong><small>优化标题、结构和表达；未配置 AI 时自动使用本地基础整理</small></span>
          </label>

          <div className="finding-section">
            <div className="section-title-row">
              <div><h3>隐私风险</h3><span>{selectedFindings.size}/{data.findings.length} 项将被替换</span></div>
              <ShieldCheck size={19} />
            </div>
            {data.findings.length ? (
              <div className="finding-list">
                {data.findings.map((finding) => (
                  <label className="finding-item" key={finding.id}>
                    <input type="checkbox" checked={selectedFindings.has(finding.id)} onChange={() => toggleFinding(finding.id)} />
                    <span className="check-control" aria-hidden="true"><Check size={13} /></span>
                    <span className="finding-copy">
                      <span><strong>{finding.label}</strong><em className={`risk risk-${finding.risk}`}>{finding.risk === 'high' ? '高风险' : '需留意'}</em></span>
                      <code>{finding.original}</code>
                      <small>替换为：{finding.replacement}</small>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="empty-findings"><CheckCircle2 size={22} /><span><strong>未发现常见敏感信息</strong><small>发布前仍建议人工复核</small></span></div>
            )}
          </div>

          <button className="button button-primary button-wide" type="button" disabled={processing} onClick={runProcess}>
            {processing ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={18} />}
            {processing ? '正在整理…' : data.status === 'processed' ? '重新应用设置' : '生成发布版本'}
          </button>

          {error && (
            <div className="processing-error" role="alert" aria-live="assertive">
              <AlertCircle size={19} />
              <div>
                <strong>生成失败</strong>
                <p>{error}</p>
                <small>文档原文和当前设置均已保留，请修正配置后重试。</small>
              </div>
            </div>
          )}

          <div className="export-section">
            <div className="section-title-row"><div><h3>导出文件</h3><span>可随时导出当前结果</span></div><Download size={19} /></div>
            <div className="export-grid">
              {(['markdown', 'docx', 'pdf'] as const).map((format) => (
                <button key={format} type="button" onClick={() => runExport(format)} disabled={Boolean(exporting)}>
                  {exporting === format ? <LoaderCircle className="spin" size={17} /> : <Download size={17} />}
                  {format === 'markdown' ? 'Markdown' : format.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </aside>
      </section>
    </div>
  )
}

function PreviewLine({ line }: { line: string }) {
  const heading = line.match(/^(#{1,6})\s+(.+)$/)
  if (heading) {
    const level = Math.min(heading[1].length + 1, 6)
    const Tag = `h${level}` as keyof JSX.IntrinsicElements
    return <Tag>{heading[2]}</Tag>
  }
  if (!line.trim()) return <span className="preview-space" aria-hidden="true" />
  if (line.startsWith('> ')) return <blockquote>{line.slice(2)}</blockquote>
  return <p>{line}</p>
}

function StatCard({ label, value, emphasized = false }: { label: string; value: string; emphasized?: boolean }) {
  return <div className={`stat-card ${emphasized ? 'is-emphasized' : ''}`}><span>{label}</span><strong>{value}</strong></div>
}

function SettingsDialog({ onClose, config }: { onClose: () => void; config: ConfigStatus | null }) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const [settings, setSettings] = useState<AiSettings>(() => {
    const saved = sessionStorage.getItem('dtb-ai-settings')
    return saved ? JSON.parse(saved) as AiSettings : { baseUrl: '', apiKey: '', model: '' }
  })
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    dialogRef.current?.focus()
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  function save() {
    sessionStorage.setItem('dtb-ai-settings', JSON.stringify(settings))
    setSaved(true)
    window.setTimeout(onClose, 500)
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title" tabIndex={-1} ref={dialogRef}>
        <div className="dialog-header">
          <div><span className="panel-kicker"><KeyRound size={15} /> API 设置</span><h2 id="settings-title">使用你的 AI 接口</h2></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭设置"><X size={19} /></button>
        </div>
        <p className="dialog-intro">配置仅保存在当前浏览器会话。AI 接入完成前，应用使用不联网的基础整理功能。</p>
        <div className="server-config-state">
          <span className={config?.official_ai_ready ? 'ok' : ''}><span className="status-dot" /> 官方测试 AI：{config?.official_ai_ready ? '已配置' : '待配置'}</span>
          <span className={config?.cos_ready ? 'ok' : ''}><span className="status-dot" /> 腾讯云 COS：{config?.cos_ready ? '已配置' : '待配置'}</span>
        </div>
        <div className="form-stack">
          <label htmlFor="api-base">API Base URL</label>
          <input id="api-base" type="url" value={settings.baseUrl} onChange={(event) => setSettings({ ...settings, baseUrl: event.target.value })} placeholder="https://api.example.com/v1" />
          <small>需要兼容 OpenAI API 格式。</small>
          <label htmlFor="api-key">API Key</label>
          <input id="api-key" type="password" autoComplete="off" value={settings.apiKey} onChange={(event) => setSettings({ ...settings, apiKey: event.target.value })} placeholder="输入后仅在本次会话中保存" />
          <label htmlFor="api-model">模型名称</label>
          <input id="api-model" value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} placeholder="例如：gpt-4.1-mini" />
        </div>
        <div className="dialog-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>取消</button>
          <button className="button button-primary" type="button" onClick={save}>{saved ? <Check size={18} /> : <KeyRound size={18} />}{saved ? '已保存' : '保存到当前会话'}</button>
        </div>
      </div>
    </div>
  )
}

export default App
