// 共享数据集状态 — 构建数据集后写入，我的数据集和数据集详情页面读取
export const sharedDatasets = [
  { dataset_id:1, name:'我的低空障碍物检测数据集 v1.0', version:'v1.0', sample_count:320, status:'draft', archive_status:'active', visibility:'private', created_at:'2024-06-15' },
  { dataset_id:2, name:'红外夜间场景数据集', version:'v1.1', sample_count:150, status:'frozen', archive_status:'active', visibility:'private', created_at:'2024-06-20' },
  { dataset_id:3, name:'多模态融合数据集 v2.0', version:'v2.0', sample_count:500, status:'published', archive_status:'active', visibility:'public', created_at:'2024-07-01' },
]