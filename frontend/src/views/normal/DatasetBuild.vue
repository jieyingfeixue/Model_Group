<template>
<div class="page">
  <!-- Hero -->
    <div class="hero">
        <div>
            <h1>🏗️ 数据集构建</h1>

            <p>
                从平台已有数据或本地上传数据快速构建新的数据集，
                支持样本筛选、数据划分、版本冻结及公开发布。
            </p>
        </div>
    </div>

    <div class="stats">
      <div class="stat-card">
          <div class="icon">📂</div>
          <h2>{{ hitCount ?? 0 }}</h2>
          <span>命中样本</span>
      </div>

      <div class="stat-card">
          <div class="icon">🗂️</div>
          <h2>{{ datasetId ? 1 : 0 }}</h2>
          <span>已创建数据集</span>
      </div>

      <div class="stat-card">
          <div class="icon">📦</div>
          <h2>{{ statusLabel }}</h2>
          <span>当前状态</span>
      </div>
  </div>
  <div class="tabs-card">
  <el-tabs v-model="activeTab" class="tabs">
    <!-- ====== 方式一：从平台数据构建 ====== -->
    <el-tab-pane label="从平台数据构建" name="platform">
      <div class="card"><h3>筛选条件</h3>
        <div class="filter-row">
          <el-select v-model="filters.modality" placeholder="模态类型" multiple clearable>
            <el-option v-for="m in modalities" :key="m" :label="modLabel(m)" :value="m" />
          </el-select>
          <el-select v-model="filters.scene" placeholder="场景环境" multiple clearable>
            <el-option v-for="s in scenes" :key="s" :label="s" :value="s" />
          </el-select>
          <el-date-picker v-model="filters.timeRange" type="daterange" range-separator="至" start-placeholder="开始" end-placeholder="结束" />
          <el-button type="primary" size="large" icon="Search" @click="onSearch"> 查询 </el-button>
        </div>
        <div class="hit-info" v-if="hitCount!==null">

        🎯 已匹配

        <strong>

        {{ hitCount }}

        </strong>

        个样本

        </div>
        <!-- 样本数量输入 -->
        <div v-if="hitCount > 0" style="margin-top:16px;">
          <p style="color:#6b7280;display:flex;align-items:center;gap:8px;">从 {{ hitCount }} 个匹配样本中，随机选用
            <el-input-number v-model="sampleCount" :min="1" :max="hitCount" style="width:180px;" @change="previewSelection" />
            个样本放入数据集
            <el-button size="small" @click="previewSelection">预览选中</el-button>
            <span v-if="selectedIds.size > 0" style="color:#3b82f6;">（已标记 {{ selectedIds.size }} 个）</span>
          </p>
          <div class="sample-grid">
            <div v-for="s in matchedSamples.slice((samplePage-1)*samplePageSize, samplePage*samplePageSize)" :key="s.sample_id"
              class="sample-item" :class="{ selected: selectedIds.has(s.sample_id) }"
              @click="toggleSelect(s.sample_id)" @dblclick="$router.push({name:'SampleDetail', params:{id:s.sample_id}})">
              <div class="thumb-row">
                <div v-for="img in s.images.slice(0,4)" :key="img.resource_id" class="mini-thumb" :class="img.modality">
                  <img :src="img.thumbnail" @error="e=>e.target.style.display='none'" />
                </div>
              </div>
              <div class="sample-meta">
                <span>#{{ s.sample_id }}</span>
                <span>{{ s.scene }}</span>
                <span>{{ s.modality_count }}模态</span>
              </div>
            </div>
          </div>
          <el-pagination v-if="hitCount > samplePageSize" background layout="prev, pager, next"
            :total="hitCount" :page-size="samplePageSize" :current-page="samplePage"
            @current-change="samplePage = $event" style="margin-top:12px;justify-content:center;" />
        </div>
      </div>
      <div class="card" v-if="hitCount > 0"><h3>子集划分</h3>
        <div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;">
          <span>训练集</span><el-input-number v-model="split.train" :min="0" :max="99 - split.val" @change="split.test = 100 - split.train - split.val" style="width:120px;" /> %
          <span>验证集</span><el-input-number v-model="split.val" :min="1" :max="99 - split.train" @change="split.test = 100 - split.train - split.val" style="width:120px;" /> %
          <span style="color:#6b7280;">测试集 = 100 - 训练 - 验证 = {{ split.test }}%</span>
        </div>
        <el-radio-group v-model="split.strategy">
            <el-radio value="random">随机划分</el-radio>
            <span style="color:#94a3b8;font-size:12px;margin-left:4px;">（所有图片随机打乱后按比例切分，适用于单模态数据集）</span>
            <el-radio value="grouped" style="margin-left:16px;">按样本分组</el-radio>
            <span style="color:#94a3b8;font-size:12px;margin-left:4px;">（同一时刻采集的多模态图片作为整体分配到同一子集，适用于多模态数据集）</span>
          </el-radio-group>
      </div>
      <div class="card" v-if="hitCount > 0">

  <h3>数据集信息</h3>

  <div class="dataset-form">

    <el-input
      v-model="datasetName"
      placeholder="数据集名称"
    />

  </div>

  <div class="action-bar">

    <el-button
      type="primary"
      size="large"
      @click="onCreate"
    >
      创建数据集
    </el-button>

    <el-button
      type="warning"
      size="large"
      :disabled="!datasetId"
      @click="onSubmitReview"
    >
      提交公开申请
    </el-button>

  </div>

