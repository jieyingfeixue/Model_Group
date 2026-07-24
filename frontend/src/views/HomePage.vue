<template>

<div class="home-layout">

  <!-- 左侧导航 -->
  

  <!-- 首页主体 -->
  <div class="home">

    <!-- ================= Hero ================= -->

    <section class="hero">

      <div class="hero-tag">
        🚀 AI Benchmark Platform
      </div>

      <h1>
        多模态目标检测
        <br>
        <span>
          AI 数据与算法评测平台
        </span>
      </h1>

      <p>
        融合可见光、红外、毫米波、激光雷达数据，
        <br>
        提供数据管理、模型训练、在线评测与算法排行榜
      </p>

      <div class="hero-buttons">

        <el-button
          type="primary"
          size="large"
          round
          @click="$router.push('/data')"
        >
          探索数据集
        </el-button>

        <el-button
          size="large"
          round
          @click="$router.push('/models')"
        >
          上传模型
        </el-button>

      </div>

      <div class="modal-tags">

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

    </section>

    <!-- ================= 核心能力 ================= -->

    <section class="feature-section">

      <h2>
        平台核心能力
      </h2>

      <div class="cards-row">

        <div
          class="card"
          v-for="card in cards"
          :key="card.title"
          @click="$router.push(card.path)"
        >

          <div class="card-icon">
            {{card.icon}}
          </div>

          <h3>
            {{card.title}}
          </h3>

          <p>
            {{card.desc}}
          </p>

        </div>

      </div>

    </section>

    <!-- ================= AI研发闭环 ================= -->

    <section class="pipeline">

      <h2>
        AI研发闭环
      </h2>

      <div class="pipeline-list">

        <div>
          📦
          <br>
          数据管理
        </div>

        <div class="arrow">
          →
        </div>

        <div>
          🖊️
          <br>
          智能标注
        </div>

        <div class="arrow">
          →
        </div>

        <div>
          🧠
          <br>
          模型训练
        </div>

        <div class="arrow">
          →
        </div>

        <div>
          🏆
          <br>
          算法评测
        </div>

      </div>

    </section>

    <!-- ================= 数据统计 ================= -->

    <section class="stats-row">

      <div
        class="stat"
        v-for="s in stats"
        :key="s.label"
      >

        <strong>
          {{s.num}}
        </strong>

        <span>
          {{s.label}}
        </span>

      </div>

    </section>

    <!-- ================= 数据集 ================= -->

    <section
      class="datasets-section"
      v-if="datasets.length"
    >

      <h2>
        最新公开数据集
      </h2>

      <div class="dataset-list">

        <div
          v-for="ds in datasets"
          :key="ds.dataset_id"
          class="ds-card"
          @click="$router.push('/market')"
        >

          <div class="ds-icon">
            📦
          </div>

          <div>

            <h3>
              {{ds.name}}
            </h3>

            <p>
              {{ds.sample_count}}
              样本 ·
              {{modalityLabel(ds.modality)}}
            </p>

          </div>

        </div>

      </div>

    </section>

    <footer>

      © 2026 MultiSense AI Platform

    </footer>


  </div>

</div>

</template>

<script setup>

