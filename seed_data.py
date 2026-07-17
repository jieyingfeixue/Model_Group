import json
from io import BytesIO
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw
from minio import Minio

MINIO = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
BUCKET = "detection-platform"
if not MINIO.bucket_exists(BUCKET):
    MINIO.make_bucket(BUCKET)

def make_image(modality, scene, index):
    colors = {"visible": (100,149,237), "infrared": (220,20,60), "mmwave": (138,43,226), "lidar": (0,139,139)}
    img = Image.new("RGB", (640, 480), colors.get(modality, (128,128,128)))
    draw = ImageDraw.Draw(img)
    draw.text((20, 220), f"{modality} | {scene} | #{index}", fill="white")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf.read()

modalities = ["visible", "infrared", "mmwave", "lidar"]
scenes = ["daytime", "night", "rainy", "foggy"]
devices = ["DJI Mavic 3", "DJI Mini 4", "Autel EVO II"]
now = datetime.now(timezone.utc)

rows = []
for i in range(24):
    m = modalities[i % 4]
    s = scenes[i % 4]
    ts = now - timedelta(days=i)
    object_name = f"data/{m}/sample_{i+1:03d}.jpg"
    img_bytes = make_image(m, s, i+1)
    MINIO.put_object(BUCKET, object_name, BytesIO(img_bytes), len(img_bytes), content_type="image/jpeg")

    meta = {
        "width": 640, "height": 480, "channels": 3, "file_size": f"{len(img_bytes)//1024}KB",
        "device": devices[i % 3], "scene": s, "weather": "clear" if i%3!=0 else "rainy",
        "time_of_day": "night" if s=="night" else "day", "geo_location": "30.5N,114.3E",
        "batch_id": f"2024Q{(i%3)+1}", "source": f"采集-批次2024Q{(i%3)+1}"
    }
    is_annotated = "TRUE" if (i % 3 != 0) else "FALSE"
    meta_json = json.dumps(meta).replace("'", "''")
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
    name = f"{m}_{i+1:03d}.jpg"
    rows.append(f"('{name}', 1, '{m}', '/{BUCKET}/{object_name}', '{meta_json}'::jsonb, 1, 'annotated', 'active', '{ts_str}', '{ts_str}')")

values = ",\n".join(rows)
sql = f"""DELETE FROM data_resources WHERE owner_id=1;
INSERT INTO data_resources (name, owner_id, modality, file_path, metadata, version, annotation_status, status, created_at, updated_at)
VALUES {values};
"""
with open("seed_data.sql", "w") as f:
    f.write(sql)
print(f"Done: {len(rows)} images in MinIO + seed_data.sql")
