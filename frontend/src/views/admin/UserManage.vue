<template>
<div class="page">
    <div class="hero">
        <div>
            <h1>👥 用户管理</h1>
            <p>
                管理平台全部用户，
                支持创建账号、角色分配、
                用户冻结及权限管理。
            </p>
        </div>
    </div>
    <div class="stats">
        <div class="stat-card">
            <div class="icon">👤</div>
            <h2>{{ users.length }}</h2>
            <span>用户总数</span>
        </div>

        <div class="stat-card">
            <div class="icon">🛡️</div>
            <h2>{{ users.filter(u=>u.role==='admin').length }}</h2>
            <span>管理员</span>
        </div>

        <div class="stat-card">
            <div class="icon">✅</div>
            <h2>{{ users.filter(u=>u.role==='reviewer').length }}</h2>
            <span>审核员</span>
        </div>

        <div class="stat-card">
            <div class="icon">👥</div>
            <h2>{{ users.filter(u=>u.role==='normal').length }}</h2>
            <span>普通用户</span>
        </div>
    </div>

    <div class="toolbar">
        <div>
            <el-button type="primary" size="large" @click="createVisible=true">+ 创建用户</el-button>
        </div>
        <div class="toolbar-right">
            <el-input v-model="keyword" placeholder="搜索用户名" clearable style="width:220px"/>
            <el-select v-model="roleFilter" placeholder="角色筛选" clearable style="width:160px">
                <el-option label="全部" value=""/><el-option label="管理员" value="admin"/><el-option label="审核员" value="reviewer"/><el-option label="普通用户" value="normal"/>
            </el-select>
        </div>
    </div>

    <div class="table-card">
        <el-table :data="users" stripe header-cell-class-name="table-header">
            <el-table-column prop="username" label="用户名"/>
            <el-table-column prop="password" label="密码"/>
            <el-table-column
                label="角色"
                width="120"
                align="center"
            >
                <template #default="{ row }">
                    <el-tag
                        round
                        :type="
                            row.role === 'admin'
                                ? 'danger'
                                : row.role === 'reviewer'
                                ? 'warning'
                                : 'primary'
                        "
                    >
                        {{
                            row.role === 'admin'
                                ? '管理员'
                                : row.role === 'reviewer'
                                ? '审核员'
                                : '普通用户'
                        }}
                    </el-tag>
                </template>
            </el-table-column>
            <el-table-column prop="is_active" label="状态">
                <template #default="{row}">
                    <el-tag
                        round
                        effect="light"
                        :type="row.is_active ? 'success' : 'danger'"
                    >
                        {{ row.is_active ? '启用' : '冻结' }}
                    </el-tag>
                </template>
            </el-table-column>
            <el-table-column
                label="操作"
                width="320"
                align="center"
            >
                <template #default="{ row }">
                    <el-button
                        v-if="row.role !== 'admin'"
                        size="small"
                        :type="row.is_active ? 'danger' : 'success'"
                        @click="onToggle(row)"
                    >
                        {{ row.is_active ? '冻结' : '解冻' }}
                    </el-button>
                </template>
            </el-table-column>
        </el-table>
    </div>

    <el-dialog v-model="createVisible" title="👤 创建用户" width="560px">
        <el-form :model="newUser" label-position="top">
            <el-form-item label="用户名">
                <el-input v-model="newUser.username"/>
            </el-form-item>
            <el-form-item label="密码">
                <el-input v-model="newUser.password" type="password"/>
            </el-form-item>
            <el-form-item label="角色">
                <el-select v-model="newUser.role">
                    <el-option label="普通用户" value="normal"/>
                    <el-option label="审核员" value="reviewer"/>
                </el-select>
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="createVisible=false">取消</el-button>
            <el-button type="primary" @click="onCreate">创建</el-button>
        </template>
    </el-dialog>


</div>
</template>

<script setup>import {ref,reactive} from 'vue';import {ElMessage} from 'element-plus'
const users=ref([{user_id:1,username:'admin',password:'123456',role:'admin',is_active:true},{user_id:2,username:'user',password:'123456',role:'normal',is_active:true},{user_id:3,username:'reviewer1',password:'123456',role:'reviewer',is_active:true}])
const createVisible=ref(false);const newUser=reactive({username:'',password:'',role:'normal'})
const keyword = ref('')
const roleFilter = ref('')

function onToggle(row){row.is_active=!row.is_active;ElMessage.success(row.is_active?'已解冻':'已冻结')}
function onCreate(){users.value.push({user_id:Date.now(),username:newUser.username,password:newUser.password,role:newUser.role,is_active:true});createVisible.value=false;ElMessage.success('用户已创建')}
</script>
<style scoped>
.page{
padding:28px;
max-width:1450px;
margin:auto;
background:#f8fafc;
min-height:100vh;
}

.hero{
padding:40px;
margin-bottom:30px;
border-radius:22px;
background:
linear-gradient(
135deg,
#1d4ed8,
#2563eb,
#3b82f6
);
color:white;
box-shadow:
0 10px 30px rgba(37,99,235,.25);
}

.hero h1{
font-size:34px;
font-weight:700;
margin-bottom:10px;
}

.hero p{
font-size:16px;
line-height:1.8;
opacity:.92;
}

.stats{
display:grid;
grid-template-columns:
repeat(4,1fr);
gap:22px;
margin-bottom:30px;
}

.stat-card{
background:white;
border-radius:18px;
padding:26px;
text-align:center;
box-shadow:
0 8px 22px rgba(15,23,42,.05);
transition:.3s;
}

.stat-card:hover{
transform:translateY(-5px);
}

.icon{
font-size:30px;
margin-bottom:12px;
}

.toolbar{
display:flex;
justify-content:space-between;
align-items:center;
margin-bottom:24px;
}

.toolbar-right{
display:flex;
gap:16px;
}

.table-card{
background:white;
padding:22px;
border-radius:20px;
box-shadow:
0 8px 24px rgba(15,23,42,.06);
}

.action-group{
    display:grid;
    grid-template-columns:90px 90px 90px;
    gap:8px;
    justify-content:center;
}

.action-btn{
    width:90px;
}

.btn-placeholder{
    width:90px;
    height:32px;
}

:deep(.table-header){
    text-align:center !important;
    font-weight:700;
    color:#334155;
}

:deep(.el-table td){
text-align:center;
}

:deep(.el-dialog){
border-radius:18px;
overflow:hidden;
}

:deep(.el-dialog__header){
background:#f8fafc;
padding:22px;
font-weight:700;
}

:deep(.el-dialog__body){
padding:24px;
}
</style>