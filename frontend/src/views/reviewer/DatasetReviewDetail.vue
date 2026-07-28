<template>
<div class="page" v-if="dataset">
  <div class="top-bar"><el-button text @click="$router.back()">← 返回审核列表</el-button></div>

  <!-- Hero -->
  <div class="hero">
    <div>
      <h1>🔍 {{ dataset.name }}</h1>
      <p>数据集审核 · {{ dataset.sample_count }} 个样本</p>
    </div>
    <el-tag size="large" round type="primary">审核中</el-tag>
  </div>

  <!-- Stats -->
  <div class="stats">
    <div class="stat-card">
      <div class="icon">📦</div>
      <h2>{{ allSamples.length }}</h2>
      <span>样本总数</span>
    </div>
    <div class="stat-card">
      <div class="icon">👁</div>
      <h2>{{ shownIds.size + currentRound.length }}</h2>
      <span>已审核</span>
    </div>
    <div class="stat-card">
      <div class="icon">⚠️</div>
      <h2>{{ problemIds.size }}</h2>
      <span>已标记问题</span>
    </div>
  </div>

  <!-- Current Round Samples -->
  <div class="card" v-if="currentRound.length > 0">
    <h3>
      第 {{ roundNumber }} 轮审核
      <span style="font-weight:400;font-size:14px;color:#94a3b8;margin-left:12px">
        （本轮 {{ currentRound.length }} 个样本 · 点击样本可查看详情）
      </span>
    </h3>
    <div class="sample-grid">
      <div
        v-for="s in currentRound"
        :key="s.sample_id"
        class="sample-item"
        :class="{ 'is-problem': problemIds.has(s.sample_id) }"
        @click="openSample(s)"
      >
        <!-- Thumbnails -->
        <div class="thumb-row" :class="'n' + displayThumbs(s).length">
          <div
            v-for="img in displayThumbs(s)"
            :key="img.resource_id"
            class="mini-thumb"
            :class="img.modality"
          >
            <span class="mod-tag">{{ img._slotLabel }}</span>
            <img :src="img.thumbnail" loading="lazy" @error="onThumbError" />
          </div>
        </div>

        <!-- Sample Info -->
        <div class="sample-meta">
          <span>#{{ s.group_no ?? s.sample_id }}</span>
          <span v-if="s.scene && s.scene !== '-'">{{ s.scene }}</span>
          <span>{{ s.modality_count }}模态</span>
        </div>

        <!-- Problem Toggle (click stops propagation) -->
        <div class="problem-row" @click.stop>
          <el-switch
            v-model="s._marked"
            size="small"
            active-text="问题"
            inactive-text="正常"
            @change="onToggleProblem(s)"
          />
          <el-input
            v-if="s._marked"
            v-model="s._note"
            size="small"
            placeholder="问题描述（可选）"
            style="margin-top:6px"
          />
        </div>
      </div>
    </div>

  </div>

  <!-- Actions — always visible below sample grid -->
  <div class="card actions-card" v-if="currentRound.length > 0">
    <div class="actions">
      <el-button
        size="large"
        type="success"
        :disabled="allSamples.length === 0"
        @click="onApprove"
      >
        ✅ 通过数据集
      </el-button>
      <el-button
        size="large"
        type="warning"
        :disabled="shownIds.size + currentRound.length >= allSamples.length"
        @click="onContinue"
      >
        🔄 继续审核（{{ allSamples.length - shownIds.size - currentRound.length }} 个未查看）
      </el-button>
      <el-button
        size="large"
        type="danger"
        :disabled="allSamples.length === 0"
        @click="rejectVisible = true"
      >
        ❌ 驳回
      </el-button>
    </div>
    <p style="text-align:center;color:#94a3b8;font-size:13px;margin-top:12px">
      本轮 {{ currentRound.length }} 个样本 · {{ currentRound.filter(s => s._marked).length }} 个已标记 ·
      累计已审核 {{ shownIds.size + currentRound.length }} / {{ allSamples.length }}
    </p>
  </div>

  <!-- Reject Dialog -->
  <el-dialog v-model="rejectVisible" title="驳回数据集" width="550px">
    <p style="color:#64748b;margin-bottom:16px">
      请填写驳回原因，该数据集将被退回给提交者修改。
    </p>
    <el-input
      v-model="rejectReason"
      type="textarea"
      :rows="4"
      placeholder="请详细描述驳回原因，如：标注框偏移严重、红外图像质量不合格、数据脱敏不完整等"
    />
    <div style="margin-top:16px;color:#94a3b8;font-size:13px">
      已标记 {{ problemIds.size }} 个问题样本，驳回原因将一并记录。
    </div>
    <template #footer>
      <el-button @click="rejectVisible = false">取消</el-button>
      <el-button type="danger" @click="onReject" :disabled="!rejectReason.trim()">
        确认驳回
      </el-button>
    </template>
  </el-dialog>

  <!-- Loading -->
  <div v-if="loading" class="loading">加载样本数据中...</div>
</div>

