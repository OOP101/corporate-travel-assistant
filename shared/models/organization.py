"""
组织与人员管理数据模型 —— P1 企业化功能

Department (部门) → Employee (员工) → TravelPolicy (差旅政策)
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum
import time
import uuid


class EmployeeLevel(str, Enum):
    """员工职级"""
    INTERN = "intern"               # 实习生
    JUNIOR = "junior"               # 初级员工
    MIDDLE = "middle"               # 中级员工
    SENIOR = "senior"               # 高级员工
    MANAGER = "manager"             # 经理
    DIRECTOR = "director"           # 总监
    VP = "vp"                       # 副总裁
    EXECUTIVE = "executive"         # 高管


class ApprovalStatus(str, Enum):
    """审批状态"""
    PENDING = "pending"             # 待审批
    APPROVED = "approved"           # 已通过
    REJECTED = "rejected"           # 已拒绝
    CANCELLED = "cancelled"         # 已取消


@dataclass
class Department:
    """部门"""
    dept_id: str = field(default_factory=lambda: f"dept_{uuid.uuid4().hex[:8]}")
    name: str = ""
    parent_id: str = ""             # 上级部门 ID
    manager_id: str = ""            # 部门主管员工 ID
    description: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "dept_id": self.dept_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "manager_id": self.manager_id,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Employee:
    """员工"""
    employee_id: str = field(default_factory=lambda: f"emp_{uuid.uuid4().hex[:8]}")
    name: str = ""
    dept_id: str = ""               # 所属部门
    level: str = EmployeeLevel.JUNIOR.value
    title: str = ""                 # 职位名称
    email: str = ""
    phone: str = ""
    manager_id: str = ""            # 直属主管
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "dept_id": self.dept_id,
            "level": self.level,
            "title": self.title,
            "email": self.email,
            "phone": self.phone,
            "manager_id": self.manager_id,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TravelPolicy:
    """差旅政策"""
    policy_id: str = field(default_factory=lambda: f"pol_{uuid.uuid4().hex[:8]}")
    name: str = ""                  # 政策名称
    description: str = ""
    level: str = ""                 # 适用职级 (EmployeeLevel value)
    city_tier: str = "all"          # 适用城市等级 (all/1/2/3)
    
    # 舱位标准
    flight_class: str = "economy"   # economy/business/first
    train_class: str = "second"     # second/first/business
    
    # 酒店标准 (每晚上限，元)
    hotel_limit: float = 0
    
    # 餐饮标准 (每日上限，元)
    meal_limit: float = 0
    
    # 市内交通标准 (每日上限，元)
    transport_limit: float = 0
    
    # 补贴标准 (每日，元)
    daily_subsidy: float = 0
    
    # 其他
    requires_approval: bool = True  # 是否需要审批
    approval_threshold: float = 0   # 超过此金额需审批
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "city_tier": self.city_tier,
            "flight_class": self.flight_class,
            "train_class": self.train_class,
            "hotel_limit": self.hotel_limit,
            "meal_limit": self.meal_limit,
            "transport_limit": self.transport_limit,
            "daily_subsidy": self.daily_subsidy,
            "requires_approval": self.requires_approval,
            "approval_threshold": self.approval_threshold,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ApprovalRequest:
    """审批请求"""
    approval_id: str = field(default_factory=lambda: f"apr_{uuid.uuid4().hex[:12]}")
    trip_id: str = ""               # 关联行程 ID
    employee_id: str = ""           # 申请人 ID
    approver_id: str = ""           # 审批人 ID
    status: str = ApprovalStatus.PENDING.value
    total_amount: float = 0         # 申请金额
    policy_id: str = ""             # 关联政策 ID
    violations: List[dict] = field(default_factory=list)  # 违规项
    remark: str = ""                # 申请备注
    approver_comment: str = ""      # 审批意见
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    approved_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "approval_id": self.approval_id,
            "trip_id": self.trip_id,
            "employee_id": self.employee_id,
            "approver_id": self.approver_id,
            "status": self.status,
            "total_amount": self.total_amount,
            "policy_id": self.policy_id,
            "violations": self.violations,
            "remark": self.remark,
            "approver_comment": self.approver_comment,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approved_at": self.approved_at,
        }


@dataclass
class PolicyDocument:
    """政策文档 (用于 RAG 检索)"""
    doc_id: str = field(default_factory=lambda: f"doc_{uuid.uuid4().hex[:8]}")
    title: str = ""
    content: str = ""               # 文档正文
    category: str = ""              # 分类 (flight/hotel/meal/transport/subsidy/general)
    tags: List[str] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)  # 向量嵌入
    source: str = ""                # 文档来源
    version: str = "1.0"
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        data = {
            "doc_id": self.doc_id,
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "version": self.version,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        # 向量嵌入：生成后必须落盘，否则重启即丢失（RAG 检索依赖）
        if self.embedding:
            data["embedding"] = self.embedding
            data["embedding_dim"] = len(self.embedding)
        return data
