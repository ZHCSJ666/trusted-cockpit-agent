import { useEffect, useRef, useState, type ReactNode } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { request, sourceUrl, type Workspace, type Media, type VehicleExtras, type Document, type TaskStep } from './workspaceTypes'

type Props = { workspace: Workspace; sessionId: string; busy: boolean; send: (text: string) => void; update: (workspace: Workspace) => void; error: (message: string) => void }
const time = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '时间待确认'
const plain = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value)
const prompts = {
  journey: ['搜索杭州东站', '搜索附近的充电站', '导航去第二个', '沿途找咖啡店'],
  info: ['查询杭州天气', '最新汽车新闻', '搜索新能源汽车充电注意事项', '10分钟后提醒我休息'],
  memory: ['记住我喜欢空调22度', '我有什么偏好？', '开启舒适模式'],
}

function ExamplePrompts({ items, send, busy }: { items: string[]; send: Props['send']; busy: boolean }) {
  return <div className="workspace-prompts">{items.map(text => <button key={text} disabled={busy} onClick={() => send(text)}>{text}<span>↗</span></button>)}</div>
}

function MapView({ workspace }: { workspace: Workspace }) {
  const element = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layers = useRef<L.LayerGroup | null>(null)
  const [tileError, setTileError] = useState(false)
  const places = workspace.candidates || workspace.places || []
  const route = workspace.route || workspace.last_route
  useEffect(() => {
    if (!element.current) return
    const instance = L.map(element.current, { scrollWheelZoom: false, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false }).setView([30.2741, 120.1551], 12)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).on('tileerror', () => setTileError(true)).on('tileload', () => setTileError(false)).addTo(instance)
    layers.current = L.layerGroup().addTo(instance); map.current = instance
    const observer = new ResizeObserver(() => { if (map.current === instance) instance.invalidateSize({ animate: false }) })
    observer.observe(element.current)
    return () => { observer.disconnect(); map.current = null; instance.stop(); instance.remove() }
  }, [])
  useEffect(() => {
    if (!map.current || !layers.current) return
    const group = layers.current; group.clearLayers()
    const bounds: L.LatLngExpression[] = []
    const marker = (lat: number, lon: number, label: string, primary = false) => {
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return
      const node = document.createElement('div'); node.textContent = label
      L.circleMarker([lat, lon], { radius: primary ? 8 : 6, color: '#fff', weight: 2, fillColor: primary ? '#4169a1' : '#408674', fillOpacity: 1 }).bindTooltip(node, { direction: 'top' }).addTo(group)
      bounds.push([lat, lon])
    }
    if (workspace.location) marker(workspace.location.lat, workspace.location.lon, `出发地：${workspace.location.name || '已设置位置'}`, true)
    places.forEach((place, index) => marker(place.lat, place.lon, `${index + 1}. ${place.name}`))
    if (route?.geometry?.coordinates?.length) {
      const points = route.geometry.coordinates.filter(point => point.length > 1 && point.every(Number.isFinite)).map(point => [point[1], point[0]] as L.LatLngTuple)
      L.polyline(points, { color: '#456fa4', weight: 5, opacity: .85 }).addTo(group); bounds.push(...points)
    }
    if (bounds.length) map.current.fitBounds(L.latLngBounds(bounds), { padding: [35, 35], maxZoom: 15, animate: false })
  }, [workspace, places, route])
  return <div className="workspace-map-wrap"><div ref={element} className="workspace-map" aria-label="地点与路线地图" />{tileError && <p className="workspace-map-warning">底图暂时无法加载；地点与路线结果仍可在下方查看。</p>}</div>
}

