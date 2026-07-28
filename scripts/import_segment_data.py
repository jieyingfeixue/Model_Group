"""
多模态采集会话导入脚本 — 对齐云上目录结构

支持目录:
  with_cameras_capture_YYYYMMDD_HHMMSS/
    ├── ..._part000_.../
    │   ├── segment_000_.../
    │   │   ├── images/{sensor}/*.jpg
    │   │   └── pointclouds/{sensor}/*.pcd
    │   └── segment_001_.../
    └── ..._part001_.../

用法:
  python scripts/import_segment_data.py
  python scripts/import_segment_data.py --capture with_cameras_capture_20260427_151113
  python scripts/import_segment_data.py --dry-run --limit-groups 20

策略:
  1. 扫描 capture → part → segment
  2. 每个 segment 内以红外时间戳为基准，最近邻匹配可见光/点云
  3. 跳过 @eaDir、不存在/不可读文件（如未下载的网盘占位）
  4. 上传 MinIO，写入 data_resources（modality + Excel 场景标签）
  5. 可选写入 alignment_groups / datasets
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image
from minio import Minio
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene_tag_utils import (  # noqa: E402
    DEFAULT_EXCEL,
    infer_batch_id_from_path,
    load_excel_folder_tags,
    lookup_tags_for_path,
)

# ─── 默认路径 / 连接 ───
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CAPTURE = Path(r"D:\桌面\with_cameras_capture_20260430_202854")
SCENE_EXCEL = Path(os.environ.get("SCENE_EXCEL", str(DEFAULT_EXCEL)))

MINIO = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
BUCKET = "detection-platform"
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:123456@localhost:5432/detection_platform"
)

SENSOR_CONFIG = {
    "hikrobot_camera__DA8679037__image_raw": {"modality": "visible", "device": "海康 DA8679037"},
    "hikrobot_camera__DA8679038__image_raw": {"modality": "visible", "device": "海康 DA8679038"},
    "usb_ir__image_raw": {"modality": "infrared", "device": "USB 红外"},
    "at360__points": {"modality": "lidar", "device": "AT360 激光雷达"},
    "mmwave_udp_radar": {"modality": "mmwave", "device": "毫米波雷达"},
}

IR_NAME = "usb_ir__image_raw"
VIS1_NAME = "hikrobot_camera__DA8679037__image_raw"
VIS2_NAME = "hikrobot_camera__DA8679038__image_raw"
LIDAR_NAME = "at360__points"
MMWAVE_NAME = "mmwave_udp_radar"

ADMIN_ID = int(os.environ.get("IMPORT_OWNER_ID", "0"))  # 0 = 自动选择/创建


def ensure_owner_id(db, preferred: int = 0) -> int:
    """保证导入用的 owner_id 在 users 表中存在。"""
    if preferred > 0:
        row = db.execute(
            text("SELECT user_id FROM users WHERE user_id = :uid"),
            {"uid": preferred},
        ).fetchone()
        if row:
            return int(row[0])
        print(f"  [WARN] 指定 owner_id={preferred} 不存在，改为自动选择")

    row = db.execute(
        text("SELECT user_id FROM users WHERE role = 'admin' ORDER BY user_id LIMIT 1")
    ).fetchone()
    if row:
        return int(row[0])

    row = db.execute(text("SELECT user_id FROM users ORDER BY user_id LIMIT 1")).fetchone()
    if row:
        return int(row[0])

    # 库中无用户：创建一个导入专用账号
    # 密码占位哈希（不可用于登录也不要紧；测试可用 phase3_fixture）
    row = db.execute(
        text(
            """
            INSERT INTO users (username, password_hash, email, role, is_active)
            VALUES ('data_importer', '!', 'importer@local', 'admin', true)
            RETURNING user_id
            """
        )
    ).fetchone()
    print(f"  已创建导入用户 data_importer，user_id={row[0]}")
    return int(row[0])


def table_exists(db, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :t
            LIMIT 1
            """
        ),
        {"t": table_name},
    ).fetchone()
    return row is not None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="导入 with_cameras_capture 会话数据")
    p.add_argument(
        "--capture",
        default=str(os.environ.get("CAPTURE_DIR", DEFAULT_CAPTURE)),
        help="采集会话根目录（含 with_cameras_capture_*）",
    )
    p.add_argument("--excel", default=str(SCENE_EXCEL), help="场景标签 Excel")
    p.add_argument("--db", default=DB_URL, help="数据库连接串")
    p.add_argument("--dry-run", action="store_true", help="只扫描/匹配，不写 MinIO/DB")
    p.add_argument("--limit-groups", type=int, default=0, help="最多导入多少个对齐样本（0=全部）")
    p.add_argument("--skip-dataset", action="store_true", help="不创建 datasets / dataset_items")
    p.add_argument("--skip-alignment", action="store_true", help="不写 alignment_groups")
    return p.parse_args()


