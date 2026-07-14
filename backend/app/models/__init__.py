"""SQLAlchemy ORM Models — 导入所有模型以便 Alembic 自动生成迁移"""

from app.models.base import Base
from app.models.user import User
from app.models.data_resource import DataResource
from app.models.data_version import DataVersion
from app.models.data_source import DataSource
from app.models.label_schema import LabelSchema
from app.models.annotation_task import AnnotationTask
from app.models.annotation import Annotation
from app.models.dataset import Dataset
from app.models.dataset_item import DatasetItem
from app.models.model_registry import Model
from app.models.model_version import ModelVersion
from app.models.train_task import TrainTask
from app.models.infer_task import InferTask
from app.models.eval_task import EvalTask
from app.models.eval_result import EvalResult
from app.models.audit_log import AuditLog
from app.models.alignment_group import AlignmentGroup, AlignmentGroupItem

__all__ = [
    "Base",
    "User",
    "DataResource",
    "DataVersion",
    "DataSource",
    "LabelSchema",
    "AnnotationTask",
    "Annotation",
    "Dataset",
    "DatasetItem",
    "Model",
    "ModelVersion",
    "TrainTask",
    "InferTask",
    "EvalTask",
    "EvalResult",
    "AuditLog",
    "AlignmentGroup",
    "AlignmentGroupItem",
]
