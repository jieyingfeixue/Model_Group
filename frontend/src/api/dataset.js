import request from './request'
import { generateDatasets } from '@/mock/data'

const USE_MOCK = true

export async function getDatasetList(params) {
  if (!USE_MOCK) return request.get('/datasets', { params })
  let list = generateDatasets(8)
  if (params?.visibility === 'public') list = list.filter(d => d.visibility === 'public')
  if (params?.modality) list = list.filter(d => d.modality === params.modality)
  if (params?.keyword) list = list.filter(d => d.name.includes(params.keyword))
  return { data: { items: list, total: list.length } }
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
export function getDatasetVersions(id)     { return request.get(`/datasets/${id}/versions`) }
export function compareVersions(id, v1, v2){ return request.get(`/datasets/${id}/diff`, { params: { v1, v2 } }) }
export function exportDataset(id, params)  { return request.get(`/datasets/${id}/export`, { params, responseType: 'blob' }) }
export function downloadCopy(id)           { return request.post(`/datasets/${id}/copy`) }
