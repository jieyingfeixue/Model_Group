# Auto-labeling-LH bin 到地图可视化链路说明

本文只说明 Auto-labeling-LH 中与毫米波雷达 `bin`、`mat`、点云地图可视化、雷达目标读取有关的实现。

## 1. 数据从哪里来

LH 数据集的每个采集场景通常位于：

```text
L:\LH_data_all_sensor\<date>\with_cameras_capture_YYYYMMDD_HHMMSS*/
```

场景目录内的毫米波雷达原始数据是：

```text
*_mmwave_udp.bin
```

这个 `bin` 文件是毫米波雷达 UDP 包的顺序落盘结果。源码里统一按固定包长读取：

```text
每包 8624 bytes
每包 2156 个 uint32 word
每包对应一个 FZ，也就是一个雷达线束/单帧包
多个连续 FZ 组成一个 AntFrame，也就是一个天线扫描帧
一个 AntFrame 会被导出为一个 .mat
```

相关代码：

```text
tools/export_mmwave_bin.py
tools/tools/batch_convert_bins.py
src/io/startup_check.py
src/io/adapters/lh_adapter.py
```

## 2. bin 包内部结构

当前代码按 `8624 bytes` 定长包解析，每包分为四块：

| 区域 | 大小 | 代码位置 | 作用 |
|---|---:|---|---|
| 包头 | 256 bytes | `HEADER_DTYPE` / 字节 0-255 | FZ 序号、天线帧起止标志、时间、飞机经纬高、航向、速度、天线方位角/俯仰角 |
| 和/差回波 | 5376 bytes | `echo()` / 字节 256-5631 | 和通道、差通道回波，每包各 668 个 `float32` 采样 |
| 地杂波目标 | 144 bytes | `terrain()` | 最多 5 个目标的方位、俯仰、距离、功率、类型 |
| 雷达检测结果 | 2848 bytes | `detection()` / `bin_detection_map.py` | 高压线段、孤立目标、稠密区域 |

包头里最重要的字段包括：

| 字段 | 含义 |
|---|---|
| `net_send_frame` | 网络发送帧号，也就是 FZ 序号 |
| `antenna_frame_start` | 是否为一个 AntFrame 的起始包 |
| `timestamp_hmsm` | HHMMSSMMM 格式时间 |
| `plane_longitude_deg` / `plane_latitude_deg` | 当前 FZ 对应飞机经纬度 |
| `true_heading_deg` | 当前 FZ 对应飞机真航向 |
| `gps_altitude_m` | 当前 FZ 对应 GPS 高度 |
| `antenna_azimuth_deg` / `antenna_elevation_deg` | 当前雷达波束方位角和俯仰角 |

这里有一个关键设计点：**每个 FZ 都带自己的飞机位置和天线角度**。所以后续点云上地图时，不把整帧雷达点强行绑定到一个统一原点，而是尽量使用每个波束采集时自己的 GPS/航向来计算点的绝对经纬度。

## 3. bin 如何转成 mat

项目里有两套 bin 转换相关代码。

### 3.1 当前通用导出工具

文件：

```text
tools/export_mmwave_bin.py
```

它是较完整的接口读取/导出工具，支持：

```powershell
python tools/export_mmwave_bin.py INPUT.bin -o OUTPUT --mat --detections
python tools/export_mmwave_bin.py INPUT.bin -o OUTPUT --all
```

主要输出：

| 输出 | 内容 |
|---|---|
| `summary.json` | 包数、AntFrame 数、同步字检查结果 |
| `packet_headers.csv` | 每个包的完整包头 |
| `terrain_targets.csv` | 地杂波接口目标 |
| `detection_frames.csv` | 每个 AntFrame 的目标数量和参考位置 |
| `detections.csv` / `detections.json` | bin 中雷达检测目标清单 |
| `echo/sum_echo.npy` / `echo/diff_echo.npy` | 全量和/差回波 |
| `mat/*.mat` | 按 AntFrame 导出的 mat 文件 |

它生成的 mat 包含：

```text
Data_Ori
BeamPose
RadarDetections
PacketIndexRange
```