function JourneyPanel({ workspace, busy, send }: Props) {
  const [query, setQuery] = useState('')
  const [origin, setOrigin] = useState('')
  const places = workspace.candidates || workspace.places || []
  const route = workspace.route || workspace.last_route
  return <section className="workspace-feature"><div className="workspace-feature-heading"><div><small>EXPLORE YOUR NEXT STOP</small><h2>下一程，已经在眼前。</h2></div><span className="workspace-pill">地图地点 / 路线</span></div>
    <form className="workspace-search" onSubmit={e => { e.preventDefault(); if (query.trim()) send(`搜索${query}`) }}><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索目的地、咖啡店或充电站" aria-label="搜索地点" /><button disabled={busy || !query.trim()}>查找</button></form>
    <MapView workspace={workspace} />
    <div className="workspace-location"><span>出发地 <b>{workspace.location?.name || '杭州 · 演示初始位置'}</b></span><details><summary>修改</summary><form onSubmit={e => { e.preventDefault(); if (origin.trim()) send(`设置出发地为${origin}`) }}><input value={origin} onChange={e => setOrigin(e.target.value)} placeholder="例如：上海虹桥站" aria-label="新的出发地" /><button disabled={busy || !origin.trim()}>设置</button></form></details></div>
    {route && <div className="workspace-route-summary"><div><small>当前规划</small><b>{typeof route.destination === 'string' ? route.destination : route.destination?.name || '已规划路线'}</b></div><span>{typeof route.distance_m === 'number' ? `${(route.distance_m / 1000).toFixed(1)} km` : '距离未提供'}<small>{typeof route.duration_s === 'number' ? `约 ${Math.ceil(route.duration_s / 60)} 分钟` : ''}</small></span><p>{route.source || 'OSRM 路线服务'} · 估算行程，不含实时路况</p>{!!route.waypoints?.length && <p>途经：{route.waypoints.map(p => p.name).join(' → ')}</p>}</div>}
    <div className="workspace-place-list">{places.map((place, index) => <article key={place.id || `${place.name}-${index}`}><span className="workspace-place-number">{index + 1}</span><div><h3>{place.name}</h3><p>{place.address || `${place.lat.toFixed(4)}, ${place.lon.toFixed(4)}`}</p>{place.data_mode === 'cached_snapshot' && <p>公开地图快照 · {time(place.snapshot_fetched_at || place.fetched_at)}</p>}{sourceUrl(place.source_url) && <a href={sourceUrl(place.source_url)} target="_blank" rel="noreferrer">地点来源 ↗</a>}</div><div className="workspace-place-actions"><button disabled={busy} onClick={() => send(`导航去第${index + 1}个`)}>到这里</button>{route && <button disabled={busy} onClick={() => send(`把第${index + 1}个加入途经点`)}>途经</button>}</div></article>)}</div>
    {!places.length && !route && <p className="workspace-empty">搜索一个地点，或直接对助手说“帮我规划去杭州东站的路线”。</p>}
    <ExamplePrompts items={prompts.journey} send={send} busy={busy} />
  </section>
}

function ServiceData({ data }: { data: Record<string, unknown> }) {
  const title = String(data.title || data.kind || data.type || '信息结果')
  const location = data.location && typeof data.location === 'object' ? (data.location as Record<string, unknown>).name : data.location
  const items = (Array.isArray(data.items) ? data.items : Array.isArray(data.results) ? data.results : []) as Record<string, unknown>[]
  const weather = (data.current && typeof data.current === 'object' ? data.current : data) as Record<string, unknown>
  const temp = weather.temperature_2m ?? weather.temperature ?? weather.temperature_c
  return <article className="workspace-information-card"><h3>{title}</h3>{temp !== undefined && <div className="workspace-weather"><strong>{String(temp)}<small>°C</small></strong><p>{String(data.location_name || location || data.city || '')}<br />{String(weather.description || weather.condition || data.description || '')}</p></div>}{!!data.message && <p>{String(data.message)}</p>}{!!data.summary && <p>{String(data.summary)}</p>}{items.map((item, index) => <div className="workspace-news-item" key={index}><h4>{sourceUrl(String(item.url || item.source_url || '')) ? <a href={sourceUrl(String(item.url || item.source_url || ''))} target="_blank" rel="noreferrer">{String(item.title || item.name || '来源')} ↗</a> : String(item.title || item.name || '')}</h4><p>{String(item.snippet || item.summary || item.description || '')}</p><small>{[item.source, item.published_at || item.published].filter(v => typeof v === 'string').join(' · ')}</small></div>)}<footer>{String(data.source || data.provider || '')}{data.fetched_at ? ` · ${time(String(data.fetched_at))}` : ''}{sourceUrl(String(data.source_url || '')) && <a href={sourceUrl(String(data.source_url))} target="_blank" rel="noreferrer">查看来源 ↗</a>}</footer></article>
}

