export type Place = { id?: string; name: string; lat: number; lon: number; address?: string; source_url?: string; data_mode?: string; fetched_at?: string; snapshot_fetched_at?: string }
export type Route = { geometry?: { coordinates: number[][] }; distance_m?: number; duration_s?: number; destination?: Place | string; origin?: Place; waypoints?: Place[]; source?: string; source_url?: string; message?: string }
export type Preference = { key: string; value: unknown; updated_at?: string }
export type Reminder = { id: string; text?: string; message?: string; title?: string; due_at?: string; status?: string }
export type Document = { id: string; title?: string; filename?: string; vehicle?: string; pages?: number; page_count?: number; chunks?: number; source_url?: string; file_url?: string; created_at?: string }
export type Workspace = { location?: Place; candidates?: Place[]; places?: Place[]; route?: Route | null; last_route?: Route | null; preferences?: Preference[] | Record<string, unknown>; reminders?: Reminder[]; documents?: Document[]; active_document_id?: string; providers?: Record<string, unknown>; info?: Record<string, unknown>; [key: string]: unknown }
export type Media = { vision?: { available?: boolean; model?: string; reason?: string }; asr?: { available?: boolean; model?: string; reason?: string }; tts?: { available?: boolean; model?: string; reason?: string }; [key: string]: unknown }
export type VehicleExtras = { sunroof_percent?: number; lights?: { headlight: boolean; ambient: boolean; warning: boolean }; wiper_level?: number; seats?: Record<string, { heating: number; ventilation: number; recline: number }> }
export type TaskStep = { id: string; tool: string; args?: unknown; depends_on?: string[]; status: string; message?: string; result?: unknown; [key: string]: unknown }

export function sourceUrl(url?: string) { return url && (/^https?:\/\//.test(url) || /^\/api\/studio\/documents\//.test(url)) ? url : undefined }
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/studio/${path}`, init)
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `请求失败（${response.status}）`)
  if (init.method && init.method !== 'GET' && ['invalid', 'unavailable', 'error', 'failed'].includes(data?.status)) throw new Error(data.message || '操作未完成')
  return data as T
}
