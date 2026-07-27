import { defineStore } from 'pinia'
import { getProfile } from '@/api/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    user: null,          // { user_id, username, email, role }
    role: null,
  }),
  getters: {
    isLoggedIn: (state) => !!state.user,
    navItems: () => [
      { path: '/data', label: '数据浏览' },
      { path: '/market', label: '数据集市场' },
    ],
    sideItems: (state) => {
      const all = {
        normal: [
          { path: '/home', icon: '🏠', label: '首页' },
          { path: '/data', icon: '📦', label: '数据浏览' },
          { path: '/market', icon: '📊', label: '数据集市场' },
          { path: '/mydatasets', icon: '📁', label: '我的数据集' },
          { path: '/models', icon: '🧠', label: '我的模型' },
          { path: '/eval', icon: '🏆', label: '评测' },
          { path: '/profile', icon: '👤', label: '个人中心' },
        ],
        reviewer: [
          { path: '/review/datasets', icon: '✅', label: '数据集审核' },
          { path: '/review/annotations', icon: '🔍', label: '标注审核' },
        ],
        admin: [
          { path: '/admin/users', icon: '👥', label: '用户管理' },
          { path: '/admin/labels', icon: '🏷️', label: '标签管理' },
          { path: '/admin/datasource', icon: '📁', label: '数据源' },
          { path: '/admin/compute', icon: '🖥️', label: '算力管理' },
          { path: '/admin/leaderboard', icon: '🏅', label: '天梯榜' },
        ],
      }
      return all[state.role] || all.normal
    },
  },
  actions: {
    login(user, accessToken, refreshToken) {
      this.user = user
      this.role = user.role
      localStorage.setItem('access_token', accessToken)
      localStorage.setItem('refresh_token', refreshToken)
      // JWT 里只有 user_id/role，刷新后需从本地恢复用户名
      if (user?.username) localStorage.setItem('username', user.username)
    },
    tryRestore() {
      const token = localStorage.getItem('access_token')
      if (!token) return
      try {
        const payload = JSON.parse(atob(token.split('.')[1]))
        const username =
          localStorage.getItem('username')
          || payload.username
          || ''
        this.user = {
          user_id: Number(payload.sub),
          username,
          role: payload.role,
        }
        this.role = payload.role
        // 后台再拉一次资料，补全用户名/邮箱（不阻塞首屏）
        this.fetchProfile()
      } catch { /* token invalid */ }
    },
    async fetchProfile() {
      try {
        const { data } = await getProfile()
        if (!data) return
        this.user = {
          user_id: data.user_id,
          username: data.username || this.user?.username || '',
          email: data.email,
          role: data.role,
        }
        this.role = data.role
        if (data.username) localStorage.setItem('username', data.username)
      } catch { /* 保持 token 恢复结果 */ }
    },
    logout() {
      const username = this.user?.username
      this.user = null
      this.role = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('username')
      if (username) localStorage.setItem('last_username', username)
    },
    setRole(role) {
      this.role = role
      if (this.user) this.user.role = role
    },
  },
})