def win_long_path(path: Path | str) -> str:
    """Windows 下路径常超 MAX_PATH(260)，需 \\?\ 前缀才能访问可见光长文件名。"""
    p = str(path)
    if os.name != "nt":
        return p
    try:
        p = str(Path(p).resolve())
    except OSError:
        p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def extract_timestamp(filename: str) -> float | None:
    m = re.search(r"_t(\d{6})\.(\d{3})", filename)
    if m:
        return float(f"{int(m.group(1))}.{m.group(2)}")
    return None


def is_usable_file(path: Path) -> bool:
    """跳过群晖 @eaDir、网盘未落地占位、空文件；Windows 长路径可用。"""
    if any(part.startswith("@") for part in path.parts):
        return False
    try:
        lp = win_long_path(path)
        st = os.stat(lp)
        if not stat.S_ISREG(st.st_mode):
            return False
        if st.st_size <= 0:
            return False
        return True
    except OSError:
        return False


def list_sensor_files(sensor_dir: Path) -> list[tuple[Path, float, str]]:
    if not sensor_dir.is_dir():
        return []
    out: list[tuple[Path, float, str]] = []
    try:
        names = sorted(os.listdir(win_long_path(sensor_dir) if os.name == "nt" else sensor_dir))
    except OSError:
        try:
            names = sorted(os.listdir(sensor_dir))
        except OSError:
            return []
    for name in names:
        if name.startswith("@"):
            continue
        fpath = sensor_dir / name
        if not is_usable_file(fpath):
            continue
        ts = extract_timestamp(name)
        if ts is None:
            continue
        out.append((fpath, ts, name))
    return out


def discover_segments(capture_dir: Path) -> list[tuple[str, Path]]:
    """返回 [(part_name, segment_dir), ...]"""
    found: list[tuple[str, Path]] = []
    if not capture_dir.is_dir():
        return found

    # 兼容：根下直接就是 segment_*（旧结构）
    direct_segs = sorted(
        [p for p in capture_dir.iterdir() if p.is_dir() and p.name.startswith("segment_")],
        key=lambda p: p.name,
    )
    if direct_segs:
        for seg in direct_segs:
            found.append((".", seg))
        return found

    parts = sorted(
        [
            p
            for p in capture_dir.iterdir()
            if p.is_dir() and ("part" in p.name.lower() or p.name.startswith("with_cameras_capture_"))
        ],
        key=lambda p: p.name,
    )
    # 若没有 part 目录，再扫一层子目录里的 segment
    if not parts:
        parts = [p for p in capture_dir.iterdir() if p.is_dir() and not p.name.startswith("@")]

    for part in parts:
        segs = sorted(
            [p for p in part.iterdir() if p.is_dir() and p.name.startswith("segment_")],
            key=lambda p: p.name,
        )
        for seg in segs:
            found.append((part.name, seg))
    return found


def nearest_index(timestamps: list[float], target: float) -> int:
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


def parse_part_wall_ts(part_name: str) -> float | None:
    """从 part 目录名解析墙钟时间戳（秒）。"""
    from datetime import datetime

    m = re.search(r"_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})$", part_name)
    if not m:
        return None
    y, mo, d, h, mi, s = map(int, m.groups())
    return datetime(y, mo, d, h, mi, s).timestamp()


def part_session_offsets(part_names: list[str]) -> dict[str, float]:
    """各 part 相对最早 part 的会话时间偏移（秒）。"""
    walls = {p: parse_part_wall_ts(p) for p in part_names}
    valid = {p: t for p, t in walls.items() if t is not None}
    if not valid:
        return {p: 0.0 for p in part_names}
    t0 = min(valid.values())
    return {p: (valid[p] - t0) if p in valid else 0.0 for p in part_names}


