<template>

<div class="auth-page">


  <!-- 左侧平台介绍 -->

  <div class="platform-info">


    <div class="brand">

      <span class="brand-icon">
        🎯
      </span>


      <div>

        <h2>
          MultiSense AI
        </h2>


        <p>
          低空多模态目标检测评测平台
        </p>

      </div>


    </div>



    <h1>

      面向智能感知的
      <br>

      AI 数据与算法平台

    </h1>



    <p class="desc">

      融合多源传感器数据，
      <br>

      提供数据管理、模型训练、
      <br>

      在线评测与算法排行榜

    </p>



    <div class="modal-list">


      <span>
        📷 可见光
      </span>


      <span>
        🔥 红外
      </span>


      <span>
        📡 毫米波
      </span>


      <span>
        🌐 激光雷达
      </span>


    </div>



  </div>





  <!-- 登录卡片 -->


  <div class="auth-card">


    <div class="card-header">


      <span class="logo">
        🎯
      </span>



      <h1>
        用户登录
      </h1>



      <p class="subtitle">

        登录您的账号，开始 AI 实验

      </p>



    </div>





    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      @submit.prevent="onLogin"
    >



      <el-form-item
      label="用户名"
      prop="username"
      >


        <el-input

          v-model="form.username"

          placeholder="请输入用户名"

        />


      </el-form-item>




      <el-form-item

      label="密码"

      prop="password"

      >


        <el-input

        v-model="form.password"

        type="password"

        placeholder="请输入密码"

        show-password

        />


      </el-form-item>





      <el-form-item>


        <el-button

        type="primary"

        native-type="submit"

        :loading="loading"

        class="login-btn"

        >


        登录平台


        </el-button>


      </el-form-item>



    </el-form>




  </div>


</div>


</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const formRef = ref(null)
const loading = ref(false)
const form = reactive({ username: localStorage.getItem('last_username') || '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onLogin() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const { data } = await login({ username: form.username, password: form.password })
    const payload = JSON.parse(atob(data.access_token.split('.')[1]))
    const user = { user_id: Number(payload.sub), username: form.username, role: data.role }
    userStore.login(user, data.access_token, data.refresh_token)
    ElMessage.success('登录成功')
    router.push('/home')
  } catch (e) {
    const msg = e?.response?.data?.detail || '登录失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>


.auth-page{


height:100vh;

display:flex;

align-items:center;

justify-content:center;


background:

radial-gradient(
circle at 20% 20%,
rgba(37,99,235,.35),
transparent 35%
),


linear-gradient(
135deg,
#020617,
#0f172a,
#1d4ed8
);


gap:80px;


}




/* 左侧介绍 */


.platform-info{


width:430px;

color:white;


}



.brand{


display:flex;

align-items:center;

gap:15px;


}



.brand-icon{


font-size:45px;


}



.brand h2{


margin:0;

font-size:28px;

font-weight:800;


}



.brand p{


margin:5px 0;

color:#cbd5e1;

font-size:14px;


}





.platform-info h1{


margin-top:55px;


font-size:42px;


line-height:1.35;


font-weight:800;


}




.desc{


margin-top:25px;


font-size:17px;


line-height:2;


color:#cbd5e1;


}





.modal-list{


display:flex;


flex-wrap:wrap;


gap:12px;


margin-top:35px;


}




.modal-list span{


padding:

8px 16px;


background:

rgba(255,255,255,.12);


border-radius:

30px;


font-size:13px;


}





/* 登录卡片 */


.auth-card{


width:400px;


background:

rgba(255,255,255,.95);


border-radius:

24px;


padding:

42px;


box-shadow:


0 25px 60px

rgba(0,0,0,.25);


backdrop-filter:

blur(10px);


}





.card-header{


text-align:center;


margin-bottom:30px;


}



.logo{


font-size:45px;


}



.card-header h1{


font-size:24px;


margin:

12px 0 8px;


color:#0f172a;


}



.subtitle{


font-size:14px;


color:#64748b;


}





.login-btn{


width:100%;


height:42px;


border-radius:

10px;


font-size:15px;


}














/* 输入框增强 */


:deep(.el-input__wrapper){


border-radius:

10px;


height:

42px;


}





@media(max-width:900px){


.platform-info{


display:none;


}



.auth-page{


padding:

20px;


}



.auth-card{


width:

100%;


max-width:

400px;


}


}



</style>
