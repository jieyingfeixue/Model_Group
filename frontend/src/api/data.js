import request from './request'

export function uploadData(formData)            { return request.post('/data/upload', formData) }

export async function getDataList(params = {}) {
  const modality = Array.isArray(params.modality)
    ? (params.modality[0] || undefined)
    : params.modality
  return request.get('/data', {
    params: {
      page: params.page || 1,
      size: params.page_size || params.size || 20,
      modality: modality || undefined,
      annotation_status: params.annotation_status || undefined,
      scene: params.scene || undefined,
      status: params.status || undefined,
    },
  })
}

export async function getDataDetail(id) {
  return request.get(`/data/resources/${id}`)
}

/** 后端暂未提供数据版本历史 */
export async function getDataVersions() {
  return { data: [] }
}

/** 后端暂未提供：保留调用方兼容，返回明确错误信息 */
export async function updateMetadata() {
  throw { response: { status: 501, data: { detail: '数据元信息更新接口尚未实现' } } }
}
export async function rollbackData() {
  throw { response: { status: 501, data: { detail: '数据回滚接口尚未实现' } } }
}
export async function getDataLineage() {
  throw { response: { status: 501, data: { detail: '数据血缘接口尚未实现' } } }
}

export function alignData(data)                 { return request.post('/data/align', data) }

export function getImageUrl(resourceId)         { return `/api/images/${resourceId}` }
export function getThumbnailUrl(resourceId)     { return `/api/images/${resourceId}/thumbnail` }
