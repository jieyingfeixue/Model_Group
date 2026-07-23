import request from './request'

const USE_MOCK = false

// 伪造 JWT：payload 编码 { user_id, username, role }，实际项目中由后端签发
function fakeToken(userId, role) {
  const payload = btoa(JSON.stringify({ sub: String(userId), role, type: 'access' }))
  return `header.${payload}.signature`
}

const mockUsers = [
  { user_id: 1, username: 'admin', password: '123456', email: 'admin@test.com', role: 'admin' },
  { user_id: 2, username: 'reviewer', password: '123456', email: 'reviewer@test.com', role: 'reviewer' },
  { user_id: 3, username: 'user', password: '123456', email: 'user@test.com', role: 'normal' },
]

export async function login(data) {
  if (USE_MOCK) {
    const u = mockUsers.find(m => m.username === data.username && m.password === data.password)
    if (!u) throw { response: { status: 401, data: { detail: '用户名或密码错误' } } }
    return {
      data: {
        access_token: fakeToken(u.user_id, u.role),
        refresh_token: fakeToken(u.user_id, u.role),
        role: u.role,
      }
    }
  }
  return request.post('/auth/login', data)
}

export async function register(data) {
  if (USE_MOCK) {
    if (mockUsers.find(m => m.username === data.username)) {
      throw { response: { status: 409, data: { detail: '用户名已存在' } } }
    }
    return { data: { message: '注册成功' } }
  }
  return request.post('/auth/register', data)
}

export function getProfile()       { return request.get('/users/me') }
export function updateProfile(d)   { return request.put('/users/me', d) }
