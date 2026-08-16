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
  getAdminHistory,
  getConfigStatus,
  getAssetUrl,
  getCurrentUser,
  getDocument,
  getHistory,
  login,
  logout,
  processDocument,
} from './api'
import type { AiSettings, ConfigStatus, CurrentUser, DocumentData } from './types'

type Theme = 'light' | 'dark'
type ExportFormat = 'markdown' | 'hexo' | 'hugo' | 'astro' | 'docx' | 'pdf'

const acceptedExtensions = ['.pdf', '.docx', '.md', '.markdown']
const steps = ['导入文档', '整理内容', '隐私检查', '导出发布']
const currentDocumentStorageKey = 'dtb-current-document'
const historyStorageKey = 'dtb-document-history'
const historyLimit = 8
const exportOptions: Array<{ value: ExportFormat; label: string; detail: string }> = [
  { value: 'markdown', label: '普通 Markdown', detail: '纯正文 Markdown' },
  { value: 'hexo', label: 'Hexo 博客', detail: 'Hexo front matter' },
  { value: 'hugo', label: 'Hugo 博客', detail: 'Hugo front matter' },
  { value: 'astro', label: 'Astro 博客', detail: 'Astro content collection' },
  { value: 'docx', label: 'Word 文档', detail: 'DOCX 文件' },
  { value: 'pdf', label: 'PDF 文档', detail: 'PDF 文件' },
]

function initialTheme(): Theme {
  const saved = localStorage.getItem('dtb-theme')
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function loadStoredDocument(): DocumentData | null {
  try {
    const raw = localStorage.getItem(currentDocumentStorageKey)
    return raw ? JSON.parse(raw) as DocumentData : null
  } catch {
    localStorage.removeItem(currentDocumentStorageKey)
    return null
  }
}

function loadHistory(): DocumentData[] {
  try {
    const raw = localStorage.getItem(historyStorageKey)
    return raw ? JSON.parse(raw) as DocumentData[] : []
  } catch {
    localStorage.removeItem(historyStorageKey)
    return []
  }
}

function saveDocumentHistory(data: DocumentData) {
  const next = [data, ...loadHistory().filter((item) => item.id !== data.id)].slice(0, historyLimit)
  localStorage.setItem(historyStorageKey, JSON.stringify(next))
}

function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [documentData, setDocumentData] = useState<DocumentData | null>(loadStoredDocument)
  const [history, setHistory] = useState<DocumentData[]>(loadHistory)
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [adminView, setAdminView] = useState(false)
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
    getCurrentUser()
      .then((current) => {
        setUser(current)
        return getHistory()
      })
      .then((items) => setHistory(items))
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true))
  }, [])

  async function handleLogin(username: string, password: string) {
    const current = await login(username, password)
    setUser(current)
    setAdminView(false)
    setHistory(await getHistory())
  }

  async function handleLogout() {
    await logout().catch(() => undefined)
    setUser(null)
    setDocumentData(null)
    setHistory([])
    setAdminView(false)
    localStorage.removeItem(currentDocumentStorageKey)
    localStorage.removeItem(historyStorageKey)
  }

  async function toggleAdminView() {
    const next = !adminView
    setAdminView(next)
    setHistory(next ? await getAdminHistory() : await getHistory())
    setDocumentData(null)
  }

  useEffect(() => {
    if (!documentData) return
    localStorage.setItem(currentDocumentStorageKey, JSON.stringify(documentData))
    saveDocumentHistory(documentData)
    setHistory(loadHistory())
  }, [documentData])

  function updateDocument(data: DocumentData | null) {
    setDocumentData(data)
    if (!data) {
      localStorage.removeItem(currentDocumentStorageKey)
      return
    }
    localStorage.setItem(currentDocumentStorageKey, JSON.stringify(data))
    saveDocumentHistory(data)
    setHistory(loadHistory())
  }

  async function handleFile(file: File) {
    const extension = `.${file.name.split('.').pop()?.toLowerCase()}`
    if (!acceptedExtensions.includes(extension)) {
      setError('请选择 PDF、DOCX 或 Markdown 文件。')
      return
    }
    setError('')
    setLoading(true)
    try {
      updateDocument(await analyzeDocument(file))
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
      updateDocument(await createDemo())
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
        user={user}
        theme={theme}
        config={config}
        onThemeChange={() => setTheme(theme === 'light' ? 'dark' : 'light')}
        onOpenSettings={() => setSettingsOpen(true)}
        onReset={documentData ? () => updateDocument(null) : undefined}
        onLogout={user ? handleLogout : undefined}
        onToggleAdminView={user?.role === 'admin' ? toggleAdminView : undefined}
        adminView={adminView}
      />
      <main id="main-content">
        {!authChecked ? (
          <div className="auth-page"><LoaderCircle className="spin" size={24} /></div>
        ) : !user ? (
          <LoginScreen onLogin={handleLogin} />
        ) : documentData ? (
          <Workspace
            data={documentData}
            error={error}
            onChange={updateDocument}
            onError={setError}
          />
        ) : (
          <Landing
            loading={loading}
            error={error}
            config={config}
            history={history}
            adminView={adminView}
            onFile={handleFile}
            onDemo={handleDemo}
            onRestore={updateDocument}
            onClearHistory={() => {
              localStorage.removeItem(historyStorageKey)
              setHistory([])
            }}
          />
        )}
      </main>
      <div className="sr-live" aria-live="polite">{loading ? '正在处理文档' : error}</div>
      {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} config={config} />}
    </div>
  )
}

