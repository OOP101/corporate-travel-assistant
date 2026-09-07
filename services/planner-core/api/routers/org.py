"""组织管理 Router —— 部门 / 员工 / 职级 (P1 企业化)"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api import deps

router = APIRouter()


class CreateDepartmentRequest(BaseModel):
    name: str = Field(..., description="部门名称")
    parent_id: str = Field(default="", description="上级部门 ID")
    manager_id: str = Field(default="", description="部门主管员工 ID")
    description: str = Field(default="", description="部门描述")


class UpdateDepartmentRequest(BaseModel):
    name: Optional[str] = Field(default=None)
    parent_id: Optional[str] = Field(default=None)
    manager_id: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)


class CreateEmployeeRequest(BaseModel):
    name: str = Field(..., description="员工姓名")
    dept_id: str = Field(..., description="所属部门 ID")
    level: str = Field(default="junior", description="职级")
    title: str = Field(default="", description="职位")
    email: str = Field(default="", description="邮箱")
    phone: str = Field(default="", description="电话")
    manager_id: str = Field(default="", description="直属主管 ID")


class UpdateEmployeeRequest(BaseModel):
    name: Optional[str] = Field(default=None)
    dept_id: Optional[str] = Field(default=None)
    level: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    manager_id: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


@router.get("/departments", tags=["组织管理"])
async def list_departments(parent_id: str = Query(default="", description="上级部门 ID")):
    """部门列表"""
    if parent_id:
        departments = deps.dept_store.list_by_parent(parent_id)
    else:
        departments = deps.dept_store.list_all()
    return {"departments": departments, "count": len(departments)}


@router.post("/departments", tags=["组织管理"])
async def create_department(req: CreateDepartmentRequest):
    """创建部门"""
    dept = {
        "name": req.name,
        "parent_id": req.parent_id,
        "manager_id": req.manager_id,
        "description": req.description,
    }
    dept_id = deps.dept_store.save(dept)
    return {"status": "ok", "dept_id": dept_id, "department": deps.dept_store.get(dept_id)}


@router.get("/departments/{dept_id}", tags=["组织管理"])
async def get_department(dept_id: str):
    """部门详情"""
    dept = deps.dept_store.get(dept_id)
    if not dept:
        raise HTTPException(404, f"部门不存在: {dept_id}")
    # 获取部门下员工
    employees = deps.employee_store.list_by_dept(dept_id)
    dept["employees"] = employees
    dept["employee_count"] = len(employees)
    return dept


@router.put("/departments/{dept_id}", tags=["组织管理"])
async def update_department(dept_id: str, req: UpdateDepartmentRequest):
    """更新部门"""
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")
    updated = deps.dept_store.update(dept_id, partial)
    if not updated:
        raise HTTPException(404, f"部门不存在: {dept_id}")
    return updated


@router.delete("/departments/{dept_id}", tags=["组织管理"])
async def delete_department(dept_id: str):
    """删除部门"""
    deleted = deps.dept_store.delete(dept_id)
    if not deleted:
        raise HTTPException(404, f"部门不存在: {dept_id}")
    return {"status": "ok", "dept_id": dept_id}


@router.get("/employees", tags=["组织管理"])
async def list_employees(
    dept_id: str = Query(default="", description="部门 ID"),
    level: str = Query(default="", description="职级"),
    keyword: str = Query(default="", description="搜索关键词"),
):
    """员工列表"""
    if keyword:
        employees = deps.employee_store.search(keyword)
    elif dept_id:
        employees = deps.employee_store.list_by_dept(dept_id)
    elif level:
        employees = deps.employee_store.list_by_level(level)
    else:
        employees = deps.employee_store.list_all()
    return {"employees": employees, "count": len(employees)}


@router.post("/employees", tags=["组织管理"])
async def create_employee(req: CreateEmployeeRequest):
    """创建员工"""
    # 验证部门存在
    if req.dept_id and not deps.dept_store.get(req.dept_id):
        raise HTTPException(400, f"部门不存在: {req.dept_id}")

    emp = {
        "name": req.name,
        "dept_id": req.dept_id,
        "level": req.level,
        "title": req.title,
        "email": req.email,
        "phone": req.phone,
        "manager_id": req.manager_id,
    }
    emp_id = deps.employee_store.save(emp)
    return {"status": "ok", "employee_id": emp_id, "employee": deps.employee_store.get(emp_id)}


@router.get("/employees/{employee_id}", tags=["组织管理"])
async def get_employee(employee_id: str):
    """员工详情"""
    emp = deps.employee_store.get(employee_id)
    if not emp:
        raise HTTPException(404, f"员工不存在: {employee_id}")
    # 获取部门信息
    if emp.get("dept_id"):
        dept = deps.dept_store.get(emp["dept_id"])
        emp["department"] = dept
    # 获取主管信息
    manager = deps.employee_store.get_manager(employee_id)
    emp["manager"] = manager
    return emp


@router.put("/employees/{employee_id}", tags=["组织管理"])
async def update_employee(employee_id: str, req: UpdateEmployeeRequest):
    """更新员工"""
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")
    updated = deps.employee_store.update(employee_id, partial)
    if not updated:
        raise HTTPException(404, f"员工不存在: {employee_id}")
    return updated


@router.delete("/employees/{employee_id}", tags=["组织管理"])
async def delete_employee(employee_id: str):
    """删除员工"""
    deleted = deps.employee_store.delete(employee_id)
    if not deleted:
        raise HTTPException(404, f"员工不存在: {employee_id}")
    return {"status": "ok", "employee_id": employee_id}
