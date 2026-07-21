import request from './request'

const USE_MOCK = false

export async function getDatasetList(params) {
  if (!USE_MOCK) return request.get('/datasets', { params })
  return { data: { items: [], total: 0 } }
}

/** 我的数据集（含私有/草稿） */
export function getMyDatasets(params) {
  return request.get('/datasets/mine', { params })
}

export function previewFilters(data)       { return request.post('/datasets/preview', data) }
export function createDataset(data)        { return request.post('/datasets', data) }
export function getDatasetDetail(id)       { return request.get(`/datasets/${id}`) }
export function splitDataset(id, data)     { return request.post(`/datasets/${id}/split`, data) }
export function freezeDataset(id)          { return request.post(`/datasets/${id}/freeze`) }
export function unfreezeDataset(id)        { return request.post(`/datasets/${id}/unfreeze`) }
export function submitForReview(id)        { return request.post(`/datasets/${id}/submit-review`) }

export function publishDataset(id, data = {}) {
  const visibility = typeof data === 'string' ? data : (data.visibility || 'public')
  return request.post(`/datasets/${id}/publish`, null, { params: { visibility } })
}

export function changeVisibility(id, data = {}) {
  const visibility = typeof data === 'string' ? data : (data.visibility || 'private')
  return request.put(`/datasets/${id}/visibility`, null, { params: { visibility } })
}

export function archiveDataset(id)         { return request.post(`/datasets/${id}/archive`) }
export function restoreDataset(id)         { return request.post(`/datasets/${id}/restore`) }
export function getDatasetVersions(id)     { return request.get(`/datasets/${id}/versions`) }
export function compareVersions(id, v1, v2){ return request.get(`/datasets/${id}/diff`, { params: { v1, v2 } }) }
export function exportDataset(id, params)  { return request.get(`/datasets/${id}/export`, { params, responseType: 'blob' }) }
export function downloadCopy(id)           { return request.post(`/datasets/${id}/copy`) }
export function previewDataset(id, params) { return request.get(`/datasets/${id}/preview`, { params }) }