import { ref, computed, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { getDatasetList } from '@/api/dataset'
import { getDataList } from '@/api/data'
import { getMyModels } from '@/api/model'

const router = useRouter()
const userStore = useUserStore()
const datasets = ref([])

async function fetchStats() {
  try {
    const [dataRes, modelRes] = await Promise.all([
      getDataList({ page: 1, size: 1 }),
      getMyModels()
    ])
    const totalResources = dataRes.data?.total || 0
    stats.value = [
      { num: totalResources.toLocaleString(), label: '数据资源' },
      { num: (dataRes.data?.items || []).filter(i => i.annotation_status === 'annotated').length.toLocaleString() + '+', label: '标注样本' },
      { num: (Array.isArray(modelRes.data) ? modelRes.data.length : (modelRes.data?.total || 0)).toString(), label: '评测模型' },
    ]
  } catch { /* ignore */ }

  try {
    const { data } = await getDatasetList({ visibility: 'public', page: 1, size: 4 })
    datasets.value = data.items || []
  } catch { /* ignore */ }
}

onMounted(fetchStats)
onActivated(fetchStats)
const cards = [
{
 icon:'📦',
 title:'数据集市场',
 desc:'浏览公开多模态数据集，探索低空障碍物检测基准数据',
 path:'/data',
 needLogin:true
},
{
 icon:'🖊️',
 title:'智能标注中心',
 desc:'在线完成目标框、类别、深度信息标注',
 path:'/annotate/1',
 needLogin:true
},
{
 icon:'🏗️',
 title:'数据集构建',
 desc:'数据筛选、智能切分、版本管理与公开发布',
 path:'/datasets/build',
 needLogin:true
},
{
 icon:'🧠',
 title:'模型仓库',
 desc:'上传、管理模型版本，追踪训练来源与评测记录',
 path:'/models',
 needLogin:true
},
{
 icon:'🏆',
 title:'算法评测',
 desc:'Benchmark测试、多模型对比与排行榜竞争',
 path:'/eval',
 needLogin:true
}
]
const stats = ref([
  { num: '~', label: '数据资源' },
  { num: '~', label: '标注样本' },
  { num: '~', label: '评测模型' },
])
const roleLabel = computed(() => {
  const map = { normal: '普通用户', reviewer: '审核员', admin: '管理员' }
  return map[userStore.role] || ''
})
const roleColor = computed(() => {
  const map = { normal: '#3b82f6', reviewer: '#f59e0b', admin: '#ef4444' }
  return map[userStore.role] || '#3b82f6'
})
function modalityLabel(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
</script>

<style scoped>
/* =========================
   全局
========================= */
.home{

min-height:100vh;

background:#f8fafc;

color:#0f172a;

overflow-x:hidden;

}
/* =========================
   Navbar
========================= */
.navbar{
height:72px;
padding:0 42px;
background:white;
display:flex;
align-items:center;
justify-content:space-between;
border-bottom:
1px solid #e5e7eb;
position:sticky;
top:0;
z-index:20;
}
.brand{
display:flex;
align-items:center;
gap:12px;
}

.brand-icon{
font-size:34px;
}
.brand-title{
font-size:18px;
font-weight:800;
letter-spacing:.5px;
color:#0f172a;
}

.brand-sub{
font-size:11px;
color:#64748b;
margin-top:2px;
}
.nav-center{
display:flex;
gap:30px;
}

.nav-item{
font-size:14px;
color:#475569;
text-decoration:none;
cursor:pointer;
transition:.25s;
}

.nav-item:hover{
color:#2563eb;
}
.nav-right{
display:flex;
align-items:center;
gap:18px;
}
.login-link{
color:#475569;
text-decoration:none;
font-size:14px;
}
.username{
cursor:pointer;
font-size:14px;
}
.role-badge{
padding:
3px 12px;
border-radius:
20px;
font-size:
12px;
color:white;
}
/* =========================
 Hero
========================= */
.hero{
padding:
70px 20px 60px;
text-align:center;
background:
radial-gradient(
circle at top,
rgba(59,130,246,.35),
transparent 40%
),
linear-gradient(
135deg,
#020617,
#0f172a,
#1d4ed8
);
color:white;
border-radius:
0 0 45px 45px;
}
.hero-tag{
display:inline-block;
padding:
6px 18px;
border-radius:
20px;
background:
rgba(255,255,255,.12);
font-size:
13px;
margin-bottom:25px;
}
.hero h1{
font-size:
46px;
line-height:
1.25;
font-weight:
800;
margin:
0;
}
.hero h1 span{
background:
linear-gradient(
90deg,
#60a5fa,
#38bdf8
);
-webkit-background-clip:text;
color:transparent;
}
.hero p{
margin-top:25px;
font-size:
17px;
line-height:
1.8;
color:
#cbd5e1;
}
.hero-buttons{
margin-top:
38px;
display:flex;
justify-content:center;
gap:
18px;
}
.modal-tags{
margin-top:
45px;
display:flex;
justify-content:center;
gap:
14px;
flex-wrap:wrap;
}
.modal-tags span{
background:
rgba(255,255,255,.12);
padding:
8px 18px;
border-radius:
30px;
font-size:
13px;
}
/* =========================
 标题
========================= */
h2{
text-align:center;
font-size:
26px;
margin-bottom:
35px;
font-weight:
750;
}
/* =========================
 功能卡片
========================= */
.feature-section{
padding:
70px 20px 40px;
}

.cards-row{

max-width:1200px;

margin:auto;

display:grid;

grid-template-columns:
repeat(5,1fr);

gap:24px;

}

.card{
background:white;
border-radius:
20px;
padding:
35px 25px;
text-align:center;
cursor:pointer;
border:
1px solid #eef2f7;
transition:
all .3s;
}

.card:hover{
transform:
translateY(-8px);
box-shadow:
0 20px 40px
rgba(15,23,42,.12);
border-color:#bfdbfe;
}

.card-icon{
font-size:
42px;
margin-bottom:
20px;
}
.card h3{
font-size:
18px;
margin-bottom:
12px;
}

.card p{
font-size:
14px;
line-height:
1.7;
color:#64748b;
}
/* =========================
 Pipeline
========================= */
.pipeline{
padding:
60px 20px;
background:white;
}

.pipeline-list{
max-width:
1000px;
margin:auto;
display:flex;
align-items:center;
justify-content:center;
gap:
25px;
}
.pipeline-list div:not(.arrow){
width:
130px;
height:
90px;
display:flex;
align-items:center;
justify-content:center;
flex-direction:column;
background:#f1f5f9;
border-radius:
18px;
font-size:
16px;
font-weight:
600;
}
.arrow{
font-size:
28px;
color:#94a3b8;
}
/* =========================
 stats
========================= */
.stats-row{
display:flex;
justify-content:center;
gap:
90px;
padding:
45px 20px;
background:
#f8fafc;
}

.stat{
text-align:center;
}
.stat strong{
display:block;
font-size:
36px;
font-weight:
800;
color:#2563eb;
}

.stat span{
font-size:
14px;
color:#64748b;
}
/* =========================
 数据集
========================= */
.datasets-section{
max-width:
1200px;
margin:
50px auto;
padding:
0 20px;
}

.dataset-list{
display:grid;
grid-template-columns:
repeat(2,1fr);
gap:
18px;
}

.ds-card{
background:white;
padding:
22px;
border-radius:
16px;
display:flex;
align-items:center;
gap:
18px;
cursor:pointer;
transition:.3s;
}

.ds-card:hover{
transform:
translateY(-4px);
box-shadow:
0 10px 25px rgba(0,0,0,.08);
}
.ds-icon{
font-size:
35px;
}
.ds-card h3{
margin:
0;
font-size:
16px;
}
.ds-card p{
margin-top:
8px;
font-size:
13px;
color:#64748b;
}
/* =========================
 footer
========================= */
footer{
text-align:center;
padding:
35px;
color:#94a3b8;
font-size:
13px;
}
.dialog-text{
text-align:center;
}
/* =========================
 响应式
========================= */
@media(max-width:900px){
.nav-center{
display:none;
}
.cards-row{
grid-template-columns:
repeat(auto-fit,minmax(220px,1fr));
}
.hero h1{
font-size:
34px;
}
.pipeline-list{
flex-wrap:wrap;
}
}

@media(max-width:600px){
.cards-row{
max-width:1200px;
margin:auto;
display:grid;
grid-template-columns:
1fr;
gap:24px;
}

.dataset-list{
grid-template-columns:
1fr;
}
.stats-row{
gap:
30px;
}
}
</style>