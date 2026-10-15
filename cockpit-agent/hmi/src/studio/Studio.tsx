import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { DocumentLibrary, MoreControls, TaskPlan, WorkspaceDeck } from './WorkspacePanels'
import { sourceUrl, type Workspace, type Media, type VehicleExtras, type TaskStep, type Reminder } from './workspaceTypes'
import './studio.css'
import './workspace.css'

type Position = 'front_left' | 'front_right' | 'rear_left' | 'rear_right'
type Page = 'cockpit' | 'lab' | 'manual' | 'results'
type Mode = 'guarded' | 'baseline'
type Provider = 'offline' | 'kimi'
type Profile = 'standard' | 'premium'
type Fault = 'none' | 'wrong_target' | 'timeout_after_apply' | 'stale_state'
type Vehicle = VehicleExtras & {
  speed: number; gear: string; windows: Record<Position, number>; temperature: number
  doors: Record<Position, boolean>; trunk_open: boolean; massage: boolean
  profile: Profile; source: string; revision: number; navigation_destination?: string | null
}
type Evidence = { id: string; title: string; text: string; source_url?: string; url?: string; page?: string | number; warning?: boolean; conditions?: unknown }
type Trace = { stage: string; status: string; detail: unknown }
type Reply = {
  session_id: string; status: string; message: string; vehicle: Vehicle; trace: Trace[]
  calls: unknown[]; evidence: Evidence[]; elapsed_ms: number; plan: unknown
  pending?: { token: string }; source: string; model?: unknown
  workspace?: Workspace; steps?: TaskStep[]; orchestration?: { tier?: string; rounds?: number }
}
type Scenario = { id: string; title: string; text: string; category: string; setup?: Partial<Setup> }
type Setup = { profile: Profile; speed: number; gear: 'P' | 'D'; fault: Fault }
type Bootstrap = { vehicle: Vehicle; capabilities: unknown; model: { available: boolean; name: string }; scenarios: Scenario[]; benchmark?: Record<string, unknown>; workspace?: Workspace; media?: Media }
type Message = { id: number; role: 'user' | 'assistant'; text: string; reply?: Reply; before?: Vehicle | null }
type Recognition = { lang: string; interimResults: boolean; continuous: boolean; start: () => void; stop: () => void; abort?: () => void; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null; onerror: ((e: { error: string }) => void) | null; onend: (() => void) | null }

const positions: [Position, string][] = [['front_left', '主驾'], ['front_right', '副驾'], ['rear_left', '左后排'], ['rear_right', '右后排']]
const defaultSetup: Setup = { profile: 'standard', speed: 0, gear: 'P', fault: 'none' }
const domains = [
  { code: '01', title: '先理解，再行动', en: 'Ambiguity resolution', icon: 'message', text: '帮我打开一点', category: 'ambiguity', note: '检查对象与幅度；信息不足时发起澄清。' },
  { code: '02', title: '把动作做对', en: 'Reliable tool calling', icon: 'window', text: '副驾车窗开50%', category: 'tool', note: '从用户目标到工具参数，再到车辆状态逐项验证。' },
  { code: '03', title: '知道能力边界', en: 'Capability awareness', icon: 'layers', text: '打开按摩功能', category: 'capability', note: '没有真实能力，就不会给出虚假的成功承诺。' },
  { code: '04', title: '安全始终在前', en: 'Safety & policy', icon: 'shield', text: '打开副驾车门', category: 'safety', note: '行驶中开门被确定性规则拦截，确认不能绕过。' },
  { code: '05', title: '回答有据可查', en: 'Grounded retrieval', icon: 'book', text: '后向式儿童座椅如何安装在副驾驶？', category: 'rag', note: '回答带上适用条件、安全警告与手册出处。' },
]

function Icon({ name, size = 20, className = '' }: { name: string; size?: number; className?: string }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    lab: <><path d="M9 3h6M10 3v6L4 19c-.6 1 .1 2 1.3 2h13.4c1.2 0 1.9-1 1.3-2L14 9V3M8 14h8" /><path d="m10 17 .01 0M14 18h.01" /></>,
    book: <><path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Zm0 0v15M6 8h3M15 8h3M6 12h3M15 12h3" /></>,
    chart: <><path d="M4 3v17h17M8 16v-5M13 16V7M18 16V4" /></>,
    arrow: <><path d="M5 12h14m-6-6 6 6-6 6" /></>,
    chevron: <path d="m9 5 7 7-7 7" />,
    shield: <><path d="M12 3 3.5 6.5v5.2c0 4.3 3.6 7.6 8.5 9.3 4.9-1.7 8.5-5 8.5-9.3V6.5L12 3Z" /><path d="m8 12 2.5 2.5 5.5-6" /></>,
    window: <><rect x="3" y="5" width="18" height="14" rx="3" /><path d="M3 11h18M8 8h.01M11 8h.01" /></>,
    message: <><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5h-9l1.8-4.2A8.5 8.5 0 1 1 21 11.5Z" /><path d="M8 10h8M8 14h5" /></>,
    layers: <><path d="m12 3 10 5-10 5L2 8l10-5Zm-9 10 9 4 9-4M3 18l9 4 9-4" /></>,
    mic: <><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1" /></>,
    sound: <><path d="M11 4 6 8H3v8h3l5 4V4Zm4 4c2 2 2 6 0 8m3-11c4 4 4 10 0 14" /></>,
    reset: <><path d="M3 11a9 9 0 1 1 2.4 7M3 4v7h7" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    x: <path d="m6 6 12 12M18 6 6 18" />,
    bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7l1-7Z" />,
    thermostat: <><path d="M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0ZM12 9v8" /><path d="M18 5h3M18 9h3" /></>,
    car: <><path d="m5 6 2-3h10l2 3 2 5v8H3v-8l2-5ZM3 11h18M6 15h2m8 0h2M5 19v2m14-2v2" /></>,
    settings: <><path d="M3 6h18M3 12h18M3 18h18" /><circle cx="8" cy="6" r="2" /><circle cx="16" cy="12" r="2" /><circle cx="10" cy="18" r="2" /></>,
    link: <><path d="M14 3h7v7m0-7L11 13M10 5H4v15h15v-6" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v.1" /></>,
  }
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.info}</svg>
}

function Mark({ small = false }: { small?: boolean }) {
  return <svg width={small ? 24 : 38} height={small ? 24 : 38} viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M5 30V10h6l9 13 9-13h6v20h-6V20l-9 12-9-12v10H5Z" fill="currentColor" /><path d="M17 7h6" stroke="currentColor" strokeWidth="2" /></svg>
}

async function api<T>(endpoint: string, data?: unknown): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 95000)
  try {
    const response = await fetch(`/api/studio/${endpoint}`, {
      method: data ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' },
      body: data ? JSON.stringify(data) : undefined, signal: controller.signal,
    })
    const result = await response.json().catch(() => null)
    if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `请求未完成（HTTP ${response.status}），请检查本地服务。`)
    if (!result) throw new Error('服务未返回有效数据，请检查本地服务。')
    return result as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('请求超时，执行状态尚未确认。请检查服务与车辆状态后再操作。')
    throw error
  } finally { window.clearTimeout(timer) }
}

