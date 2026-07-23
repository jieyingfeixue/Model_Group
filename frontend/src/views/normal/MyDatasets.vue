<template>
<div class="page">
  <!-- Hero -->
  <div class="hero">
    <div>
      <h1>📚 我的数据集</h1>
      <p>
        管理个人创建的数据集，
        支持冻结、发布、归档及版本管理。
      </p>
    </div>

  </div>
  <!-- 统计 -->
  <div class="stats">
    <div class="stat-card">
      <div class="icon">📦</div>
      <h2>{{ datasets.length }}</h2>
      <span>数据集总数</span>
    </div>
    <div class="stat-card">
      <div class="icon">🚀</div>
      <h2>{{ datasets.filter(d=>d.status==='published').length }}</h2>
      <span>已发布</span>
    </div>

    <div class="stat-card">
      <div class="icon">📝</div>
      <h2>{{ datasets.filter(d=>d.status==='draft').length }}</h2>
      <span>草稿</span>
    </div>
  </div>

  <div class="toolbar">
      <div class="left">
          <el-button
              type="primary"
              size="large"
              @click="$router.push({path:'/datasets/build', query:{fresh:'1'}})"
          >
              + 构建数据集
          </el-button>
      </div>

      <div class="right">
          <el-select
              v-model="filter.status"
              placeholder="状态筛选"
              clearable
              style="width:160px"
          >
              <el-option label="全部" value=""/>
              <el-option label="草稿" value="draft"/>
              <el-option label="已冻结" value="frozen"/>
              <el-option label="已发布" value="published"/>
              <el-option label="已归档" value="archived"/>
          </el-select>
      </div>
  </div>

  <div class="table-card">
    <el-table :data="datasets" style="margin-top:12px;">
      <el-table-column prop="name" label="数据集名称" />
      <el-table-column prop="version" label="版本" width="80" header-align="center" align="center" />
      <el-table-column prop="sample_count" label="样本数" width="100" header-align="center" align="center" />
      <el-table-column prop="status" label="状态" width="100" header-align="center" align="center">
        <template #default="{row}"><el-tag
        :type="statusType(row.status)"
        round
        effect="light"
        >
        {{row.status}}
        </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="visibility" label="可见范围" width="100" header-align="center" align="center" />
      <el-table-column prop="created_at" label="创建时间" width="120" header-align="center" align="center" />
      <el-table-column label="操作" width="280" header-align="center" align="center">
        <template #default="{ row }">

          <!-- 详情 -->
          <el-button
            size="small"
            plain
            @click="$router.push('/datasets/' + row.dataset_id)"
          >
            详情
          </el-button>

          <!-- 冻结 -->
          <el-button
            v-if="row.status === 'draft'"
            size="small"
            type="success"
            round
            @click="onFreeze(row)"
          >
            冻结
          </el-button>

          <!-- 发布 -->
          <el-button
            v-if="row.status === 'frozen'"
            size="small"
            type="warning"
            round
            @click="onPublish(row)"
          >
            发布
          </el-button>

          <!-- 归档 -->
          <el-button
            v-if="row.archive_status !== 'archived'"
            size="small"
            type="danger"
            plain
            round
            @click="onArchive(row)"
          >
            归档
          </el-button>
          <el-button
            v-else
            size="small"
            type="success"
            round
            @click="onRestore(row)"
          >
            恢复
          </el-button>

        </template>
      </el-table-column>
    </el-table>
  </div>
  <el-empty v-if="datasets.length===0" description="暂无数据集，点击上方构建第一个数据集" />
</div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { sharedDatasets } from '@/mock/data'
const filter = reactive({ status: '' })
const datasets = ref(sharedDatasets)
function statusType(s){ const map={draft:'info',frozen:'warning',published:'success'}; return map[s]||'info' }
function onFreeze(row){ row.status='frozen'; ElMessage.success('已冻结') }
function onPublish(row){ row.status='published'; row.visibility='public'; ElMessage.success('已发布') }
function onArchive(row){ row.archive_status='archived'; ElMessage.success('已归档') }
function onRestore(row){ row.archive_status='active'; ElMessage.success('已恢复') }
</script>

<style scoped>
.page{
  padding:28px;
  max-width:1450px;
  margin:auto;
  background:#f8fafc;
  min-height:100vh;
}
.toolbar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:24px;
}
h2{ margin-bottom:16px; }
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
  margin-bottom:10px;
}

.hero p{
  font-size:16px;
  opacity:.92;
  line-height:1.8;
}
.stats{
  display:grid;
  grid-template-columns:
  repeat(3,1fr);
  gap:22px;
  margin-bottom:30px;
}

.stat-card{
  background:white;
  border-radius:18px;
  padding:28px;
  text-align:center;
  box-shadow:
  0 8px 22px rgba(15,23,42,.05);
  transition:.3s;
}

.stat-card:hover{transform:translateY(-6px);}

.icon{
  font-size:30px;
  margin-bottom:12px;
}

.stat-card h2{
  font-size:34px;
  color:#2563eb;
  margin-bottom:8px;
}

.stat-card span{color:#64748b;}

.table-card{
  background:white;
  padding:20px;
  border-radius:20px;
  box-shadow:
  0 8px 24px rgba(15,23,42,.06);
}
</style>
