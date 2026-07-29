# 毫米波雷达 bin 文件接口协议说明

## 概述

- **bin 文件**：UDP 包流式存储，每个包对应一个**线束（FZ）**
- **FZ（单帧）**：= 数据帧头（64 × 32bit = 256 字节）+ 回波数据体（1344 × 32bit）+ 地形点数据体（36 × 32bit）+ 天线帧数据（712 × 32bit）
- **每包字节数**：`(64 + 1344 + 36 + 712) × 4 = 2156 × 4 = 8624 字节`
- **天线帧（AntFrame）**：多个连续 FZ 组成一个天线扫描帧，对应一个 `.mat` 文件

---

## 包内字段偏移表（字节偏移，从包起始计）

| 偏移 (bytes) | 字段 | 类型 | 说明 |
|---|---|---|---|
| 0 | 同步头 0xABABABAB | Uint32 | |
| 4 | 同步头 0xABABABAB | Uint32 | |
| 8 | 低功率帧号 | Uint32 | |
| 12 | 网络发送帧号（FZ 序号） | Uint32 | mat 文件名中的 FZ{start}-{end} 即此字段范围 |
| 16 | 本数据长度（32位字） | Uint32 | |
| 20 | 工作方式字 | Uint32 | |
| 24 | 天线帧起始标志 | Uint32 | **==1 表示本 FZ 是天线帧第一包** |
| 28 | 天线帧结束标志 | Uint32 | |
| 32 | 距离量程 (km) | float32 | DOCX 写作 Uint32，但实测 `bag1.1` 原始值 `0x40800000`，即 4.0f |
| 36 | 有效点数（668） | Uint32 | |
| 40 | 时间戳高 32bit：年(16b)+月(8b)+日(8b) | Uint32 | |
| 44 | **时间戳低 32bit：HHMMSSMMM（uint32）** | Uint32 | 编码：`HH×10_000_000 + MM×100_000 + SS×1_000 + ms` |
| 48 | 载机经度 (deg) | float32 | 正东 |
| 52 | 载机纬度 (deg) | float32 | 正北 |
| 56 | 载机真航向角 (deg) | float32 | 0=北，顺时针 |
| 60 | 载机 GPS 高度 (m) | float32 | |
| 64 | 载机速度 (m/s) | float32 | 机头相对地面地速 |
| 68 | 载机东向速度 (m/s) | float32 | |
| 72 | 载机北向速度 (m/s) | float32 | |
| 76 | 载机天向速度 (m/s) | float32 | |
| 80 | 天线方位角 (deg) | float32 | `OFFSET_ANT_AZ` |
| 84 | 天线俯仰角 (deg) | float32 | `OFFSET_ANT_EL` |
| 88–108 | 安装误差角、天线扫描参数等 | float32 | |
| 108–248 | 备份字（34 × Uint32） | Uint32×34 | |
| 248 | 帧头同步尾 0xBCBCBCBC | Uint32 | |
| 252 | 帧头同步尾 0xBCBCBCBC | Uint32 | 回波数据从 byte 256 开始 |

---

## 时间戳解码

```
ts_hmsm (uint32, offset 44) 编码格式 "HHMMSSMMM"：
    ts_int = HH * 10_000_000 + MM * 100_000 + SS * 1_000 + millis
    当日秒数 = ts_int / 1000.0   (单位：秒，CST 北京时间)

示例：ts_hmsm = 161943000
    → HH=16, MM=19, SS=43, ms=0
    → 当日秒数 = 16×3600 + 19×60 + 43 = 58783.0 s (CST)
    → UTC 秒 = 58783 - 8×3600 = 29983 s
```

---

## 时间对齐：雷达线束 → 相机图像

```
1. 解析 bin 文件，逐包读取 ts_hmsm → 得到 {FZ_序号: 当日秒数(CST)} 映射

2. 读取 nav100__state.csv，构建：
   GPS时刻(当日秒 CST) → relative_time_sec 的插值表
   （nav100__state.csv 中 gps_hour/gps_minute/gps_second/gps_millisecond 均为 UTC，
     CST = UTC + 8h，即 gps_cst_sec = gps_utc_sec + 28800）

3. 对每个 mat（AntFrame{NNN}，FZ{start}-{end}）：
   - 中间 FZ = (start + end) // 2
   - 查 FZ 时间表 → 得到 ts_cst_sec
   - 插值 nav100__state.csv → 得到 relative_time_sec
   - 找时间戳最近的相机图像

4. 结果写入 segment 目录下的 radar_camera_match_ts.csv
```

---

## 数据量

- 帧头：64 × 32bit = 256 bytes
- 回波数据体：1344 × 32bit = 5376 bytes（和路 672 字 + 差路 672 字）
- 地形点数据体：36 × 32bit = 144 bytes
- 天线帧检测结果：712 × 32bit = 2848 bytes
- **总计：2156 × 32bit = 8624 bytes/包**
- 典型帧率：约 769 Hz（1.3 ms/包）

---

## mat 文件命名规则

```
mmwave_YYYYMMDD_HHMMSS_AntFrame{NNN}_FZ{start}-{end}.mat
```

- `YYYYMMDD_HHMMSS`：capture 目录名中的 CST 采集时刻
- `NNN`：天线帧（AntFrame）序号，从 000 开始
- `FZ{start}-{end}`：本天线帧包含的 FZ 网络发送帧号范围（对应 bin 包 offset 12 的字段）
