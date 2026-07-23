"""
时间戳匹配导入脚本 — 以红外为基准，可见光最近邻匹配
用法: python scripts/import_segment_data.py

策略:
  1. 解析所有传感器文件名中的时间戳 (_tSSSSSS.mmm → 秒.毫秒)
  2. 以红外 (usb_ir) 的 1286 个时间戳为基准
  3. 对每张红外，在可见光相机1 (DA8679037) 和相机2 (DA8679038) 中二分查找最近时间戳
  4. 上传匹配后的文件到 MinIO
  5. 写入 data_resources（同组共享 group_id）
  6. 创建 alignment_groups 记录对齐关系
  7. 创建数据集并填充 dataset_items
"""
import os, sys, re, json
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from bisect import bisect_left
from collections import defaultdict

from PIL import Image
from minio import Minio
from sqlalchemy import create_engine, text

# ─── 路径配置 ───
BASE_DIR = Path(__file__).resolve().parent.parent
SEGMENT_DIR = BASE_DIR / "segment_001_000112.000_000203.000"

# ─── 连接配置 ───
MINIO = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
BUCKET = "detection-platform"
DB_URL = "postgresql://postgres:123456@localhost:5432/detection_platform"

# ─── 传感器配置 ───
SENSOR_CONFIG = {
    "hikrobot_camera__DA8679037__image_raw": {"modality": "visible",  "device": "海康 DA8679037"},
    "hikrobot_camera__DA8679038__image_raw": {"modality": "visible",  "device": "海康 DA8679038"},
    "usb_ir__image_raw":                     {"modality": "infrared", "device": "USB 红外"},
    "at360__points":                         {"modality": "lidar",    "device": "AT360 激光雷达"},
}

ADMIN_ID = 5

# ─── 工具函数 ───
def extract_timestamp(filename: str) -> float | None:
    """从文件名提取时间戳: _t000112.040 → 112.040"""
    m = re.search(r'_t(\d{6})\.(\d{3})', filename)
    if m:
        return float(f"{int(m.group(1))}.{m.group(2)}")
    return None


def read_image_info(fpath: Path) -> dict:
    """读取图片宽高通道数"""
    try:
        img = Image.open(fpath)
        w, h = img.size
        c = len(img.getbands())
        img.close()
        return {"width": w, "height": h, "channels": c}
    except Exception:
        return {"width": 0, "height": 0, "channels": 0}


def upload_to_minio(local_path: Path, object_name: str) -> str:
    """上传文件到 MinIO，返回 file_path"""
    ext = local_path.suffix.lower()
    content_type = "image/jpeg" if ext in ('.jpg', '.jpeg') else \
                   "image/png" if ext == '.png' else \
                   "application/octet-stream"
    MINIO.fput_object(BUCKET, object_name, str(local_path), content_type=content_type)
    return f"/{BUCKET}/{object_name}"


def insert_resource(db, name: str, modality: str, file_path: str,
                    captured_at: float, metadata: dict, owner_id: int = ADMIN_ID) -> int:
    """插入 data_resources 记录，返回 resource_id"""
    meta_json = json.dumps(metadata, ensure_ascii=False)
    result = db.execute(
        text("""
            INSERT INTO data_resources
            (name, owner_id, modality, file_path, metadata, captured_at, version, annotation_status, status, created_at, updated_at)
            VALUES (:name, :owner_id, :modality, :file_path, :metadata, :captured_at, 1, 'unannotated', 'active', NOW(), NOW())
            RETURNING resource_id
        """),
        {
            "name": name,
            "owner_id": owner_id,
            "modality": modality,
            "file_path": file_path,
            "metadata": meta_json,
            "captured_at": captured_at,
        }
    )
    return result.fetchone()[0]


def nearest_index(timestamps: list[float], target: float) -> int:
    """在有序时间戳列表中二分查找最接近 target 的索引"""
    if not timestamps:
        return -1
    idx = bisect_left(timestamps, target)
    if idx == 0:
        return 0
    if idx == len(timestamps):
        return len(timestamps) - 1
    left = timestamps[idx - 1]
    right = timestamps[idx]
    return idx - 1 if (target - left) <= (right - target) else idx