其中：

| 字段 | 含义 |
|---|---|
| `Data_Ori` | 按俯仰层组织的回波强度数据 |
| `BeamPose` | 每个波束的 `[az, el, lat, lon, alt, heading, timestamp]` |
| `RadarDetections` | 该 AntFrame 起始包中的雷达检测接口数据 |
| `PacketIndexRange` | 该 mat 对应的原始 bin 包索引范围 |

### 3.2 软件启动/批处理使用的转换器

文件：

```text
tools/tools/batch_convert_bins.py
```

它会递归扫描数据集中的：

```text
*_mmwave_udp.bin
```

并在 bin 同级目录生成：

```text
{bin_stem}_radar/
    mmwave_YYYYMMDD_HHMMSS_AntFrame000_FZ000000-000123.mat
    mmwave_YYYYMMDD_HHMMSS_AntFrame001_FZ000124-000245.mat
    ...
    _timetable.json
```

这个转换器的核心步骤是：

1. 读取 bin 文件大小，按 `8624 bytes` 切分为 FZ 包。
2. 扫描每个包的 `antenna_frame_start` 字段。
3. 以 `antenna_frame_start == 1` 的位置作为 AntFrame 起点。
4. 每个 AntFrame 区间 `[start, end)` 转为一个 `.mat`。
5. 从每个 FZ 提取：
   - 天线方位角 `ant_az`
   - 天线俯仰角 `ant_el`
   - 飞机纬度 `lat`
   - 飞机经度 `lon`
   - 飞机航向 `hdg`
   - 飞机高度 `alt`
   - 原始时间 `ts_hmsm`
6. 从回波区读取和/差通道 `float32`。
7. 将回波转为 dB：

```python
10 * log10(max(x, 1e-3))
```

8. 去掉首尾保护采样，输出 666 个距离单元。
9. 按俯仰角分层，每层内按方位角排序。
10. 写入 `Data_Ori`。
11. 写 `_timetable.json`，记录每个 mat 对应的 FZ 范围和时间范围。

这套 mat 是兼容旧 1218 风格的结构：

```text
Data_Ori: cell(n_el, 1)
  每层是 cell(1, 5)
    {1}: el_scalar
    {2}: az array
    {3}: diff dB, shape = (666, n_az)
    {4}: sum dB,  shape = (666, n_az)
    {5}: meta,    shape = (n_az, 7)
```

`meta` 的列定义为：

```text
[rangeGate, latitude, longitude, heading, altitude, planeEL, radarEL]
```

这里的 `latitude / longitude / heading / altitude` 是每个 FZ 自己的原始信息，不做统一参考帧归零。

### 3.3 启动检查如何触发转换

文件：

```text
src/io/startup_check.py
```

核心函数：

```python
find_all_bins(root)
needs_conversion(bin_path)
run_startup_check(root)
```

判断逻辑：

```text
如果 bin 同级不存在 {bin_stem}_radar/，需要转换
如果 {bin_stem}_radar/_timetable.json 不存在，需要转换
如果 mat 数量少于 _timetable.json 记录数量，需要转换
如果 mat 数量为 0，需要转换
```

真正执行转换时调用：

```python
from tools.tools.batch_convert_bins import convert_bin
```

也就是说，软件运行时默认查找的是：

```text
capture_dir/
    xxx_mmwave_udp.bin
    xxx_mmwave_udp_radar/
        *.mat
        _timetable.json
```

## 4. 软件如何找到雷达 mat

文件：

```text
src/io/adapters/lh_adapter.py
```

函数：

```python
_find_radar_dir(capture_dir)
```

查找顺序：

1. 在 capture 目录下寻找以 `_radar` 结尾的目录。
2. 如果没有，则回退到旧格式：

```text
mmwave_mat_1218style/
```

所以当前常见结构是：

```text
with_cameras_capture_YYYYMMDD_HHMMSS/
    with_cameras_capture_YYYYMMDD_HHMMSS_mmwave_udp.bin
    with_cameras_capture_YYYYMMDD_HHMMSS_mmwave_udp_radar/
        *.mat
```

