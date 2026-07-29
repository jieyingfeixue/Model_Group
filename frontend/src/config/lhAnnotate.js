/**
 * LH 半自动标注工具（Auto-labeling-LH）入口配置。
 * 工具独立进程运行，平台只负责跳转与结果回显（LabelMe 目录）。
 */
export const LH_ANNOTATE_BASE =
  (import.meta.env.VITE_LH_ANNOTATE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '')

export const LH_ANNOTATE_PAGE = `${LH_ANNOTATE_BASE}/annotate`
export const LH_HEALTH_URL = `${LH_ANNOTATE_BASE}/health`

export function openLhAnnotateTool() {
  window.open(LH_ANNOTATE_PAGE, '_blank', 'noopener,noreferrer')
}

export async function checkLhAnnotateHealth(timeoutMs = 2500) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(LH_HEALTH_URL, { signal: ctrl.signal, mode: 'cors' })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}
