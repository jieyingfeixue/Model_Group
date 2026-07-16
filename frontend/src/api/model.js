import request from './request'

export function registerModel(data) {
  // 后端要求 multipart/form-data: file + name + framework + metadata
  const formData = new FormData()
  formData.append('name', data.name || data.get?.('name') || '')
  formData.append('framework', data.framework || data.get?.('framework') || 'pytorch')
  formData.append('metadata', JSON.stringify(data.metadata || { backbone: data.backbone || '', input_size: data.inputSize || '640x640' }))
  if (data.file) formData.append('file', data.file)
  return request.post('/models', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export function getMyModels(params)              { return request.get('/models', { params }) }
export function getModelDetail(id)               { return request.get(`/models/${id}`) }
export function uploadVersion(id, formData)      { return request.post(`/models/${id}/versions`, formData) }
export function setVisibility(id, data)          { return request.put(`/models/${id}/visibility`, data) }
export function deprecateModel(id)               { return request.delete(`/models/${id}`) }
export function getBaselines()                   { return request.get('/models/baselines') }
export function submitTrain(data)                { return request.post('/train/tasks', data) }
export function getTrainDetail(id)               { return request.get(`/train/tasks/${id}`) }
export function stopTrain(id)                    { return request.post(`/train/tasks/${id}/stop`) }
export function submitInfer(data)                { return request.post('/infer/tasks', data) }
export function getInferResults(id, params)      { return request.get(`/infer/tasks/${id}/results`, { params }) }
