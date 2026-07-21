import request from './request'

export function registerModel(formData)          { return request.post('/models', formData) }
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
