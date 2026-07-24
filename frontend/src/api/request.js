import axios from 'axios'
import { useUserStore } from '@/stores/user'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

const AUTH_NO_REFRESH = ['/auth/login', '/auth/register', '/auth/refresh']

function isAuthEndpoint(config) {
  const url = config?.url || ''
  return AUTH_NO_REFRESH.some((p) => url.includes(p))
}

// 请求拦截器：附加 JWT Token
request.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：401 时尝试刷新 Token（登录/注册本身失败不要重试）
request.interceptors.response.use(
  response => response,
  async error => {
    const status = error.response?.status
    const config = error.config || {}

    if (status === 401 && !isAuthEndpoint(config) && !config._retry) {
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        config._retry = true
        try {
          const { data } = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
          localStorage.setItem('access_token', data.access_token)
          config.headers = config.headers || {}
          config.headers.Authorization = `Bearer ${data.access_token}`
          return request(config)
        } catch {
          const userStore = useUserStore()
          userStore.logout()
          if (!window.location.pathname.includes('/login')) {
            window.location.href = '/login'
          }
        }
      } else if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default request
