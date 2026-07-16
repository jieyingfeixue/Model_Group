import request from './request'

export function submitEval(data)               { return request.post('/eval/tasks', data) }
export function getEvalStatus(id)              { return request.get(`/eval/tasks/${id}`) }
export function getEvalMetrics(id)             { return request.get(`/eval/tasks/${id}/metrics`) }
export function getPRCurve(id, classId)         { return request.get(`/eval/tasks/${id}/pr-curve`, { params: { class_id: classId } }) }
export function getConfusionMatrix(id)          { return request.get(`/eval/tasks/${id}/confusion`) }
export function getErrorSamples(id, params)     { return request.get(`/eval/tasks/${id}/errors`, { params }) }
export function compareModels(data)             { return request.post('/eval/compare', data) }
export function getLeaderboard(params)          { return request.get('/eval/leaderboard', { params }) }
export function getHistoryTrend(modelId, params){ return request.get(`/eval/history/${modelId}`, { params }) }
