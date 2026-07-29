# 带深度的 LabelMe 标注格式

导出工具：

```text
tools/export_labelme_depth.py
```

读取工具：

```text
tools/read_labelme_depth.py
```

输出保持原 LabelMe JSON 的目录、文件名、标签和框坐标不变。深度信息写入每个
`shapes[]` 的 `attributes`：

```json
{
  "label": "Power tower",
  "points": [[485.7, 92.9], [721.4, 981.4]],
  "shape_type": "rectangle",
  "attributes": {
    "depth_m": 1520.4,
    "depth_method": "gps_db_temporal",
    "depth_confidence": 0.98,
    "depth_support_points": 0,
    "depth_target_id": "osm_tower_1661526675"
  }
}
```

无法可靠匹配时：

```json
"attributes": {
  "depth_m": null,
  "depth_method": "no_bin_target_in_box_fov",
  "depth_confidence": 0.0,
  "depth_support_points": 0
}
```

Python 读取：

```python
from tools.read_labelme_depth import iter_depth_boxes

for box in iter_depth_boxes("annotation.json"):
    print(box["label"], box["depth_m"])
```

命令行读取：

```powershell
python tools/read_labelme_depth.py "L:\LH_data_all_sensor_annotations_depth" --limit 10
```