</div>
      <div
          class="success-card"
          v-if="datasetId"
          >

          <h3>✅ 数据集创建成功</h3>

          <p>数据集ID：<strong>{{ datasetId }}</strong></p>

          </div>
    </el-tab-pane>

    <!-- ====== 方式二：从本地上传 ====== -->
    <el-tab-pane label="从本地上传" name="upload">
      <div class="card"><h3>上传文件</h3>
        <div class="upload-zone" @dragover.prevent @drop.prevent="onDrop">
          <p>📁 将图片文件拖拽到此处，或点击下方按钮选择</p>
          <p class="hint">支持 JPG / PNG 格式，可批量上传</p>
          <el-upload :auto-upload="false" multiple drag @change="onFileChange">
            <el-button type="primary">选择文件</el-button>
          </el-upload>
        </div>
        <div class="upload-options" style="margin-top:16px;">
          <el-checkbox v-model="uploadOpts.withAnnotation">同时上传标注文件</el-checkbox>
          <el-select v-if="uploadOpts.withAnnotation" v-model="uploadOpts.format" placeholder="标注格式" style="width:160px;margin-left:8px;">
            <el-option label="COCO JSON" value="coco" /><el-option label="VOC XML" value="voc" /><el-option label="YOLO TXT" value="yolo" />
          </el-select>
        </div>
        <div v-if="uploadFiles.length > 0" style="margin-top:12px;">
          <p>已选择 {{ uploadFiles.length }} 个文件</p>
          <div class="file-list">
            <span v-for="f in uploadFiles.slice(0,10)" :key="f.name" class="file-tag">{{ f.name }}</span>
            <span v-if="uploadFiles.length > 10">...等</span>
          </div>
        </div>
      </div>
      <div class="card">
        <el-input v-model="datasetName2" placeholder="数据集名称" style="width:260px;margin-right:12px;" />
        <el-select v-model="uploadOpts.modality" placeholder="模态类型" style="width:160px;margin-right:12px;">
          <el-option v-for="m in modalities" :key="m" :label="modLabel(m)" :value="m" />
        </el-select>
        <el-button type="primary" @click="onUploadCreate">上传并创建数据集</el-button>
      </div>
      <div class="card" v-if="uploadDone">
        <p>数据集已创建，ID: {{ datasetId }}，状态: {{ statusText }}</p>
        <el-button type="success" :disabled="!datasetId" @click="onFreeze">冻结</el-button>
        <el-button type="warning" :disabled="!datasetId" @click="onPublish">发布</el-button>
      </div>
    </el-tab-pane>
  </el-tabs>
</div>
</div>
</template>

<script>
export default { name: 'DatasetBuild' }
</script>
<script setup>
import { ref, reactive, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDataList } from '@/api/data'
import { createDataset, submitForReview } from '@/api/dataset'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
function resetAll() {
  // 筛选条件
  filters.modality = []; filters.scene = []; filters.timeRange = null
  // 查询结果
  hitCount.value = null; matchedSamples.value = []; selectedIds.value = new Set()
  samplePage.value = 1; sampleCount.value = 20
  // 数据集信息
  datasetId.value = null
  datasetName.value = ''
  // 子集划分
  split.train = 70; split.val = 20; split.test = 10; split.strategy = 'random'
  // 本地上传
  uploadFiles.value = []; uploadDone.value = false
  datasetName2.value = ''
  uploadOpts.withAnnotation = false; uploadOpts.format = 'coco'; uploadOpts.modality = 'visible'
}