<div v-else class="loading">加载数据集信息中...</div>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getDatasetDetail } from '@/api/dataset'
import request from '@/api/request'

const route = useRoute()
const router = useRouter()

// ─── Thumbnail helpers ───
const THUMB_SLOTS = [
  { modality: 'visible', prefer: 'DA8679037', label: '可见光' },
  { modality: 'infrared', prefer: null, label: '红外' },
  { modality: 'mmwave', prefer: null, label: '毫米波' },
  { modality: 'lidar', prefer: null, label: '激光雷达' },
]

function displayThumbs(sample) {
  const images = sample?.images || []
  const used = new Set()
  const result = []
  for (const slot of THUMB_SLOTS) {
    const candidates = images.filter(
      img => (img.modality || '') === slot.modality && !used.has(img.resource_id)
    )
    if (!candidates.length) continue
    let pick = candidates[0]
    if (slot.prefer) {
      const preferred = candidates.find(img =>
        String(img.sensor || img.name || '').includes(slot.prefer)
      )
      if (preferred) pick = preferred
    }
    used.add(pick.resource_id)
    result.push({ ...pick, _slotLabel: slot.label })
  }
  return result
}

function onThumbError(e) {
  e.target.style.opacity = '0.25'
}

function openSample(s) {
  const ids = (s.images || []).map(i => i.resource_id).filter(Boolean).join(',')
  router.push({
    name: 'SampleDetail',
    params: { id: String(s.group_no ?? s.sample_id) },
    query: {
      batch: s.batch_id || undefined,
      ids: ids || undefined,
    },
  })
}

// ─── State ───
const dataset = ref(null)
const loading = ref(false)
const allSamples = ref([])
const shownIds = reactive(new Set())
const problemIds = reactive(new Set())
const problemNotes = ref({})
const currentRound = ref([])
const roundNumber = ref(1)
const rejectVisible = ref(false)
const rejectReason = ref('')

// ─── Load Dataset ───
async function loadDataset(id) {
  if (!id) return
  dataset.value = null
  allSamples.value = []
  currentRound.value = []
  shownIds.clear()
  problemIds.clear()
  problemNotes.value = {}
  roundNumber.value = 1
  loading.value = true

  try {
    const { data } = await getDatasetDetail(id)
    dataset.value = data

    try {
      const res = await request.get(`/datasets/${id}/items`)
      const samples = (res.data?.samples || []).map(s => {
        const images = (s.resources || []).map(r => ({
          resource_id: r.resource_id,
          modality: r.modality,
          name: r.name,
          sensor: r.sensor || '',
          thumbnail: `/api/images/${r.resource_id}/thumbnail`,
          annotation_status: r.annotation_status,
        }))
        return {
          sample_id: s.sample_id || `${s.batch_id || 'unknown'}::${s.sample_group}`,
          group_no: s.sample_group,
          batch_id: s.batch_id || '',
          scene: s.scene || '-',
          modality_count: new Set(images.map(i => i.modality)).size,
          images,
          _marked: false,
          _note: '',
        }
      }).sort((a, b) => {
        const na = Number(a.group_no)
        const nb = Number(b.group_no)
        if (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) return na - nb
        return String(a.group_no ?? '').localeCompare(String(b.group_no ?? ''), undefined, { numeric: true })
      })
      allSamples.value = samples
      nextRound()
    } catch {
      allSamples.value = []
    }
  } catch {
    dataset.value = null
  } finally {
    loading.value = false
  }
}

// ─── Round Management ───
function nextRound() {
  // Add current round to shown set
  for (const s of currentRound.value) {
    shownIds.add(s.sample_id)
  }

  const unseen = allSamples.value.filter(s => !shownIds.has(s.sample_id))
  if (unseen.length === 0) {
    currentRound.value = []
    return
  }

  const count = Math.min(10, unseen.length)
  const shuffled = [...unseen].sort(() => Math.random() - 0.5)
  const picked = shuffled.slice(0, count)

  for (const s of picked) {
    s._marked = problemIds.has(s.sample_id)
  }

  currentRound.value = picked
}

function onToggleProblem(sample) {
  if (sample._marked) {
    problemIds.add(sample.sample_id)
    if (sample._note) problemNotes.value[sample.sample_id] = sample._note
  } else {
    problemIds.delete(sample.sample_id)
    delete problemNotes.value[sample.sample_id]
  }
}

// ─── Actions ───
async function onContinue() {
  // Save current round markings
  for (const s of currentRound.value) {
    if (s._marked) {
      problemIds.add(s.sample_id)
      if (s._note) problemNotes.value[s.sample_id] = s._note
    }
  }
  roundNumber.value++
  nextRound()
  scrollTo({ top: 0, behavior: 'smooth' })
}

