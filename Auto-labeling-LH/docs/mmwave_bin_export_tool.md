# 毫米波雷达 BIN 读取与导出工具

工具位置：

```text
tools/export_mmwave_bin.py
```

它依据 `docs/bin_interface_protocol.md` 中的 8624 字节定长包协议，读取以下全部接口：

1. 256 字节综合信息包头：时间、经纬高、姿态、速度、加速度、波束角、帧号和状态。
2. 5376 字节和/差回波数据：每包各 668 个 `float32` 采样。
3. 144 字节地杂波目标：最多 5 个目标的方位、俯仰、距离、功率和类型。
4. 2848 字节雷达检测结果：高压线段、孤立目标和稠密区域。

## 快速使用

只导出目标检测列表和检查摘要：

```powershell
python tools/export_mmwave_bin.py "D:\Dataset\LH_2026-04-27\bag1.1\with_cameras_capture_20260427_151113_mmwave_udp.bin"
```

导出 MAT 和目标列表：

```powershell
python tools/export_mmwave_bin.py INPUT.bin -o OUTPUT --mat --detections
```

导出协议中的全部数据：

```powershell
python tools/export_mmwave_bin.py INPUT.bin -o OUTPUT --all
```

`--all` 会写出完整回波，数据量接近原 BIN，请先确认磁盘空间。调试时可以使用：

```powershell
python tools/export_mmwave_bin.py INPUT.bin -o OUTPUT --all --max-packets 5000 --max-ant-frames 2
```

## 输出文件

| 文件 | 内容 |
|---|---|
| `summary.json` | 包数、天线帧数、尾部残留字节和各同步字错误数量 |
| `packet_headers.csv` | 每个 8624 字节包的全部 64 个包头字段 |
| `terrain_targets.csv` | 地杂波接口返回的目标列表 |
| `detection_frames.csv` | 每个天线帧的检测数量和检测参考位置 |
| `detections.csv` | 可直接筛选、统计的毫米波目标列表 |
| `detections.json` | 与 CSV 相同的目标，复杂端点/顶点保留为 JSON |
| `echo/sum_echo.npy` | 全部和通道回波，形状为 `(包数, 668)` |
| `echo/diff_echo.npy` | 全部差通道回波，形状为 `(包数, 668)` |
| `mat/*.mat` | 按天线帧输出的 MATLAB 文件 |

不指定任何导出开关时，默认生成 `summary.json`、`detection_frames.csv`、
`detections.csv` 和 `detections.json`。

## 目标类别和位置

`detections.csv` 的 `category` 有三种：

| 类别 | 含义 | `position_*` 的定义 |
|---|---|---|
| `powerline_segment` | 高压线/线状目标的一段 | 线段起点和终点的中点 |
| `isolated_object` | 孤立目标 | 雷达返回的目标点 |
| `dense_region` | 稠密目标区域 | 有效多边形顶点的质心 |

每个目标同时输出：

- `position_x/y/z_m`：检测参考坐标系下的代表位置。
- `bbox_min/max_*_m`：目标在局部三维坐标中的包围盒。
- `world_latitude/longitude/altitude`：根据参考经纬高换算的代表位置。
- `details_json`：线段端点、原始线段信息或稠密区域全部顶点。

雷达协议没有给这三类结果提供图像二维框，也没有给出汽车检测中常见的标准
三维长方体框。这里的 `bbox` 是根据返回点、线段端点或区域顶点计算的轴对齐
包围盒，不能直接当作相机图像框。

## 坐标模式

协议文档给出了 XYZ 和参考经纬度，但没有明确说明 XYZ 的轴定义。工具提供：

```text
--coordinate-mode nwu
```

- `nwu`：X 向北、Y 向西、Z 向上。毫米波接口文档规定的坐标，默认模式。
- `enu`：兼容旧实验结果，假设 X 向东、Y 向北、Z 向上。
- `body`：假设 X 向右、Y 向前，再使用检测接口中的参考航向角旋转到东北坐标。
- `local`：不做经纬度换算，只保留原始 XYZ。

`nwu` 中世界坐标按 `北向=X、东向=-Y` 换算。原始 XYZ、参考经纬度和航向角
始终保留。若检测接口的参考高度为 0，
`world_altitude_m` 也不应视为可靠海拔。

## MAT 结构

每个天线帧生成一个 MAT，包含：

- `Data_Ori`：兼容现有 Auto-labeling-LH 雷达加载逻辑。和/差回波去掉首尾各一个
  采样，转换为 666 个 dB 距离单元。
- `BeamPose`：每个波束的方位、俯仰、纬度、经度、高度、航向和原始时间字段。
- `RadarDetections`：该天线帧起始包中的完整检测接口数组。
- `PacketIndexRange`：该 MAT 对应的原 BIN 包索引范围。

MAT 文件名中的 `FZ` 取实际 `net_send_frame` 起止值，而不是文件内包索引。

## Python 读取示例

```python
import json
import pandas as pd
from scipy.io import loadmat

targets = pd.read_csv("OUTPUT/detections.csv")
powerlines = targets[targets["category"] == "powerline_segment"]

details = json.loads(powerlines.iloc[0]["details_json"])
print(details["start_xyz"], details["end_xyz"])

mat = loadmat("OUTPUT/mat/example_AntFrame000_FZ000001-000100.mat")
print(mat["Data_Ori"].shape)
print(mat["RadarDetections"].dtype)
```

## 完整性检查

`summary.json` 的 `sync_mismatch_counts` 会分别检查包头、和回波、差回波、地杂波
和检测接口的首尾同步字。正常文件中各项应为 0。`trailing_bytes` 也应为 0；
非零表示文件尾部不是完整的 8624 字节包。
