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
          <el-select v-model="filters.weather" placeholder="天气" clearable>
            <el-option label="全部" value="" />
            <el-option label="晴天" value="sunny" />
            <el-option label="雨天" value="rainy" />
            <el-option label="雾天" value="foggy" />
          </el-select>
          <el-select v-model="filters.time_of_day" placeholder="时段" clearable>
            <el-option label="全部" value="" />
            <el-option label="白天" value="day" />
            <el-option label="夜晚" value="night" />
          </el-select>
          <el-select v-model="filters.terrain" placeholder="地形" clearable>
            <el-option label="全部" value="" />
            <el-option label="山地" value="mountain" />
            <el-option label="平原" value="plain" />
            <el-option label="河流" value="river" />
          </el-select>
          <el-select v-model="filters.obstacle" placeholder="障碍物" clearable>
            <el-option label="全部" value="" />
            <el-option label="高压线塔" value="power_tower" />
            <el-option label="风力发电车" value="wind_turbine" />
            <el-option label="建筑物" value="building" />
          </el-select>
          <el-button type="primary" size="large" @click="onSearch">查询</el-button>
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
              @click="toggleSelect(s.sample_id)"
              @dblclick="$router.push({ name:'SampleDetail', params:{ id: String(s.group_no ?? s.sample_id) }, query:{ batch: s.batch_id || undefined } })">
              <div class="thumb-row">
                <div v-for="img in s.images.slice(0,4)" :key="img.resource_id" class="mini-thumb" :class="img.modality">
                  <img :src="img.thumbnail" @error="e=>e.target.style.display='none'" />
                </div>
              </div>
              <div class="sample-meta">
                <span>#{{ s.group_no ?? s.sample_id }}</span>
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
        <p style="margin:0 0 12px;color:#64748b;font-size:13px;">
          已选 <b style="color:#3b82f6;">{{ selectedIds.size }}</b> 个样本（至少 10 个）
        </p>
        <el-radio-group v-model="split.mode" style="margin-bottom:14px;" @change="onSplitModeChange">
          <el-radio value="tenths">十分制自动划分</el-radio>
          <el-radio value="count" style="margin-left:16px;">按数量手动划分</el-radio>
        </el-radio-group>

        <div v-if="split.mode === 'tenths'" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;">
          <span>训练集</span>
          <el-input-number
            v-model="split.train"
            :min="0"
            :max="10 - split.val"
            :step="1"
            :precision="0"
            @change="onTenthsChange"
            style="width:110px;"
          />
          <span style="color:#94a3b8;">/10</span>
          <span>验证集</span>
          <el-input-number
            v-model="split.val"
            :min="0"
            :max="10 - split.train"
            :step="1"
            :precision="0"
            @change="onTenthsChange"
            style="width:110px;"
          />
          <span style="color:#94a3b8;">/10</span>
          <span style="color:#6b7280;">测试集 = {{ split.test }}/10</span>
          <span v-if="selectedIds.size >= 10" style="color:#94a3b8;font-size:12px;width:100%;">
            预览：训练 {{ tenthsPreview.train }} · 验证 {{ tenthsPreview.val }} · 测试 {{ tenthsPreview.test }}
          </span>
        </div>

        <div v-else style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;">
          <span>训练集</span>
          <el-input-number
            v-model="split.trainCount"
            :min="0"
            :max="Math.max(0, selectedIds.size - split.valCount)"
            :step="1"
            :precision="0"
            @change="onCountChange"
            style="width:120px;"
          />
          <span>个</span>
          <span>验证集</span>
          <el-input-number
            v-model="split.valCount"
            :min="0"
            :max="Math.max(0, selectedIds.size - split.trainCount)"
            :step="1"
            :precision="0"
            @change="onCountChange"
            style="width:120px;"
          />
          <span>个</span>
          <span :style="{ color: countTest < 0 ? '#ef4444' : '#6b7280' }">
            测试集 = {{ countTest }} 个
          </span>
          <span style="color:#94a3b8;font-size:12px;width:100%;">
            训练 + 验证 + 测试须等于已选样本数 {{ selectedIds.size }}
          </span>
        </div>
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

          <p>数据集ID：<strong>{{ datasetId }}</strong>（已就绪，可直接提交公开申请）</p>

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
        <el-button type="warning" :disabled="!datasetId" @click="onSubmitReview">提交公开申请</el-button>
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
import { ref, reactive, computed, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDataList } from '@/api/data'
import { createDataset, submitForReview } from '@/api/dataset'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()