## 5. mat 如何被读取成雷达层

文件：

```text
src/io/adapters/lh_adapter.py
```

函数：

```python
_load_mmwave_layers(path)
```

它支持两种 mat：

### 5.1 新导出格式

包含：

```text
Data_Ori
BeamPose
```

`BeamPose` 已经是标准形式：

```text
[az_deg, el_deg, lat, lon, alt, heading_deg, ts]
```

### 5.2 旧 1218/batch_convert 格式

只有：

```text
Data_Ori
```

位姿嵌在 `Data_Ori` 每层的 `sub[4]` 里。代码会把它归一化成同样的 `pose`：

```text
pose[:, 0] = az
pose[:, 1] = el
pose[:, 2] = lat
pose[:, 3] = lon
pose[:, 4] = alt
pose[:, 5] = heading
pose[:, 6] = ts 或 0
```

最终 `_load_mmwave_layers()` 返回：

```python
[
    {
        "el_deg": float,
        "az": np.ndarray,      # shape = (n_az,)
        "sd": np.ndarray,      # shape = (n_range, n_az), dB
        "pose": np.ndarray,    # shape = (n_az, 7)
    },
    ...
]
```

`sd` 当前取的是 `Data_Ori` 中的和通道 dB 数据。

## 6. mat 点云如何转成地图经纬度

文件：

```text
src/io/adapters/lh_adapter.py
```

函数：

```python
_load_mmwave_enu_pts(mat_path)
```

返回：

```text
points, center_lat, center_lon
```

其中：

```text
points: [lat_deg, lon_deg, absolute_altitude_m, dB]
```

注意名字里有 `enu`，但当前返回的不是局部 ENU 坐标，而是已经换算后的绝对经纬高点。

转换过程如下：

1. 读取 mat 中所有俯仰层。
2. 对每个俯仰层、每个方位波束做 CA-CFAR。
3. 距离单元按固定步长换算为距离：

```python
rng_m = np.arange(1, n_range + 1) * _RADAR_RANGE_STEP_M
```

4. 过滤超过最大雷达距离的点。
5. 对每个过阈值距离单元，根据当前波束的方位角、俯仰角转为本机体系三维点：

```text
xb = R * cos(el) * sin(az)
yb = R * cos(el) * cos(az)
zb = R * sin(el)
```

6. 取该波束对应的 GPS：

```text
lat_b, lon_b, alt_b, heading_b
```

7. 按当前波束航向旋转到局部 East/North/Up：

```text
E_local = xb * cos(heading) + yb * sin(heading)
N_local = -xb * sin(heading) + yb * cos(heading)
U_local = zb
```

8. 用地球半径近似把局部 ENU 转成绝对经纬度：

```text
lat_target = lat_b + N_local / R_polar
lon_target = lon_b + E_local / (R_equator * cos(lat_b))
alt_target = alt_b + U_local
```

9. 输出：

```text
[lat_target, lon_target, alt_target, intensity_db]
```

这个设计的意义是：无人机在一个 AntFrame 内也可能运动，软件尽量使用每束自己的飞机位姿，而不是用单个 mat 中心位置近似所有点。

## 7. 全场景点云如何构建

### 7.1 全量点云

文件：

```text
src/io/adapters/lh_adapter.py
```

函数：

```python
load_capture_all_enu_pts(capture_dir)
```

流程：

1. 调用 `_find_radar_dir(capture_dir)` 找到 mat 目录。
2. 遍历所有 `.mat`。
3. 对每个 mat 调用 `_load_mmwave_enu_pts()`。
4. 过滤非法值和高度小于 0 的点。
5. 合并为：

```text
[lat, lon, altitude, dB]
```

6. 写入缓存：

```text
Auto-labeling-LH/temp/radar_capture_cache/*.npz
```

缓存签名由以下信息组成：

```text
mat 数量
mat 最大修改时间
mat 总大小
```

只要 mat 没变，下次直接读缓存。

### 7.2 稳定深度点云图

函数：

```python
load_capture_depth_radar_map(capture_dir)
```

