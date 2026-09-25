"""认证模块 —— 用户注册 / 登录 / Token 签发 / 管理员守卫

设计：
- 用户存 JSON（pbkdf2-sha256 口令哈希，旧 sha256+salt 记录仍可验证并自动升级），
  启动时种子管理员账号
- Token 为 HMAC 签名的无状态串（24h 过期）：服务重启不掉线；planner-core 持有
  同一 SESSION_SECRET 即可离线校验，无需回调本服务
- 前端请求带 Authorization: Bearer <token>；管理接口额外校验 admin 角色
- 注册开放（自助注册）：用户名与已有账号及种子员工重名一律拒绝
"""
import hashlib
import logging
import re
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from shared.config import settings
from shared.middleware.session import SignedSession
from shared.store.base_store import BaseJsonStore

logger = logging.getLogger("journey-hub.auth")

TOKEN_TTL_SECONDS = 24 * 3600

# 保留用户名：这些既是种子账号，也与组织侧的 employee_id 同值，
# 放开注册会让新用户直接继承到别人的员工档案 / 行程 / 审批，必须挡住。
RESERVED_USERNAMES = {"admin", "web-user", "default"}

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

PASSWORD_MIN_LENGTH = 8

_PBKDF2_ROUNDS = 120_000


class UserStore(BaseJsonStore):
    """用户存储（username 即主键）"""
    _id_field = "username"
    _id_prefix = "user_"

    @staticmethod
    def _legacy_hash(password: str, salt: str) -> str:
        """旧版单轮 sha256 —— 仅用于验证历史记录，不再用于新写入。"""
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    @staticmethod
    def hash_password(password: str, salt: str) -> str:
        """pbkdf2-sha256（stdlib，无第三方依赖）。

        单轮 sha256 对弱口令的暴力破解成本过低，这里改为带大量迭代的 KDF；
        用标准库实现以免为一个哈希引入 passlib/bcrypt 依赖。
        """
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
        ).hex()

    def create_user(self, username: str, password: str, role: str = "user") -> str:
        salt = secrets.token_hex(8)
        return self.save({
            "username": username,
            "salt": salt,
            "password_hash": self.hash_password(password, salt),
            "algo": "pbkdf2-sha256",
            "role": role,
        })

    def verify(self, username: str, password: str) -> Optional[dict]:
        user = self.get(username)
        if not user:
            return None
        salt = user.get("salt", "")
        expected = user.get("password_hash", "")

        if user.get("algo") == "pbkdf2-sha256":
            # compare_digest：定长比较，避免哈希比对上的时序侧信道
            matched = secrets.compare_digest(self.hash_password(password, salt), expected)
        else:
            # 旧记录：验证通过后顺手升级为 pbkdf2，用户无感
            matched = secrets.compare_digest(self._legacy_hash(password, salt), expected)
            if matched:
                user["password_hash"] = self.hash_password(password, salt)
                user["algo"] = "pbkdf2-sha256"
                self.save(user)
        return user if matched else None

    def exists(self, username: str) -> bool:
        return self.get(username) is not None


class AuthService:
    """无状态签名 Token 管理（HMAC-SHA256，跨服务可离线验证）"""

    def __init__(self, ttl: int = TOKEN_TTL_SECONDS, secret: Optional[str] = None):
        self._ttl = ttl
        self._secret = secret

    @property
    def secret(self) -> str:
        return self._secret or settings.session_secret

    def issue(self, username: str, role: str) -> str:
        return SignedSession.encode({"username": username, "role": role}, self.secret, self._ttl)

    def resolve(self, token: str) -> Optional[dict]:
        return SignedSession.decode(token, self.secret)

    def revoke(self, token: str):
        """无状态 token 无法单方面作废（前端登出即清本地副本）。

        需要让全部在途 token 立刻失效时，改 SESSION_SECRET 即可。
        """
        return None


auth_service = AuthService()


def get_current_user(request: Request) -> dict:
    """FastAPI 依赖：校验 Bearer Token，返回 {username, role}"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""
    info = auth_service.resolve(token) if token else None
    if not info:
        raise HTTPException(401, "未登录或登录已过期")
    return info


def require_admin(request: Request) -> dict:
    """FastAPI 依赖：要求管理员角色"""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


def resolve_session_id(request: Request, fallback: str = "default") -> str:
    """会话 / 用户身份：登录态优先（Bearer → username），未登录沿用调用方给的值。

    登录态贯穿的起点：journey 把它当作 session_id 转发给 planner-core，
    planner 侧在无 Bearer（服务间调用只带 X-API-Key）时认这个值。
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if token:
        info = auth_service.resolve(token)
        if info and info.get("username"):
            return info["username"]
    return fallback or "default"


# ---------------------------------------------------------------------------
# 登录 / 注册路由
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="用户名")
    password: str = Field(..., min_length=1, description="密码")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, description="用户名（3-32 位字母数字._-）")
    password: str = Field(..., min_length=1, description="密码（至少 8 位）")


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str


def _validate_username(username: str) -> str:
    """注册用户名校验 —— 返回规范化后的用户名，不合法直接 400。"""
    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        raise HTTPException(
            400, "用户名需为 3-32 位，仅可含字母、数字、下划线、点或连字符"
        )
    if username.lower() in RESERVED_USERNAMES:
        raise HTTPException(400, "该用户名为系统保留，请换一个")
    return username


def _validate_password(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"密码至少 {PASSWORD_MIN_LENGTH} 位")
    return password


auth_router = APIRouter(tags=["认证"])


@auth_router.post("/auth/register", response_model=LoginResponse)
def register(req: RegisterRequest, request: Request):
    """自助注册：创建账号并直接签发 Token（注册即登录）。

    新账号一律为普通用户 —— 不接受客户端指定角色，否则任何人都能自封管理员。
    """
    user_store: UserStore = request.app.state.user_store
    if user_store is None:
        raise HTTPException(503, "服务未就绪")

    username = _validate_username(req.username)
    _validate_password(req.password)

    if user_store.exists(username):
        raise HTTPException(409, "用户名已被占用")

    user_store.create_user(username, req.password, role="user")
    token = auth_service.issue(username, "user")
    logger.info(f"user_register: {username}")
    return LoginResponse(token=token, username=username, role="user")


@auth_router.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request):
    """用户登录，返回 Token 与角色（user_store 由 lifespan 注入 request.app.state）"""
    user_store: UserStore = request.app.state.user_store
    if user_store is None:
        raise HTTPException(503, "服务未就绪")
    user = user_store.verify(req.username.strip(), req.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    token = auth_service.issue(user["username"], user.get("role", "user"))
    logger.info(f"user_login: {user['username']} role={user.get('role')}")
    return LoginResponse(token=token, username=user["username"], role=user.get("role", "user"))


@auth_router.post("/auth/logout")
def logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if token:
        auth_service.revoke(token)
    return {"status": "ok"}