def discover_mmwave_frames(capture_dir: Path) -> list[tuple[Path, int, float, str]]:
    """扫描会话根下 mmwave_* 目录，返回 [(mat_path, frame_idx, session_ts, display_name)]。

    时间轴：文件名 FZxxxxx-yyyyy 按毫秒理解，帧在区间内均匀插值。
    """
    out: list[tuple[Path, int, float, str]] = []
    mm_dirs = [
        p
        for p in capture_dir.iterdir()
        if p.is_dir() and "mmwave" in p.name.lower() and not p.name.startswith("@")
    ]
    if not mm_dirs:
        return out

    for mm_dir in sorted(mm_dirs, key=lambda p: p.name):
        mats = sorted(mm_dir.glob("*.mat"))
        for mat_path in mats:
            m = re.search(r"FZ(\d+)-(\d+)", mat_path.name, re.IGNORECASE)
            if not m:
                continue
            fz_a, fz_b = int(m.group(1)), int(m.group(2))
            try:
                import scipy.io as sio

                data = sio.loadmat(win_long_path(mat_path), simplify_cells=True)
                n = len(data.get("Data_Ori", []))
            except Exception as exc:
                print(f"  [WARN] 无法读取 mmwave mat {mat_path.name}: {exc}")
                continue
            if n <= 0:
                continue
            for i in range(n):
                fz = fz_a + (fz_b - fz_a) * ((i + 0.5) / n)
                session_ts = fz / 1000.0  # FZ ≈ 毫秒
                display = f"{mat_path.name}::frame{i}"
                out.append((mat_path, i, session_ts, display))
    out.sort(key=lambda x: x[2])
    return out


def build_groups(
    sensor_files: dict[str, list[tuple[Path, float, str]]],
) -> list[list[tuple[Path, float, str, str, str, bool]]]:
    ir_files = sensor_files.get(IR_NAME, [])
    vis1_files = sensor_files.get(VIS1_NAME, [])
    vis2_files = sensor_files.get(VIS2_NAME, [])
    lidar_files = sensor_files.get(LIDAR_NAME, [])

    vis1_ts = [ts for _, ts, _ in vis1_files]
    vis2_ts = [ts for _, ts, _ in vis2_files]
    lidar_ts = [ts for _, ts, _ in lidar_files]

    groups: list[list[tuple[Path, float, str, str, str, bool]]] = []
    for ir_fpath, ir_ts_val, ir_fname in ir_files:
        group: list[tuple[Path, float, str, str, str, bool]] = [
            (ir_fpath, ir_ts_val, ir_fname, IR_NAME, "infrared", True)
        ]
        idx1 = nearest_index(vis1_ts, ir_ts_val)
        if idx1 >= 0:
            fpath, ts_val, fname = vis1_files[idx1]
            group.append((fpath, ts_val, fname, VIS1_NAME, "visible", False))
        idx2 = nearest_index(vis2_ts, ir_ts_val)
        if idx2 >= 0:
            fpath, ts_val, fname = vis2_files[idx2]
            group.append((fpath, ts_val, fname, VIS2_NAME, "visible", False))
        idx_l = nearest_index(lidar_ts, ir_ts_val)
        if idx_l >= 0:
            fpath, ts_val, fname = lidar_files[idx_l]
            group.append((fpath, ts_val, fname, LIDAR_NAME, "lidar", False))
        groups.append(group)
    return groups


def read_image_info(fpath: Path) -> dict:
    try:
        with Image.open(win_long_path(fpath)) as img:
            w, h = img.size
            c = len(img.getbands())
        return {"width": w, "height": h, "channels": c}
    except Exception:
        return {"width": 0, "height": 0, "channels": 0}


def upload_to_minio(local_path: Path, object_name: str) -> str:
    ext = local_path.suffix.lower()
    content_type = (
        "image/jpeg"
        if ext in (".jpg", ".jpeg")
        else "image/png"
        if ext == ".png"
        else "application/octet-stream"
    )
    src = win_long_path(local_path)
    MINIO.fput_object(BUCKET, object_name, src, content_type=content_type)
    return f"/{BUCKET}/{object_name}"