这个函数同样遍历全部 mat，但会把点按三维 voxel 聚合：

```text
voxel_xy_m = 12m
voxel_z_m  = 6m
min_mat_support = 2
```

每个 mat 对一个 voxel 最多贡献一次，最后只保留被多个 mat 支持的稳定点。输出：

```text
[lat, lon, altitude, mean_peak_db, mat_support]
```

缓存目录：

```text
Auto-labeling-LH/temp/radar_depth_cache/*.npz
```

## 8. 点云如何显示到地图上

文件：

```text
src/ui/panels/map_panel.py
```

核心类：

```python
MapView
MapPanel
```

外部调用入口：

```python
MapPanel.set_frame(...)
MapView.set_frame(...)
```

输入里与地图显示有关的字段：

```text
gps_lat
gps_lon
gps_hdg
camera_hdg
gps_track
frame_time
gps_alt
radar_enu_pts
radar_ref_lat
radar_ref_lon
```

其中 `radar_enu_pts` 实际是：

```text
[lat, lon, altitude, dB]
```

### 8.1 底图坐标

地图底图支持高德卫星和 OSM。高德使用 GCJ-02，因此渲染前会做：

```python
_to_mc(lat, lon)
_to_mc_arr(lats, lons)
```

如果当前底图是高德：

```text
WGS-84 -> GCJ-02
```

如果是 OSM：

```text
保持 WGS-84
```

然后通过 Web Mercator tile 公式把经纬度转为 scene 坐标：

```python
_latlon_to_scene_xy(lat, lon, zoom)
```

### 8.2 瓦片加载

底图瓦片由 `_TileLoader` 异步加载，缓存目录在：

```text
Auto-labeling-LH/temp/gaode_sat_tiles
Auto-labeling-LH/temp/osm_tiles
```

地图放大时，`MapView._request_base_tiles()` 根据当前视口中心和 zoom 计算需要的瓦片。加载失败或高 zoom 无有效影像时，会尝试从低 zoom 父瓦片裁剪放大作为回退图。

### 8.3 点云渲染

函数：

```python
MapView._draw_radar(...)
```

渲染逻辑：

1. 输入点必须是：

```text
[lat, lon, altitude, dB]
```

2. 经纬度按底图类型转 GCJ-02 或保留 WGS-84。
3. 经纬度转 Web Mercator scene 像素。
4. 为了避免每个点都是一个 `QGraphicsItem` 导致卡顿，所有点会画到一张透明 `QImage` 上，再作为一个 `QGraphicsPixmapItem` 加到地图。
5. 如果点数超过 5000，只绘制强度最高的 5000 个点，但原始点仍保留给选择/查询逻辑使用。
6. 点颜色按 dB 的 2%-98% 分位动态归一化。
7. 如果某个点带有雷达目标 metadata，会用黄色强调显示。
8. 同一 zoom 和同一批点的渲染结果会缓存到 `_radar_pixmap_cache`，避免频繁重画。

### 8.4 飞机位置、轨迹和朝向

函数：

```python
MapView._draw_track(...)
MapView._draw_vehicle(...)
```

显示内容：

| 内容 | 来源 |
|---|---|
| 飞机当前位置 | 当前帧/当前 mat 的 GPS |
| 飞机轨迹 | `gps_track` |
| 已飞过轨迹 | `frame_time` 与轨迹时间比较 |
| 箭头朝向 | `camera_hdg` 或传入的 heading |
| 高度/姿态文字 | `gps_alt`、pitch、roll、yaw |

独立 mat 地图可视化工具中，箭头默认指向“飞机位置到点云范围中心”的方向。

## 9. 独立 mat 地图可视化工具

文件：

```text
tools/visualize_mat_on_map.py
```

用途：

```text
输入一个 mat，把该 mat 的雷达点云显示到地图窗口中。
```

使用：

```powershell
python tools/visualize_mat_on_map.py path\to\mmwave_*.mat
```

如果不传 mat，会弹出文件选择框。

它的流程：

