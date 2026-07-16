import request from './request'

// 数据集审核
export function getPendingDatasets()            { return request.get('/review/datasets') }
export function claimDatasetReview(id)          { return request.post(`/review/datasets/${id}/claim`) }
export function unclaimDatasetReview(id)        { return request.post(`/review/datasets/${id}/unclaim`) }
export function reviewDataset(id, data)         { return request.post(`/review/datasets/${id}/verdict`, data) }

// 标注审核
export function getPendingAnnotationTasks()     { return request.get('/review/annotation-tasks') }
export function claimAnnotationReview(id)       { return request.post(`/review/annotation-tasks/${id}/claim`) }
export function setupSampling(id, data)         { return request.post(`/review/annotation-tasks/${id}/sample`, data) }
export function reviewAnnotation(id, data)      { return request.post(`/review/annotations/${id}/verdict`, data) }
export function getSamplingResult(id)           { return request.get(`/review/annotation-tasks/${id}/summary`) }
export function finalizeReview(id, data)        { return request.post(`/review/annotation-tasks/${id}/finalize`, data) }
export function getReviewerStats()              { return request.get('/review/stats') }
