import request from './request'

export function createTask(data)               { return request.post('/annotation/tasks', data) }
export function getMyTasks(params)             { return request.get('/annotation/tasks', { params }) }
export function getTaskProgress(id)            { return request.get(`/annotation/tasks/${id}/progress`) }
export function getNextImage(taskId)           { return request.get(`/annotation/tasks/${taskId}/next`) }
export function saveAnnotation(imageId, data)  { return request.put(`/annotation/images/${imageId}/save`, data) }
export function submitAnnotation(imageId)      { return request.post(`/annotation/images/${imageId}/submit`) }
export function getAnnotationHistory(imageId)  { return request.get(`/annotation/images/${imageId}/history`) }
export function rollbackAnnotation(imageId, v) { return request.post(`/annotation/images/${imageId}/rollback`, { version: v }) }
export function getActiveCategories(schemaId)  { return request.get(`/schemas/${schemaId}/categories`) }