def insert_resource(
    db,
    name: str,
    modality: str,
    file_path: str,
    captured_at: float,
    metadata: dict,
    owner_id: int,
) -> int:
    meta_json = json.dumps(metadata, ensure_ascii=False)
    result = db.execute(
        text(
            """
            INSERT INTO data_resources
            (name, owner_id, modality, file_path, metadata, captured_at, version,
             annotation_status, status, created_at, updated_at)
            VALUES
            (:name, :owner_id, :modality, :file_path, CAST(:metadata AS jsonb), :captured_at, 1,
             'unannotated', 'active', NOW(), NOW())
            RETURNING resource_id
            """
        ),
        {
            "name": name,
            "owner_id": owner_id,
            "modality": modality,
            "file_path": file_path,
            "metadata": meta_json,
            "captured_at": captured_at,
        },
    )
    return result.fetchone()[0]


def scan_segment(segment_dir: Path) -> dict[str, list[tuple[Path, float, str]]]:
    sensor_files: dict[str, list[tuple[Path, float, str]]] = defaultdict(list)
    images_dir = segment_dir / "images"
    pc_dir = segment_dir / "pointclouds"
    if images_dir.is_dir():
        for sensor_name in SENSOR_CONFIG:
            if SENSOR_CONFIG[sensor_name]["modality"] == "lidar":
                continue
            files = list_sensor_files(images_dir / sensor_name)
            if files:
                sensor_files[sensor_name] = files
    if pc_dir.is_dir():
        files = list_sensor_files(pc_dir / LIDAR_NAME)
        if files:
            sensor_files[LIDAR_NAME] = files
    return sensor_files


