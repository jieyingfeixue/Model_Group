import request from './request'

// 数据集审核
export function getPendingDatasets(params)      { return request.get('/review/datasets', { params }) }
export function claimDatasetReview(id)          { return request.post(`/review/datasets/${id}/claim`) }
export function unclaimDatasetReview(id)        { return request.post(`/review/datasets/${id}/unclaim`) }
export function getChecklist(id)                { return request.get(`/review/datasets/${id}/checklist`) }
export function reviewDataset(id, data = {}) {
  const params = {
    result: data.result,
    failed_items: Array.isArray(data.failed_items)
      ? data.failed_items.join(',')
      : data.failed_items,
    notes: data.notes,
  }
  return request.post(`/review/datasets/${id}/verdict`, null, { params })
}

// 标注审核
export function getPendingAnnotationTasks(params) {
  return request.get('/review/annotation-tasks', { params })
}
export function claimAnnotationReview(id) {
  return request.post(`/review/annotation-tasks/${id}/claim`)
}
export function setupSampling(id, data = {}) {
  const params = {
    ratio: data.ratio ?? 0.2,
    mode: data.mode || 'random',
    manual_ids: Array.isArray(data.manual_ids)
      ? data.manual_ids.join(',')
      : data.manual_ids,
  }
  return request.post(`/review/annotation-tasks/${id}/sample`, null, { params })
}
export function reviewAnnotation(id, data = {}) {
  const params = {
    action: data.action,
    reject_codes: Array.isArray(data.reject_codes)
      ? data.reject_codes.join(',')
      : data.reject_codes,
    note: data.note,
  }
  return request.post(`/review/annotations/${id}/verdict`, null, { params })
}
export function getSamplingResult(id) {
  return request.get(`/review/annotation-tasks/${id}/summary`)
}
export function finalizeReview(id, data = {}) {
  const params = {
    action: data.action,
    new_ratio: data.new_ratio,
  }
  return request.post(`/review/annotation-tasks/${id}/finalize`, null, { params })
}
export function runQualityCheck(id) {
  return request.get(`/review/annotation-tasks/${id}/quality-check`)
}
export function getReviewerStats() {
  return request.get('/review/stats')
}
