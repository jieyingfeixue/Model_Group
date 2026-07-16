<template>
<div class="page"><h2>数据集构建</h2>

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
          <el-select v-model="filters.annotation_status" placeholder="标注状态" clearable>
            <el-option label="全部" value="" /><el-option label="已标注" value="annotated" /><el-option label="未标注" value="unannotated" />
          </el-select>
          <el-select v-model="filters.labels" placeholder="标签类别" multiple clearable>
            <el-option v-for="c in categoryList" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-date-picker v-model="filters.timeRange" type="daterange" range-separator="至" start-placeholder="开始" end-placeholder="结束" />
          <el-button type="primary" @click="onSearch">查询</el-button>
        </div>
        <div class="hit-info" v-if="hitCount !== null">命中 <strong>{{ hitCount }}</strong> 个样本</div>
      </div>
      <div class="card" v-if="hitCount > 0"><h3>子集划分</h3>
        <div class="split-row">
          <span>训练集</span><el-slider v-model="split.train" :max="100-split.val-split.test" show-input style="flex:1;margin:0 12px;" />
          <span>验证集</span><el-slider v-model="split.val" :max="100-split.train-split.test" show-input style="flex:1;margin:0 12px;" />
          <span>测试集</span><el-slider v-model="split.test" :max="100-split.train-split.val" show-input style="flex:1;margin:0 12px;" />
        </div>
        <p>训练: {{ split.train }}% | 验证: {{ split.val }}% | 测试: {{ split.test }}%</p>
        <el-radio-group v-model="split.strategy"><el-radio value="random">随机划分</el-radio><el-radio value="stratified">分层均衡</el-radio></el-radio-group>
      </div>
      <div class="card" v-if="hitCount > 0">
        <el-input v-model="datasetName" placeholder="数据集名称" style="width:260px;margin-right:12px;" />
        <el-input v-model="versionNote" placeholder="版本说明" style="width:260px;margin-right:12px;" />
        <el-button type="primary" @click="onCreate">创建数据集</el-button>
        <el-button type="success" :disabled="!datasetId" @click="onFreeze">冻结</el-button>
        <el-button type="warning" :disabled="!datasetId" @click="onPublish">发布</el-button>
      </div>
      <div class="card" v-if="datasetId"><p>数据集已创建，ID: {{ datasetId }}，状态: {{ statusText }}</p></div>
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
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'

const activeTab = ref('platform')
const modalities = ['visible','infrared','mmwave','lidar']
const scenes = ['daytime','night','rainy','foggy']
const categoryList = [{id:1,name:'电线杆'},{id:2,name:'桥梁'},{id:3,name:'建筑物'},{id:4,name:'树木'},{id:5,name:'路灯'}]
function modLabel(m){ const map={visible:'可见光',infrared:'红外',mmwave:'毫米波',lidar:'激光雷达'}; return map[m]||m }

// ---- 方式一：平台数据 ----
const filters = reactive({ modality:[], scene:[], annotation_status:'', labels:[], timeRange:null, logic:'and' })
const split = reactive({ train:70, val:20, test:10, strategy:'random' })
const hitCount = ref(null)
const datasetName = ref('')
const versionNote = ref('')
const datasetId = ref(null)
const statusText = ref('draft')
function onSearch(){ hitCount.value = 320 }
function onCreate(){ datasetId.value = Date.now(); statusText.value='draft'; ElMessage.success('数据集已创建（Mock）') }
function onFreeze(){ statusText.value='frozen'; ElMessage.success('已冻结') }
function onPublish(){ statusText.value='published'; ElMessage.success('已发布') }

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
.page{ padding:24px; max-width:1200px; }
.tabs{ margin-bottom:16px; }
.card{ background:#fff; border-radius:8px; padding:20px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,.04); }
.card h3{ margin-bottom:12px; font-size:15px; }
.filter-row{ }
.filter-row>*{ display:block; width:100%; margin-bottom:12px; }
.hit-info{ margin-top:12px; font-size:14px; color:#6b7280; }
.split-row{ display:flex; align-items:center; }
.upload-zone{ border:2px dashed #d1d5db; border-radius:8px; padding:40px; text-align:center; }
.upload-zone .hint{ font-size:12px; color:#9ca3af; margin-top:4px; }
.file-list{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
.file-tag{ background:#f3f4f6; padding:2px 8px; border-radius:4px; font-size:12px; }</style>
