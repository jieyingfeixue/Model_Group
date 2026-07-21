"""训练执行器 — Phase2：Docker demo 容器 / 本地 subprocess，解析 Loss/进度。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.redis import get_redis_client

PROGRESS_RE = re.compile(
    r"PROGRESS\s+epoch=(?P<epoch>\d+)\s+total_epochs=(?P<total>\d+)\s+"
    r"loss=(?P<loss>[\d.]+)\s+map50=(?P<map50>[\d.]+)"
)

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[dict[str, Any]], None]
ShouldStop = Callable[[], bool]


@dataclass
class TrainRunResult:
    ok: bool
    status: str
    progress: dict[str, Any] | None
    error: str | None = None
    output_weight_path: Path | None = None


def job_dir(task_id: int) -> Path:
    root = Path(settings.TRAIN_JOBS_DIR)
    path = root / f"task_{task_id}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "output").mkdir(exist_ok=True)
    (path / "input").mkdir(exist_ok=True)
    return path


def host_job_dir(task_id: int) -> Path:
    """Docker 绑定挂载用的宿主机路径。"""
    host_root = (settings.TRAIN_HOST_JOBS_DIR or "").strip()
    if not host_root:
        return job_dir(task_id).resolve()
    return Path(host_root) / f"task_{task_id}"


def write_train_config(task_id: int, payload: dict[str, Any]) -> Path:
    path = job_dir(task_id) / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def acquire_train_slot(task_id: int) -> bool:
    """全局训练槽位（默认 1）。成功返回 True。"""
    try:
        client = get_redis_client()
        return bool(
            client.set(
                settings.TRAIN_SLOT_KEY,
                str(task_id),
                nx=True,
                ex=settings.TRAIN_TIMEOUT_SEC + 300,
            )
        )
    except Exception:
        return True


def release_train_slot(task_id: int) -> None:
    try:
        client = get_redis_client()
        current = client.get(settings.TRAIN_SLOT_KEY)
        if current is None or str(current) == str(task_id):
            client.delete(settings.TRAIN_SLOT_KEY)
    except Exception:
        pass


def mark_stop_requested(task_id: int) -> None:
    try:
        client = get_redis_client()
        client.set(f"train_stop:{task_id}", "1", ex=86400)
    except Exception:
        pass


def clear_stop_flag(task_id: int) -> None:
    try:
        client = get_redis_client()
        client.delete(f"train_stop:{task_id}")
    except Exception:
        pass


def is_stop_requested(task_id: int) -> bool:
    try:
        client = get_redis_client()
        return bool(client.get(f"train_stop:{task_id}"))
    except Exception:
        return False


def remember_container(task_id: int, container_id: str) -> None:
    try:
        client = get_redis_client()
        client.set(f"train_container:{task_id}", container_id, ex=86400)
    except Exception:
        pass


def clear_container_ref(task_id: int) -> None:
    try:
        client = get_redis_client()
        client.delete(f"train_container:{task_id}")
    except Exception:
        pass


def kill_train_container(task_id: int) -> bool:
    """按 Redis 中记录的 container_id 强制停止训练容器。"""
    mark_stop_requested(task_id)
    try:
        client = get_redis_client()
        cid = client.get(f"train_container:{task_id}")
    except Exception:
        cid = None
    if not cid:
        return False
    try:
        import docker

        docker_client = docker.from_env()
        container = docker_client.containers.get(str(cid))
        container.kill()
        return True
    except Exception:
        return False


def _parse_line(
    line: str,
    on_log: LogCallback,
    on_progress: ProgressCallback,
) -> dict[str, Any] | None:
    on_log(line)
    m = PROGRESS_RE.search(line)
    if m:
        progress = {
            "epoch": int(m.group("epoch")),
            "total_epochs": int(m.group("total")),
            "loss": float(m.group("loss")),
            "map50": float(m.group("map50")),
        }
        on_progress(progress)
        return progress
    return None


def _demo_train_script() -> Path:
    return Path(__file__).resolve().parents[2] / "training" / "demo_trainer" / "train.py"


def run_local_trainer(
    task_id: int,
    *,
    on_log: LogCallback,
    on_progress: ProgressCallback,
    should_stop: ShouldStop,
) -> TrainRunResult:
    """用本机 Python 跑 demo_trainer（无需 Docker 镜像）。"""
    script = _demo_train_script()
    config = job_dir(task_id) / "config.json"
    output = job_dir(task_id) / "output" / "weights.pt"
    last_progress: dict[str, Any] | None = None

    on_log(f"[executor] local python {script}")
    proc = subprocess.Popen(
        [sys.executable, str(script), "--config", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert proc.stdout is not None
    deadline = time.time() + settings.TRAIN_TIMEOUT_SEC
    try:
        while True:
            if time.time() > deadline:
                proc.kill()
                return TrainRunResult(False, "failed", last_progress, "train timeout")
            if should_stop() or is_stop_requested(task_id):
                proc.kill()
                return TrainRunResult(False, "stopped", last_progress, "stopped by user/admin")

            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                time.sleep(0.05)
                continue
            parsed = _parse_line(line.rstrip("\n"), on_log, on_progress)
            if parsed:
                last_progress = parsed

        code = proc.wait(timeout=5)
        if code != 0:
            return TrainRunResult(
                False, "failed", last_progress, f"trainer exit code {code}"
            )
        if not output.exists():
            return TrainRunResult(False, "failed", last_progress, "output weights missing")
        return TrainRunResult(True, "completed", last_progress, None, output)
    finally:
        if proc.poll() is None:
            proc.kill()


def _running_inside_container() -> bool:
    return Path("/.dockerenv").exists()


def run_docker_trainer(
    task_id: int,
    *,
    on_log: LogCallback,
    on_progress: ProgressCallback,
    should_stop: ShouldStop,
) -> TrainRunResult:
    """拉取 detection-train:demo 容器执行训练。"""
    import docker
    from docker.errors import DockerException, ImageNotFound, NotFound

    # Celery 跑在容器内时，必须配置宿主机绝对路径才能 bind-mount；否则回退 local
    if _running_inside_container() and not (settings.TRAIN_HOST_JOBS_DIR or "").strip():
        on_log(
            "[executor] nested docker without TRAIN_HOST_JOBS_DIR; fallback local"
        )
        return run_local_trainer(
            task_id, on_log=on_log, on_progress=on_progress, should_stop=should_stop
        )

    host_dir = host_job_dir(task_id)
    job_dir(task_id)
    last_progress: dict[str, Any] | None = None
    container = None
    cname = f"train-task-{task_id}"

    try:
        client = docker.from_env()
    except DockerException as exc:
        on_log(f"[executor] docker unavailable: {exc}; fallback local")
        return run_local_trainer(
            task_id, on_log=on_log, on_progress=on_progress, should_stop=should_stop
        )

    bind_src = str(host_dir).replace("\\", "/")
    on_log(f"[executor] docker run {settings.TRAIN_IMAGE} bind={bind_src}")

    try:
        try:
            client.images.get(settings.TRAIN_IMAGE)
        except ImageNotFound:
            on_log(f"[executor] image {settings.TRAIN_IMAGE} missing; fallback local")
            return run_local_trainer(
                task_id, on_log=on_log, on_progress=on_progress, should_stop=should_stop
            )

        # 清理同名残留容器，避免 Conflict
        try:
            old = client.containers.get(cname)
            old.remove(force=True)
        except NotFound:
            pass
        except DockerException:
            pass

        container = client.containers.run(
            settings.TRAIN_IMAGE,
            command=["--config", "/workspace/config.json"],
            volumes={bind_src: {"bind": "/workspace", "mode": "rw"}},
            detach=True,
            name=cname,
            remove=False,
        )
        remember_container(task_id, container.id)

        deadline = time.time() + settings.TRAIN_TIMEOUT_SEC
        for raw in container.logs(stream=True, follow=True):
            if time.time() > deadline:
                container.kill()
                return TrainRunResult(False, "failed", last_progress, "train timeout")
            if should_stop() or is_stop_requested(task_id):
                try:
                    container.kill()
                except Exception:
                    pass
                return TrainRunResult(
                    False, "stopped", last_progress, "stopped by user/admin"
                )

            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not line:
                continue
            parsed = _parse_line(line, on_log, on_progress)
            if parsed:
                last_progress = parsed

        result = container.wait(timeout=30)
        status_code = int(result.get("StatusCode", 1))
        output = job_dir(task_id) / "output" / "weights.pt"
        if status_code != 0:
            return TrainRunResult(
                False, "failed", last_progress, f"container exit {status_code}"
            )
        if not output.exists():
            return TrainRunResult(False, "failed", last_progress, "output weights missing")
        return TrainRunResult(True, "completed", last_progress, None, output)
    except DockerException as exc:
        on_log(f"[executor] docker error: {exc}; fallback local")
        return run_local_trainer(
            task_id, on_log=on_log, on_progress=on_progress, should_stop=should_stop
        )
    finally:
        clear_container_ref(task_id)
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass


def run_trainer(
    task_id: int,
    *,
    on_log: LogCallback,
    on_progress: ProgressCallback,
    should_stop: ShouldStop,
) -> TrainRunResult:
    mode = (settings.TRAIN_EXECUTOR or "docker").lower().strip()
    if mode == "local":
        return run_local_trainer(
            task_id, on_log=on_log, on_progress=on_progress, should_stop=should_stop
        )
    return run_docker_trainer(
        task_id, on_log=on_log, on_progress=on_progress, should_stop=should_stop
    )


def cleanup_job_dir(task_id: int) -> None:
    path = Path(settings.TRAIN_JOBS_DIR) / f"task_{task_id}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
