// 为以下标注框预生成类别：电线杆、桥梁、建筑物、树木、路灯
const bboxTemplates = [
  { category_id: 1, category_name: '电线杆', depth: 15.2, occlusion: 'none', truncation: 'none' },
  { category_id: 2, category_name: '桥梁', depth: 45.0, occlusion: 'none', truncation: 'none' },
  { category_id: 3, category_name: '建筑物', depth: 32.5, occlusion: 'partial', truncation: 'none' },
  { category_id: 4, category_name: '树木', depth: 8.7, occlusion: 'none', truncation: 'edge' },
  { category_id: 5, category_name: '路灯', depth: 12.1, occlusion: 'none', truncation: 'none' },
]

function makeBboxes(seed) {
  const count = (seed % 4) + 1
  const boxes = []
  for (let i = 0; i < count; i++) {
    const t = bboxTemplates[(seed + i) % bboxTemplates.length]
    boxes.push({
      x: 0.1 + (i * 0.25),
      y: 0.15 + (i * 0.15),
      w: 0.12,
      h: 0.22,
      ...t
    })
  }
  return boxes
}

const modalities = ['visible', 'infrared', 'mmwave', 'lidar']
const scenes = ['daytime', 'night', 'rainy', 'foggy']
const sources = ['无人机采集-批次2024Q1', '无人机采集-批次2024Q2', '无人机采集-批次2024Q3']

export function generateDataResources(count = 24) {
  const items = []
  for (let i = 0; i < count; i++) {
    const modality = modalities[i % 4]
    const isAnnotated = i % 3 !== 0
    const scene = scenes[i % 4]
    items.push({
      resource_id: i + 1,
      name: `${modality}_${String(i + 1).padStart(4, '0')}.jpg`,
      owner_id: 1,
      modality,
      file_path: `data/2024/${modality}/${modality}_${String(i + 1).padStart(4, '0')}.jpg`,
      metadata: {
        width: 1920,
        height: 1080,
        channels: 3,
        file_size: `${(200 + i * 50)}KB`,
        device: 'DJI Mavic 3',
        scene,
        weather: i % 2 === 0 ? 'clear' : 'cloudy',
        time_of_day: scene === 'night' ? 'night' : 'day',
        geo_location: '30.5N, 114.3E',
        batch_id: `2024Q${(i % 3) + 1}`,
        source: sources[i % 3],
      },
      version: isAnnotated ? (i % 5) + 1 : 1,
      annotation_status: isAnnotated ? 'annotated' : 'unannotated',
      status: 'active',
      bboxes: isAnnotated ? makeBboxes(i) : [],
      created_at: new Date(2024, 2, i + 1).toISOString(),
      updated_at: new Date(2024, 6, i + 1).toISOString(),
    })
  }
  return items
}

export function generateVersions(resourceId) {
  const versions = []
  for (let v = 1; v <= 3; v++) {
    versions.push({
      version_id: resourceId * 10 + v,
      resource_id: resourceId,
      version_number: v,
      change_note: v === 1 ? '初始导入' : v === 2 ? '元信息补充修改' : '标注结果更新',
      metadata_snapshot: { scene: scenes[resourceId % 4], weather: 'clear' },
      created_by: 1,
      created_at: new Date(2024, 2, v * 10).toISOString(),
    })
  }
  return versions
}

export function generateDatasets(count = 8) {
  const items = []
  for (let i = 0; i < count; i++) {
    items.push({
      dataset_id: i + 1,
      name: `低空多模态障碍物检测数据集 v${i + 1}.0`,
      description: '包含城市和高速场景的多模态障碍物标注数据',
      owner_id: i % 2 === 0 ? 1 : 2,
      modality: modalities[i % 4],
      sample_count: 200 + i * 50,
      status: 'published',
      visibility: 'public',
      is_official: i < 3,
      review_status: i < 3 ? 'reviewed' : 'reviewed',
      created_at: new Date(2024, i, 1).toISOString(),
    })
  }
  return items
}

export const categoryLabels = bboxTemplates.map(t => ({
  id: t.category_id,
  name: t.category_name,
}))
