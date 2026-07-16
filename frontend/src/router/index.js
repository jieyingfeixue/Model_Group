import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const routes = [
  // 默认跳转登录页
  { path: '/', redirect: '/login' },
  // 独立登录页（无导航栏）
  { path: '/login', name: 'Login', component: () => import('@/views/auth/Login.vue') },
  { path: '/register', name: 'Register', component: () => import('@/views/auth/Register.vue') },

  // 嵌套路由 — 所有业务页面包裹在 AppLayout 中（含侧边栏）
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: 'home', name: 'Home', component: () => import('@/views/HomePage.vue') },
      { path: 'mydatasets', name: 'MyDatasets', component: () => import('@/views/normal/MyDatasets.vue') },
      { path: 'profile', name: 'Profile', component: () => import('@/views/auth/Profile.vue') },
      { path: 'data', name: 'DataBrowse', component: () => import('@/views/normal/DataBrowse.vue') },
      { path: 'data/:id', name: 'DataDetail', component: () => import('@/views/normal/DataDetail.vue') },
      { path: 'market', name: 'DataMarket', component: () => import('@/views/normal/DataMarket.vue') },
      { path: 'annotate/:taskId', name: 'AnnotationTool', component: () => import('@/views/normal/AnnotationTool.vue') },
      { path: 'datasets/build', name: 'DatasetBuild', component: () => import('@/views/normal/DatasetBuild.vue') },
      { path: 'datasets/:id', name: 'DatasetDetail', component: () => import('@/views/normal/DatasetDetail.vue') },
      { path: 'models', name: 'ModelList', component: () => import('@/views/normal/ModelList.vue') },
      { path: 'models/:id', name: 'ModelDetail', component: () => import('@/views/normal/ModelDetail.vue') },
      { path: 'train', name: 'TrainTask', component: () => import('@/views/normal/TrainTask.vue') },
      { path: 'infer/:taskId', name: 'InferResult', component: () => import('@/views/normal/InferResult.vue') },
      { path: 'eval', name: 'EvalTask', component: () => import('@/views/normal/EvalTask.vue') },
      { path: 'eval/:taskId', name: 'EvalReport', component: () => import('@/views/normal/EvalReport.vue') },
      { path: 'compare', name: 'CompareBoard', component: () => import('@/views/normal/CompareBoard.vue') },
      { path: 'review/datasets', name: 'DatasetReview', component: () => import('@/views/reviewer/DatasetReview.vue') },
      { path: 'review/annotations', name: 'AnnotationReview', component: () => import('@/views/reviewer/AnnotationReview.vue') },
      { path: 'admin/users', name: 'UserManage', component: () => import('@/views/admin/UserManage.vue') },
      { path: 'admin/labels', name: 'LabelManage', component: () => import('@/views/admin/LabelManage.vue') },
      { path: 'admin/datasource', name: 'DataSource', component: () => import('@/views/admin/DataSource.vue') },
      { path: 'admin/compute', name: 'ComputeManage', component: () => import('@/views/admin/ComputeManage.vue') },
      { path: 'admin/leaderboard', name: 'Leaderboard', component: () => import('@/views/admin/Leaderboard.vue') },
    ],
  },

  { path: '/:pathMatch(.*)*', component: () => import('@/views/auth/NotFound.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 导航守卫：未登录只能访问登录/注册页
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('access_token')
  const publicPages = ['/login', '/register']
  if (!token && !publicPages.includes(to.path)) {
    return next('/login')
  }
  next()
})

export default router
