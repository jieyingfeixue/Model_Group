import request from './request'

const USE_MOCK = false  // 后端已就绪

export function uploadData(formData)            { return request.post('/data/upload', formData) }

export async function getDataList(params) {
  // 后端接口: GET /api/data?page=1&size=20&modality=visible&scene=daytime&weather=sunny...
  const apiParams = {
    page: params.page || 1,
    size: params.page_size || params.size || 20,
  }
  // 转发所有筛选参数
  const filterFields = ['modality', 'scene', 'weather', 'time_of_day', 'terrain', 'obstacle',
    'annotation_status', 'status', 'batch_id', 'sample_group', 'start_time', 'end_time']
  filterFields.forEach(f => {
    if (params[f] !== undefined && params[f] !== '' && params[f] !== null) {
      apiParams[f] = params[f]
    }
  })
  return request.get('/data', { params: apiParams })
}

/** 按样本分页：GET /api/data/samples — 每页只返回当前页样本 */
export async function getSampleList(params) {
  const apiParams = {
    page: params.page || 1,
    size: params.page_size || params.size || 12,
  }
  const filterFields = ['modality', 'scene', 'weather', 'time_of_day', 'terrain', 'obstacle',
    'annotation_status', 'status', 'batch_id', 'sample_group']
  filterFields.forEach(f => {
    if (params[f] !== undefined && params[f] !== '' && params[f] !== null) {
      apiParams[f] = params[f]
    }
  })
  return request.get('/data/samples', { params: apiParams })
}

export async function getDataDetail(id) {
  // 后端: GET /api/data/{resource_id}
  return request.get(`/data/${id}`)
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