# ─── 主流程 ───
def main():
    engine = create_engine(DB_URL)

    # 确保 MinIO 桶存在
    if not MINIO.bucket_exists(BUCKET):
        MINIO.make_bucket(BUCKET)
        print(f"已创建 MinIO 桶: {BUCKET}")

    # ── 1. 扫描所有传感器文件，提取时间戳 ──
    print("=" * 60)
    print("阶段 1: 扫描文件 & 解析时间戳")
    print("=" * 60)

    images_dir = SEGMENT_DIR / "images"
    pc_dir = SEGMENT_DIR / "pointclouds"

    # {sensor_name: [(filepath, timestamp, filename), ...]}
    sensor_files: dict[str, list[tuple[Path, float, str]]] = defaultdict(list)

    if images_dir.exists():
        for sensor_dir in sorted(images_dir.iterdir()):
            if not sensor_dir.is_dir():
                continue
            sensor_name = sensor_dir.name
            for fpath in sorted(sensor_dir.iterdir()):
                ts = extract_timestamp(fpath.name)
                if ts is not None:
                    sensor_files[sensor_name].append((fpath, ts, fpath.name))

    if pc_dir.exists():
        for sensor_dir in sorted(pc_dir.iterdir()):
            if not sensor_dir.is_dir():
                continue
            sensor_name = sensor_dir.name
            for fpath in sorted(sensor_dir.iterdir()):
                ts = extract_timestamp(fpath.name)
                if ts is not None:
                    sensor_files[sensor_name].append((fpath, ts, fpath.name))

    for name, files in sensor_files.items():
        cfg = SENSOR_CONFIG.get(name, {})
        print(f"  {name}: {len(files)} 文件 [{cfg.get('modality', '?')}]")

    # ── 2. 时间戳匹配 ──
    print("\n" + "=" * 60)
    print("阶段 2: 时间戳最近邻匹配 (红外为基准)")
    print("=" * 60)

    ir_name = "usb_ir__image_raw"
    vis1_name = "hikrobot_camera__DA8679037__image_raw"
    vis2_name = "hikrobot_camera__DA8679038__image_raw"
    lidar_name = "at360__points"

    ir_files = sensor_files.get(ir_name, [])
    vis1_files = sensor_files.get(vis1_name, [])
    vis2_files = sensor_files.get(vis2_name, [])
    lidar_files = sensor_files.get(lidar_name, [])

    # 提取纯时间戳列表 (已排序)
    ir_ts = [ts for _, ts, _ in ir_files]
    vis1_ts = [ts for _, ts, _ in vis1_files]
    vis2_ts = [ts for _, ts, _ in vis2_files]
    lidar_ts = [ts for _, ts, _ in lidar_files]

    # 为每个红外匹配最近的可见光
    # groups[group_id] = [(fpath, ts, filename, sensor_name, modality), ...]
    groups: list[list[tuple[Path, float, str, str, str, bool]]] = []

    for ir_fpath, ir_ts_val, ir_fname in ir_files:
        group: list[tuple[Path, float, str, str, str, bool]] = []
        # 红外是基准 (primary)
        group.append((ir_fpath, ir_ts_val, ir_fname, ir_name, "infrared", True))

        # 匹配可见光1
        idx1 = nearest_index(vis1_ts, ir_ts_val)
        if idx1 >= 0:
            fpath, ts_val, fname = vis1_files[idx1]
            diff = abs(ts_val - ir_ts_val)
            group.append((fpath, ts_val, fname, vis1_name, "visible", False))
        else:
            print(f"  [WARN] 红外 {ir_fname} (t={ir_ts_val:.3f}) 无可见光1匹配")

        # 匹配可见光2
        idx2 = nearest_index(vis2_ts, ir_ts_val)
        if idx2 >= 0:
            fpath, ts_val, fname = vis2_files[idx2]
            diff = abs(ts_val - ir_ts_val)
            group.append((fpath, ts_val, fname, vis2_name, "visible", False))
        else:
            print(f"  [WARN] 红外 {ir_fname} (t={ir_ts_val:.3f}) 无可见光2匹配")

        # 匹配点云 (可选)
        idx_l = nearest_index(lidar_ts, ir_ts_val)
        if idx_l >= 0:
            fpath, ts_val, fname = lidar_files[idx_l]
            diff = abs(ts_val - ir_ts_val)
            group.append((fpath, ts_val, fname, lidar_name, "lidar", False))

        groups.append(group)

    print(f"  红外基准: {len(ir_files)} 张")
    print(f"  匹配后样本数: {len(groups)}")
    matched_vis1 = sum(1 for g in groups for _, _, _, sn, _, _ in g if sn == vis1_name)
    matched_vis2 = sum(1 for g in groups for _, _, _, sn, _, _ in g if sn == vis2_name)
    matched_lidar = sum(1 for g in groups for _, _, _, sn, _, _ in g if sn == lidar_name)
    print(f"  匹配可见光1: {matched_vis1}")
    print(f"  匹配可见光2: {matched_vis2}")
    print(f"  匹配点云: {matched_lidar}")

    # 时间偏移统计
    vis1_diffs = []
    vis2_diffs = []
    for g in groups:
        ir_ts_val = g[0][1]
        for item in g[1:]:
            diff = abs(item[1] - ir_ts_val)
            if item[3] == vis1_name:
                vis1_diffs.append(diff)
            elif item[3] == vis2_name:
                vis2_diffs.append(diff)
    if vis1_diffs:
        print(f"  可见光1 时间差: min={min(vis1_diffs):.4f}s  max={max(vis1_diffs):.4f}s  avg={sum(vis1_diffs)/len(vis1_diffs):.4f}s")
    if vis2_diffs:
        print(f"  可见光2 时间差: min={min(vis2_diffs):.4f}s  max={max(vis2_diffs):.4f}s  avg={sum(vis2_diffs)/len(vis2_diffs):.4f}s")

    # ── 3. 上传 MinIO + 写入数据库 ──
    print("\n" + "=" * 60)
    print("阶段 3: 上传 MinIO & 写入数据库")
    print("=" * 60)

    db = engine.connect()
    total_uploaded = 0
    total_resources = 0

    # 用于后续创建数据集
    all_resource_ids: list[int] = []

    try:
        for i, group in enumerate(groups):
            group_id = i + 1  # 1-based
            if (i + 1) % 200 == 0:
                print(f"  进度: {i+1}/{len(groups)}")

            resource_ids_in_group = []

            for fpath, ts_val, fname, sensor_name, modality, is_primary in group:
                # 上传 MinIO
                object_name = f"segment/{sensor_name}/{fname}"
                file_path = upload_to_minio(fpath, object_name)
                total_uploaded += 1

                # 读取图片信息
                img_info = read_image_info(fpath)

                # 写入 data_resources
                metadata = {
                    "width": img_info["width"],
                    "height": img_info["height"],
                    "channels": img_info["channels"],
                    "file_size": f"{fpath.stat().st_size // 1024}KB",
                    "device": SENSOR_CONFIG.get(sensor_name, {}).get("device", ""),
                    "sensor": sensor_name,
                    "segment": "001",
                    "timestamp_offset": ts_val,
                    "sample_group": group_id,
                    "is_primary": is_primary,
                }

                rid = insert_resource(
                    db, name=fname, modality=modality,
                    file_path=file_path, captured_at=ts_val,
                    metadata=metadata,
                )
                resource_ids_in_group.append(rid)
                total_resources += 1

            # 创建 alignment_group
            ir_item = group[0]
            result = db.execute(
                text("""
                    INSERT INTO alignment_groups (strategy, params, report, created_by, created_at)
                    VALUES ('nearest_neighbor', :params, :report, :created_by, NOW())
                    RETURNING group_id
                """),
                {
                    "params": json.dumps({
                        "base_sensor": "infrared",
                        "base_timestamp": ir_item[1],
                        "matched_sensors": list(set(item[3] for item in group[1:])),
                    }),
                    "report": json.dumps({
                        "time_diffs": {item[3]: round(abs(item[1] - ir_item[1]), 4) for item in group[1:]},
                    }),
                    "created_by": ADMIN_ID,
                }
            )
            ag_id = result.fetchone()[0]

            # 写入 alignment_group_items
            for fpath, ts_val, fname, sensor_name, modality, is_primary in group:
                rid_for_ag = resource_ids_in_group[group.index((fpath, ts_val, fname, sensor_name, modality, is_primary))]
                db.execute(
                    text("""
                        INSERT INTO alignment_group_items (group_id, resource_id, sensor_type, is_primary)
                        VALUES (:group_id, :resource_id, :sensor_type, :is_primary)
                    """),
                    {
                        "group_id": ag_id,
                        "resource_id": rid_for_ag,
                        "sensor_type": modality,
                        "is_primary": is_primary,
                    }
                )

            all_resource_ids.extend(resource_ids_in_group)

        # ── 4. 创建数据集 ──
        print("\n" + "=" * 60)
        print("阶段 4: 创建数据集")
        print("=" * 60)

        result = db.execute(
            text("""
                INSERT INTO datasets (name, description, owner_id, filters, version, status, visibility, review_status, created_at, updated_at)
                VALUES (:name, :desc, :owner_id, :filters, 'v1.0', 'published', 'public', 'approved', NOW(), NOW())
                RETURNING dataset_id
            """),
            {
                "name": "多模态低空场景数据集 (时间对齐)",
                "desc": f"以红外时间戳为基准，最近邻匹配可见光。共 {len(groups)} 个样本，{total_resources} 个数据资源。",
                "owner_id": ADMIN_ID,
                "filters": json.dumps({
                    "modalities": ["visible", "infrared", "lidar"],
                    "match_strategy": "nearest_neighbor",
                    "base_sensor": "infrared",
                }),
            }
        )
        ds_id = result.fetchone()[0]
        print(f"  数据集 ID: {ds_id}")

        # 填充 dataset_items (全部放入 train 子集)
        for rid in all_resource_ids:
            db.execute(
                text("""
                    INSERT INTO dataset_items (dataset_id, resource_id, subset, added_at)
                    VALUES (:dataset_id, :resource_id, 'train', NOW())
                """),
                {"dataset_id": ds_id, "resource_id": rid}
            )
        print(f"  数据集项数: {len(all_resource_ids)}")

        db.commit()

        print("\n" + "=" * 60)
        print(f">> 完成!")
        print(f"   样本数 (对齐组): {len(groups)}")
        print(f"   上传 MinIO: {total_uploaded} 个文件")
        print(f"   数据库资源: {total_resources} 条")
        print(f"   数据集 ID: {ds_id}")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
