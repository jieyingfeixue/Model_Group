# LH 数据集配置说明

`Auto-labeling-LH` 是 `Auto-labeling` 的 LH 数据集专用分支。本目录下所有改动都
**只服务于 LH（多模态数据库）数据集**，K-Radar 相关支持已被剥离。

参考数据集路径：`D:/Dataset/多模态数据库/{scene_id}/`（`scene_id` = `1, 2, ...`）

## 数据集顶层结构

```
多模态数据库/
└── 1/                                                # scene_id
    ├── readme.md
    ├── with_cameras_capture_*_mmwave_udp.bin           # 原始 UDP 包
    ├── mmwave_mat_1218style/
    │   ├── mmwave_*_AntFrameNNN_FZxxxxxx-yyyyyy.mat     # 雷达 cube (~95)
    │   └── mmwave_*_AntFrameNNN_FZxxxxxx-yyyyyy.png     # 伪彩图
    └── segment_<idx>_<t_start>_<t_end>/                # 同步切分子段
        ├── images/
        │   ├── hikrobot_camera__DA8679037__image_raw/*.jpg # 主相机 1
        │   ├── hikrobot_camera__DA8679038__image_raw/*.jpg # 主相机 2
        │   └── usb_ir__image_raw/*.jpg                     # IR 辅助
        ├── pointclouds/
        │   └── at360__points/at360__points_NNNNNN_t*.pcd   # LiDAR (~261 帧)
        ├── gps/         nav100__fix/...
        ├── heading/     nav100__heading/...
        └── nav100_state/nav100__state/nav100__state.csv    # 时间戳基准
```

要点：

- **包含 LiDAR**（`at360__points`，`.pcd`），与之前理解不同，已在 profile 中加入
- Scene 是顶层单元；segment 是同步切片后的子段，一个 scene 可含多个 segment
- **无 `mat_to_image_range.csv`** — 通过文件名内的 `_tNNNNNN.NNN` 时间戳与
  `nav100__state.csv` 基准做最近邻对齐（mmwave / lidar / image 三者）
- 主相机与雷达为多对一：~95 个 mat 对 ~765 张 image 对 ~261 帧 pcd

## 配置文件清单

| 文件 | 作用 |
| --- | --- |
| [config/default.yaml](../config/default.yaml) | 应用全局配置；`dataset.root` 指向 `D:/Dataset/多模态数据库`，新增 `dataset.scene_id: "1"`，`default_profile: lh`，`export.default_format: lh` |
| [profiles/lh.yaml](../profiles/lh.yaml) | LH 传感器 profile（sensors / frame_sync / sequences 骨架） |
| [profiles/lh_calib_overrides.json](../profiles/lh_calib_overrides.json) | 标定覆盖项占位（含主相机 / IR / at360 LiDAR / mmwave） |

## 后续待办（仅在 `Auto-labeling-LH` 内进行）

1. **标定数值**：填充 `profiles/lh.yaml` 和 `lh_calib_overrides.json` 中所有
   `0.0 / null / TODO` 字段。建议以 `lidar_at360` 为 ego 原点。
2. **adapter**：在 `src/io/adapters/` 新增 `lh_adapter.py`：
   - 扫描 `{dataset_root}/{scene_id}/segment_*/` 生成序列列表
   - 以主相机 1 的 jpg 顺序为锚生成 `frame_id`
   - 从文件名 `_t(\d+\.\d+)` 提取时间戳，并读 `nav100__state.csv` 作为基准
   - 最近邻匹配：image_t ↔ lidar_t (`at360__points_*.pcd`) ↔ mmwave_t
     （mmwave 以 AntFrame 起始 FZ 序号估算时间中心）
   - 读 `*.mat` 参考数据集发布方提供的旧脚本
     （如 `plot_1218style_mats.py` / `parse_mmwave_v2.py`）
3. **label IO**：`src/io/label_io.py` 增加 `lh` format。
4. **export writer**：`src/export/lh_writer.py`，对接 `default_format: "lh"`。
5. **UI**：加入 scene 选择器（按 `1, 2, ...` 列出）与 segment 子选择器。

> 在以上工作完成前，`python run.py` 启动后选择 `lh` profile 会触发未实现路径，
> 提示信息会指向本文件。
