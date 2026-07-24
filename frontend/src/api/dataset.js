import request from './request'

export async function getDatasetList(params) {
  return request.get('/datasets', { params })
}

export function previewFilters(data)       { return request.post('/datasets/preview', data) }
export function createDataset(data)        { return request.post('/datasets', data) }
export function getDatasetDetail(id)       { return request.get(`/datasets/${id}`) }
export function splitDataset(id, data)     { return request.post(`/datasets/${id}/split`, data) }
export function freezeDataset(id)          { return request.post(`/datasets/${id}/freeze`) }
export function publishDataset(id, data)   { return request.post(`/datasets/${id}/publish`, data) }
export function submitForReview(id)        { return request.post(`/datasets/${id}/submit-review`) }
export function changeVisibility(id, data) { return request.put(`/datasets/${id}/visibility`, data) }
export function archiveDataset(id)         { return request.post(`/datasets/${id}/archive`) }
export function restoreDataset(id)         { return request.post(`/datasets/${id}/restore`) }
export function deleteDataset(id)          { return request.delete(`/datasets/${id}`) }
export function getDatasetVersions(id)     { return request.get(`/datasets/${id}/versions`) }
export function compareVersions(id, v1, v2){ return request.get(`/datasets/${id}/diff`, { params: { v1, v2 } }) }
export function exportDataset(id, params)  { return request.get(`/datasets/${id}/export`, { params, responseType: 'blob' }) }
export function downloadCopy(id)           { return request.post(`/datasets/{id}/copy`) }