def main() -> None:
    args = parse_args()
    capture_dir = Path(args.capture)
    if not capture_dir.is_absolute():
        capture_dir = BASE_DIR / capture_dir
    if not capture_dir.is_dir():
        raise SystemExit(f"采集目录不存在: {capture_dir}")

    batch_id = infer_batch_id_from_path(capture_dir) or capture_dir.name
    print("=" * 60)
    print(f"采集会话: {capture_dir}")
    print(f"batch_id: {batch_id}")
    print("=" * 60)

    print("阶段 0: 加载场景 Excel")
    folder_tags: dict = {}
    try:
        folder_tags = load_excel_folder_tags(args.excel)
        scene_tags = lookup_tags_for_path(capture_dir, folder_tags, fallback_batch_id=batch_id)
        print(f"  Excel: {args.excel}")
        print(f"  会话标签数: {len(folder_tags)}")
        print(f"  本会话标签: { {k: scene_tags.get(k) for k in ('weather','time_of_day','terrain','obstacle','scene') if k in scene_tags} }")
    except Exception as e:
        scene_tags = {"batch_id": batch_id}
        print(f"  [WARN] Excel 未加载: {e}")

    segments = discover_segments(capture_dir)
    if not segments:
        raise SystemExit(f"未找到 segment_* 目录: {capture_dir}")
    print(f"\n发现 segment: {len(segments)} 个")
    for part, seg in segments:
        print(f"  - {part} / {seg.name}")

    print("\n阶段 0.5: 扫描毫米波 MAT")
    mmwave_frames = discover_mmwave_frames(capture_dir)
    mm_ts_list = [t for _, _, t, _ in mmwave_frames]
    print(f"  mmwave 帧数: {len(mmwave_frames)}")
    if mmwave_frames:
        print(f"  mmwave 时间范围: {mm_ts_list[0]:.3f} ~ {mm_ts_list[-1]:.3f} s")

    part_names = list({p for p, _ in segments})
    part_offsets = part_session_offsets(part_names)
    print(f"  part 会话偏移: { {k: round(v,1) for k,v in part_offsets.items()} }")

    # 汇总所有对齐组
    all_groups: list[tuple[str, str, list]] = []  # part, segment_name, group
    for part_name, segment_dir in segments:
        sensor_files = scan_segment(segment_dir)
        print(f"\n扫描 {part_name}/{segment_dir.name}:")
        for name, files in sensor_files.items():
            mod = SENSOR_CONFIG.get(name, {}).get("modality", "?")
            print(f"  {name}: {len(files)} [{mod}]")
        if not sensor_files.get(IR_NAME):
            print("  [SKIP] 无可用红外文件")
            continue
        groups = build_groups(sensor_files)
        # 按会话时间对齐毫米波
        off = part_offsets.get(part_name, 0.0)
        mm_hit = 0
        if mmwave_frames:
            for g in groups:
                ir_ts = g[0][1]
                session_ts = off + float(ir_ts)
                idx = nearest_index(mm_ts_list, session_ts)
                if idx >= 0:
                    mat_path, frame_idx, mts, dname = mmwave_frames[idx]
                    # 时间差过大则跳过（>2s）
                    if abs(mts - session_ts) <= 2.0:
                        g.append((mat_path, mts, dname, MMWAVE_NAME, "mmwave", False))
                        mm_hit += 1
        print(f"  对齐组: {len(groups)}（其中含毫米波 {mm_hit}）")
        for g in groups:
            all_groups.append((part_name, segment_dir.name, g))

    if args.limit_groups and args.limit_groups > 0:
        all_groups = all_groups[: args.limit_groups]
        print(f"\n已限制为前 {len(all_groups)} 个对齐组")

    print(f"\n合计对齐样本: {len(all_groups)}")
    if args.dry_run:
        # 统计模态覆盖
        mod_count = defaultdict(int)
        for _, _, g in all_groups:
            for *_, modality, _ in g:
                mod_count[modality] += 1
        print("dry-run 模态资源计数:", dict(mod_count))
        print("dry-run 完成（未写库）")
        return

    if not MINIO.bucket_exists(BUCKET):
        MINIO.make_bucket(BUCKET)
        print(f"已创建 MinIO 桶: {BUCKET}")

    engine = create_engine(args.db)
    db = engine.connect()
    owner_id = ensure_owner_id(db, ADMIN_ID)
    print(f"导入归属用户 owner_id={owner_id}")

    skip_alignment = args.skip_alignment
    if not skip_alignment and not table_exists(db, "alignment_groups"):
        print("  [WARN] 表 alignment_groups 不存在，自动跳过对齐组写入（不影响场景/模态筛选）")
        skip_alignment = True
    skip_dataset = args.skip_dataset
    if not skip_dataset and not table_exists(db, "datasets"):
        print("  [WARN] 表 datasets 不存在，自动跳过数据集写入")
        skip_dataset = True

    total_uploaded = 0
    total_resources = 0
    all_resource_ids: list[int] = []
    # 用「库内已有最大 sample_group + 1」起编，避免多会话都从 1 编号导致前端误合并
    sample_group_id = 0
    try:
        row = db.execute(text(
            "SELECT COALESCE(MAX((metadata->>'sample_group')::int), 0) FROM data_resources "
            "WHERE metadata->>'sample_group' ~ '^[0-9]+$'"
        )).scalar()
        sample_group_id = int(row or 0)
    except Exception:
        sample_group_id = 0
    print(f"  sample_group 起始序号: {sample_group_id + 1}")

    try:
        print("\n阶段 3: 上传 MinIO & 写入数据库")
        for i, (part_name, segment_name, group) in enumerate(all_groups):
            sample_group_id += 1
            if sample_group_id % 100 == 0 or sample_group_id == 1:
                print(f"  进度: {sample_group_id}/{len(all_groups)}")

            resource_ids_in_group: list[int] = []
            for fpath, ts_val, fname, sensor_name, modality, is_primary in group:
                mmwave_frame_index = None
                if modality == "mmwave" and "::frame" in fname:
                    try:
                        mmwave_frame_index = int(fname.rsplit("::frame", 1)[-1])
                    except ValueError:
                        mmwave_frame_index = 0
                    object_name = f"{batch_id}/mmwave/{fpath.name}"
                else:
                    object_name = f"{batch_id}/{part_name}/{segment_name}/{sensor_name}/{fname}"
                file_path = upload_to_minio(fpath, object_name)
                total_uploaded += 1

                if modality in ("lidar", "mmwave"):
                    img_info = {"width": 0, "height": 0, "channels": 0}
                else:
                    img_info = read_image_info(fpath)
                metadata = {
                    "width": img_info["width"],
                    "height": img_info["height"],
                    "channels": img_info["channels"],
                    "file_size": f"{os.stat(win_long_path(fpath)).st_size // 1024}KB",
                    "device": SENSOR_CONFIG.get(sensor_name, {}).get("device", ""),
                    "sensor": sensor_name,
                    "part": part_name,
                    "segment": segment_name,
                    "timestamp_offset": ts_val,
                    "sample_group": sample_group_id,
                    "is_primary": is_primary,
                    "modality": modality,
                }
                if mmwave_frame_index is not None:
                    metadata["mmwave_frame_index"] = mmwave_frame_index
                # 会话级场景标签（Excel）
                metadata.update(scene_tags)
                metadata["batch_id"] = batch_id

                rid = insert_resource(
                    db,
                    name=fname if modality != "mmwave" else fpath.name,
                    modality=modality,
                    file_path=file_path,
                    captured_at=ts_val,
                    metadata=metadata,
                    owner_id=owner_id,
                )
                resource_ids_in_group.append(rid)
                total_resources += 1

            if not skip_alignment:
                ir_item = group[0]
                result = db.execute(
                    text(
                        """
                        INSERT INTO alignment_groups (strategy, params, report, created_by, created_at)
                        VALUES ('nearest_neighbor', CAST(:params AS jsonb), CAST(:report AS jsonb), :created_by, NOW())
                        RETURNING group_id
                        """
                    ),
                    {
                        "params": json.dumps(
                            {
                                "base_sensor": "infrared",
                                "base_timestamp": ir_item[1],
                                "batch_id": batch_id,
                                "part": part_name,
                                "segment": segment_name,
                                "matched_sensors": list({item[3] for item in group[1:]}),
                            },
                            ensure_ascii=False,
                        ),
                        "report": json.dumps(
                            {
                                "time_diffs": {
                                    item[3]: round(abs(item[1] - ir_item[1]), 4)
                                    for item in group[1:]
                                }
                            },
                            ensure_ascii=False,
                        ),
                        "created_by": owner_id,
                    },
                )
                ag_id = result.fetchone()[0]
                for j, (fpath, ts_val, fname, sensor_name, modality, is_primary) in enumerate(group):
                    db.execute(
                        text(
                            """
                            INSERT INTO alignment_group_items
                            (group_id, resource_id, sensor_type, is_primary)
                            VALUES (:group_id, :resource_id, :sensor_type, :is_primary)
                            """
                        ),
                        {
                            "group_id": ag_id,
                            "resource_id": resource_ids_in_group[j],
                            "sensor_type": modality,
                            "is_primary": is_primary,
                        },
                    )

            all_resource_ids.extend(resource_ids_in_group)

        ds_id = None
        if not skip_dataset and all_resource_ids:
            print("\n阶段 4: 创建数据集")
            result = db.execute(
                text(
                    """
                    INSERT INTO datasets
                    (name, description, owner_id, filters, version, status, visibility,
                     review_status, created_at, updated_at)
                    VALUES
                    (:name, :desc, :owner_id, CAST(:filters AS jsonb), 1, 'published', 'public',
                     'approved', NOW(), NOW())
                    RETURNING dataset_id
                    """
                ),
                {
                    "name": f"多模态数据集 {batch_id}",
                    "desc": (
                        f"会话 {batch_id}，红外对齐。样本 {len(all_groups)}，"
                        f"资源 {total_resources}。"
                    ),
                    "owner_id": owner_id,
                    "filters": json.dumps(
                        {
                            "batch_id": batch_id,
                            "modalities": ["visible", "infrared", "lidar"],
                            "match_strategy": "nearest_neighbor",
                            **{k: scene_tags[k] for k in ("weather", "time_of_day", "terrain", "obstacle", "scene") if k in scene_tags},
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            ds_id = result.fetchone()[0]
            for rid in all_resource_ids:
                db.execute(
                    text(
                        """
                        INSERT INTO dataset_items (dataset_id, resource_id, subset, added_at)
                        VALUES (:dataset_id, :resource_id, 'train', NOW())
                        """
                    ),
                    {"dataset_id": ds_id, "resource_id": rid},
                )
            print(f"  数据集 ID: {ds_id}，条目 {len(all_resource_ids)}")

        db.commit()
        print("\n" + "=" * 60)
        print("完成")
        print(f"  对齐样本: {len(all_groups)}")
        print(f"  MinIO 上传: {total_uploaded}")
        print(f"  DB 资源: {total_resources}")
        if ds_id:
            print(f"  数据集 ID: {ds_id}")
        print(f"  场景标签: weather={scene_tags.get('weather')} terrain={scene_tags.get('terrain')} "
              f"obstacle={scene_tags.get('obstacle')} time={scene_tags.get('time_of_day')}")
        print("=" * 60)
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
