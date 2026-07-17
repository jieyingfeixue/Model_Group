<template>
<div class="sidebar">
  <!-- Logo -->
  <div class="sidebar-logo">
    🎯
    <span>
      目标检测算法评测平台
    </span>
  </div>
  <!-- 菜单 -->
  <div class="menu">
	    <router-link v-for="item in userStore.sideItems" :key="item.path" :to="item.path" class="menu-item">
	      {{ item.icon }} {{ item.label }}
	    </router-link>
	  </div>

  <!-- 用户区域 -->
  <div
  class="user-area"
  v-if="userStore.isLoggedIn"
  >
      <div class="user-card">
          <div class="avatar">
              {{ userStore.user?.username?.charAt(0).toUpperCase() }}
          </div>
          <div class="user-name">
              {{ userStore.user?.username }}
          </div>
          <div class="user-role">
              普通用户
          </div>
          <el-button
              class="logout-btn"
              plain
              @click="logout"
          >
              退出登录
          </el-button>
      </div>
  </div>
</div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'
const router = useRouter()
const userStore = useUserStore()
function logout() {
  userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
.sidebar{
position:fixed;
left:0;
top:0;
width:240px;
min-width:240px;
height:100vh;
background:#0f172a;
color:white;
display:flex;
flex-direction:column;
flex-shrink:0;
z-index:1000;
}
.sidebar-logo{
height:70px;
display:flex;
align-items:center;
gap:10px;
padding:0 20px;
font-size:16px;
font-weight:700;
border-bottom:1px solid rgba(255,255,255,.1);
}
.menu{
padding:20px 12px;
flex:1;
}
.menu-item{
display:block;
padding:12px 16px;
margin-bottom:8px;
border-radius:8px;
color:#cbd5e1;
text-decoration:none;
transition:.2s;
}

.menu-item:hover{
background:#1e293b;
color:white;
}

.router-link-active{
background:#2563eb;
color:white;
}

.user-area{

    padding:20px;

    border-top:1px solid rgba(255,255,255,.08);

}

.user-card{

    background:#1e293b;

    border-radius:16px;

    padding:18px;

    text-align:center;

    border:1px solid rgba(255,255,255,.06);

}

.avatar{

    width:56px;

    height:56px;

    border-radius:50%;

    margin:0 auto 12px;

    background:linear-gradient(
        135deg,
        #3b82f6,
        #60a5fa
    );

    display:flex;
    align-items:center;
    justify-content:center;
    color:white;
    font-size:22px;
    font-weight:700;
}

.user-name{
    color:white;
    font-size:15px;
    font-weight:600;
    margin-bottom:6px;
}

.user-role{
    display:inline-block;
    padding:4px 12px;
    border-radius:30px;
    font-size:12px;
    background:#2563eb;
    color:white;
    margin-bottom:18px;
}

.logout-btn{
    width:100%;
}

.logout-btn{
    width:100%;
    border-radius:10px;
}

.logout-btn:hover{
    background:#ef4444;
    border-color:#ef4444;
    color:white;
}
</style>