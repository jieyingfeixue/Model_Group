import request from './request'

export function createTask(data)               { return request.post('/annotation/tasks', data) }
export function getMyTasks(params)             { return request.get('/annotation/tasks', { params }) }
export function getTaskProgress(id)            { return request.get(`/annotation/tasks/${id}/progress`) }
export function getNextImage(taskId)           { return request.get(`/annotation/tasks/${taskId}/next`) }

export function saveAnnotation(imageId, data, taskId) {
  const body = Array.isArray(data) ? { bboxes: data } : data
  return request.put(`/annotation/images/${imageId}/save`, body, {
    params: { task_id: taskId ?? data?.task_id },
  })
}

export function submitAnnotation(imageId, taskId) {
  return request.post(`/annotation/images/${imageId}/submit`, null, {
    params: { task_id: taskId },
  })
}

export function getAnnotationHistory(imageId, taskId) {
  return request.get(`/annotation/images/${imageId}/history`, {
    params: { task_id: taskId },
  })
}

export function rollbackAnnotation(imageId, version, taskId) {
  return request.post(`/annotation/images/${imageId}/rollback`, null, {
    params: { task_id: taskId, version },
  })
}

export function getActiveCategories(schemaId)  { return request.get(`/schemas/${schemaId}/categories`) }