1. 调用 `_load_mmwave_layers(mat_path)` 读取波束层。
2. 调用 `_load_mmwave_enu_pts(mat_path)` 生成绝对经纬高点云。
3. 从 `pose` 构建轨迹：

```text
[lat, lon, timestamp]
```

4. 计算点云范围中心。
5. 箭头朝向设为：

```text
飞机中心 -> 点云范围中心
```

6. 创建一个 `MapView` 子类，屏蔽相机视场角绘制。
7. 调用 `map_view.set_frame(...)` 显示：

```text
飞机位置
飞机轨迹
点云
箭头
地图底图
```

这个工具不需要图像数据，也不依赖图像标定。

## 10. 软件如何从 bin 中读取雷达目标

点云来自 mat；雷达目标列表则可以直接从 bin 中读取。

相关文件：

```text
src/io/bin_detection_map.py
src/fusion/bin_detection_projection.py
src/io/adapters/lh_adapter.py
src/ui/panels/map_panel.py
```

### 10.1 运行时读取入口

函数：

```python
load_capture_bin_detection_map(capture_dir, coordinate_mode="nwu")
```

位置：

```text
src/io/adapters/lh_adapter.py
```

它会：

1. 在 capture 目录下查找第一个：

```text
*_mmwave_udp.bin
```

2. 调用：

```python
load_or_build_bin_detection_world_map(...)
```

3. 缓存结果到：

```text
Auto-labeling-LH/temp/bin_detection_cache/*.npz
```

### 10.2 bin 目标快照读取

文件：

```text
src/io/bin_detection_map.py
```

函数：

```python
load_bin_detection_snapshots(bin_path)
```

读取逻辑：

1. 按 `8624 bytes` mmap 整个 bin。
2. 找到所有 `antenna_frame_start == 1` 的包。
3. 只在每个 AntFrame 起始包读取检测接口。
4. 从检测接口中解析：

```text
n_powerline_segments
n_isolated_objects
n_dense_regions
```

以及对应数据：

```text
hv_segments_xyz
isolated_xyz
dense_vertices_xyz
```

如果一个快照里三类目标数量都为 0，则跳过。

### 10.3 目标类别

当前软件使用三类 bin 原生目标：

| 类别 | 源字段 | 表示 |
|---|---|---|
| `powerline_segments` | `hv_segments_xyz` | 高压线/线状目标，每个目标两个端点 |
| `isolated` | `isolated_xyz` | 孤立目标，每个目标一个点 |
| `dense_vertices` | `dense_vertices_xyz` | 稠密区域，每个区域最多 8 个顶点 |

### 10.4 局部坐标如何转世界坐标

函数：

```python
_local_to_wgs84(...)
```

默认坐标模式：

```text
nwu
```

即：

```text
X -> North
Y -> West
Z -> Up
```

转换到 East/North：

```text
north = x
east  = -y
```

然后用检测接口中的参考位置：

```text
ref_lat
ref_lon
ref_alt
ref_heading_deg
```

换算成：

```text
[lat, lon, absolute_altitude]
```

支持的坐标模式还有：

| 模式 | 说明 |
|---|---|
| `nwu` | 默认，X 北、Y 西、Z 上 |
| `enu` | X 东、Y 北、Z 上 |
| `body` | 使用参考航向把本体系坐标旋转到世界水平坐标 |

当前主流程默认使用 `nwu`。

### 10.5 目标世界图结构

`build_bin_detection_world_map()` 返回：

```python
{
    "isolated": ndarray,
    "powerline_segments": ndarray,
    "dense_vertices": ndarray,
    "coordinate_mode": ndarray,
    "snapshot_count": ndarray,
    "reference_altitude_valid": ndarray,
}
```

各数组结构：

```text
isolated:
    [lat, lon, alt, snapshot_index, packet_index]

powerline_segments:
    [start_lat, start_lon, start_alt,
     end_lat,   end_lon,   end_alt,
     segment_info,
     snapshot_index,
     packet_index]

dense_vertices:
    [lat, lon, alt, snapshot_index, dense_region_index, packet_index]
```

### 10.6 目标缓存

函数：