async function streamChat(data: unknown, progress: (step: Trace) => void): Promise<Reply> {
  const controller = new AbortController(); const timer = window.setTimeout(() => controller.abort(), 240000)
  try {
    const response = await fetch('/api/studio/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data), signal: controller.signal })
    if (!response.ok || !response.body) { const error = await response.json().catch(() => null); throw new Error(error?.detail || `请求失败（${response.status}）`) }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let result: Reply | null = null
    const consume = (block: string) => {
      const event = block.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim() || 'message'
      const raw = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
      if (!raw) return
      const payload = JSON.parse(raw)
      if (event === 'final' || payload.type === 'final') result = payload.reply || payload.data || payload
      else if (event === 'error') throw new Error(payload.detail || payload.message || '执行流中断，请核对状态后再操作。')
      else if (event === 'progress' || payload.stage) progress(payload)
    }
    while (true) { const { done, value } = await reader.read(); buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n'); let end; while ((end = buffer.indexOf('\n\n')) >= 0) { consume(buffer.slice(0, end)); buffer = buffer.slice(end + 2) } if (done) break }
    if (buffer.trim()) consume(buffer)
    if (!result) throw new Error('执行连接已结束，但未收到最终结果；请刷新车辆状态后再操作。')
    return result
  } catch (error) { if (error instanceof DOMException && error.name === 'AbortError') throw new Error('执行超时，请先刷新并核对状态。'); throw error }
  finally { window.clearTimeout(timer) }
}

function statusLabel(status: string) {
  const labels: Record<string, string> = { executed: '执行完成', partial: '部分完成', invalid: '参数无效', success: '执行完成', ok: '完成', clarified: '等待补充', clarify: '需要澄清', clarification: '需要澄清', needs_clarification: '需要澄清', blocked: '安全拦截', refused: '已拦截', unsupported: '能力不支持', unavailable: '能力不可用', needs_confirmation: '等待确认', need_confirm: '等待确认', confirmation_required: '等待确认', confirm: '等待确认', verified: '已验证', answered: '有据回答', answer: '有据回答', failed: '执行失败', error: '异常', cancelled: '已取消' }
  return labels[status] || status
}
function statusTone(status: string) {
  return /block|fail|error|reject|refus|invalid/.test(status) ? 'red' : /clar|confirm|unsupported|unavailable|warn|pending|partial/.test(status) ? 'amber' : 'green'
}
function stringify(value: unknown) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
const safeUrl = sourceUrl

function CarScene({ vehicle }: { vehicle: Vehicle | null }) {
  return <div className="meridian-car-scene">
    <div className="meridian-car-orbit orbit-one" /><div className="meridian-car-orbit orbit-two" />
    <div className="meridian-road-line line-left" /><div className="meridian-road-line line-right" />
    <svg className="meridian-car" viewBox="0 0 300 510" aria-label="车辆俯视图，车窗状态见四周标注" role="img">
      <defs>
        <linearGradient id="body-metal" x1="0" x2="1" y1="0" y2=".3"><stop stopColor="#8495a7" /><stop offset=".12" stopColor="#c5d0dc" /><stop offset=".35" stopColor="#eff3f8" /><stop offset=".52" stopColor="#dce4eb" /><stop offset=".85" stopColor="#a2b2c2" /><stop offset="1" stopColor="#677d92" /></linearGradient>
        <linearGradient id="glass" x1="0" y1="0" x2=".8" y2="1"><stop stopColor="#33475c" /><stop offset=".4" stopColor="#152a3d" /><stop offset="1" stopColor="#0b1828" /></linearGradient>
        <linearGradient id="hood" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#f0f4f8" /><stop offset="1" stopColor="#b4c4d3" /></linearGradient>
        <filter id="car-shadow" x="-60%" width="220%" y="-25%" height="150%"><feDropShadow dx="0" dy="15" stdDeviation="16" floodColor="#000" floodOpacity=".6" /></filter>
      </defs>
      <g filter="url(#car-shadow)">
        <rect x="47" y="107" width="22" height="77" rx="10" fill="#07101a" /><rect x="231" y="107" width="22" height="77" rx="10" fill="#07101a" />
        <rect x="47" y="339" width="22" height="76" rx="10" fill="#07101a" /><rect x="231" y="339" width="22" height="76" rx="10" fill="#07101a" />
        <path d="M150 23C111 23 82 32 69 58 59 86 58 151 61 197L59 363c0 58 7 87 28 110 13 13 114 13 127 0 20-23 27-52 27-110l-2-166c3-46 2-111-8-139-13-26-42-35-81-35Z" fill="url(#body-metal)" stroke="#e0e7ee" strokeWidth="1.5" />
        <path d="M82 67Q150 45 218 67l6 84Q150 134 76 151l6-84Z" fill="url(#hood)" stroke="#9aabba" />
        <path d="M87 65 97 141m116-76-10 76" stroke="#8c9dad" opacity=".7" />
        <path d="M74 158Q150 126 226 158l-22 67Q150 210 96 225l-22-67Z" fill="url(#glass)" stroke="#5d7285" strokeWidth="3" />
        <path d="M90 164q60-24 117 0" stroke="#7192aa" opacity=".6" />
        <path d="M97 236Q150 226 203 236l4 118Q150 367 93 354l4-118Z" fill="url(#glass)" stroke="#879aab" strokeWidth="2" />
        <path d="m112 240-5 109m83-109 5 109" stroke="#324b61" /><path d="M98 300h104" stroke="#4d657c" strokeWidth="2" />
        <path d="m92 369 116 0 14 61q-70 27-144 0l14-61Z" fill="url(#glass)" stroke="#708698" strokeWidth="2" />
        <path d="M87 440q62 17 126 0m-124 13q61 14 122 0" stroke="#8a9eaf" />
        <path d="M74 182 89 229l-4 67-13-6 2-108Zm-2 125 13 4-3 51-12 37 2-92Z" fill={vehicle?.windows?.front_left ? '#55d3c1' : '#294155'} opacity={vehicle?.windows?.front_left ? '.75' : '1'} />
        <path d="M226 182 211 229l4 67 13-6-2-108Zm2 125-13 4 3 51 12 37-2-92Z" fill="#294155" />
        <path d="M226 182 211 229l4 67 13-6-2-108Z" fill={vehicle?.windows?.front_right ? '#55d3c1' : '#294155'} opacity={vehicle?.windows?.front_right ? '.75' : '1'} />
        <path d="m72 307 13 4-3 51-12 37 2-92Z" fill={vehicle?.windows?.rear_left ? '#55d3c1' : '#294155'} opacity={vehicle?.windows?.rear_left ? '.75' : '1'} />
        <path d="m228 307-13 4 3 51 12 37-2-92Z" fill={vehicle?.windows?.rear_right ? '#55d3c1' : '#294155'} opacity={vehicle?.windows?.rear_right ? '.75' : '1'} />
        <path d="M64 191 39 204v13l23-7m176-19 23 13v13l-23-7" fill="url(#body-metal)" stroke="#a5b6c6" />
        <path d="m69 72 29-14M202 58l29 14" stroke="#d9f3ff" strokeWidth="5" strokeLinecap="round" />
        <path d="m77 452 26 7m94 0 26-7" stroke="#e8807f" strokeWidth="4" strokeLinecap="round" />
        <path d="M142 86h16m-8-8v16" stroke="#90a3b5" strokeWidth="2" /><path d="M126 39h48" stroke="#92a4b5" strokeWidth="2" />
      </g>
    </svg>
    {positions.map(([key, label], i) => <div className={`meridian-window-tag window-${i}`} key={key}>
      <span>{label}车窗</span><strong>{vehicle ? vehicle.windows?.[key] ?? '—' : '—'}<small>{vehicle ? '%' : ''}</small></strong>
      <div className="window-meter"><i style={{ width: `${vehicle?.windows?.[key] ?? 0}%` }} /></div>
    </div>)}
    <div className="meridian-car-caption"><span className="meridian-dot" />{vehicle ? '车辆状态实时映射' : '等待车辆状态'}<span>·</span>模拟车辆</div>
  </div>
}

function TracePanel({ reply, before, open = false }: { reply: Reply; before?: Vehicle | null; open?: boolean }) {
  const changes: { name: string; before: unknown; after: unknown }[] = []
  if (before && reply.vehicle) {
    positions.forEach(([key, label]) => {
      if (before.windows?.[key] !== reply.vehicle.windows?.[key]) changes.push({ name: `${label}车窗`, before: `${before.windows?.[key]}%`, after: `${reply.vehicle.windows?.[key]}%` })
      if (before.doors?.[key] !== reply.vehicle.doors?.[key]) changes.push({ name: `${label}车门`, before: before.doors?.[key] ? '开' : '关', after: reply.vehicle.doors?.[key] ? '开' : '关' })
    })
    for (const [key, label] of [['temperature', '空调温度'], ['trunk_open', '后备箱'], ['massage', '座椅按摩'], ['navigation_destination', '模拟导航目的地']] as const) {
      if (before[key] !== reply.vehicle[key]) changes.push({ name: label, before: before[key], after: reply.vehicle[key] })
    }
  }
  return <details className="meridian-trace" open={open || undefined}>
    <summary><span><Icon name="layers" size={15} />查看执行证据</span><span>{reply.trace?.length || 0} 个检查 <Icon name="chevron" size={13} /></span></summary>
    <div className="meridian-trace-content">
      <div className="trace-timeline">{reply.trace?.map((step, i) => <div key={`${step.stage}-${i}`} className="trace-step"><span className={`trace-node ${statusTone(step.status)}`} /><div><b>{step.stage}</b><span className="trace-step-status">{step.status}</span><p>{stringify(step.detail)}</p></div></div>)}</div>
      <h4>车辆状态变化 <span>SIMULATED</span></h4>
      {changes.length ? <div className="state-diff">{changes.map(change => <div key={change.name}><span>{change.name}</span><span>{String(change.before)} <Icon name="arrow" size={12} /> <b>{String(change.after)}</b></span></div>)}</div> : <p className="meridian-muted">{before ? '本轮未观测到车辆状态变化。' : '暂无本轮执行前快照。'}</p>}
      <details className="meridian-json"><summary>工具调用与原始计划</summary><pre>{stringify({ calls: reply.calls, plan: reply.plan, model: reply.model })}</pre></details>
    </div>
  </details>
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  return <div className="meridian-evidence">{evidence.map((item, i) => <details key={`${item.id}-${i}`}><summary><Icon name={item.warning ? 'shield' : 'book'} size={14} /><span>{item.title || item.id}{item.warning ? ' · 安全提示' : ''}</span><Icon name="chevron" size={12} /></summary><p>{item.text}</p>{!!item.conditions && <p className="workspace-evidence-scope">适用范围：{typeof item.conditions === 'string' ? item.conditions : stringify(item.conditions)}</p>}{safeUrl(item.url || item.source_url) && <a href={safeUrl(item.url || item.source_url)} target="_blank" rel="noreferrer">查看原始来源{item.page ? ` · 第 ${item.page} 页` : ''}<Icon name="link" size={12} /></a>}</details>)}</div>
}

type BenchmarkMetric = { total: number; passed: number }
type BenchmarkGroup = BenchmarkMetric & { provider: string; mode: string; model?: string; categories?: Record<string, BenchmarkMetric> }
const benchmarkCategories = [['ambiguity', '歧义澄清'], ['tool_calling', '可靠工具调用'], ['capability', '能力边界'], ['safety', '安全约束'], ['rag', '有据回答']] as const
const metricRate = (metric?: BenchmarkMetric) => metric && metric.total > 0 ? metric.passed / metric.total * 100 : null
const formatRate = (rate: number | null) => rate === null ? '—' : `${rate.toFixed(2)}%`
const deltaText = (before: number | null, after: number | null) => before === null || after === null ? '暂无对比' : `${after > before ? '提升' : after < before ? '下降' : '持平'} ${Math.abs(after - before).toFixed(2)} 个百分点`

function BenchmarkView({ report, refreshing, onRefresh }: { report: Record<string, unknown> | null; refreshing: boolean; onRefresh: () => void }) {
  const groups = Array.isArray(report?.groups) ? report.groups.filter((entry): entry is BenchmarkGroup => !!entry && typeof entry === 'object' && entry.provider === 'kimi' && Number.isFinite(entry.total) && entry.total > 0 && Number.isFinite(entry.passed)) : []
  const before = groups.find(group => group.mode === 'baseline')
  const after = groups.find(group => group.mode === 'guarded')
  const hasPair = report?.available !== false && report?.status !== 'not_run' && before && after
  const repeats = typeof report?.repeats === 'number' && report.repeats > 0 ? report.repeats : null
  const beforeRate = metricRate(before)
  const afterRate = metricRate(after)
  return <section className="meridian-results">
    <div className="meridian-section-header"><div><span className="meridian-eyebrow">BEFORE & AFTER</span><h2>方案前后，准确率对比。</h2><p>{hasPair ? `${String(report?.cases ?? '—')} 个用例${repeats ? ` · 每例重复 ${repeats} 次` : ''} · 同一批输入与初始车态` : '同一批输入与初始车态，比较采用方案前后的结果。'}</p></div><button className="meridian-button ghost" onClick={onRefresh} disabled={refreshing}><Icon name="reset" size={16} />刷新结果</button></div>
    {hasPair ? <>
      <div className="meridian-comparison-overview" aria-label="总准确率对比">
        <div className="meridian-comparison-score before"><span>方案前 <small>简化对照</small></span><strong>{formatRate(beforeRate)}</strong><p>{before.passed} / {before.total} 次通过</p></div>
        <div className="meridian-comparison-score after"><span>方案后 <small>可信执行</small></span><strong>{formatRate(afterRate)}</strong><p>{after.passed} / {after.total} 次通过</p></div>
        <div className={`meridian-comparison-change ${beforeRate !== null && afterRate !== null && afterRate < beforeRate ? 'decline' : ''}`}><span>总准确率变化</span><strong>{beforeRate !== null && afterRate !== null ? `${afterRate > beforeRate ? '+' : ''}${(afterRate - beforeRate).toFixed(2)}` : '—'}<small>个百分点</small></strong><p>{before.total === after.total ? `每组 ${before.total} 次评测` : `方案前 ${before.total} 次 · 方案后 ${after.total} 次`}</p></div>
      </div>
      <div className="meridian-report-card">
        <div className="meridian-comparison-heading"><h3>五类问题的准确率</h3><div className="meridian-comparison-legend"><span><i />方案前</span><span><i className="after" />方案后</span></div></div>
        <div className="meridian-comparison-categories">{benchmarkCategories.map(([key, label]) => {
          const initial = before.categories?.[key]
          const improved = after.categories?.[key]
          const initialRate = metricRate(initial)
          const improvedRate = metricRate(improved)
          const count = initial && improved && initial.total === improved.total ? initial.total : null
          return <div className="meridian-comparison-row" key={key}>
            <div className="meridian-comparison-label"><h4>{label}</h4><p>{count !== null ? `${repeats && Number.isInteger(count / repeats) ? `${count / repeats} 例 × ${repeats} 次 · ` : ''}每组 ${count} 次` : '样本数见评测说明'}</p></div>
            <div className="meridian-comparison-bars">{([[initial, initialRate, 'before', '方案前'], [improved, improvedRate, 'after', '方案后']] as const).map(([metric, rate, variant, name]) => <div className="meridian-comparison-bar-line" key={variant} aria-label={`${label}，${name}准确率 ${formatRate(rate)}，${metric ? `${metric.passed} / ${metric.total} 次通过` : '暂无结果'}`}><span>{name}</span><div className="meridian-comparison-track"><i className={variant} style={{ width: `${Math.min(100, Math.max(0, rate ?? 0))}%` }} /></div><b>{formatRate(rate)}</b></div>)}</div>
            <span className={`meridian-comparison-delta ${initialRate !== null && improvedRate !== null && improvedRate < initialRate ? 'decline' : ''}`}>{deltaText(initialRate, improvedRate)}</span>
          </div>
        })}</div>
      </div>
      <p className="meridian-comparison-footnote">准确率＝用例全部断言通过的比例。方案前为关闭新增机制的受控对照，不代表原项目完整成绩。</p>
      <details className="meridian-comparison-details"><summary>评测说明</summary><dl><div><dt>模型</dt><dd>{after.model || before.model || String(report?.model || 'Kimi')}</dd></div><div><dt>生成时间</dt><dd>{String(report?.generated_at || '—')}</dd></div>{typeof report?.run_seconds === 'number' && <div><dt>运行耗时</dt><dd>{report.run_seconds.toFixed(1)} 秒</dd></div>}</dl><p>两组复用相同模型候选计划与初始车态，分别运行；多轮计划使用可信分支的历史。测试集为开发可见的回归用例，结果限于模拟车辆环境，不代表实车表现。本报告评测基础可信机制；本轮扩展功能另行验收。</p></details>
    </> : <div className="meridian-empty-results"><div className="meridian-empty-icon"><Icon name="chart" size={34} /></div><h3>等待模型评测结果</h3><p>完成同一模型的方案前后评测后，刷新此页查看准确率。</p><code>python evaluate.py --provider kimi --repeats 3</code></div>}
  </section>
}

export default function Studio() {
  const [page, setPage] = useState<Page>('cockpit')
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [model, setModel] = useState<Bootstrap['model']>({ available: false, name: '' })
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [capabilities, setCapabilities] = useState<unknown>(null)
  const [mode, setMode] = useState<Mode>('guarded')
  const [provider, setProvider] = useState<Provider>('offline')
  const [setup, setSetup] = useState<Setup>(defaultSetup)
  const [showSetup, setShowSetup] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState<{ token: string } | null>(null)
  const [report, setReport] = useState<Record<string, unknown> | null>(null)
  const [manual, setManual] = useState<Evidence[]>([])
  const [manualQuery, setManualQuery] = useState('')
  const [manualLoaded, setManualLoaded] = useState(false)
  const [recording, setRecording] = useState(false)
  const [autoRead, setAutoRead] = useState(false)
  const [handsFree, setHandsFree] = useState(false)
  const [workspace, setWorkspace] = useState<Workspace>({})
  const [media, setMedia] = useState<Media>({})
  const [progress, setProgress] = useState<Trace[]>([])
  const [speaking, setSpeaking] = useState(false)
  const [dueReminders, setDueReminders] = useState<Reminder[]>([])
  const [sessionId] = useState(() => {
    try { let value = sessionStorage.getItem('meridian.session'); if (!value) { value = `studio-${crypto.randomUUID()}`; sessionStorage.setItem('meridian.session', value) }; return value } catch { return `studio-${Date.now()}` }
  })
  const lock = useRef(false)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<Recognition | null>(null)
  const handsFreeRef = useRef(false)
  const speakingRef = useRef(false)
  const voiceTimer = useRef<number | undefined>()
  const sendRef = useRef<(text: string) => void>(() => {})
  const startVoiceRef = useRef<() => void>(() => {})
  const initialProvider = useRef(false)
  const activeChannel = useRef<'lab' | 'workspace'>('workspace')
  const channelMessages = useRef<Record<string, Message[]>>({ workspace: [], lab: [] })
  const channelPending = useRef<Record<string, { token: string } | null>>({ workspace: null, lab: null })
  const nextId = useRef(1)
  const lastReply = [...messages].reverse().find(m => m.reply)
  const SpeechRecognitionClass = (window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }).SpeechRecognition || (window as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition

  async function refresh() {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      const data = await api<Bootstrap>(`bootstrap?session_id=${encodeURIComponent(sessionId)}`)
      setVehicle(data.vehicle); setModel(data.model); setScenarios(data.scenarios || []); setCapabilities(data.capabilities); setReport(data.benchmark || null); setConnected(true)
      setWorkspace(data.workspace || {}); setMedia(data.media || {}); if (!initialProvider.current) { setProvider(data.model.available ? 'kimi' : 'offline'); initialProvider.current = true }
      setSetup(s => ({ ...s, profile: data.vehicle.profile, speed: data.vehicle.speed, gear: data.vehicle.gear === 'D' ? 'D' : 'P' }))
    } catch (e) { setConnected(false); setError(e instanceof Error ? e.message : '无法连接本地演示服务。') }
    finally { lock.current = false; setBusy(false) }
  }

  useEffect(() => { void refresh(); return () => { handsFreeRef.current = false; window.clearTimeout(voiceTimer.current); recognitionRef.current?.stop(); window.speechSynthesis?.cancel() } }, [])
  useEffect(() => {
    const timer = window.setInterval(() => { if (!lock.current) void api<{ due: Reminder[]; workspace: Workspace }>(`reminders/due?session_id=${encodeURIComponent(sessionId)}`).then(data => { setWorkspace(data.workspace); if (data.due?.length) setDueReminders(items => [...items, ...data.due]) }).catch(() => {}) }, 15000)
    return () => window.clearInterval(timer)
  }, [sessionId])
  useEffect(() => {
    const nextChannel = page === 'lab' ? 'lab' : 'workspace'
    if (activeChannel.current === nextChannel) return
    channelMessages.current[activeChannel.current] = messages; channelPending.current[activeChannel.current] = pending
    activeChannel.current = nextChannel; setMessages(channelMessages.current[nextChannel] || []); setPending(channelPending.current[nextChannel]); setProgress([])
    void api<Bootstrap>(`bootstrap?session_id=${encodeURIComponent(sessionId)}&channel=${nextChannel}`).then(data => { setVehicle(data.vehicle); setCapabilities(data.capabilities); if (data.workspace) setWorkspace(data.workspace) }).catch(() => {})
  }, [page])
  useEffect(() => { messagesEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [messages, busy, pending])
  useEffect(() => {
    if (page === 'manual' && !manualLoaded) {
      void api<{ chunks: Evidence[] }>('manual').then(data => { setManual(data.chunks || []); setManualLoaded(true) }).catch(e => setError(e instanceof Error ? e.message : '手册加载失败。'))
    }
  }, [page, manualLoaded])

  function resumeVoice() {
    window.clearTimeout(voiceTimer.current)
    if (handsFreeRef.current) voiceTimer.current = window.setTimeout(() => { if (!lock.current && !speakingRef.current) startVoiceRef.current() }, 450)
  }
  function stopSpeaking() { speakingRef.current = false; setSpeaking(false); window.speechSynthesis?.cancel() }
  function speak(text: string) {
    if (!window.speechSynthesis) { setError('当前浏览器不支持语音播报，请阅读文字回复。'); return }
    recognitionRef.current?.stop(); window.speechSynthesis.cancel(); speakingRef.current = true; setSpeaking(true)
    const utterance = new SpeechSynthesisUtterance(text); utterance.lang = 'zh-CN'; utterance.rate = 1.04
    utterance.onend = () => { speakingRef.current = false; setSpeaking(false); resumeVoice() }
    utterance.onerror = () => { speakingRef.current = false; setSpeaking(false) }
    window.speechSynthesis.speak(utterance)
  }
  function receive(reply: Reply, before: Vehicle | null) {
    if (reply.vehicle) setVehicle(reply.vehicle); setPending(reply.pending?.token ? reply.pending : null); if (reply.workspace) setWorkspace(reply.workspace)
    setMessages(ms => [...ms, { id: nextId.current++, role: 'assistant', text: reply.message, reply, before }])
    if (autoRead || handsFreeRef.current) speak(reply.message)
  }
  async function send(text: string, scenario?: Scenario) {
    if (!text.trim() || lock.current || !connected) return
    lock.current = true; setBusy(true); setError(''); setInput(''); setProgress([]); recognitionRef.current?.stop(); stopSpeaking()
    let before = vehicle
    try {
      if (scenario) {
        const sceneSetup = { ...defaultSetup, ...scenario.setup }
        const reset = await api<{ vehicle: Vehicle; capabilities?: unknown }>('reset', { session_id: sessionId, ...sceneSetup })
        before = reset.vehicle; setVehicle(reset.vehicle); if (reset.capabilities) setCapabilities(reset.capabilities); setSetup(sceneSetup); setMessages([]); setPending(null)
      }
      setMessages(ms => [...ms, { id: nextId.current++, role: 'user', text }])
      const payload = { session_id: sessionId, text, mode: scenario || page === 'lab' ? mode : 'guarded', provider, channel: scenario || page === 'lab' ? 'lab' : 'workspace' }
      const reply = payload.channel === 'lab' ? await api<Reply>('chat', payload) : await streamChat(payload, step => setProgress(items => [...items, step]))
      receive(reply, before)
    } catch (e) { setError(e instanceof Error ? e.message : '请求失败，请检查服务。') }
    finally { lock.current = false; setBusy(false); inputRef.current?.focus(); resumeVoice() }
  }
  async function confirm(approve: boolean) {
    if (!pending || lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      const reply = await api<Reply>('confirm', { session_id: sessionId, token: pending.token, approve, mode, provider, channel: page === 'lab' ? 'lab' : 'workspace' }); receive(reply, vehicle)
    } catch (e) { setError(e instanceof Error ? e.message : '确认请求失败。') }
    finally { lock.current = false; setBusy(false); resumeVoice() }
  }
  async function reset(next = setup) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      const data = await api<{ vehicle: Vehicle; capabilities?: unknown; workspace?: Workspace }>('reset', { session_id: sessionId, ...next })
      setVehicle(data.vehicle); if (data.capabilities) setCapabilities(data.capabilities); if (data.workspace) setWorkspace(data.workspace); setSetup(next); setMessages([]); setPending(null); channelMessages.current = { workspace: [], lab: [] }; channelPending.current = { workspace: null, lab: null }; setInput(''); setShowSetup(false); stopSpeaking()
    } catch (e) { setError(e instanceof Error ? e.message : '重置失败。') }
    finally { lock.current = false; setBusy(false) }
  }
  function demo(index: number) {
    const domain = domains[index]
    const scene = scenarios.find(s => s.category === domain.category || s.id === domain.category || s.category.includes(domain.category))
    const fallback: Scenario = { id: domain.category, title: domain.title, text: domain.text, category: domain.category, setup: index === 3 ? { speed: 100, gear: 'D' } : defaultSetup }
    void send(scene?.text || domain.text, scene || fallback)
  }
  function startRecording() {
    if (recognitionRef.current || lock.current || pending) return
    if (!SpeechRecognitionClass) { setError('当前浏览器不支持语音识别，请使用文字输入。'); return }
    if (!window.isSecureContext) { setError('麦克风需要安全连接，请通过 localhost 或 HTTPS 打开页面。'); return }
    stopSpeaking()
    const recognition = new SpeechRecognitionClass(); recognitionRef.current = recognition
    recognition.lang = 'zh-CN'; recognition.interimResults = true; recognition.continuous = false
    let submitted = false
    recognition.onresult = event => {
      const parts = Array.from(event.results); const text = parts.map(result => result[0]?.transcript || '').join(''); setInput(text)
      if (!submitted && parts.some(result => result.isFinal) && text.trim()) {
        submitted = true; recognition.stop()
        if (/^(停止聆听|退出语音|结束对话|退下吧)[。！!]?$/u.test(text.trim())) { handsFreeRef.current = false; setHandsFree(false); setInput(''); return }
        sendRef.current(text)
      }
    }
    recognition.onerror = event => {
      if (event.error === 'aborted') return
      if (event.error !== 'no-speech') { handsFreeRef.current = false; setHandsFree(false); setError(`语音识别未完成（${event.error}）。请确认麦克风权限及浏览器语音服务连接，可继续文字输入。`) }
      setRecording(false)
    }
    recognition.onend = () => { recognitionRef.current = null; setRecording(false); if (!submitted) resumeVoice() }
    try { recognition.start(); setRecording(true) } catch { recognitionRef.current = null; handsFreeRef.current = false; setHandsFree(false); setError('无法启动麦克风，请检查浏览器权限与 localhost/HTTPS 连接。') }
  }
  function toggleRecording() { if (recording) { handsFreeRef.current = false; setHandsFree(false); recognitionRef.current?.stop() } else startRecording() }
  function toggleHandsFree() { const next = !handsFree; handsFreeRef.current = next; setHandsFree(next); if (next) startRecording(); else { window.clearTimeout(voiceTimer.current); recognitionRef.current?.stop(); stopSpeaking() } }
  sendRef.current = text => { void send(text) }; startVoiceRef.current = startRecording
  const submit = (event: FormEvent) => { event.preventDefault(); void send(input) }
  const nav: { id: Page; icon: string; label: string; en: string }[] = [
    { id: 'cockpit', icon: 'grid', label: '我的座舱', en: 'COCKPIT' }, { id: 'lab', icon: 'lab', label: '可信实验室', en: 'TRUST LAB' },
    { id: 'manual', icon: 'book', label: '车辆知识', en: 'KNOWLEDGE' }, { id: 'results', icon: 'chart', label: '评测报告', en: 'BENCHMARK' },
  ]

  return <div className="meridian-app">
    <aside className="meridian-sidebar">
      <a className="meridian-brand" href="#" aria-label="经纬可信座舱首页" onClick={e => { e.preventDefault(); setPage('cockpit') }}><Mark /><span>MERIDIAN<span>COCKPIT LAB</span></span></a>
      <div className="meridian-sidebar-label">WORKSPACE <span>01</span></div>
      <nav aria-label="主导航">{nav.map(item => <button key={item.id} className={page === item.id ? 'active' : ''} disabled={busy} onClick={() => setPage(item.id)} aria-current={page === item.id ? 'page' : undefined}><Icon name={item.icon} size={21} /><span>{item.label}<small>{item.en}</small></span>{page === item.id && <i />}</button>)}</nav>
      <div className="meridian-sidebar-bottom"><div className="meridian-sidebar-art"><div className="art-circle" /><div className="art-circle second" /><Mark /></div><p>每一个动作，<br />都值得被信任。</p><div className="meridian-project-tag"><span className="meridian-dot" />独立研究与演示项目</div><a href="?upstream=1" className="meridian-upstream">开源底座入口 <Icon name="link" size={13} /></a></div>
    </aside>
    <main className="meridian-main">
      <header className="meridian-topbar"><div className="meridian-breadcrumb">MERIDIAN <span>/</span> <b>{nav.find(n => n.id === page)?.label}</b></div><div className="meridian-topbar-right"><span className={`meridian-connect ${connected ? '' : 'offline'}`}><i />{connected ? '模拟环境已连接' : busy ? '正在连接' : '服务未连接'}</span><span className="meridian-version">WORKSPACE · V2.0</span><button className="meridian-avatar" title="独立面试展示项目，无企业官方关联" aria-label="独立演示项目">M</button></div></header>
      <div className="meridian-content">
        <div className="meridian-heading"><div><div className="meridian-eyebrow">INTELLIGENCE, WITH CERTAINTY.</div><h1>{page === 'cockpit' ? <>经纬<span> · </span>可信座舱</> : page === 'lab' ? '把信任，变成可验证的过程。' : page === 'manual' ? '车辆知识，每一句都有出处。' : '可信能力，经过实测。'}</h1><p>{page === 'cockpit' ? '理解你的意图，认真对待每一次出发。' : page === 'lab' ? '五类真实问题，一条有边界、有证据的执行链。' : page === 'manual' ? '依据当前演示手册回答；完整条件与安全提示同样重要。' : '记录正确，也记录失败。对照实验帮助我们看清改进。'}</p></div><div className="meridian-heading-actions"><button className="meridian-button ghost" onClick={() => setShowSetup(!showSetup)} aria-expanded={showSetup}><Icon name="settings" size={17} />模拟环境</button><button className="meridian-icon-button" onClick={() => connected ? void reset() : void refresh()} disabled={busy} title={connected ? '重置车辆与对话' : '重新连接'} aria-label={connected ? '重置车辆与对话' : '重新连接'}><Icon name="reset" size={18} /></button></div></div>
        {dueReminders.length > 0 && <div className="workspace-reminder-toast" role="status"><span>⏱</span><div><b>提醒时间到了</b>{dueReminders.map(item => <p key={item.id}>{item.message || item.text || item.title}</p>)}</div><button onClick={() => setDueReminders([])}>知道了</button></div>}{error && <div className="meridian-error" role="alert"><Icon name="info" size={18} /><span>{error}</span><button onClick={() => setError('')} aria-label="关闭提示"><Icon name="x" size={17} /></button></div>}
        {showSetup && <form className="meridian-setup" onSubmit={e => { e.preventDefault(); void reset(setup) }}><div><b>模拟环境设置</b><small>应用后会重置本次对话与车辆状态。</small></div><label>车辆配置<select value={setup.profile} onChange={e => setSetup(s => ({ ...s, profile: e.target.value as Profile }))}><option value="standard">Standard · 无按摩</option><option value="premium">Premium · 带按摩</option></select></label><label>车速 / km/h<input aria-label="模拟车速" type="number" min="0" max="160" value={setup.speed} onChange={e => setSetup(s => ({ ...s, speed: Math.min(160, Math.max(0, Number(e.target.value))) }))} /></label><label>挡位<select value={setup.gear} onChange={e => setSetup(s => ({ ...s, gear: e.target.value as 'P' | 'D' }))}><option value="P">P · 驻车</option><option value="D">D · 行驶</option></select></label><label>故障注入<select value={setup.fault} onChange={e => setSetup(s => ({ ...s, fault: e.target.value as Fault }))}><option value="none">无故障</option><option value="wrong_target">动作发给错误车窗</option><option value="timeout_after_apply">执行后响应超时</option><option value="stale_state">过期车态</option></select></label><button type="submit" className="meridian-button primary" disabled={busy || !connected}>应用设置</button></form>}
        {(page === 'cockpit' || page === 'lab') && <>
          <div className="meridian-control-bar"><div className="meridian-control-left"><span className="meridian-control-caption"><Icon name="shield" size={17} />执行策略</span>{page === 'lab' ? <div className="meridian-segment"><button disabled={busy || !!pending} className={mode === 'guarded' ? 'selected' : ''} onClick={() => setMode('guarded')}>可信执行</button><button disabled={busy || !!pending} className={mode === 'baseline' ? 'selected' : ''} onClick={() => setMode('baseline')}>简化对照</button></div> : <span className="workspace-pill">可信执行已启用</span>}{page === 'lab' && mode === 'baseline' && <span className="meridian-baseline-note">仅用于模拟对照</span>}</div><label className="meridian-provider"><span className={`meridian-dot ${provider === 'kimi' ? 'blue' : ''}`} /><select aria-label="推理提供方" value={provider} disabled={busy || !!pending} onChange={e => setProvider(e.target.value as Provider)}><option value="offline">离线规则 · 可复现</option><option value="kimi" disabled={!model.available}>Kimi · {model.available ? '在线模型' : '暂未配置'}</option></select></label></div>
          <div className={`meridian-workspace ${page === 'lab' ? 'laboratory' : ''}`}>
            <div className="meridian-visual-column">
              {page === 'cockpit' ? <WorkspaceDeck workspace={workspace} media={media} sessionId={sessionId} busy={busy || !connected || !!pending} send={text => void send(text)} update={setWorkspace} error={setError} onVision={(data, prompt) => { setMessages(ms => [...ms, { id: nextId.current++, role: 'user', text: `图片识别：${prompt}` }]); receive(data as Reply, vehicle) }}>
                <section className="meridian-vehicle-panel"><div className="meridian-vehicle-header"><div><span className="meridian-eyebrow">YOUR SPACE, IN SYNC</span><h2>舒适，由你定义。</h2></div><span className="meridian-model-badge">{vehicle?.profile === 'premium' ? 'PREMIUM' : 'STANDARD'} <Icon name="car" size={15} /></span></div><div className="meridian-driving-status"><div><strong>{vehicle?.speed ?? '—'}</strong><span>km/h</span></div><span className="meridian-gear">{vehicle?.gear ?? '—'}</span><span>{vehicle ? vehicle.speed === 0 ? '车辆静止' : '模拟行驶中' : '等待连接'}</span></div><CarScene vehicle={vehicle} /><div className="meridian-vehicle-bottom"><div><Icon name="shield" size={16} /><span>确定性安全规则已启用</span></div><span>REV {vehicle?.revision ?? '—'}</span></div></section>
                <div className="meridian-comfort-grid"><section className="meridian-comfort-card"><div className="meridian-comfort-top"><Icon name="thermostat" size={21} /><span>座舱温度</span><span className="meridian-comfort-unit">CLIMATE</span></div><div className="meridian-temperature"><strong>{vehicle?.temperature ?? '—'}<span>°C</span></strong><div className="meridian-adjust"><button disabled={busy || !connected || !vehicle || !!pending} onClick={() => void send(`空调温度设为${Math.max(16, (vehicle?.temperature || 22) - 1)}度`)} aria-label="降低空调温度">−</button><button disabled={busy || !connected || !vehicle || !!pending} onClick={() => void send(`空调温度设为${Math.min(30, (vehicle?.temperature || 22) + 1)}度`)} aria-label="升高空调温度">+</button></div></div><p>通过可信执行调节</p></section><section className="meridian-comfort-card journey"><div className="meridian-comfort-top"><Icon name="car" size={21} /><span>我的行程</span><span className="meridian-comfort-unit">JOURNEY</span></div><div className="meridian-route"><i /><span className="route-dash" /><i /><span className="route-dash" /><i /></div><h3 title={vehicle?.navigation_destination || undefined}>{vehicle?.navigation_destination || '下一程，从容出发'}</h3><p>{workspace.last_route || workspace.route ? '路线已规划 · 导航出行查看地图' : '切换导航出行，搜索目的地'}</p></section></div>
              <MoreControls vehicle={vehicle} busy={busy || !connected || !!pending} send={text => void send(text)} /></WorkspaceDeck> : <section className="meridian-lab-stage"><div className="meridian-panel-title"><div><span className="meridian-eyebrow">FIVE QUESTIONS. ONE TRUST CHAIN.</span><h2>从一个问题开始。</h2></div><span className="meridian-counter">05</span></div><div className="meridian-domain-list">{domains.map((domain, i) => <button key={domain.code} className="meridian-domain-card" disabled={busy || !connected} onClick={() => demo(i)}><span className="meridian-domain-number">{domain.code}</span><div className="meridian-domain-icon"><Icon name={domain.icon} size={22} /></div><div><h3>{domain.title}<small>{domain.en}</small></h3><p>{domain.note}</p><span className="meridian-example">“{domain.text}”</span></div><Icon name="arrow" size={19} /></button>)}</div><div className="meridian-lab-state"><span><i className="meridian-dot" />当前模拟车态</span><b>{vehicle?.profile || '—'} <em>·</em> {vehicle?.speed ?? '—'} km/h <em>·</em> {vehicle?.gear ?? '—'}</b><button onClick={() => setShowSetup(true)}>调整环境 <Icon name="settings" size={14} /></button></div><p className="meridian-lab-caption">点击场景会加载其初始车态并开启新对话；“安全”场景自动切换至 100 km/h。</p></section>}
            </div>
            <section className="meridian-assistant"><div className="meridian-assistant-header"><div className="meridian-assistant-mark"><Mark small /></div><div><h2>经纬助手 <span>AI</span></h2><p><i className="meridian-dot" />{busy ? '正在理解与校验' : provider === 'kimi' ? model.name || 'Kimi 在线模型' : '离线规则引擎 · 演示模式'}</p></div><button className={`meridian-icon-button ${autoRead ? 'enabled' : ''}`} onClick={() => { setAutoRead(!autoRead); if (autoRead) window.speechSynthesis?.cancel() }} aria-label={autoRead ? '关闭自动朗读' : '开启自动朗读'} title={autoRead ? '关闭自动朗读' : '开启自动朗读'}><Icon name="sound" size={18} /></button></div>
              <div className="meridian-messages" aria-live="polite" aria-relevant="additions text">
                {!messages.length && <div className="meridian-welcome"><div className="meridian-welcome-symbol"><div /><Mark /></div><span className="meridian-eyebrow">READY WHEN YOU ARE</span><h3>你好，我是经纬。</h3><p>出行、天气、记忆与车内设备，<br />把你的下一步，交给我来安排。</p><div className="meridian-welcome-prompts"><button disabled={busy || !connected} onClick={() => void send(page === 'lab' ? '副驾车窗开50%' : '查询杭州天气，然后把空调设为22度')}><Icon name="window" size={16} />{page === 'lab' ? '把副驾车窗打开一半' : '查杭州天气，再把空调设为22度'}<Icon name="arrow" size={14} /></button><button disabled={busy || !connected} onClick={() => void send(page === 'lab' ? '空调温度设为23度' : '搜索杭州东站')}><Icon name="car" size={16} />{page === 'lab' ? '把车内温度调到23°C' : '找个目的地，开始规划行程'}<Icon name="arrow" size={14} /></button><button disabled={busy || !connected} onClick={() => void send('后向式儿童座椅如何安装在副驾驶？')}><Icon name="book" size={16} />了解儿童座椅安装要求<Icon name="arrow" size={14} /></button></div></div>}
                {messages.map(message => <article className={`meridian-message ${message.role}`} key={message.id}><div className="meridian-message-label">{message.role === 'user' ? '你' : <><Mark small />经纬助手</>}{message.reply && <span className={`meridian-result-badge ${statusTone(message.reply.status)}`}>{statusLabel(message.reply.status)}</span>}</div><div className="meridian-message-text">{message.text}</div>{message.reply && <><TaskPlan steps={message.reply.steps} tier={message.reply.orchestration?.tier} />{message.reply.evidence?.length > 0 && <EvidenceList evidence={message.reply.evidence} />}<div className="meridian-reply-footer"><span>{(message.reply.elapsed_ms / 1000).toFixed(2)}s <span>·</span> {message.reply.source || '工作台'}</span><button onClick={() => speak(message.text)} aria-label="朗读这条回复"><Icon name="sound" size={14} /></button></div><TracePanel reply={message.reply} before={message.before} /></>}</article>)}
                {busy && progress.length > 0 && <div className="workspace-live-progress" aria-label="任务执行进度">{progress.slice(-5).map((step, i) => <div key={i}><i /><b>{step.stage}</b><span>{typeof step.detail === 'string' ? step.detail : step.status}</span></div>)}</div>}{busy && <div className="meridian-thinking"><i /><i /><i /><span>{messages.length ? '理解意图，检查执行条件…' : '正在连接模拟环境…'}</span></div>}
                <div ref={messagesEnd} />
              </div>
              {pending && <div className="meridian-confirm"><div><Icon name="shield" size={18} /><b>此操作需要你的确认</b></div><p>执行前将再次检查车辆状态与安全条件。</p><div className="meridian-confirm-buttons"><button disabled={busy} onClick={() => void confirm(false)}>取消操作</button><button disabled={busy} onClick={() => void confirm(true)}>确认执行 <Icon name="check" size={15} /></button></div></div>}
              <div className="workspace-voice-bar"><button type="button" aria-pressed={handsFree} disabled={!SpeechRecognitionClass || !window.isSecureContext || !!pending} onClick={toggleHandsFree}>{handsFree ? '● 持续对话中' : '开启连续语音'}</button>{speaking && <button type="button" disabled={busy || !!pending} onClick={startRecording}>打断并说话</button>}<span>{recording ? '正在聆听' : speaking ? '正在播报' : !window.isSecureContext ? '麦克风需 localhost / HTTPS' : !SpeechRecognitionClass ? '此浏览器不支持语音识别' : handsFree ? '等待下一轮' : '浏览器识别 · 自动发送'}</span></div><form className="meridian-composer" onSubmit={submit}><div className="meridian-composer-field"><textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)} placeholder={pending ? '请先确认或取消上方操作' : recording ? '正在聆听，识别完成后自动发送…' : '说说你的想法…'} aria-label="给经纬助手发送指令" rows={2} disabled={busy || !!pending} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(input) } }} /><div><button type="button" className={`meridian-mic ${recording ? 'recording' : ''}`} onClick={toggleRecording} disabled={busy || !!pending || !SpeechRecognitionClass || !window.isSecureContext} title={SpeechRecognitionClass ? '点击开始语音输入，识别完成自动发送；可能使用浏览器厂商语音服务' : '此浏览器不支持语音识别，请使用 Chrome 或 Edge 的 localhost/HTTPS 页面'} aria-label={recording ? '停止语音识别' : '开始语音识别'}><Icon name="mic" size={19} /></button><button type="submit" className="meridian-send" disabled={!input.trim() || busy || !connected || !!pending} aria-label="发送指令"><Icon name="arrow" size={19} /></button></div></div><p><span className="meridian-dot" />{pending ? '确认与本次操作绑定' : mode === 'guarded' ? '信息不足时先澄清，高风险动作先确认' : '简化策略仅用于对照，所有动作均为模拟'}</p></form>
            </section>
          </div>
          {page === 'cockpit' && <section className="meridian-quick-lab"><div><span className="meridian-eyebrow">BUILT ON TRUST</span><h3>五个问题，认识可信座舱。</h3></div><div>{domains.map((domain, i) => <button disabled={busy || !connected} key={domain.code} onClick={() => { setPage('lab') }} title={domain.note}><Icon name={domain.icon} size={17} /><span>{['歧义澄清', '准确执行', '能力边界', '安全拦截', '有据回答'][i]}</span><Icon name="arrow" size={13} /></button>)}</div></section>}
          {page === 'lab' && <div className="meridian-lab-evidence"><div className="meridian-panel-title"><h3>执行观察台</h3><span>按需展开，查看确定性检查与真实返回</span></div>{lastReply?.reply ? <TracePanel reply={lastReply.reply} before={lastReply.before} open /> : <p className="meridian-muted">运行一个场景后，这里将显示工具参数、检查节点和执行前后的车辆状态。</p>}<details className="meridian-json"><summary>当前车辆能力注册表</summary><pre>{stringify(capabilities)}</pre></details></div>}
        </>}
        {page === 'manual' && <section className="meridian-manual"><DocumentLibrary workspace={workspace} sessionId={sessionId} busy={busy || !connected} send={text => { setPage('cockpit'); void send(text) }} update={setWorkspace} error={setError} /><div className="meridian-manual-banner"><div className="meridian-manual-graphic"><Icon name="book" size={60} /><span>OWNER’S MANUAL</span></div><div><span className="meridian-eyebrow">KNOWLEDGE WITH CONTEXT</span><h2>不止找到答案，<br />也找到答案适用的条件。</h2><p>手册片段用于检索与演示。车型、座位位置和座椅朝向不同，<br />安全要求也可能不同，请结合对应车辆的完整说明书。</p></div><span className="meridian-manual-count">{manual.length}<small>已索引片段</small></span></div><div className="meridian-manual-toolbar"><h3>手册证据库</h3><input type="search" value={manualQuery} onChange={e => setManualQuery(e.target.value)} placeholder="搜索手册内容，例如：安全气囊" aria-label="搜索手册证据" /></div><div className="meridian-manual-grid">{manual.filter(item => `${item.title} ${item.text}`.toLowerCase().includes(manualQuery.toLowerCase())).map((item, i) => <article key={`${item.id}-${i}`} className="meridian-manual-card"><div><span className={`meridian-manual-tag ${item.warning ? 'warning' : ''}`}><Icon name={item.warning ? 'shield' : 'book'} size={14} />{item.warning ? '安全提示' : '手册证据'}</span><span className="meridian-manual-id">{item.id}</span></div><h3>{item.title}</h3><p>{item.text}</p>{!!item.conditions && <div className="meridian-conditions"><b>适用条件</b>{stringify(item.conditions)}</div>}{safeUrl(item.source_url) && <a href={safeUrl(item.source_url)} target="_blank" rel="noreferrer">原始手册{item.page ? ` · 第 ${item.page} 页` : ''}<Icon name="link" size={14} /></a>}</article>)}</div>{!manualLoaded && <p className="meridian-muted">正在读取手册片段…</p>}{manualLoaded && !manual.filter(item => `${item.title} ${item.text}`.toLowerCase().includes(manualQuery.toLowerCase())).length && <p className="meridian-no-match">没有匹配片段。试试“儿童座椅”“车窗”或“气囊”。</p>}</section>}
        {page === 'results' && <BenchmarkView report={report} refreshing={busy} onRefresh={() => { setBusy(true); void api<Record<string, unknown>>('benchmark').then(setReport).catch(e => setError(e instanceof Error ? e.message : '报告加载失败。')).finally(() => setBusy(false)) }} />}
        <footer className="meridian-footer"><span>MERIDIAN COCKPIT LAB <i>·</i> 可信车载 Agent 研究演示</span><span>模拟车辆 <i>/</i> 独立项目，非企业官方产品 <i>/</i> 基于 cockpit-agent 开源底座</span></footer>
      </div>
    </main>
  </div>
}
