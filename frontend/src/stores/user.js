import { defineStore } from 'pinia'

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
          { path: '/home', icon: '🏠', label: '首页' },
          { path: '/data', icon: '📦', label: '数据浏览' },
          { path: '/market', icon: '📊', label: '数据集市场' },
          { path: '/review/datasets', icon: '✅', label: '数据集审核' },
          { path: '/review/annotations', icon: '🔍', label: '标注审核' },
        ],
        admin: [
          { path: '/home', icon: '🏠', label: '首页' },
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
    },
    tryRestore() {
      const token = localStorage.getItem('access_token')
      if (!token) return
      try {
        const payload = JSON.parse(atob(token.split('.')[1]))
        this.user = { user_id: payload.user_id, username: payload.username, role: payload.role }
        this.role = payload.role
      } catch { /* token invalid */ }
    },
    logout() {
      const username = this.user?.username
      this.user = null
      this.role = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      if (username) localStorage.setItem('last_username', username)
    },
    setRole(role) {
      this.role = role
      if (this.user) this.user.role = role
    },
  },
})