```python
load_or_build_bin_detection_world_map(...)
```

缓存签名：

```text
bin 文件大小
bin 修改时间
coordinate_mode
```

缓存路径：

```text
Auto-labeling-LH/temp/bin_detection_cache/
```

命名包含：

```text
bin stem
bin path hash
coordinate mode
```

这样同一个 bin 在不同坐标模式下会生成不同缓存。

## 11. 雷达目标如何显示到地图

地图面板里有“雷达目标”按钮。

相关代码：

```text
src/ui/panels/map_panel.py
```

按钮触发：

```python
MapPanel._on_bin_targets_toggled(...)
```

流程：

1. 保存当前地图上显示的普通点云。
2. 调用：

```python
load_capture_bin_detection_map(capture_dir)
```

3. 调用：

```python
sample_bin_detection_targets(detection_map)
```

4. 将 bin 原生目标转换成地图可绘制点：

```text
[lat, lon, altitude, pseudo_intensity]
```

5. 同时生成每个点的 metadata：

```text
target_type_text
target_id
segment_info
snapshot_index
packet_index
```

6. 调用：

```python
map_view._draw_radar(points, ref_lat, ref_lon, point_metadata=metadata)
```

7. 鼠标悬停到点上时，`_check_radar_hover()` 会显示：

```text
经纬度
高度
强度
距离当前飞机位置
目标类型
目标编号
Snapshot
Packet
Segment info
```

### 11.1 线状目标采样

文件：

```text
src/fusion/bin_detection_projection.py
```

函数：

```python
sample_bin_detection_targets(...)
```

高压线段不是只显示端点，而是按线段插值采样：

```python
_interpolate_segment(start, end, spacing_m=20.0)
```

这样地图上能看到一段连续线状目标。

伪强度值：

| 目标 | intensity |
|---|---:|
| 稠密区域 | 15 |
| 孤立目标 | 25 |
| 高压线段 | 35 |

这些强度主要用于复用现有点云颜色渲染逻辑，不代表真实回波强度。

## 12. bin 目标如何与单个 mat 对应

有些功能只希望看某一个 mat 对应包范围内的 bin 目标。

函数：

```python
filter_detection_map_by_packet_range(detection_map, packet_start, packet_end)
```

文件：

```text
src/fusion/bin_detection_projection.py
```

它按 `packet_index` 过滤：

```text
isolated 使用第 4 列 packet_index
powerline_segments 使用第 8 列 packet_index
dense_vertices 使用第 5 列 packet_index
```

这样可以从全 bin 的目标世界图中截取当前 mat 对应的目标。

## 13. bin 目标如何变成可投影点

函数：

```python
sample_bin_detection_map(detection_map)
```

输出：

```text
[lat, lon, altitude, intensity, kind]
```

其中 `kind` 是：

```text
1 = dense region
2 = isolated object
3 = powerline segment
```

高压线段和稠密区域边界会被插值采样，孤立目标直接保留点。

如果需要从世界点转为机体系点，使用：

```python
world_samples_to_body(...)
```

输出：

```text
[right, forward, up, intensity]
```

主要过滤条件：

```text
forward > 0
distance >= min_distance_m
distance <= max_distance_m
abs(azimuth) <= half_fov_deg
altitude >= 0
```

这个函数用于把 bin 目标世界坐标转换成以当前飞机位置/航向为参考的局部点。

## 14. 文件级调用关系总览

### 14.1 bin 转 mat

```text
*_mmwave_udp.bin
    -> tools/tools/batch_convert_bins.py::convert_bin()
        -> {bin_stem}_radar/*.mat
        -> {bin_stem}_radar/_timetable.json
```

或：

```text
*_mmwave_udp.bin
    -> tools/export_mmwave_bin.py
        -> output/mat/*.mat
        -> output/detections.csv
        -> output/detections.json
        -> output/summary.json
```

### 14.2 mat 转地图点云

```text
*.mat
    -> lh_adapter._load_mmwave_layers()
    -> lh_adapter._load_mmwave_enu_pts()
    -> [lat, lon, altitude, dB]
    -> map_panel.MapView._draw_radar()
    -> 地图点云
```