function InfoPanel(props: Props) {
  const { workspace, send, busy, sessionId, update, error } = props
  const [localBusy, setLocalBusy] = useState(false)
  const sources: Record<string, unknown>[] = []
  for (const key of ['weather', 'news', 'search', 'last_weather', 'last_news', 'last_search']) {
    const value = workspace[key] || workspace.info?.[key]
    if (value && typeof value === 'object' && !Array.isArray(value)) sources.push({ kind: { weather: '天气', news: '新闻', search: '联网搜索', last_weather: '天气', last_news: '新闻', last_search: '联网搜索' }[key], ...value as Record<string, unknown> })
  }
  const cancel = async (id: string) => { setLocalBusy(true); try { await request(`reminders/${encodeURIComponent(id)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' }); update(await request<Workspace>(`workspace?session_id=${encodeURIComponent(sessionId)}`)) } catch (e) { error(e instanceof Error ? e.message : '取消提醒失败') } finally { setLocalBusy(false) } }
  return <section className="workspace-feature"><div className="workspace-feature-heading"><div><small>STAY INFORMED</small><h2>路上的信息，及时抵达。</h2></div></div><ExamplePrompts items={prompts.info} send={send} busy={busy} /><div className="workspace-information-list">{sources.map((data, i) => <ServiceData data={data} key={i} />)}</div>{!sources.length && <div className="workspace-empty large">查天气、读新闻、搜索资料。<br /><span>获取到的结果将在这里显示，附真实来源。</span></div>}<div className="workspace-section-label"><h3>我的提醒</h3><span>保存在本地 · 应用打开时提示</span></div>{(workspace.reminders || []).map(item => <article key={item.id} className={`workspace-reminder ${['due', 'notified'].includes(item.status || '') ? 'due' : ''}`}><div><b>{item.text || item.message || item.title}</b><p>{time(item.due_at)} · {['due', 'notified'].includes(item.status || '') ? '已到时间' : item.status === 'cancelled' ? '已取消' : '等待提醒'}</p></div><button disabled={busy || localBusy || item.status === 'cancelled'} onClick={() => void cancel(item.id)}>取消</button></article>)}{!workspace.reminders?.length && <p className="workspace-empty">还没有提醒，试试“10分钟后提醒我休息”。</p>}</section>
}

function MemoryPanel({ workspace, sessionId, update, error, send, busy }: Props) {
  const [key, setKey] = useState(''); const [value, setValue] = useState(''); const [saving, setSaving] = useState(false)
  const preferences = Array.isArray(workspace.preferences) ? workspace.preferences : Object.entries(workspace.preferences || {}).map(([k, v]) => ({ key: k, value: v }))
  const mutate = async (remove?: string) => { setSaving(true); try { await request(remove ? `preferences/${encodeURIComponent(remove)}?session_id=${encodeURIComponent(sessionId)}` : 'preferences', { method: remove ? 'DELETE' : 'POST', headers: { 'Content-Type': 'application/json' }, body: remove ? undefined : JSON.stringify({ session_id: sessionId, key: key.trim(), value: value.trim() }) }); update(await request<Workspace>(`workspace?session_id=${encodeURIComponent(sessionId)}`)); if (!remove) { setKey(''); setValue('') } } catch (e) { error(e instanceof Error ? e.message : '偏好保存失败') } finally { setSaving(false) } }
  return <section className="workspace-feature"><div className="workspace-feature-heading"><div><small>REMEMBER WHAT MATTERS</small><h2>你的习惯，下次还记得。</h2></div><span className="workspace-pill">跨会话保存</span></div><p className="workspace-intro">明确告诉助手要记住的偏好，会保存在本机。你可以随时修改或删除。</p><ExamplePrompts items={prompts.memory} send={send} busy={busy} /><div className="workspace-preference-list">{preferences.map(item => <article key={item.key}><div><span>{item.key}</span><b>{plain(item.value)}</b></div><button disabled={busy || saving} onClick={() => { setKey(item.key); setValue(plain(item.value)) }}>修改</button><button disabled={busy || saving} onClick={() => void mutate(item.key)}>删除</button></article>)}</div>{!preferences.length && <p className="workspace-empty">当前没有已保存的偏好。</p>}<form className="workspace-preference-form" onSubmit={e => { e.preventDefault(); void mutate() }}><label>偏好名称<input value={key} onChange={e => setKey(e.target.value)} placeholder="例如：favorite_drink" required /></label><label>偏好内容<input value={value} onChange={e => setValue(e.target.value)} placeholder="例如：无糖拿铁" required /></label><button disabled={busy || saving || !key.trim() || !value.trim()}>{saving ? '保存中…' : '保存偏好'}</button></form><p className="workspace-note">重置对话会保留偏好；删除后，后续任务将不再使用该偏好。</p></section>
}

export function MoreControls({ vehicle, busy, send }: { vehicle: VehicleExtras | null; busy: boolean; send: Props['send'] }) {
  const values = [
    { name: '天窗', value: vehicle?.sunroof_percent === undefined ? '—' : `${vehicle.sunroof_percent}%`, options: [['关闭', '关闭天窗'], ['开30%', '天窗开30%']] },
    { name: '前大灯', value: vehicle?.lights ? vehicle.lights.headlight ? '已开启' : '已关闭' : '—', options: [['开', '打开大灯'], ['关', '关闭大灯']] },
    { name: '氛围灯', value: vehicle?.lights ? vehicle.lights.ambient ? '已开启' : '已关闭' : '—', options: [['开', '打开氛围灯'], ['关', '关闭氛围灯']] },
    { name: '双闪', value: vehicle?.lights ? vehicle.lights.warning ? '已开启' : '已关闭' : '—', options: [['开', '打开双闪'], ['关', '关闭双闪']] },
    { name: '雨刷', value: vehicle?.wiper_level === undefined ? '—' : `${vehicle.wiper_level} 挡`, options: [['关闭', '雨刷调到0挡'], ['2挡', '雨刷调到2挡']] },
    { name: '副驾座椅加热', value: vehicle?.seats ? `${vehicle.seats.front_right?.heating ?? 0} 挡` : '—', options: [['关闭', '副驾座椅加热0挡'], ['2挡', '副驾座椅加热2挡']] },
    { name: '主驾座椅通风', value: vehicle?.seats ? `${vehicle.seats.front_left?.ventilation ?? 0} 挡` : '—', options: [['关闭', '主驾座椅通风0挡'], ['1挡', '主驾座椅通风1挡']] },
    { name: '副驾靠背', value: vehicle?.seats ? `${vehicle.seats.front_right?.recline ?? 90}°` : '—', options: [['90°', '副驾座椅靠背调到90度'], ['110°', '副驾座椅靠背调到110度']] },
  ]
  return <section className="workspace-controls"><div className="workspace-section-label"><h3>车内设备</h3><span>实时模拟车态</span></div><div className="workspace-control-grid">{values.map(item => <article key={item.name}><div><span>{item.name}</span><b>{item.value}</b></div><div>{item.options.map(([label, text]) => <button disabled={busy} key={text} onClick={() => send(text)} aria-label={text}>{label}</button>)}</div></article>)}</div><button className="workspace-scene" disabled={busy} onClick={() => send('开启舒适模式')}><div><b>一键舒适模式</b><small>恢复温度偏好、关闭车窗和天窗、开启氛围灯</small></div><span>↗</span></button></section>
}

export function VisionPanel({ media, workspace, sessionId, busy, onReply, error }: { media: Media; workspace: Workspace; sessionId: string; busy: boolean; onReply: (reply: unknown, prompt: string) => void; error: Props['error'] }) {
  const [documentId, setDocumentId] = useState(workspace.active_document_id || ''); const [image, setImage] = useState(''); const [question, setQuestion] = useState('请识别这张图片中的仪表提示，并结合车辆手册说明。'); const [sending, setSending] = useState(false); const [camera, setCamera] = useState(false)
  const video = useRef<HTMLVideoElement>(null); const stream = useRef<MediaStream | null>(null)
  const stopCamera = () => { stream.current?.getTracks().forEach(track => track.stop()); stream.current = null; setCamera(false) }
  useEffect(() => () => { stream.current?.getTracks().forEach(track => track.stop()) }, [])
  useEffect(() => { if (camera && video.current && stream.current) { video.current.srcObject = stream.current; void video.current.play().catch(() => error('摄像头预览未启动，请重新打开。')) } }, [camera])
  const capture = async () => { if (camera && video.current) { const canvas = document.createElement('canvas'); const ratio = Math.min(1, 1280 / video.current.videoWidth); canvas.width = video.current.videoWidth * ratio; canvas.height = video.current.videoHeight * ratio; canvas.getContext('2d')?.drawImage(video.current, 0, 0, canvas.width, canvas.height); setImage(canvas.toDataURL('image/jpeg', .85)); stopCamera(); return } try { stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false }); setCamera(true) } catch { error('摄像头不可用，请使用 localhost/HTTPS 并允许摄像头权限，或上传图片。') } }
  const upload = (file?: File) => { if (!file) return; if (!file.type.startsWith('image/')) { error('请选择图片文件。'); return } if (file.size > 8 * 1024 * 1024) { error('图片请小于8MB。'); return } const reader = new FileReader(); reader.onload = () => { const img = new Image(); img.onload = () => { const ratio = Math.min(1, 1600 / Math.max(img.width, img.height)); const canvas = document.createElement('canvas'); canvas.width = Math.round(img.width * ratio); canvas.height = Math.round(img.height * ratio); canvas.getContext('2d')?.drawImage(img, 0, 0, canvas.width, canvas.height); setImage(canvas.toDataURL('image/jpeg', .85)) }; img.onerror = () => error('图片无法解码，请尝试 JPG 或 PNG。'); img.src = String(reader.result) }; reader.readAsDataURL(file) }
  const analyze = async () => { setSending(true); try { const reply = await request('vision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, image, question, document_id: documentId || undefined }) }); onReply(reply, question) } catch (e) { error(e instanceof Error ? e.message : '图像识别失败') } finally { setSending(false) } }
  return <section className="workspace-feature"><div className="workspace-feature-heading"><div><small>SEE, THEN UNDERSTAND</small><h2>看见提示，找到依据。</h2></div><span className="workspace-pill">{media.vision?.available ? '视觉模型已接入' : '视觉服务待就绪'}</span></div><p className="workspace-intro">上传仪表照片、车辆提示或手册截图。仅发送你选择的图片，不持续录像。</p><div className="workspace-vision-preview">{camera ? <video ref={video} playsInline muted aria-label="摄像头预览" /> : image ? <img src={image} alt="待识别的车辆图片" /> : <div><span>▧</span><p>选择图片或拍摄一帧</p><small>JPG / PNG · 最大 8 MB</small></div>}</div><div className="workspace-vision-actions"><label className="workspace-file-button">上传图片<input type="file" accept="image/*" onChange={e => upload(e.target.files?.[0])} disabled={sending || busy} /></label><button onClick={() => void capture()} disabled={sending || busy}>{camera ? '拍摄这一帧' : '打开摄像头'}</button>{camera && <button onClick={stopCamera}>关闭摄像头</button>}{image && !camera && <button onClick={() => setImage('')}>移除</button>}</div><label className="workspace-document-select">结合车辆手册<select aria-label="视觉检索手册" value={documentId} onChange={e => setDocumentId(e.target.value)}><option value="">仅识别图片</option>{(workspace.documents || []).map(doc => <option key={doc.id} value={doc.id}>{doc.vehicle || doc.title || doc.filename}</option>)}</select></label><label className="workspace-vision-question">想了解什么<textarea value={question} onChange={e => setQuestion(e.target.value)} rows={2} /></label><button className="workspace-primary" disabled={!image || !question.trim() || busy || sending || !media.vision?.available} onClick={() => void analyze()}>{sending ? '正在识别与查证…' : '识别并查询知识'}</button>{media.vision?.reason && !media.vision.available && <p className="workspace-note">{media.vision.reason}</p>}<p className="workspace-note">图片识别可能有误；识别结果仅用于解释，不会自动执行车控。</p></section>
}

export function WorkspaceDeck({ children, media, onVision, ...props }: Props & { children: ReactNode; media: Media; onVision: (reply: unknown, prompt: string) => void }) {
  const [tab, setTab] = useState('vehicle')
  const tabs = [['vehicle', '车辆'], ['journey', '导航出行'], ['info', '信息服务'], ['memory', '记忆偏好'], ['vision', '视觉']]
  return <><div className="workspace-tabs" role="tablist" aria-label="座舱功能">{tabs.map(([key, label]) => <button id={`workspace-tab-${key}`} role="tab" aria-selected={tab === key} aria-controls={`workspace-panel-${key}`} key={key} onClick={() => setTab(key)}>{label}</button>)}</div><div id={`workspace-panel-${tab}`} role="tabpanel" aria-labelledby={`workspace-tab-${tab}`}>{tab === 'vehicle' ? children : tab === 'journey' ? <JourneyPanel {...props} /> : tab === 'info' ? <InfoPanel {...props} /> : tab === 'memory' ? <MemoryPanel {...props} /> : <VisionPanel media={media} workspace={props.workspace} sessionId={props.sessionId} busy={props.busy} onReply={onVision} error={props.error} />}</div></>
}

export function TaskPlan({ steps, tier }: { steps?: TaskStep[]; tier?: string }) {
  if (!steps?.length) return null
  return <div className="workspace-task-plan"><header><b>{tier === 'T2' ? '根据反馈调整计划' : steps.length > 1 ? '多步骤任务' : '本轮任务'}</b><span>{tier || 'EXECUTION'} · {steps.length} 步</span></header>{steps.map((step, i) => <div key={`${step.id}-${i}`} className="workspace-task-step"><span className={/fail|block|error|unsupported/.test(step.status) ? 'failed' : /running|pending/.test(step.status) ? 'pending' : ''}>{i + 1}</span><div><b>{step.tool}</b>{step.message && <p>{step.message}</p>}{!!step.depends_on?.length && <small>依赖：{step.depends_on.join('、')}</small>}</div><small>{step.status}</small></div>)}</div>
}

export function DocumentLibrary({ workspace, sessionId, update, error, send, busy }: Props) {
  const [file, setFile] = useState<File | null>(null); const [vehicle, setVehicle] = useState(''); const [uploading, setUploading] = useState(false); const [query, setQuery] = useState('')
  const docs: Document[] = workspace.documents || []
  const importPDF = async () => { if (!file) return; if (file.size > 30_000_000) { error('PDF 请小于30MB。'); return } setUploading(true); try { const form = new FormData(); form.append('file', file); form.append('vehicle', vehicle); form.append('session_id', sessionId); await request('documents/import', { method: 'POST', body: form }); update(await request<Workspace>(`workspace?session_id=${encodeURIComponent(sessionId)}`)); setFile(null) } catch (e) { error(e instanceof Error ? e.message : '手册导入失败') } finally { setUploading(false) } }
  return <section className="workspace-document-library"><div className="workspace-feature-heading"><div><small>YOUR MANUAL, YOUR EVIDENCE</small><h2>完整手册，逐页可查。</h2></div><span className="workspace-pill">本地索引</span></div><p className="workspace-intro">导入带文字层的车辆说明书 PDF，检索结果可跳转原始页面。不同车型分别标注，避免混用。</p><div className="workspace-document-list">{docs.map(doc => <article key={doc.id}><span className="workspace-pdf-mark">PDF</span><div><h3>{doc.title || doc.filename || '车辆手册'}</h3><p>{doc.vehicle || '车型未标注'} · {doc.pages || doc.page_count || '—'} 页</p></div><a href={sourceUrl(doc.file_url) || `/api/studio/documents/${encodeURIComponent(doc.id)}/file`} target="_blank" rel="noreferrer">查看原文 ↗</a></article>)}</div><form className="workspace-import-form" onSubmit={e => { e.preventDefault(); void importPDF() }}><label className="workspace-file-button">{file?.name || '选择 PDF'}<input type="file" accept="application/pdf,.pdf" onChange={e => setFile(e.target.files?.[0] || null)} disabled={uploading} /></label><input value={vehicle} onChange={e => setVehicle(e.target.value)} placeholder="车型 / 年款 / 市场（必填）" required aria-label="手册车型" /><button disabled={!file || !vehicle.trim() || uploading || busy}>{uploading ? '正在提取与索引…' : '导入手册'}</button></form><label className="workspace-document-select">本次提问使用的手册<select aria-label="本次提问手册" value={workspace.active_document_id || ''} disabled={busy} onChange={e => { if (e.target.value) void request<Workspace>('workspace', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, document_id: e.target.value }) }).then(update).catch(e => error(e instanceof Error ? e.message : '选择手册失败')) }}><option value="">请选择车型与手册</option>{docs.map(doc => <option key={doc.id} value={doc.id}>{doc.vehicle || doc.title || doc.filename}</option>)}</select></label><form className="workspace-search" onSubmit={e => { e.preventDefault(); if (query.trim()) send(`查询手册：${query}`) }}><input value={query} onChange={e => setQuery(e.target.value)} aria-label="查询完整手册" placeholder="向手册提问，例如：仪表胎压警告是什么意思？" /><button disabled={busy || !query.trim() || !workspace.active_document_id}>提问</button></form></section>
}