onActivated(() => {
  if (route.query.fresh === '1') {
    resetAll()
    // 清除 fresh 参数，避免从样本详情返回时再次重置
    router.replace({ query: {} })
  }
})
const activeTab = ref('platform')
const modalities = ['visible','infrared','mmwave','lidar']
const scenes = ['daytime','night','rainy','foggy']
const categoryList = [{id:1,name:'电线杆'},{id:2,name:'桥梁'},{id:3,name:'建筑物'},{id:4,name:'树木'},{id:5,name:'路灯'}]
function modLabel(m){ const map={visible:'可见光',infrared:'红外',mmwave:'毫米波',lidar:'激光雷达'}; return map[m]||m }
// ---- 方式一：平台数据 ----
const filters = reactive({ modality:[], scene:[], timeRange:null })
const split = reactive({ train:70, val:20, test:10, strategy:'random' })
const hitCount = ref(null)
const datasetName = ref('')
const datasetId = ref(null)
const matchedSamples = ref([])
const samplePage = ref(1)
const samplePageSize = ref(12)
const sampleCount = ref(20)
const selectedIds = ref(new Set())
function previewSelection() {
  const pool = [...matchedSamples.value]
  const n = Math.min(sampleCount.value, pool.length)
  const ids = new Set()
  for (let i = 0; i < n; i++) {
    const idx = Math.floor(Math.random() * pool.length)
    ids.add(pool.splice(idx, 1)[0].sample_id)
  }
  selectedIds.value = ids
  sampleCount.value = ids.size
}
function toggleSelect(id) {
  const s = new Set(selectedIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selectedIds.value = s
  sampleCount.value = s.size
}
async function onSearch() {
  if (!filters.modality || filters.modality.length === 0) {
    ElMessage.warning('请先选择至少一种模态类型')
    return
  }
  try {
    const { data } = await getDataList({ page: 1, size: 6000 })
    const items = (data.items || []).filter(item => item.meta_info?.sample_group)
    // 按 sample_group 分组为样本
    const groupMap = {}
    items.forEach(item => {
      const gid = item.meta_info.sample_group
      if (!groupMap[gid]) groupMap[gid] = {
        sample_id: gid, scene: item.meta_info.scene || '-', images: [],
        modality_count: 0, batch_id: item.meta_info.batch_id || '-'
      }
      groupMap[gid].images.push({
        resource_id: item.resource_id, modality: item.modality, name: item.name,
        thumbnail: `/api/images/${item.resource_id}/thumbnail`,
        annotation_status: item.annotation_status,
      })
      groupMap[gid].modality_count = groupMap[gid].images.length
    })
    let all = Object.values(groupMap)
    const f = filters
    // 筛选：样本必须包含所有选中模态
    if (f.modality?.length) all = all.filter(s => f.modality.every(m => s.images.some(img => img.modality === m)))
    if (f.scene?.length) all = all.filter(s => f.scene.includes(s.scene))
    // 去掉不需要的模态
    if (f.modality?.length) {
      all = all.map(s => ({
        ...s,
        images: s.images.filter(img => f.modality.includes(img.modality)),
        modality_count: s.images.filter(img => f.modality.includes(img.modality)).length
      }))
    }
    hitCount.value = all.length
    matchedSamples.value = all
    samplePage.value = 1
    sampleCount.value = Math.min(20, all.length)
  } catch { /* backend not ready */ }
}
async function onCreate(){
  if (selectedIds.value.size < 1) { ElMessage.warning('请至少选择1个样本'); return }
  const selected = matchedSamples.value.filter(s => selectedIds.value.has(s.sample_id))
  // 从选中样本中收集所有 resource_id
  const resourceIds = selected.flatMap(s => s.images.map(img => img.resource_id))
  const n = resourceIds.length
  try {
    const { data } = await createDataset({
      name: datasetName.value || '新建数据集',
      description: '',
      resource_ids: resourceIds,
      split_config: {
        train: split.train,
        val: split.val,
        test: split.test,
        strategy: split.strategy
      },
      visibility: 'private'
    })
    datasetId.value = data.dataset_id
    ElMessage.success(`已从 ${matchedSamples.value.length} 个样本中选取 ${selected.length} 个样本（${n} 个资源），数据集已创建，ID: ${data.dataset_id}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建数据集失败')
  }
}
async function onSubmitReview(){
  if (!datasetId.value) return
  try {
    await submitForReview(datasetId.value)
    ElMessage.success('已提交公开申请，等待审核员审批')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  }
}

// ---- 方式二：本地上传 ----
const uploadFiles = ref([])
const uploadOpts = reactive({ withAnnotation: false, format: 'coco', modality: 'visible' })
const datasetName2 = ref('')
const uploadDone = ref(false)
function onFileChange(file){ uploadFiles.value.push(file) }
function onDrop(e){ const files = Array.from(e.dataTransfer.files); uploadFiles.value.push(...files) }
function onUploadCreate(){ datasetId.value = Date.now(); statusText.value='draft'; uploadDone.value=true; ElMessage.success('数据集已创建（Mock）') }
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
  padding:45px 50px;
  margin-bottom:28px;
  border-radius:18px;
  color:white;
  background: linear-gradient(135deg, #0f172a, #1e3a8a);
  box-shadow: 0 10px 30px rgba(30,64,175,.18);
}

.hero h1{
    font-size:34px;
    font-weight:700;
    margin-bottom:12px;
}

.hero p{
    max-width:700px;
    line-height:1.8;
    opacity:.92;
}

.stats{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:22px;
    margin-bottom:30px;
}

.stat-card{
    background:white;
    border-radius:18px;
    padding:26px;
    text-align:center;
    box-shadow:
    0 8px 24px rgba(15,23,42,.05);
}

.stat-card h2{
    font-size:34px;
    color:#2563eb;
    margin:8px 0;
}

.stat-card span{
    color:#64748b;
}

.icon{
    font-size:30px;
}

.tabs{ margin-bottom:16px; }

.tabs-card{

background:white;

border-radius:22px;

margin-bottom:30px;

padding:28px;

box-shadow:
0 8px 24px rgba(15,23,42,.05);

}
.card{

background:white;

padding:26px;

border-radius:18px;

border:1px solid #e2e8f0;

box-shadow:

0 8px 24px rgba(15,23,42,.05);

margin-bottom:24px;

transition:.3s;

}

.card:hover{

transform:translateY(-3px);

box-shadow:

0 12px 30px rgba(15,23,42,.08);

}
.card h3{

font-size:18px;

font-weight:700;

margin-bottom:22px;

color:#1e293b;

}
.filter-row{

display:grid;

grid-template-columns:

repeat(auto-fit,minmax(220px,1fr));

gap:18px;

align-items:center;

}

.hit-info{

margin-top:22px;

padding:18px;

background:#eff6ff;

border-left:

5px solid #2563eb;

border-radius:12px;

font-size:15px;

color:#2563eb;

}

.success-card{

padding:24px;

background:#f0fdf4;

border:1px solid #86efac;

border-radius:16px;

}

.split-row{

display:grid;

grid-template-columns:

repeat(3,1fr);

gap:30px;

margin:20px 0;

}
.upload-zone{

padding:70px;

border-radius:18px;

border:2px dashed #3b82f6;

background:#f8fbff;

transition:.3s;

cursor:pointer;

}
.upload-zone:hover{

background:#eff6ff;

border-color:#2563eb;

}

.upload-zone .hint{ font-size:12px; color:#9ca3af; margin-top:4px; }
.file-list{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
.file-tag{

background:#dbeafe;

color:#2563eb;

padding:6px 12px;

border-radius:30px;

font-size:13px;

}
.dataset-form{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:16px;
}

.action-bar{
  display:flex;
  justify-content:flex-end;
  gap:16px;
  margin-top:26px;
}

:deep(.el-tabs__header){

    margin-bottom:28px;

}

:deep(.el-tabs__nav){

    background:white;

    border-radius:14px;

    padding:6px;

    box-shadow:
    0 8px 22px rgba(15,23,42,.05);

}

:deep(.el-tabs__item){

    height:46px;

    font-size:15px;

    font-weight:600;

}

:deep(.el-tabs__item.is-active){

    color:#2563eb;

}

:deep(.el-input__wrapper){

border-radius:10px;

}

:deep(.el-select__wrapper){

border-radius:10px;

}

:deep(.el-button){

border-radius:10px;

}

:deep(.el-date-editor){

width:100%;

}

:deep(.el-slider__runway){

margin:20px 0;

}
.sample-grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px; }
.sample-item{ background:#fff; border-radius:10px; padding:10px; cursor:pointer;
  border:2px solid #e5e7eb; transition:all .2s; }
.sample-item:hover{ border-color:#93c5fd; }
.sample-item.selected{ border-color:#3b82f6; background:#eff6ff; }
.thumb-row{ display:grid; grid-template-columns:1fr 1fr; gap:2px; margin-bottom:8px; }
.mini-thumb{ height:70px; background:#f3f4f6; border-radius:6px; overflow:hidden; }
.mini-thumb img{ width:100%; height:100%; object-fit:cover; }
.sample-meta{ display:flex; align-items:center; gap:8px; font-size:12px; color:#6b7280; }
</style>
