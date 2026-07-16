import request from './request'

const USE_MOCK = false  // 后端已就绪

export function uploadData(formData)            { return request.post('/data/upload', formData) }

export async function getDataList(params) {
  // 后端接口: GET /api/data?page=1&size=20&modality=visible
  return request.get('/data', {
    params: {
      page: params.page || 1,
      size: params.page_size || params.size || 20,
      modality: params.modality || undefined,
      scene: params.scene || undefined,
      annotation_status: params.annotation_status || undefined,
    }
  })
}

export async function getDataDetail(id) {
  // 后端暂未提供单条查询，用列表接口模拟
  return request.get('/data', { params: { page: 1, size: 100 } })
}

// 后端暂未提供版本历史接口，保留函数签名后续对接
export async function getDataVersions(id) {
  return { data: [] }
}

// 后端暂未提供以下接口
export function updateMetadata(id, data)        { return request.put(`/data/${id}/metadata`, data) }
export function rollbackData(id, version)       { return request.post(`/data/${id}/rollback`, { version_number: version }) }
export function getDataLineage(id)              { return request.get(`/data/${id}/lineage`) }
export function alignData(data)                 { return request.post('/data/align', data) }

// 后端图片接口: GET /api/images/{id} 和 GET /api/images/{id}/thumbnail
export function getImageUrl(resourceId)         { return `/api/images/${resourceId}` }
export function getThumbnailUrl(resourceId)     { return `/api/images/${resourceId}/thumbnail` }