async function onApprove() {
  for (const s of currentRound.value) {
    if (s._marked) {
      problemIds.add(s.sample_id)
      if (s._note) problemNotes.value[s.sample_id] = s._note
    }
  }

  const totalReviewed = shownIds.size + currentRound.value.length
  const notes = {
    action: 'approved',
    reviewed_count: totalReviewed,
    total_count: allSamples.value.length,
    problem_count: problemIds.size,
    problem_samples: problemIds.size > 0
      ? Array.from(problemIds).map(id => ({
          sample_id: id,
          note: problemNotes.value[id] || ''
        }))
      : []
  }

  try {
    await request.post(`/review/datasets/${dataset.value.dataset_id}/verdict`, {
      verdict: 'approved',
      notes: JSON.stringify(notes)
    })
    ElMessage.success('数据集审核已通过')
    router.push('/review/datasets')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function onReject() {
  if (!rejectReason.value.trim()) return

  for (const s of currentRound.value) {
    if (s._marked) {
      problemIds.add(s.sample_id)
      if (s._note) problemNotes.value[s.sample_id] = s._note
    }
  }

  const totalReviewed = shownIds.size + currentRound.value.length
  const notes = {
    action: 'rejected',
    reason: rejectReason.value.trim(),
    reviewed_count: totalReviewed,
    total_count: allSamples.value.length,
    problem_count: problemIds.size,
    problem_samples: problemIds.size > 0
      ? Array.from(problemIds).map(id => ({
          sample_id: id,
          note: problemNotes.value[id] || ''
        }))
      : []
  }

  try {
    await request.post(`/review/datasets/${dataset.value.dataset_id}/verdict`, {
      verdict: 'rejected',
      notes: JSON.stringify(notes)
    })
    ElMessage.success('数据集已驳回')
    rejectVisible.value = false
    router.push('/review/datasets')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

watch(() => route.params.id, (id) => { loadDataset(id) }, { immediate: true })
</script>

<style scoped>
.page{
  padding:30px;
  max-width:1450px;
  margin:auto;
  background:#f8fafc;
  min-height:100vh;
}
.top-bar{ margin-bottom:12px; }
.hero{
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:45px 50px;
  border-radius:18px;
  background:linear-gradient(135deg,#0f172a,#1e3a8a);
  color:white;
  margin-bottom:28px;
  box-shadow:0 10px 30px rgba(30,64,175,.18);
}
.hero h1{ font-size:34px; font-weight:700; margin-bottom:12px; }
.hero p{ font-size:16px; opacity:.92; line-height:1.8; }
.stats{
  display:grid;
  grid-template-columns: repeat(3, 1fr);
  gap:22px;
  margin-bottom:30px;
}
.stat-card{
  background:#fff; border-radius:18px; padding:28px; text-align:center;
  box-shadow:0 8px 22px rgba(15,23,42,.05); transition:.3s;
}
.stat-card:hover{ transform:translateY(-6px); }
.stat-card .icon{ font-size:30px; margin-bottom:12px; }
.stat-card h2{ font-size:34px; color:#2563eb; margin:8px 0; }
.stat-card span{ color:#64748b; font-size:14px; }

.card{
  background:white;
  padding:26px;
  border-radius:20px;
  box-shadow:0 8px 24px rgba(15,23,42,.06);
  margin-bottom:24px;
  transition:.3s;
}
.card h3{ margin-bottom:14px; font-size:18px; }

.sample-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:12px;
}
.sample-item{
  background:white;
  border-radius:16px;
  padding:12px;
  border:2px solid #e5e7eb;
  transition:.3s;
  box-shadow:0 4px 12px rgba(15,23,42,.04);
  cursor:pointer;
}
.sample-item:hover{
  transform:translateY(-4px);
  box-shadow:0 12px 28px rgba(15,23,42,.12);
}
.sample-item.is-problem{
  border-color:#ef4444;
  background:#fef2f2;
}
.thumb-row{ display:grid; gap:2px; margin-bottom:8px; background:#e2e8f0; border-radius:8px; overflow:hidden; padding:2px; }
.thumb-row.n1{ grid-template-columns:1fr; }
.thumb-row.n2{ grid-template-columns:1fr 1fr; }
.thumb-row.n3,
.thumb-row.n4{ grid-template-columns:1fr 1fr; }
.mini-thumb{
  position:relative;
  aspect-ratio:1;
  min-height:72px;
  border-radius:6px;
  overflow:hidden;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:12px;
  color:#fff;
  background:#0f172a;
}
.mini-thumb img{ width:100%; height:100%; object-fit:cover; }
.mod-tag{
  position:absolute; top:4px; left:4px; z-index:1;
  font-size:10px; padding:1px 6px; border-radius:8px;
  background:rgba(0,0,0,.55); color:#fff;
}
.sample-meta{ display:flex; gap:8px; font-size:12px; color:#6b7280; flex-wrap:wrap; margin-bottom:8px; }
.problem-row{
  border-top:1px solid #e5e7eb;
  padding-top:8px;
  margin-top:4px;
}

.actions-card{
  background:linear-gradient(135deg,#f0f9ff,#eff6ff);
  border:1px solid #bfdbfe;
}
.actions{
  display:flex;
  gap:16px;
  flex-wrap:wrap;
  justify-content:center;
}

.loading{ text-align:center; padding:60px; color:#9ca3af; }
</style>