### 14.3 capture 全段点云

```text
capture_dir
    -> lh_adapter._find_radar_dir()
    -> 遍历 *_radar/*.mat
    -> lh_adapter.load_capture_all_enu_pts()
    -> temp/radar_capture_cache/*.npz
    -> map_panel.MapView._draw_radar()
```

### 14.4 bin 目标读取

```text
capture_dir/*_mmwave_udp.bin
    -> lh_adapter.load_capture_bin_detection_map()
    -> bin_detection_map.load_or_build_bin_detection_world_map()
    -> bin_detection_map.load_bin_detection_snapshots()
    -> temp/bin_detection_cache/*.npz
    -> bin_detection_projection.sample_bin_detection_targets()
    -> map_panel.MapView._draw_radar(..., point_metadata=metadata)
```

### 14.5 单 mat 地图可视化

```text
tools/visualize_mat_on_map.py
    -> _load_mmwave_layers()
    -> _load_mmwave_enu_pts()
    -> MapView.set_frame()
    -> 地图窗口
```

## 15. 当前实现中的几个重要约定

1. `bin` 是原始数据源，`mat` 是为了后续快速读取和兼容旧格式生成的中间格式。
2. 普通点云显示主要依赖 `mat`，不是直接从 bin 回波实时计算。
3. 原生雷达目标显示主要直接读取 `bin` 的检测接口，并缓存为 `npz`。
4. 点云地图坐标使用绝对经纬高：

```text
[lat, lon, altitude, dB]
```

5. 高德底图显示前需要 WGS-84 转 GCJ-02；OSM 不需要。
6. mat 点云计算时使用每个波束自己的 GPS/航向，尽量减少无人机运动造成的位置误差。
7. 全场景点云缓存和 bin 目标缓存都带签名，原始数据变化后会自动失效。
8. 地图上普通点云、bin 原生目标点最终复用同一套 `_draw_radar()` 栅格化渲染逻辑。

## 16. 常用命令

### 导出一个 bin 的目标清单

```powershell
cd D:\ProjectHub\Open-Vocabulary-3D-Auto-Annotation-main\Open-Vocabulary-3D-Auto-Annotation-main\Auto-labeling-LH
.\.venv\Scripts\python.exe tools\export_mmwave_bin.py "D:\Dataset\LH_2026-04-27\bag1.1\xxx_mmwave_udp.bin"
```

### 导出 mat 和目标清单

```powershell
.\.venv\Scripts\python.exe tools\export_mmwave_bin.py "path\to\xxx_mmwave_udp.bin" -o "path\to\output" --mat --detections
```

### 批量把数据集 bin 转 mat

```powershell
.\.venv\Scripts\python.exe tools\tools\batch_convert_bins.py "L:\LH_data_all_sensor" --skip-existing
```

### 打开一个 mat 到地图窗口

```powershell
.\.venv\Scripts\python.exe tools\visualize_mat_on_map.py "path\to\mmwave_*.mat"
```

## 17. 主要源码索引

| 文件 | 作用 |
|---|---|
| `tools/export_mmwave_bin.py` | 完整读取 bin 接口，导出 header、echo、terrain、detections、mat |
| `tools/tools/batch_convert_bins.py` | 批量把 LH 数据集中的 bin 转成 `{bin_stem}_radar/*.mat` |
| `src/io/startup_check.py` | 检查 bin 是否已转 mat，必要时调用转换器 |
| `src/io/adapters/lh_adapter.py` | 查找雷达目录、读取 mat、生成地图点云、读取 bin 目标缓存 |
| `src/io/bin_detection_map.py` | 直接解析 bin 中的雷达检测接口，并转为世界坐标目标图 |
| `src/fusion/bin_detection_projection.py` | 将 bin 目标采样成点、按 packet 过滤、转机体系 |
| `src/ui/panels/map_panel.py` | 地图瓦片加载、飞机/轨迹/点云/雷达目标显示 |
| `tools/visualize_mat_on_map.py` | 独立输入一个 mat 并显示点云到地图 |
