import request from './request'

// 用户管理
export function getUsers(params)               { return request.get('/admin/users', { params }) }
export function createUser(data)               { return request.post('/admin/users', data) }
export function setUserRole(id, data)           { return request.put(`/admin/users/${id}/role`, data) }
export function toggleUserStatus(id, data)      { return request.put(`/admin/users/${id}/status`, data) }
export function getAuditLogs(params)            { return request.get('/admin/audit-logs', { params }) }
export function getLineage(targetType, id)      { return request.get('/admin/lineage', { params: { target_type: targetType, target_id: id } }) }

// 标签体系
export function createSchema(data)              { return request.post('/admin/schemas', data) }
export function addCategory(id, data)           { return request.post(`/admin/schemas/${id}/categories`, data) }
export function updateCategory(sid, cid, data)  { return request.put(`/admin/schemas/${sid}/categories/${cid}`, data) }
export function deprecateCategory(sid, cid)     { return request.delete(`/admin/schemas/${sid}/categories/${cid}`) }
export function exportSchema(id)                { return request.get(`/admin/schemas/${id}/export`) }
export function importSchema(data)              { return request.post('/admin/schemas/import', data) }

// 数据源
export function createDataSource(data)          { return request.post('/admin/data-sources', data) }
export function testConnection(id)              { return request.post(`/admin/data-sources/${id}/test`) }
export function syncSource(id, data)            { return request.post(`/admin/data-sources/${id}/sync`, data) }
export function configureSensors(id, data)      { return request.put(`/admin/data-sources/${id}/sensors`, data) }
export function cleanSource(id)                 { return request.post(`/admin/data-sources/${id}/clean`) }

// 算力管理
export function getPendingTrainTasks()          { return request.get('/admin/train-tasks/pending') }
export function approveTrain(id)                { return request.post(`/admin/train-tasks/${id}/approve`) }
export function rejectTrain(id, data)           { return request.post(`/admin/train-tasks/${id}/reject`, data) }
export function terminateTrain(id)              { return request.post(`/admin/train-tasks/${id}/terminate`) }
export function getPendingInferTasks()          { return request.get('/admin/infer-tasks/pending') }
export function approveInfer(id)                { return request.post(`/admin/infer-tasks/${id}/approve`) }
export function getGpuNodes()                   { return request.get('/admin/gpu/nodes') }
export function updateConfig(data)              { return request.put('/admin/config', data) }

// 天梯榜
export function lockTestset(id)                 { return request.post(`/admin/datasets/${id}/lock`) }
export function invalidateResult(id)            { return request.post(`/admin/eval-results/${id}/invalidate`) }
export function updateWeights(data)             { return request.put('/admin/eval/weights', data) }
export function getLeaderboardCategories()      { return request.get('/admin/eval/categories') }
