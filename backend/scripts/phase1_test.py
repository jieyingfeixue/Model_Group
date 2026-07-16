"""第一阶段整体功能测试脚本 — 不做任何代码修改，仅发送 HTTP 请求并验证结果"""

import json
import os
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

# 确保 backend/ 在 Python 路径中，以便导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://127.0.0.1:8002"
PASS = 0
FAIL = 0


def test(num, name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"T{num:02d} PASS {name}")
    except AssertionError as e:
        FAIL += 1
        print(f"T{num:02d} FAIL {name}: {e}")
    except Exception as e:
        FAIL += 1
        print(f"T{num:02d} ERR {name}: {type(e).__name__}: {e}")
        traceback.print_exc()


def api(method, path, body=None, token=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            rbody = resp.read().decode()
            return resp.status, (json.loads(rbody) if rbody else {})
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def upload(token, files, meta_info="{}"):
    """multipart/form-data 上传"""
    import io

    boundary = "----TestBoundary" + uuid.uuid4().hex
    body = io.BytesIO()
    for path in files:
        fname = os.path.basename(path)
        body.write(f"--{boundary}\r\n".encode())
        body.write(
            f'Content-Disposition: form-data; name="files"; filename="{fname}"\r\n'.encode()
        )
        body.write(b"Content-Type: image/jpeg\r\n\r\n")
        with open(path, "rb") as f:
            body.write(f.read())
        body.write(b"\r\n")
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="meta_info"\r\n\r\n{meta_info}\r\n'.encode()
    )
    body.write(f"--{boundary}--\r\n".encode())

    body_bytes = body.getvalue()
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        BASE + "/api/data/upload", data=body_bytes, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


# ──── 准备测试用户 ────
ts = str(uuid.uuid4())[:8]
USER = f"test_{ts}"
PWD = "Abc12345!"
EMAIL = f"{USER}@test.com"
AT = None
RT = None

print("=" * 60)
print(f"  第一阶段整体功能测试 — {USER}")
print(f"  {datetime.now(timezone.utc).isoformat()}")
print("=" * 60)

# ═══════════════ 模块一：用户鉴权 ═══════════════
print()
print("━━━ 模块一：用户鉴权（15 项） ━━━")


def t01():
    global AT, RT
    c, r = api("POST", "/api/auth/register", {"username": USER, "password": PWD, "email": EMAIL})
    assert c == 201, f"status={c}"
    assert r["username"] == USER
    assert r["role"] == "normal"
    assert r["is_active"] is True


def t02():
    c, r = api("POST", "/api/auth/register", {"username": USER, "password": PWD, "email": "dup@t.com"})
    assert c == 409, f"status={c} (expected 409)"


def t03():
    c, r = api("POST", "/api/auth/register", {"username": "weak", "password": "123", "email": "w@t.com"})
    assert c == 422, f"status={c} (expected 422)"


def t04():
    global AT, RT
    c, r = api("POST", "/api/auth/login", {"username": USER, "password": PWD})
    assert c == 200, f"status={c}"
    assert "access_token" in r
    assert "refresh_token" in r
    assert r["token_type"] == "bearer"
    assert r["role"] == "normal"
    AT = r["access_token"]
    RT = r["refresh_token"]


def t05():
    c, r = api("POST", "/api/auth/login", {"username": USER, "password": "wrongpass"})
    assert c == 401, f"status={c} (expected 401)"


def t06():
    c, r = api("GET", "/api/users/me", token=AT)
    assert c == 200, f"status={c}"
    assert r["username"] == USER
    assert r["email"] == EMAIL


def t07():
    new_email = f"updated_{EMAIL}"
    c, r = api("PUT", "/api/users/me", {"email": new_email}, token=AT)
    assert c == 200, f"status={c}"
    assert r["email"] == new_email


def t08():
    c, r = api("PUT", "/api/users/me", {"old_password": PWD, "new_password": "Xyz98765@"}, token=AT)
    assert c == 200, f"status={c}"


def t09():
    global AT, RT
    c, r = api("POST", "/api/auth/login", {"username": USER, "password": "Xyz98765@"})
    assert c == 200, f"status={c}"
    AT = r["access_token"]
    RT = r["refresh_token"]


def t10():
    c, r = api("POST", "/api/auth/refresh", {"refresh_token": RT})
    assert c == 200, f"status={c}"
    assert "access_token" in r
    assert "refresh_token" in r


def t11():
    c, r = api("POST", f"/api/auth/logout?refresh_token={RT}", token=AT)
    assert c == 204, f"status={c} (expected 204)"


def t12():
    c, r = api("GET", "/api/users/me", token=AT)
    assert c == 401, f"status={c} (expected 401)"


def t13():
    c, r = api("POST", "/api/auth/refresh", {"refresh_token": RT})
    assert c == 401, f"status={c} (expected 401 — token revoked)"


def t14():
    c, r = api("GET", "/api/users/me")
    assert c == 401, f"status={c} (expected 401)"


def t15():
    global AT
    c, r = api("POST", "/api/auth/login", {"username": USER, "password": "Xyz98765@"})
    AT = r["access_token"]
    c2, r2 = api("GET", "/api/users/me/history?page=1&size=10", token=AT)
    assert c2 == 200, f"status={c2}"
    assert "items" in r2
    assert "total" in r2
    assert "page" in r2


