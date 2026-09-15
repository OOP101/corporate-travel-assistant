"""
AI 出行管家 —— 配置管理 (shared 模块)

统一从环境变量读取配置，全平台复用。
"""
import os
from dataclasses import dataclass, field
from typing import Optional

# 项目根目录（shared/config/settings.py → 上三级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _anchor_data_path(value: str) -> str:
    """相对数据路径锚定到项目根。

    各服务以自己的目录为 cwd 启动，若直接使用相对路径，数据会散落到
    services/<service>/data/ 下形成数据孤岛；统一锚定到 <项目根>/data/。
    """
    if os.path.isabs(value):
        return value
    return os.path.join(_PROJECT_ROOT, value)


@dataclass
class Settings:
    """全局配置"""

    # --- LLM ---
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai_compatible"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "deepseek-chat"))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.3")))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "4096")))
    # 未显式指定 model_id 时使用的默认模型（须已注册路由，否则回退 llm_provider）
    llm_default_model: str = field(default_factory=lambda: os.getenv("LLM_DEFAULT_MODEL", ""))

    # --- 多模型服务商（2026-09-03 接入，修复下拉框"假选项"） ---
    # 腾讯 TokenHub 统一网关：托管 混元(hy-mt2-pro) / DeepSeek(deepseek-v4-flash) / 智谱(glm-5-turbo)
    tencent_maas_api_key: str = field(default_factory=lambda: os.getenv("TENCENT_MAAS_API_KEY", ""))
    tencent_maas_base_url: str = field(default_factory=lambda: os.getenv("TENCENT_MAAS_BASE_URL", ""))
    # 月之暗面 Kimi（探针实测账户 suspended，暂未接入路由）
    kimi_api_key: str = field(default_factory=lambda: os.getenv("KIMI_API_KEY", ""))
    kimi_base_url: str = field(default_factory=lambda: os.getenv("KIMI_BASE_URL", ""))
    # 阿里云百炼 / 通义千问（探针实测 key 无效 401，暂未接入路由）
    alibaba_api_key: str = field(default_factory=lambda: os.getenv("ALIBABA_API_KEY", ""))
    alibaba_base_url: str = field(default_factory=lambda: os.getenv("ALIBABA_BASE_URL", ""))

    # --- Embedding（可插拔：local 本地 bge / api OpenAI 兼容 / auto 自动选择 / none 关闭）---
    embedding_provider: str = field(default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "auto"))
    embedding_base_url: str = field(default_factory=lambda: os.getenv("EMBEDDING_BASE_URL", ""))
    embedding_api_key: str = field(default_factory=lambda: os.getenv("EMBEDDING_API_KEY", ""))
    # local 模式：BAAI/bge-large-zh-v1.5(1024维) / bge-base-zh(768) / bge-small-zh(512)
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5"))
    # api 模式专用模型名（留空则用 embedding_model），如 kinfra-text-embedding-0.6b
    embedding_api_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_API_MODEL", ""))
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "0")))  # 0 = 自动推断

    # --- 行智 · Journey Hub (8001) ---
    journey_host: str = field(default_factory=lambda: os.getenv("JOURNEY_HOST", "0.0.0.0"))
    journey_port: int = field(default_factory=lambda: int(os.getenv("JOURNEY_PORT", "8001")))

    # --- 服务间调用 ---
    planner_service_url: str = field(default_factory=lambda: os.getenv("PLANNER_SERVICE_URL", "http://127.0.0.1:8002"))
    sense_service_url: str = field(default_factory=lambda: os.getenv("SENSE_SERVICE_URL", "http://127.0.0.1:8003"))

    # --- 策程 · Planner Core (8002) ---
    planner_host: str = field(default_factory=lambda: os.getenv("PLANNER_HOST", "0.0.0.0"))
    planner_port: int = field(default_factory=lambda: int(os.getenv("PLANNER_PORT", "8002")))

    # --- 感知 · Sense Engine (8003) ---
    sense_host: str = field(default_factory=lambda: os.getenv("SENSE_HOST", "0.0.0.0"))
    sense_port: int = field(default_factory=lambda: int(os.getenv("SENSE_PORT", "8003")))

    # --- 数据存储 ---
    chroma_persist_dir: str = field(default_factory=lambda: _anchor_data_path(os.getenv("CHROMA_PERSIST_DIR", "./data/chromadb")))
    trip_data_dir: str = field(default_factory=lambda: _anchor_data_path(os.getenv("TRIP_DATA_DIR", "./data/trips")))
    profile_data_dir: str = field(default_factory=lambda: _anchor_data_path(os.getenv("PROFILE_DATA_DIR", "./data/profiles")))
    template_data_dir: str = field(default_factory=lambda: _anchor_data_path(os.getenv("TEMPLATE_DATA_DIR", "./data/templates")))

    # --- 外部数据源 ---
    # 地图：腾讯位置服务（需 key + SecretKey 做 SN 签名；高德已切换至腾讯）
    tencent_map_key: str = field(default_factory=lambda: os.getenv("TENCENT_MAP_KEY", ""))
    tencent_map_sk: str = field(default_factory=lambda: os.getenv("TENCENT_MAP_SK", ""))
    weather_api_key: str = field(default_factory=lambda: os.getenv("WEATHER_API_KEY", ""))
    weather_base_url: str = field(default_factory=lambda: os.getenv("WEATHER_BASE_URL", "https://devapi.qweather.com"))
    flight_api_key: str = field(default_factory=lambda: os.getenv("FLIGHT_API_KEY", ""))
    attraction_api_key: str = field(default_factory=lambda: os.getenv("ATTRACTION_API_KEY", ""))
    attraction_base_url: str = field(default_factory=lambda: os.getenv("ATTRACTION_BASE_URL", "https://attractions.example.com"))

    # --- 中间件 ---
    # （已移除未使用的 REDIS_URL 配置）

    # --- 鉴权 ---
    dev_api_key: str = field(default_factory=lambda: os.getenv("DEV_API_KEY", "ak_dev_local"))
    # 会话签名密钥：journey-hub 签发登录 token，planner-core 用同一密钥离线校验。
    # 未显式设置时回退 dev_api_key（本地/单体开箱可用）；生产必须显式设置
    # SESSION_SECRET，否则任何知道默认 key 的人都能伪造登录态。
    session_secret: str = field(
        default_factory=lambda: os.getenv("SESSION_SECRET", "") or os.getenv("DEV_API_KEY", "ak_dev_local")
    )

    # --- 日志 ---
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_json: bool = field(default_factory=lambda: os.getenv("LOG_JSON", "false").lower() == "true")

    def llm_config(self) -> dict:
        """返回 LLM 注册参数"""
        return {
            "api_key": self.llm_api_key,
            "base_url": self.llm_base_url,
            "model": self.llm_model,
            "temperature": self.llm_temperature,
            "max_tokens": self.llm_max_tokens,
        }


settings = Settings()
