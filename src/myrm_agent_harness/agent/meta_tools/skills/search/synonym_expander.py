"""Synonym Expander

Expands queries with synonyms and related terms for improved recall.
Supports both English technical terms and Chinese semantic mappings.
Loads mappings from external YAML configuration.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import ClassVar

from .config_loader import ConfigLoader

logger = logging.getLogger(__name__)


class SynonymExpander:
    """Synonym expansion for technical terms and concepts"""

    # Technical term synonyms (English)
    SYNONYMS_EN: ClassVar[dict[str, list[str]]] = {
        "db": ["database", "db"],
        "database": ["database", "db"],
        "postgres": ["postgresql", "postgres"],
        "postgresql": ["postgresql", "postgres"],
        "js": ["javascript", "js"],
        "javascript": ["javascript", "js"],
        "ts": ["typescript", "ts"],
        "typescript": ["typescript", "ts"],
        "py": ["python", "py"],
        "python": ["python", "py"],
        "k8s": ["kubernetes", "k8s"],
        "kubernetes": ["kubernetes", "k8s"],
        "docker": ["docker", "container"],
        "container": ["docker", "container"],
        "api": ["api", "rest", "endpoint"],
        "rest": ["api", "rest", "endpoint"],
        "endpoint": ["api", "rest", "endpoint"],
        "auth": ["authentication", "auth", "login"],
        "authentication": ["authentication", "auth", "login"],
        "login": ["authentication", "auth", "login"],
        "cache": ["cache", "caching", "redis"],
        "redis": ["cache", "redis"],
        "queue": ["queue", "message", "mq"],
        "message": ["queue", "message", "mq"],
        "mq": ["queue", "message", "mq"],
        "ml": ["machine learning", "ml", "ai"],
        "ai": ["machine learning", "ml", "ai", "artificial intelligence"],
        "llm": ["llm", "language model", "gpt"],
        "gpt": ["llm", "gpt", "openai"],
        # Conceptual mappings
        "booking": ["booking", "reservation", "ticket", "订票", "预订"],
        "reservation": ["booking", "reservation", "ticket"],
        "notification": ["notification", "email", "sms", "message", "alert", "通知"],
        "alert": ["notification", "alert", "email", "message"],
        "persistence": ["persistence", "database", "storage", "save", "存储"],
        "storage": ["storage", "database", "save", "persistence"],
        "monitoring": ["monitoring", "monitor", "metrics", "观察", "监控"],
        "metrics": ["monitoring", "metrics", "monitor"],
        "testing": ["testing", "test", "unit", "integration", "测试"],
        "deployment": ["deployment", "deploy", "release", "部署"],
        "logging": ["logging", "log", "logs", "日志"],
    }

    # Chinese synonyms (comprehensive mapping for robust multilingual search)
    SYNONYMS_ZH: ClassVar[dict[str, list[str]]] = {
        # Database & Storage
        "数据库": ["数据库", "db", "database", "postgresql", "mysql", "mongo"],
        "数据库查询": ["数据库", "查询", "query", "db", "database"],
        "存储": ["存储", "storage", "database", "save", "persistence"],
        "持久化": ["持久化", "存储", "database", "persistence", "storage"],
        "备份": ["备份", "backup", "数据", "导出", "export"],
        "备份数据": ["备份", "数据", "backup", "database", "export"],
        # Cache & Queue
        "缓存": ["缓存", "cache", "redis", "内存"],
        "缓存数据": ["缓存", "cache", "redis", "数据", "memory"],
        "队列": ["队列", "消息队列", "queue", "mq", "消息"],
        "消息队列": ["队列", "消息队列", "queue", "mq", "message"],
        # Auth & User
        "认证": ["认证", "登录", "auth", "authentication", "鉴权"],
        "用户认证": ["认证", "用户", "auth", "authentication", "登录"],
        "登录": ["认证", "登录", "auth", "login", "signin"],
        "鉴权": ["鉴权", "认证", "auth", "authorization"],
        "用户": ["用户", "user", "账号", "account"],
        "账号": ["账号", "用户", "account", "user"],
        # Search & Query
        "搜索": ["搜索", "查询", "search", "find"],
        "搜索代码": ["搜索", "代码", "search", "code", "github"],
        "查询": ["搜索", "查询", "search", "query", "find"],
        "检索": ["检索", "搜索", "查询", "search", "retrieval"],
        # Booking & Ticket
        "火车票": ["火车票", "12306", "铁路", "train", "ticket", "railway"],
        "查票": ["查票", "查询", "火车票", "12306", "ticket", "railway"],
        "购票": ["购票", "买票", "订票", "火车票", "booking", "ticket", "railway"],
        "买票": ["买票", "购票", "订票", "火车票", "booking", "ticket"],
        "订票": ["订票", "购票", "预订", "booking", "reservation", "ticket"],
        "预订": ["预订", "订票", "预约", "booking", "reservation"],
        "预约": ["预约", "预订", "booking", "reservation", "appointment"],
        # ML & AI
        "机器学习": ["机器学习", "ml", "ai", "人工智能", "模型"],
        "人工智能": ["人工智能", "ai", "机器学习", "ml"],
        "模型": ["模型", "model", "ml", "machine learning"],
        "训练": ["训练", "training", "model", "机器学习"],
        # Browser & Web
        "浏览器": ["浏览器", "browser", "chrome", "web"],
        "网页": ["网页", "web", "browser", "html"],
        "爬虫": ["爬虫", "crawler", "spider", "scraping"],
        # Email & Notification
        "邮件": ["邮件", "email", "mail", "smtp"],
        "发送邮件": ["邮件", "发送", "email", "send", "smtp"],
        "通知": ["通知", "notification", "alert", "消息", "提醒"],
        "提醒": ["提醒", "通知", "alert", "notification", "reminder"],
        # Message & Communication
        "消息": ["消息", "message", "发送", "send", "通知"],
        "发送消息": ["消息", "发送", "message", "send", "whatsapp", "sms"],
        "短信": ["短信", "sms", "message", "消息"],
        "聊天": ["聊天", "chat", "message", "消息"],
        # Weather & Forecast
        "天气": ["天气", "weather", "气象"],
        "天气预报": ["天气", "预报", "weather", "forecast"],
        "预报": ["预报", "forecast", "天气", "weather"],
        "气象": ["气象", "天气", "weather", "forecast"],
        # Translation & Language
        "翻译": ["翻译", "translate", "translation", "语言"],
        "语言": ["语言", "language", "翻译", "translate"],
        # Payment
        "支付": ["支付", "payment", "pay", "stripe", "alipay", "付款"],
        "付款": ["付款", "支付", "payment", "pay"],
        "收款": ["收款", "支付", "payment", "收费"],
        # Deployment & DevOps
        "部署": ["部署", "deploy", "deployment", "k8s", "docker", "发布"],
        "部署应用": ["部署", "应用", "deploy", "deployment", "k8s"],
        "发布": ["发布", "部署", "deploy", "release", "deployment"],
        "上线": ["上线", "发布", "部署", "deploy", "release"],
        "容器": ["容器", "docker", "container", "k8s"],
        # Monitoring & Logging
        "监控": ["监控", "monitor", "monitoring", "prometheus", "观察"],
        "监控系统": ["监控", "系统", "monitor", "prometheus", "grafana"],
        "观察": ["观察", "监控", "monitor", "observe", "observability"],
        "日志": ["日志", "log", "logging", "elasticsearch", "记录"],
        "日志分析": ["日志", "分析", "log", "analysis", "elasticsearch"],
        "记录": ["记录", "log", "logging", "日志"],
        # File & Upload
        "上传": ["上传", "upload", "file", "s3", "文件"],
        "文件上传": ["文件", "上传", "file", "upload", "s3"],
        "下载": ["下载", "download", "file", "文件"],
        "文件": ["文件", "file", "upload", "download"],
        # API & Network
        "接口": ["接口", "api", "interface", "endpoint"],
        "网络": ["网络", "network", "http", "api"],
        "请求": ["请求", "request", "http", "api"],
        # Testing & Debug
        "测试": ["测试", "test", "testing", "unit", "integration"],
        "调试": ["调试", "debug", "测试", "test"],
        "错误": ["错误", "error", "异常", "exception"],
        "异常": ["异常", "exception", "错误", "error"],
        # Config & Settings
        "配置": ["配置", "config", "configuration", "settings"],
        "设置": ["设置", "config", "configuration", "settings"],
        # Security
        "安全": ["安全", "security", "安全性", "加密"],
        "加密": ["加密", "encryption", "安全", "security"],
        "权限": ["权限", "permission", "authorization", "鉴权"],
        # Task & Job
        "任务": ["任务", "task", "job", "工作"],
        "工作": ["工作", "job", "task", "任务"],
        "定时": ["定时", "schedule", "cron", "timer"],
        "调度": ["调度", "schedule", "scheduling", "定时"],
    }

    def __init__(self, config_path: str | Path | None = None) -> None:
        """Initialize synonym expander

        [INPUT]

        [POS]
        Loads synonyms from external YAML config if available.
        Falls back to hardcoded SYNONYMS_EN/ZH if config not found.
        """
        # Try loading from external config first
        config = ConfigLoader.load_synonyms(config_path)

        if config["english"] or config["chinese"]:
            # Use external config
            self._all_synonyms = {**config["english"], **config["chinese"]}
            logger.info(
                " Loaded %d synonym mappings from external config (%d EN + %d ZH)",
                len(self._all_synonyms),
                len(config["english"]),
                len(config["chinese"]),
            )
        else:
            # Fallback to hardcoded
            self._all_synonyms = {**self.SYNONYMS_EN, **self.SYNONYMS_ZH}
            logger.warning(" Using hardcoded synonym mappings (%d total)", len(self._all_synonyms))

    def expand(self, query: str) -> list[str]:
        """Expand query with synonyms

        [INPUT]

        [OUTPUT]
        List of query variations including synonyms

        [POS]
        Generates multiple query variations by substituting synonyms.
        Limits to top 5 variations to avoid explosion.
        """
        if not query.strip():
            return [query]

        expanded_queries = [query]

        # Expand with synonyms
        for term, synonyms in self._all_synonyms.items():
            if term in query:
                for synonym in synonyms:
                    if synonym != term:
                        expanded_query = re.sub(re.escape(term), synonym, query, flags=re.IGNORECASE)
                        if expanded_query not in expanded_queries:
                            expanded_queries.append(expanded_query)

        # Limit to top 5 variations to avoid explosion
        return expanded_queries[:5]