test(1, "POST /api/auth/register", t01)
test(2, "重复用户名 → 409", t02)
test(3, "弱密码 → 422", t03)
test(4, "POST /api/auth/login", t04)
test(5, "错误密码 → 401", t05)
test(6, "GET /api/users/me", t06)
test(7, "PUT /api/users/me 改邮箱", t07)
test(8, "PUT /api/users/me 改密码", t08)
test(9, "新密码登录", t09)
test(10, "POST /api/auth/refresh", t10)
test(11, "POST /api/auth/logout", t11)
test(12, "登出后访问 → 401", t12)
test(13, "登出后 Refresh → 401", t13)
test(14, "无 Token → 401", t14)
test(15, "GET /api/users/me/history", t15)

# ═══════════════ 模块二：数据资源 CRUD ═══════════════
print()
print("━━━ 模块二：数据资源 CRUD（7 项） ━━━")

tmpdir = tempfile.gettempdir()
img_path = os.path.join(tmpdir, "phase1_test.jpg")

# 创建测试图片
try:
    from PIL import Image
    Image.new("RGB", (320, 240), color="green").save(img_path)
except ImportError:
    # Pillow 不可用时用简单 bytes 模拟
    with open(img_path, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 1000)


def t16():
    c, r = upload(AT, [img_path], '{"scene":"urban","modality":"visible"}')
    assert c == 201, f"status={c}"
    assert len(r) > 0
    assert "meta_info" in r[0]
    assert "file_path" in r[0]
    assert r[0]["annotation_status"] == "unannotated"


def t17():
    c, r = api("GET", "/api/data?page=1&size=50", token=AT)
    assert c == 200, f"status={c}"
    assert r["total"] >= 1
    assert len(r["items"]) >= 1


def t18():
    c, r = api("GET", "/api/data?modality=visible&page=1&size=50", token=AT)
    assert c == 200, f"status={c}"


def t19():
    c, r = api("GET", "/api/data?scene=urban&page=1&size=50", token=AT)
    assert c == 200, f"status={c}"


def t20():
    yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    c, r = api("GET", f"/api/data?start_time={yesterday}&page=1&size=50", token=AT)
    assert c == 200, f"status={c}"
    assert r["total"] >= 1, f"total={r['total']} (expected >=1)"


def t21():
    c, r = api("GET", "/api/data?page=1&size=1", token=AT)
    assert c == 200, f"status={c}"
    assert len(r["items"]) <= 1, f"got {len(r['items'])} items (expected <=1)"


def t22():
    c, r = upload(AT, [img_path], '{"scene":"night","modality":"infrared"}')
    assert c == 201, f"status={c}"
    c2, r2 = api("GET", "/api/data?modality=infrared&page=1&size=50", token=AT)
    assert c2 == 200, f"status={c2}"
    assert r2["total"] >= 1, f"no infrared results"


test(16, "POST /api/data/upload", t16)
test(17, "GET /api/data 全量查询", t17)
test(18, "按 modality 筛选", t18)
test(19, "按 scene 筛选", t19)
test(20, "按 time_range 筛选", t20)
test(21, "分页 size=1", t21)
test(22, "上传 infrared + 筛选验证", t22)

# ═══════════════ 模块三：基础设施 ═══════════════
print()
print("━━━ 模块三：基础设施（6 项） ━━━")


def t23():
    req = urllib.request.Request(BASE + "/api/health")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert data["status"] == "ok"
        assert "version" in data


def t24():
    req = urllib.request.Request(BASE + "/docs")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert "swagger" in resp.read().decode().lower()


def t25():
    req = urllib.request.Request(BASE + "/openapi.json")
    with urllib.request.urlopen(req) as resp:
        paths = json.loads(resp.read().decode())["paths"]
    required = [
        "/api/auth/register", "/api/auth/login", "/api/auth/refresh",
        "/api/auth/logout", "/api/users/me", "/api/users/me/history",
        "/api/data/upload", "/api/data", "/api/health",
    ]
    for p in required:
        assert p in paths, f"missing endpoint: {p}"


def t26():
    from app.core.redis import get_redis_client
    assert get_redis_client().ping()


def t27():
    from app.core.storage import _client
    from app.core.config import settings
    assert _client.bucket_exists(settings.MINIO_BUCKET)


def t28():
    from app.core.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        assert db.execute(text("SELECT 1")).scalar() == 1
    finally:
        db.close()


test(23, "GET /api/health", t23)
test(24, "Swagger UI /docs 可访问", t24)
test(25, "OpenAPI JSON 含全部 9 个端点", t25)
test(26, "Redis 连接正常", t26)
test(27, "MinIO 连接正常", t27)
test(28, "PostgreSQL 连接正常", t28)

# ═══════════════ 结果 ═══════════════
print()
print("=" * 60)
print(f"  测试结果: {PASS} 通过 / {FAIL} 失败 / {PASS + FAIL} 总计")
if FAIL == 0:
    print("  第一阶段全部测试通过 PASS")
else:
    print(f"  有 {FAIL} 项测试未通过 FAIL")
print("=" * 60)