function resetAll() {
  filters.modality = []
  filters.weather = ''
  filters.time_of_day = ''
  filters.terrain = ''
  filters.obstacle = ''
  hitCount.value = null
  matchedSamples.value = []
  selectedIds.value = new Set()
  samplePage.value = 1
  sampleCount.value = 20
  datasetId.value = null
  datasetName.value = ''
  split.mode = 'tenths'
  split.train = 7
  split.val = 2
  split.test = 1
  split.trainCount = 0
  split.valCount = 0
  uploadFiles.value = []
  uploadDone.value = false
  datasetName2.value = ''
  uploadOpts.withAnnotation = false
  uploadOpts.format = 'coco'
  uploadOpts.modality = 'visible'
  statusText.value = 'frozen'
}

onActivated(() => {
  if (route.query.fresh === '1') {
    resetAll()
    router.replace({ query: {} })
  }
})

const activeTab = ref('platform')
const modalities = ['visible', 'infrared', 'mmwave', 'lidar']
function modLabel(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
const statusText = ref('frozen')
const statusLabel = computed(() => {
  if (!datasetId.value) return '未创建'
  const map = {
    frozen: '已就绪',
    published: '已发布',
    draft: '已就绪',
  }
  return map[statusText.value] || statusText.value || '已就绪'
})

const filters = reactive({
  modality: [],
  weather: '',
  time_of_day: '',
  terrain: '',
  obstacle: '',
})
const split = reactive({
  mode: 'tenths',
  train: 7,
  val: 2,
  test: 1,
  trainCount: 0,
  valCount: 0,
})

function onTenthsChange() {
  const t = Math.max(0, Math.min(10, Math.floor(Number(split.train) || 0)))
  const v = Math.max(0, Math.min(10 - t, Math.floor(Number(split.val) || 0)))
  split.train = t
  split.val = v
  split.test = 10 - t - v
}

const tenthsPreview = computed(() => {
  const n = selectedIds.value.size
  if (n < 10) return { train: 0, val: 0, test: 0 }
  const train = Math.floor((n * split.train) / 10)
  const val = Math.floor((n * split.val) / 10)
  return { train, val, test: n - train - val }
})

const countTest = computed(() => selectedIds.value.size - (Number(split.trainCount) || 0) - (Number(split.valCount) || 0))

function onCountChange() {
  const n = selectedIds.value.size
  let train = Math.max(0, Math.floor(Number(split.trainCount) || 0))
  let val = Math.max(0, Math.floor(Number(split.valCount) || 0))
  if (train + val > n) {
    if (train > n) train = n
    val = Math.min(val, Math.max(0, n - train))
  }
  split.trainCount = train
  split.valCount = val
}

function onSplitModeChange(mode) {
  if (mode === 'count' && selectedIds.value.size >= 10) {
    const p = tenthsPreview.value
    split.trainCount = p.train
    split.valCount = p.val
  }
}
const hitCount = ref(null)
const datasetName = ref('')
const datasetId = ref(null)
const matchedSamples = ref([])
const samplePage = ref(1)
const samplePageSize = ref(15)
const sampleCount = ref(20)
const selectedIds = ref(new Set())

async function fetchAllResources(filterParams = {}) {
  const pageSizeApi = 6000
  let page = 1
  let items = []
  let apiTotal = Infinity
  while (items.length < apiTotal) {
    const { data } = await getDataList({
      ...filterParams,
      page,
      size: pageSizeApi,
    })
    apiTotal = Number(data?.total ?? 0)
    const chunk = data?.items || []
    if (!chunk.length) break
    items = items.concat(chunk)
    if (chunk.length < pageSizeApi) break
    page += 1
  }
  return items
}

function sampleKey(meta) {
  return `${meta?.batch_id || 'unknown'}::${meta?.sample_group}`
}

function buildSampleGroups(rawItems) {
  const groupMap = {}
  rawItems
    .filter(item => item.meta_info?.sample_group != null)
    .forEach(item => {
      const meta = item.meta_info || {}
      const gid = sampleKey(meta)
      if (!groupMap[gid]) {
        groupMap[gid] = {
          sample_id: gid,
          group_no: meta.sample_group,
          scene: meta.scene || '-',
          batch_id: meta.batch_id || '',
          images: [],
          modality_count: 0,
          _seenResource: new Set(),
          _seenSensor: new Set(),
        }
      }
      const g = groupMap[gid]
      if (g._seenResource.has(item.resource_id)) return
      const sensorKey = meta.sensor || `${item.modality}:${item.name}`
      if (g._seenSensor.has(sensorKey)) return
      g._seenResource.add(item.resource_id)
      g._seenSensor.add(sensorKey)
      g.images.push({
        resource_id: item.resource_id,
        modality: item.modality,
        name: item.name,
        sensor: meta.sensor || '',
        thumbnail: `/api/images/${item.resource_id}/thumbnail`,
        annotation_status: item.annotation_status,
      })
      g.modality_count = new Set(g.images.map(i => i.modality)).size
    })
  return Object.values(groupMap).map(({ _seenResource, _seenSensor, ...rest }) => rest)
}

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
    // 场景条件与数据浏览一致；再按模态取全部分页并分组
    const sceneParams = {
      weather: filters.weather || undefined,
      time_of_day: filters.time_of_day || undefined,
      terrain: filters.terrain || undefined,
      obstacle: filters.obstacle || undefined,
    }
    let rawItems = []
    for (const m of filters.modality) {
      const chunk = await fetchAllResources({ ...sceneParams, modality: m })
      rawItems = rawItems.concat(chunk)
    }
    let all = buildSampleGroups(rawItems)
    if (filters.modality.length > 1) {
      all = all.filter(s => filters.modality.every(m => s.images.some(img => img.modality === m)))
    }
    all = all.map(s => {
      const images = s.images.filter(img => filters.modality.includes(img.modality))
      return {
        ...s,
        images,
        modality_count: new Set(images.map(i => i.modality)).size,
      }
    })
    hitCount.value = all.length
    matchedSamples.value = all
    selectedIds.value = new Set()
    samplePage.value = 1
    sampleCount.value = Math.min(20, all.length)
  } catch {
    ElMessage.error('查询失败')
  }
}
async function onCreate(){
  const selectedCount = selectedIds.value.size
  if (selectedCount < 10) {
    ElMessage.warning('请至少选择 10 个样本后再创建数据集')
    return
  }
  if (split.mode === 'tenths') {
    onTenthsChange()
    if (split.train + split.val + split.test !== 10) {
      ElMessage.warning('十分制划分要求训练/验证/测试份数之和为 10')
      return
    }
  } else {
    onCountChange()
    const test = countTest.value
    if (split.trainCount < 0 || split.valCount < 0 || test < 0) {
      ElMessage.warning('子集数量不能为负数')
      return
    }
    if (split.trainCount + split.valCount + test !== selectedCount) {
      ElMessage.warning(`训练+验证+测试必须等于已选样本数 ${selectedCount}`)
      return
    }
  }
  const selected = matchedSamples.value.filter(s => selectedIds.value.has(s.sample_id))
  // 从选中样本中收集所有 resource_id
  const resourceIds = selected.flatMap(s => s.images.map(img => img.resource_id))
  const n = resourceIds.length
  const split_config = {
    mode: split.mode,
    strategy: 'grouped',
  }
  if (split.mode === 'tenths') {
    split_config.train = split.train
    split_config.val = split.val
    split_config.test = split.test
  } else {
    split_config.train_count = split.trainCount
    split_config.val_count = split.valCount
    split_config.test_count = countTest.value
  }
  try {
    const { data } = await createDataset({
      name: datasetName.value || '新建数据集',
      description: '',
      resource_ids: resourceIds,
      split_config,
      visibility: 'private'
    })
    datasetId.value = data.dataset_id
    statusText.value = data.status || 'frozen'
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
function onUploadCreate(){ datasetId.value = Date.now(); statusText.value='frozen'; uploadDone.value=true; ElMessage.success('数据集已创建（Mock）') }
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
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.filter-row > .el-select {
  width: 150px;
}
.filter-row > .el-select:first-child {
  width: 180px;
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