interface HeaderProps {
  user: CurrentUser | null
  theme: Theme
  config: ConfigStatus | null
  onThemeChange: () => void
  onOpenSettings: () => void
  onReset?: () => void
  onLogout?: () => void
  onToggleAdminView?: () => void
  adminView: boolean
}

function Header({ user, theme, config, onThemeChange, onOpenSettings, onReset, onLogout, onToggleAdminView, adminView }: HeaderProps) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <button className="brand" type="button" onClick={onReset} aria-label="DraftToBlog 首页">
          <span className="brand-mark" aria-hidden="true"><FileText size={20} /></span>
          <span>DraftToBlog</span>
          <span className="brand-beta">BETA</span>
        </button>
        <div className="topbar-actions">
          {user && <span className="user-badge">{user.role === 'admin' ? '管理员' : '用户'} · {user.username}</span>}
          {onToggleAdminView && (
            <button className="button button-ghost header-text-button" type="button" onClick={onToggleAdminView}>
              {adminView ? '我的历史' : '全部历史'}
            </button>
          )}
          {onLogout && (
            <button className="button button-ghost header-text-button" type="button" onClick={onLogout}>
              退出
            </button>
          )}
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

function LoginScreen({ onLogin }: { onLogin: (username: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState('demo_user')
  const [password, setPassword] = useState('123456')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await onLogin(username, password)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <div>
          <span className="panel-kicker"><KeyRound size={15} /> 登录</span>
          <h1>DraftToBlog</h1>
        </div>
        <label htmlFor="login-username">用户名</label>
        <input id="login-username" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
        <label htmlFor="login-password">密码</label>
        <input id="login-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
        {error && <div className="inline-error" role="alert"><AlertCircle size={17} />{error}</div>}
        <button className="button button-primary button-wide" type="submit" disabled={submitting}>
          {submitting ? <LoaderCircle className="spin" size={18} /> : <KeyRound size={18} />}
          登录
        </button>
        <small>普通用户 demo_user / 123456；管理员 admin / admin123456</small>
      </form>
    </div>
  )
}

interface LandingProps {
  loading: boolean
  error: string
  config: ConfigStatus | null
  history: DocumentData[]
  adminView: boolean
  onFile: (file: File) => void
  onDemo: () => void
  onRestore: (data: DocumentData) => void
  onClearHistory: () => void
}

function Landing({ loading, error, config, history, adminView, onFile, onDemo, onRestore, onClearHistory }: LandingProps) {
  return (
    <div className="landing-page">
      {adminView && <div className="admin-history-note">正在查看所有用户的历史记录</div>}
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
      {history.length > 0 && (
        <section className="history-panel" aria-label="历史记录">
          <div className="history-header">
            <div>
              <span className="step-kicker">历史记录</span>
              <h2>最近处理的文档</h2>
            </div>
            <button className="text-button" type="button" onClick={onClearHistory}>清空历史</button>
          </div>
          <div className="history-list">
            {history.map((item) => (
              <button className="history-item" type="button" key={item.id} onClick={() => onRestore(item)}>
                <span>
                  <strong>{item.filename}</strong>
                  <small>{statusLabel(item.status)} · {item.progress_percent ?? 0}% · {item.stats.characters.toLocaleString()} 字符 · {item.stats.images} 张图片</small>
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
          </div>
        </section>
      )}
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
  const [processing, setProcessing] = useState(false)
  const [exporting, setExporting] = useState<string | null>(null)
  const [exportFormat, setExportFormat] = useState<ExportFormat>('hexo')

  async function runProcess() {
    setProcessing(true)
    onError('')
    try {
      const savedAiConfig = sessionStorage.getItem('dtb-ai-settings')
      const aiConfig = savedAiConfig ? JSON.parse(savedAiConfig) as AiSettings : undefined
      let result = await processDocument(data.id, [...selectedFindings], improveStructure, aiConfig)
      onChange(result)
      while (result.status === 'processing') {
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
        result = await getDocument(data.id)
        onChange(result)
      }
      if (result.status === 'failed') {
        onError(result.error_message || '处理失败，请重试。')
      }
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : '处理失败，请重试。')
    } finally {
      setProcessing(false)
    }
  }

  async function runExport(format: ExportFormat) {
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
          </div>
          <div className="comparison-grid" aria-label="整理前后内容对比">
            <article className="document-preview comparison-document" aria-label="整理前文档内容">
              <div className="comparison-label">整理前</div>
              {data.original_content.split('\n').map((line, index) => (
                <PreviewLine
                  key={`original-${index}-${line.slice(0, 8)}`}
                  line={line}
                  documentId={data.id}
                  assets={data.assets}
                />
              ))}
            </article>
            <article className="document-preview comparison-document" aria-label="整理后文档内容">
              <div className="comparison-label">整理后</div>
              {data.processed_content.split('\n').map((line, index) => (
                <PreviewLine
                  key={`processed-${index}-${line.slice(0, 8)}`}
                  line={line}
                  documentId={data.id}
                  assets={data.assets}
                />
              ))}
            </article>
          </div>
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

          {(processing || data.status === 'processing' || data.status === 'failed') && (
            <div className={`task-progress task-progress-${data.status}`} role="status" aria-live="polite">
              <div className="task-progress-bar">
                <span style={{ width: `${Math.max(0, Math.min(100, data.progress_percent ?? 0))}%` }} />
              </div>
              <small>{data.progress_message || statusLabel(data.status)} · {data.progress_percent ?? 0}%</small>
            </div>
          )}

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
            <div className="export-picker">
              <label htmlFor="export-format">输出格式</label>
              <select
                id="export-format"
                value={exportFormat}
                onChange={(event) => setExportFormat(event.target.value as ExportFormat)}
                disabled={Boolean(exporting)}
              >
                {exportOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <small>{exportOptions.find((option) => option.value === exportFormat)?.detail}</small>
            </div>
            <button className="button button-primary button-wide export-action" type="button" onClick={() => runExport(exportFormat)} disabled={Boolean(exporting)}>
              {exporting ? <LoaderCircle className="spin" size={18} /> : <Download size={18} />}
              {exporting ? '正在导出...' : '导出当前格式'}
            </button>
          </div>
        </aside>
      </section>
    </div>
  )
}

function PreviewLine({
  line,
  documentId,
  assets,
}: {
  line: string
  documentId: string
  assets: DocumentData['assets']
}) {
  const heading = line.match(/^(#{1,6})\s+(.+)$/)
  if (heading) {
    const level = Math.min(heading[1].length + 1, 6)
    const Tag = `h${level}` as keyof JSX.IntrinsicElements
    return <Tag>{renderInlineMarkdown(heading[2])}</Tag>
  }
  const imageOnly = resolvePreviewImage(line.trim(), documentId, assets)
  if (imageOnly) return <PreviewImage image={imageOnly} />

  const inlineImages = [...line.matchAll(/!\[([^\]]*)\]\(([^)]+)\)/g)]
  if (inlineImages.length) {
    const nodes: React.ReactNode[] = []
    let lastIndex = 0
    inlineImages.forEach((match, index) => {
      const before = line.slice(lastIndex, match.index)
      if (before.trim()) nodes.push(<p key={`text-${index}`}>{renderInlineMarkdown(before)}</p>)
      nodes.push(<PreviewImage key={`image-${index}`} image={resolveMarkdownImage(match[1], match[2], documentId, assets)} />)
      lastIndex = (match.index ?? 0) + match[0].length
    })
    const after = line.slice(lastIndex)
    if (after.trim()) nodes.push(<p key="text-after">{renderInlineMarkdown(after)}</p>)
    return <>{nodes}</>
  }

  if (!line.trim()) return <span className="preview-space" aria-hidden="true" />
  if (line.startsWith('> ')) return <blockquote>{renderInlineMarkdown(line.slice(2))}</blockquote>
  return <p>{renderInlineMarkdown(line)}</p>
}

function statusLabel(status: DocumentData['status']) {
  if (status === 'processed') return '已生成'
  if (status === 'processing') return '生成中'
  if (status === 'failed') return '生成失败'
  return '待整理'
}

function PreviewImage({ image }: { image: { src: string; alt: string; caption?: string } }) {
  return (
    <figure className="preview-image">
      <img src={image.src} alt={image.alt} loading="lazy" />
      {(image.caption || image.alt) && <figcaption>{image.caption || image.alt}</figcaption>}
    </figure>
  )
}

function resolvePreviewImage(line: string, documentId: string, assets: DocumentData['assets']) {
  const markdownImage = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
  if (markdownImage) return resolveMarkdownImage(markdownImage[1], markdownImage[2], documentId, assets)

  const marker = line.match(/^\[IMG_(\d+)\]$/)
  if (marker) {
    const asset = assets[Number(marker[1])]
    if (asset) return assetPreviewImage(asset, documentId)
  }

  const filename = line.match(/^(image-(\d+)\.(?:png|jpe?g|gif|webp|bmp))$/i)
  if (filename) {
    const asset = assets.find((item) => item.filename.toLowerCase() === filename[1].toLowerCase())
      || assets[Number(filename[2]) - 1]
    if (asset) return assetPreviewImage(asset, documentId)
  }

  return null
}

function resolveMarkdownImage(alt: string, src: string, documentId: string, assets: DocumentData['assets']) {
  const filename = src.match(/([^/\\]+)$/)?.[1] ?? ''
  const asset = assets.find((item) => item.filename.toLowerCase() === filename.toLowerCase())
  if (asset) return assetPreviewImage(asset, documentId)
  return { src, alt: alt || filename || '文档图片', caption: alt || filename || undefined }
}

function assetPreviewImage(asset: DocumentData['assets'][number], documentId: string) {
  return {
    src: getAssetUrl(documentId, asset.filename),
    alt: asset.filename,
    caption: asset.filename,
  }
}

function renderInlineMarkdown(text: string) {
  const nodes: React.ReactNode[] = []
  const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`)/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index))
    if (match[2]) nodes.push(<strong key={match.index}>{match[2]}</strong>)
    else if (match[3]) nodes.push(<code key={match.index}>{match[3]}</code>)
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))
  return nodes
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
