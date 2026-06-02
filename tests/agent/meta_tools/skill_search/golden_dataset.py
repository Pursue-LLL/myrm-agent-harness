"""Golden Dataset for Skill Search Quality Evaluation

This module provides a curated dataset of queries and expected results
for evaluating and benchmarking skill search quality.

Usage:
    from golden_dataset import GOLDEN_DATASET, evaluate_search_quality

    results = evaluate_search_quality(search_engine, GOLDEN_DATASET)
    print(f"MRR: {results['mrr']:.3f}")
    print(f"Top-1 Accuracy: {results['top1_accuracy']:.3f}")
    print(f"Top-3 Accuracy: {results['top3_accuracy']:.3f}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class GoldenQuery:
    """A single golden query with expected results

    Attributes:
        query: The search query
        expected_skills: List of expected skill names in order of relevance
        description: Human-readable description of what this query tests
        category: Query category (e.g., "exact_match", "semantic", "multilingual")
    """

    query: str
    expected_skills: list[str]
    description: str
    category: str


GOLDEN_DATASET: list[GoldenQuery] = [
    # ==================== Exact Match Queries (10) ====================
    GoldenQuery(
        query="12306",
        expected_skills=["12306_skill", "railway_ticket_booking"],
        description="Exact skill name match - railway",
        category="exact_match",
    ),
    GoldenQuery(
        query="whatsapp",
        expected_skills=["whatsapp_send_message", "whatsapp_receive_message"],
        description="Exact provider name match - messaging",
        category="exact_match",
    ),
    GoldenQuery(
        query="github",
        expected_skills=["github_api", "github_search", "github_repo"],
        description="Exact provider name match - code hosting",
        category="exact_match",
    ),
    GoldenQuery(
        query="slack",
        expected_skills=["slack_send_message", "slack_channel", "slack_bot"],
        description="Exact provider name match - team communication",
        category="exact_match",
    ),
    GoldenQuery(
        query="docker",
        expected_skills=["docker_container", "docker_image", "docker_compose"],
        description="Exact provider name match - containerization",
        category="exact_match",
    ),
    GoldenQuery(
        query="kubernetes",
        expected_skills=["k8s_deployment", "k8s_service", "k8s_pod"],
        description="Exact provider name match - orchestration",
        category="exact_match",
    ),
    GoldenQuery(
        query="postgres",
        expected_skills=["postgres_query", "postgres_backup", "postgres_admin"],
        description="Exact provider name match - database",
        category="exact_match",
    ),
    GoldenQuery(
        query="redis",
        expected_skills=["redis_cache", "redis_pubsub", "redis_queue"],
        description="Exact provider name match - cache",
        category="exact_match",
    ),
    GoldenQuery(
        query="aws",
        expected_skills=["aws_s3", "aws_ec2", "aws_lambda"],
        description="Exact provider name match - cloud",
        category="exact_match",
    ),
    GoldenQuery(
        query="stripe",
        expected_skills=["stripe_payment", "stripe_subscription", "stripe_invoice"],
        description="Exact provider name match - payment",
        category="exact_match",
    ),
    # ==================== Semantic Queries - Chinese (15) ====================
    GoldenQuery(
        query="火车票",
        expected_skills=["railway_ticket_booking", "12306_skill"],
        description="Chinese semantic - railway tickets",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="查票",
        expected_skills=["railway_ticket_booking", "ticket_query"],
        description="Chinese semantic - ticket lookup",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="天气预报",
        expected_skills=["weather_forecast", "weather_api"],
        description="Chinese semantic - weather",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="发送消息",
        expected_skills=["whatsapp_send_message", "sms_send", "email_send"],
        description="Chinese semantic - send message",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="数据库查询",
        expected_skills=["postgres_query", "mysql_query", "mongodb_query"],
        description="Chinese semantic - database query",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="支付",
        expected_skills=["stripe_payment", "alipay_payment", "wechat_pay"],
        description="Chinese semantic - payment",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="部署应用",
        expected_skills=["k8s_deployment", "docker_deploy", "heroku_deploy"],
        description="Chinese semantic - deploy application",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="备份数据",
        expected_skills=["postgres_backup", "mysql_backup", "s3_backup"],
        description="Chinese semantic - backup data",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="搜索代码",
        expected_skills=["github_search", "code_search", "grep_search"],
        description="Chinese semantic - search code",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="监控系统",
        expected_skills=["prometheus_monitor", "grafana_dashboard", "alerting"],
        description="Chinese semantic - system monitoring",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="日志分析",
        expected_skills=["log_analysis", "elasticsearch_logs", "kibana_logs"],
        description="Chinese semantic - log analysis",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="文件上传",
        expected_skills=["s3_upload", "file_upload", "cloud_storage"],
        description="Chinese semantic - file upload",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="用户认证",
        expected_skills=["oauth_auth", "jwt_auth", "session_auth"],
        description="Chinese semantic - user authentication",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="发送邮件",
        expected_skills=["email_send", "smtp_send", "sendgrid_email"],
        description="Chinese semantic - send email",
        category="semantic_chinese",
    ),
    GoldenQuery(
        query="缓存数据",
        expected_skills=["redis_cache", "memcached_cache", "local_cache"],
        description="Chinese semantic - cache data",
        category="semantic_chinese",
    ),
    # ==================== Semantic Queries - English (15) ====================
    GoldenQuery(
        query="railway ticket",
        expected_skills=["railway_ticket_booking", "12306_skill"],
        description="English semantic - railway tickets",
        category="semantic_english",
    ),
    GoldenQuery(
        query="weather forecast",
        expected_skills=["weather_forecast", "weather_api"],
        description="English semantic - weather",
        category="semantic_english",
    ),
    GoldenQuery(
        query="send message",
        expected_skills=["whatsapp_send_message", "sms_send", "email_send"],
        description="English semantic - messaging",
        category="semantic_english",
    ),
    GoldenQuery(
        query="database query",
        expected_skills=["postgres_query", "mysql_query", "mongodb_query"],
        description="English semantic - database operations",
        category="semantic_english",
    ),
    GoldenQuery(
        query="payment processing",
        expected_skills=["stripe_payment", "paypal_payment", "payment_gateway"],
        description="English semantic - payment",
        category="semantic_english",
    ),
    GoldenQuery(
        query="deploy application",
        expected_skills=["k8s_deployment", "docker_deploy", "heroku_deploy"],
        description="English semantic - deployment",
        category="semantic_english",
    ),
    GoldenQuery(
        query="backup data",
        expected_skills=["postgres_backup", "mysql_backup", "s3_backup"],
        description="English semantic - data backup",
        category="semantic_english",
    ),
    GoldenQuery(
        query="search code",
        expected_skills=["github_search", "code_search", "grep_search"],
        description="English semantic - code search",
        category="semantic_english",
    ),
    GoldenQuery(
        query="monitor system",
        expected_skills=["prometheus_monitor", "grafana_dashboard", "alerting"],
        description="English semantic - monitoring",
        category="semantic_english",
    ),
    GoldenQuery(
        query="analyze logs",
        expected_skills=["log_analysis", "elasticsearch_logs", "kibana_logs"],
        description="English semantic - log analysis",
        category="semantic_english",
    ),
    GoldenQuery(
        query="upload file",
        expected_skills=["s3_upload", "file_upload", "cloud_storage"],
        description="English semantic - file operations",
        category="semantic_english",
    ),
    GoldenQuery(
        query="user authentication",
        expected_skills=["oauth_auth", "jwt_auth", "session_auth"],
        description="English semantic - authentication",
        category="semantic_english",
    ),
    GoldenQuery(
        query="send email",
        expected_skills=["email_send", "smtp_send", "sendgrid_email"],
        description="English semantic - email",
        category="semantic_english",
    ),
    GoldenQuery(
        query="cache data",
        expected_skills=["redis_cache", "memcached_cache", "local_cache"],
        description="English semantic - caching",
        category="semantic_english",
    ),
    GoldenQuery(
        query="schedule task",
        expected_skills=["cron_job", "celery_task", "task_scheduler"],
        description="English semantic - task scheduling",
        category="semantic_english",
    ),
    # ==================== Multilingual Queries (15) ====================
    GoldenQuery(
        query="火车票/railway ticket",
        expected_skills=["railway_ticket_booking", "12306_skill"],
        description="Bilingual - railway tickets",
        category="multilingual",
    ),
    GoldenQuery(
        query="天气/weather",
        expected_skills=["weather_forecast", "weather_api"],
        description="Bilingual - weather",
        category="multilingual",
    ),
    GoldenQuery(
        query="数据库/database",
        expected_skills=["postgres_query", "mysql_query", "mongodb_query"],
        description="Bilingual - database",
        category="multilingual",
    ),
    GoldenQuery(
        query="支付/payment",
        expected_skills=["stripe_payment", "alipay_payment", "wechat_pay"],
        description="Bilingual - payment",
        category="multilingual",
    ),
    GoldenQuery(
        query="部署/deploy",
        expected_skills=["k8s_deployment", "docker_deploy", "heroku_deploy"],
        description="Bilingual - deployment",
        category="multilingual",
    ),
    GoldenQuery(
        query="备份/backup",
        expected_skills=["postgres_backup", "mysql_backup", "s3_backup"],
        description="Bilingual - backup",
        category="multilingual",
    ),
    GoldenQuery(
        query="搜索/search",
        expected_skills=["github_search", "code_search", "elasticsearch_search"],
        description="Bilingual - search",
        category="multilingual",
    ),
    GoldenQuery(
        query="监控/monitor",
        expected_skills=["prometheus_monitor", "grafana_dashboard", "alerting"],
        description="Bilingual - monitoring",
        category="multilingual",
    ),
    GoldenQuery(
        query="日志/logs",
        expected_skills=["log_analysis", "elasticsearch_logs", "kibana_logs"],
        description="Bilingual - logs",
        category="multilingual",
    ),
    GoldenQuery(
        query="上传/upload",
        expected_skills=["s3_upload", "file_upload", "cloud_storage"],
        description="Bilingual - upload",
        category="multilingual",
    ),
    GoldenQuery(
        query="认证/authentication",
        expected_skills=["oauth_auth", "jwt_auth", "session_auth"],
        description="Bilingual - authentication",
        category="multilingual",
    ),
    GoldenQuery(
        query="邮件/email",
        expected_skills=["email_send", "smtp_send", "sendgrid_email"],
        description="Bilingual - email",
        category="multilingual",
    ),
    GoldenQuery(
        query="缓存/cache",
        expected_skills=["redis_cache", "memcached_cache", "local_cache"],
        description="Bilingual - cache",
        category="multilingual",
    ),
    GoldenQuery(
        query="任务/task",
        expected_skills=["cron_job", "celery_task", "task_scheduler"],
        description="Bilingual - task",
        category="multilingual",
    ),
    GoldenQuery(
        query="容器/container",
        expected_skills=["docker_container", "k8s_pod", "container_runtime"],
        description="Bilingual - container",
        category="multilingual",
    ),
    # ==================== Conceptual Queries (15) ====================
    GoldenQuery(
        query="booking",
        expected_skills=["railway_ticket_booking", "hotel_booking", "flight_booking"],
        description="Conceptual - booking services",
        category="conceptual",
    ),
    GoldenQuery(
        query="communication",
        expected_skills=["whatsapp_send_message", "sms_send", "email_send"],
        description="Conceptual - communication tools",
        category="conceptual",
    ),
    GoldenQuery(
        query="storage",
        expected_skills=["s3_upload", "cloud_storage", "file_storage"],
        description="Conceptual - data storage",
        category="conceptual",
    ),
    GoldenQuery(
        query="notification",
        expected_skills=["email_send", "sms_send", "push_notification"],
        description="Conceptual - notification systems",
        category="conceptual",
    ),
    GoldenQuery(
        query="orchestration",
        expected_skills=["k8s_deployment", "docker_compose", "swarm_orchestration"],
        description="Conceptual - container orchestration",
        category="conceptual",
    ),
    GoldenQuery(
        query="persistence",
        expected_skills=["postgres_query", "redis_cache", "file_storage"],
        description="Conceptual - data persistence",
        category="conceptual",
    ),
    GoldenQuery(
        query="automation",
        expected_skills=["cron_job", "celery_task", "workflow_automation"],
        description="Conceptual - task automation",
        category="conceptual",
    ),
    GoldenQuery(
        query="security",
        expected_skills=["oauth_auth", "jwt_auth", "encryption"],
        description="Conceptual - security features",
        category="conceptual",
    ),
    GoldenQuery(
        query="analytics",
        expected_skills=["log_analysis", "metrics_collection", "data_analytics"],
        description="Conceptual - data analytics",
        category="conceptual",
    ),
    GoldenQuery(
        query="integration",
        expected_skills=["api_integration", "webhook_integration", "third_party_api"],
        description="Conceptual - system integration",
        category="conceptual",
    ),
    GoldenQuery(
        query="scaling",
        expected_skills=["k8s_autoscaling", "load_balancer", "horizontal_scaling"],
        description="Conceptual - system scaling",
        category="conceptual",
    ),
    GoldenQuery(
        query="reliability",
        expected_skills=["health_check", "circuit_breaker", "retry_mechanism"],
        description="Conceptual - system reliability",
        category="conceptual",
    ),
    GoldenQuery(
        query="observability",
        expected_skills=["prometheus_monitor", "log_analysis", "tracing"],
        description="Conceptual - system observability",
        category="conceptual",
    ),
    GoldenQuery(
        query="configuration",
        expected_skills=["config_management", "env_vars", "secrets_management"],
        description="Conceptual - configuration management",
        category="conceptual",
    ),
    GoldenQuery(
        query="testing",
        expected_skills=["unit_test", "integration_test", "e2e_test"],
        description="Conceptual - software testing",
        category="conceptual",
    ),
    # ==================== Synonym Queries (15) ====================
    GoldenQuery(
        query="train",
        expected_skills=["railway_ticket_booking", "12306_skill"],
        description="Synonym - train vs railway",
        category="synonym",
    ),
    GoldenQuery(
        query="climate",
        expected_skills=["weather_forecast", "weather_api"],
        description="Synonym - climate vs weather",
        category="synonym",
    ),
    GoldenQuery(
        query="k8s",
        expected_skills=["k8s_deployment", "k8s_service", "k8s_pod"],
        description="Synonym - k8s vs kubernetes",
        category="synonym",
    ),
    GoldenQuery(
        query="db",
        expected_skills=["postgres_query", "mysql_query", "database_admin"],
        description="Synonym - db vs database",
        category="synonym",
    ),
    GoldenQuery(
        query="msg",
        expected_skills=["whatsapp_send_message", "sms_send", "message_queue"],
        description="Synonym - msg vs message",
        category="synonym",
    ),
    GoldenQuery(
        query="auth",
        expected_skills=["oauth_auth", "jwt_auth", "authentication"],
        description="Synonym - auth vs authentication",
        category="synonym",
    ),
    GoldenQuery(
        query="repo",
        expected_skills=["github_repo", "git_repository", "code_repo"],
        description="Synonym - repo vs repository",
        category="synonym",
    ),
    GoldenQuery(
        query="pod",
        expected_skills=["k8s_pod", "docker_container", "container_runtime"],
        description="Synonym - pod vs container",
        category="synonym",
    ),
    GoldenQuery(
        query="queue",
        expected_skills=["redis_queue", "rabbitmq_queue", "message_queue"],
        description="Synonym - queue vs message queue",
        category="synonym",
    ),
    GoldenQuery(
        query="job",
        expected_skills=["cron_job", "celery_task", "background_job"],
        description="Synonym - job vs task",
        category="synonym",
    ),
    GoldenQuery(
        query="api",
        expected_skills=["rest_api", "graphql_api", "api_gateway"],
        description="Synonym - api vs interface",
        category="synonym",
    ),
    GoldenQuery(
        query="store",
        expected_skills=["s3_upload", "file_storage", "data_store"],
        description="Synonym - store vs storage",
        category="synonym",
    ),
    GoldenQuery(
        query="alert",
        expected_skills=["alerting", "notification", "alarm"],
        description="Synonym - alert vs notification",
        category="synonym",
    ),
    GoldenQuery(
        query="metric",
        expected_skills=["prometheus_monitor", "metrics_collection", "stats"],
        description="Synonym - metric vs statistics",
        category="synonym",
    ),
    GoldenQuery(
        query="trace",
        expected_skills=["tracing", "distributed_tracing", "opentelemetry"],
        description="Synonym - trace vs tracing",
        category="synonym",
    ),
    # ==================== Short Queries (10) ====================
    GoldenQuery(
        query="票",
        expected_skills=["railway_ticket_booking", "ticket_query", "flight_booking"],
        description="Short query - single Chinese character",
        category="short_query",
    ),
    GoldenQuery(
        query="天",
        expected_skills=["weather_forecast", "weather_api"],
        description="Short query - single Chinese character for weather",
        category="short_query",
    ),
    GoldenQuery(
        query="db",
        expected_skills=["postgres_query", "mysql_query", "database_admin"],
        description="Short query - 2 letters",
        category="short_query",
    ),
    GoldenQuery(
        query="k8s",
        expected_skills=["k8s_deployment", "k8s_service", "k8s_pod"],
        description="Short query - abbreviation",
        category="short_query",
    ),
    GoldenQuery(
        query="aws",
        expected_skills=["aws_s3", "aws_ec2", "aws_lambda"],
        description="Short query - cloud provider",
        category="short_query",
    ),
    GoldenQuery(
        query="api",
        expected_skills=["rest_api", "graphql_api", "api_gateway"],
        description="Short query - 3 letters",
        category="short_query",
    ),
    GoldenQuery(
        query="log",
        expected_skills=["log_analysis", "elasticsearch_logs", "logging"],
        description="Short query - 3 letters",
        category="short_query",
    ),
    GoldenQuery(
        query="pay",
        expected_skills=["stripe_payment", "paypal_payment", "payment_gateway"],
        description="Short query - 3 letters",
        category="short_query",
    ),
    GoldenQuery(
        query="msg",
        expected_skills=["whatsapp_send_message", "sms_send", "message_queue"],
        description="Short query - abbreviation",
        category="short_query",
    ),
    GoldenQuery(
        query="bot",
        expected_skills=["slack_bot", "telegram_bot", "chatbot"],
        description="Short query - 3 letters",
        category="short_query",
    ),
    # ==================== Long Queries (10) ====================
    GoldenQuery(
        query="how to book railway tickets online for china railways",
        expected_skills=["railway_ticket_booking", "12306_skill"],
        description="Long query - natural language question",
        category="long_query",
    ),
    GoldenQuery(
        query="I need to send a message to my contacts on whatsapp",
        expected_skills=["whatsapp_send_message", "contact_management"],
        description="Long query - conversational style",
        category="long_query",
    ),
    GoldenQuery(
        query="what is the weather forecast for tomorrow and next week",
        expected_skills=["weather_forecast", "weather_api"],
        description="Long query - detailed weather request",
        category="long_query",
    ),
    GoldenQuery(
        query="deploy my application to kubernetes cluster with autoscaling",
        expected_skills=["k8s_deployment", "k8s_autoscaling"],
        description="Long query - deployment with requirements",
        category="long_query",
    ),
    GoldenQuery(
        query="backup my postgres database and upload to s3 storage",
        expected_skills=["postgres_backup", "s3_upload"],
        description="Long query - multi-step operation",
        category="long_query",
    ),
    GoldenQuery(
        query="search for code in github repositories by keyword",
        expected_skills=["github_search", "code_search"],
        description="Long query - search with context",
        category="long_query",
    ),
    GoldenQuery(
        query="monitor system performance and send alerts when cpu usage is high",
        expected_skills=["prometheus_monitor", "alerting"],
        description="Long query - monitoring with conditions",
        category="long_query",
    ),
    GoldenQuery(
        query="analyze application logs to find errors and exceptions",
        expected_skills=["log_analysis", "error_tracking"],
        description="Long query - log analysis task",
        category="long_query",
    ),
    GoldenQuery(
        query="authenticate users with oauth and manage their sessions",
        expected_skills=["oauth_auth", "session_auth"],
        description="Long query - authentication flow",
        category="long_query",
    ),
    GoldenQuery(
        query="process payment transactions securely using stripe api",
        expected_skills=["stripe_payment", "payment_gateway"],
        description="Long query - payment processing",
        category="long_query",
    ),
    # ==================== Fuzzy/Ambiguous Queries (10) ====================
    GoldenQuery(
        query="ticket",
        expected_skills=["railway_ticket_booking", "ticket_query", "flight_booking"],
        description="Ambiguous - multiple ticket types",
        category="fuzzy",
    ),
    GoldenQuery(
        query="message",
        expected_skills=["whatsapp_send_message", "sms_send", "email_send"],
        description="Ambiguous - multiple messaging channels",
        category="fuzzy",
    ),
    GoldenQuery(
        query="data",
        expected_skills=["postgres_query", "s3_upload", "data_analytics"],
        description="Ambiguous - data operations",
        category="fuzzy",
    ),
    GoldenQuery(
        query="cloud",
        expected_skills=["aws_s3", "aws_ec2", "cloud_storage"],
        description="Ambiguous - cloud services",
        category="fuzzy",
    ),
    GoldenQuery(
        query="container",
        expected_skills=["docker_container", "k8s_pod", "container_runtime"],
        description="Ambiguous - container technologies",
        category="fuzzy",
    ),
    GoldenQuery(
        query="service",
        expected_skills=["k8s_service", "microservice", "service_mesh"],
        description="Ambiguous - service concepts",
        category="fuzzy",
    ),
    GoldenQuery(
        query="network",
        expected_skills=["network_config", "vpc_network", "service_mesh"],
        description="Ambiguous - network operations",
        category="fuzzy",
    ),
    GoldenQuery(
        query="config",
        expected_skills=["config_management", "env_vars", "secrets_management"],
        description="Ambiguous - configuration",
        category="fuzzy",
    ),
    GoldenQuery(
        query="test",
        expected_skills=["unit_test", "integration_test", "e2e_test"],
        description="Ambiguous - testing types",
        category="fuzzy",
    ),
    GoldenQuery(
        query="sync",
        expected_skills=["data_sync", "file_sync", "database_sync"],
        description="Ambiguous - synchronization",
        category="fuzzy",
    ),
    # ==================== Error/Typo Queries (10) ====================
    GoldenQuery(
        query="kubernets",
        expected_skills=["k8s_deployment", "k8s_service"],
        description="Typo - kubernetes misspelled",
        category="error_query",
    ),
    GoldenQuery(
        query="postgress",
        expected_skills=["postgres_query", "postgres_backup"],
        description="Typo - postgres misspelled",
        category="error_query",
    ),
    GoldenQuery(
        query="wether",
        expected_skills=["weather_forecast", "weather_api"],
        description="Typo - weather misspelled",
        category="error_query",
    ),
    GoldenQuery(
        query="mesage",
        expected_skills=["whatsapp_send_message", "sms_send"],
        description="Typo - message misspelled",
        category="error_query",
    ),
    GoldenQuery(
        query="autentication",
        expected_skills=["oauth_auth", "jwt_auth"],
        description="Typo - authentication misspelled",
        category="error_query",
    ),
    GoldenQuery(
        query="火车piao",
        expected_skills=["railway_ticket_booking", "12306_skill"],
        description="Mixed language with pinyin",
        category="error_query",
    ),
    GoldenQuery(
        query="tianqi",
        expected_skills=["weather_forecast", "weather_api"],
        description="Pinyin query for weather",
        category="error_query",
    ),
    GoldenQuery(
        query="k8",
        expected_skills=["k8s_deployment", "k8s_service"],
        description="Incomplete abbreviation",
        category="error_query",
    ),
    GoldenQuery(
        query="postgre",
        expected_skills=["postgres_query", "postgres_backup"],
        description="Incomplete word",
        category="error_query",
    ),
    GoldenQuery(
        query="dock",
        expected_skills=["docker_container", "docker_image"],
        description="Incomplete word - docker",
        category="error_query",
    ),
    # ==================== Multilingual Format Queries (20) ====================
    # These queries simulate LLM following the prompt to provide multilingual format:
    # "concept/translation/synonym concept2/translation2/synonym2"
    # Note: Multi-word terms use underscores or hyphens to avoid parsing ambiguity
    GoldenQuery(
        query="火车票/railway/train/booking/ticket",
        expected_skills=["railway_ticket_booking", "12306_skill"],
        description="Multilingual format - railway tickets (Chinese/English)",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="天气/weather/forecast 预报/prediction",
        expected_skills=["weather_forecast", "weather_api"],
        description="Multilingual format - weather forecast",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="数据库/database/db 查询/query/search",
        expected_skills=["postgres_query", "mysql_query", "mongodb_query"],
        description="Multilingual format - database query",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="支付/payment/pay 处理/processing",
        expected_skills=["stripe_payment", "alipay_payment", "wechat_pay"],
        description="Multilingual format - payment processing",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="发送/send 消息/message/notification",
        expected_skills=["whatsapp_send_message", "sms_send", "email_send"],
        description="Multilingual format - send message",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="部署/deploy/deployment 应用/application/app",
        expected_skills=["k8s_deployment", "docker_deploy", "heroku_deploy"],
        description="Multilingual format - deploy application",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="备份/backup 数据/data",
        expected_skills=["postgres_backup", "mysql_backup", "s3_backup"],
        description="Multilingual format - backup data",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="监控/monitor/monitoring 系统/system",
        expected_skills=["prometheus_monitor", "grafana_dashboard", "alerting"],
        description="Multilingual format - system monitoring",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="搜索/search 代码/code",
        expected_skills=["github_search", "code_search", "grep_search"],
        description="Multilingual format - search code",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="日志/log/logs 分析/analysis/analyze",
        expected_skills=["log_analysis", "elasticsearch_logs", "kibana_logs"],
        description="Multilingual format - log analysis",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="文件/file 上传/upload",
        expected_skills=["s3_upload", "file_upload", "cloud_storage"],
        description="Multilingual format - file upload",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="用户/user 认证/authentication/auth",
        expected_skills=["oauth_auth", "jwt_auth", "session_auth"],
        description="Multilingual format - user authentication",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="缓存/cache/caching 数据/data",
        expected_skills=["redis_cache", "memcached_cache", "local_cache"],
        description="Multilingual format - cache data",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="容器/container/docker 镜像/image",
        expected_skills=["docker_container", "docker_image", "docker_compose"],
        description="Multilingual format - docker container",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="API/接口/endpoint 测试/test/testing",
        expected_skills=["api_test", "postman_test", "integration_test"],
        description="Multilingual format - API testing",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="队列/queue 消息/message",
        expected_skills=["redis_queue", "rabbitmq_queue", "kafka_queue"],
        description="Multilingual format - message queue",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="加密/encryption/encrypt 数据/data",
        expected_skills=["encryption_service", "data_encryption", "crypto"],
        description="Multilingual format - data encryption",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="配置/config/configuration 管理/management",
        expected_skills=["config_manager", "env_config", "settings"],
        description="Multilingual format - configuration management",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="通知/notification/alert 推送/push",
        expected_skills=["push_notification", "email_notification", "sms_notification"],
        description="Multilingual format - push notification",
        category="multilingual_format",
    ),
    GoldenQuery(
        query="12306/railway/火车 订票/booking/ticket",
        expected_skills=["12306_skill", "railway_ticket_booking"],
        description="Multilingual format - specific service (12306)",
        category="multilingual_format",
    ),
]


def evaluate_search_quality(
    search_func: callable, dataset: list[GoldenQuery] | None = None, k_values: list[int] | None = None
) -> dict[str, float]:
    """Evaluate search quality using golden dataset

    [INPUT]
    - search_func: Function(query: str) -> list[SkillMetadata | str]
    - dataset: List of GoldenQuery objects (defaults to GOLDEN_DATASET)
    - k_values: K values for Top-K metrics (defaults to [1, 3, 5, 10])

    [OUTPUT]
    Dictionary with metrics:
    - mrr: Mean Reciprocal Rank (average 1/rank of first relevant result)
    - map: Mean Average Precision (average precision across all relevant results)
    - top{k}_accuracy: Percentage of queries with relevant result in top-K
    - precision@{k}: Average proportion of relevant results in top-K
    - recall@{k}: Average proportion of all relevant results retrieved in top-K
    - f1@{k}: Harmonic mean of Precision@K and Recall@K
    - ndcg@{k}: Normalized Discounted Cumulative Gain (ranking quality)

    [POS]
    Core evaluation function for measuring search quality across multiple dimensions.
    Includes both ranking metrics (MRR, MAP, NDCG) and retrieval metrics (Top-K, P/R/F1).
    """
    if dataset is None:
        dataset = GOLDEN_DATASET
    if k_values is None:
        k_values = [1, 3, 5, 10]

    total_queries = len(dataset)
    reciprocal_ranks: list[float] = []
    average_precisions: list[float] = []

    # Initialize metrics for each K
    metrics_at_k = {k: {"hits": 0, "precision": [], "recall": [], "ndcg": []} for k in k_values}

    for golden_query in dataset:
        results = search_func(golden_query.query)
        result_names = [r.name if hasattr(r, "name") else r for r in results]
        expected_set = set(golden_query.expected_skills)
        num_expected = len(expected_set)

        # MRR: Find first relevant result
        first_relevant_rank = None
        for rank, result_name in enumerate(result_names, start=1):
            if result_name in expected_set:
                if first_relevant_rank is None:
                    first_relevant_rank = rank
                    reciprocal_ranks.append(1.0 / rank)
                break
        if first_relevant_rank is None:
            reciprocal_ranks.append(0.0)

        # MAP: Average precision across all relevant results
        relevant_ranks = [rank for rank, result_name in enumerate(result_names, start=1) if result_name in expected_set]
        if relevant_ranks:
            precisions_at_relevant = [
                sum(1 for r in result_names[:rank] if r in expected_set) / rank for rank in relevant_ranks
            ]
            average_precisions.append(sum(precisions_at_relevant) / num_expected)
        else:
            average_precisions.append(0.0)

        # Metrics at each K
        for k in k_values:
            top_k_results = result_names[:k]
            relevant_in_top_k = [r for r in top_k_results if r in expected_set]
            num_relevant_in_top_k = len(relevant_in_top_k)

            # Top-K Accuracy (hit rate)
            if num_relevant_in_top_k > 0:
                metrics_at_k[k]["hits"] += 1

            # Precision@K
            precision = num_relevant_in_top_k / k if k > 0 else 0.0
            metrics_at_k[k]["precision"].append(precision)

            # Recall@K
            recall = num_relevant_in_top_k / num_expected if num_expected > 0 else 0.0
            metrics_at_k[k]["recall"].append(recall)

            # NDCG@K
            dcg = sum(
                (1.0 if result_names[i] in expected_set else 0.0) / math.log2(i + 2)
                for i in range(min(k, len(result_names)))
            )
            ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(min(k, num_expected)))
            ndcg = dcg / ideal_dcg if ideal_dcg > 0 else 0.0
            metrics_at_k[k]["ndcg"].append(ndcg)

    # Aggregate results
    results = {
        "mrr": sum(reciprocal_ranks) / total_queries if total_queries > 0 else 0.0,
        "map": sum(average_precisions) / total_queries if total_queries > 0 else 0.0,
        "total_queries": total_queries,
    }

    # Add metrics for each K
    for k in k_values:
        results[f"top{k}_accuracy"] = metrics_at_k[k]["hits"] / total_queries if total_queries > 0 else 0.0
        results[f"precision@{k}"] = sum(metrics_at_k[k]["precision"]) / total_queries if total_queries > 0 else 0.0
        results[f"recall@{k}"] = sum(metrics_at_k[k]["recall"]) / total_queries if total_queries > 0 else 0.0
        results[f"ndcg@{k}"] = sum(metrics_at_k[k]["ndcg"]) / total_queries if total_queries > 0 else 0.0

        # F1@K: Harmonic mean of Precision and Recall
        precision = results[f"precision@{k}"]
        recall = results[f"recall@{k}"]
        results[f"f1@{k}"] = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Backward compatibility: keep old metric names
    results["top1_accuracy"] = results.get("top1_accuracy", 0.0)
    results["top3_accuracy"] = results.get("top3_accuracy", 0.0)
    results["top5_accuracy"] = results.get("top5_accuracy", 0.0)

    return results


def print_evaluation_report(results: dict[str, float], *, detailed: bool = False) -> None:
    """Print formatted evaluation report

    [INPUT]
    - results: Metrics dictionary from evaluate_search_quality
    - detailed: If True, show Precision/Recall/NDCG breakdown

    [OUTPUT]
    Formatted console output with metrics organized by category
    """
    print("\n" + "=" * 80)
    print("SKILL SEARCH QUALITY EVALUATION REPORT")
    print("=" * 80)
    print(f"Total Queries: {results['total_queries']}")
    print("\nRANKING METRICS:")
    print(f"  MRR (Mean Reciprocal Rank): {results['mrr']:.3f}")
    print(f"  MAP (Mean Average Precision): {results.get('map', 0.0):.3f}")

    print("\nTOP-K ACCURACY:")
    for k in [1, 3, 5, 10]:
        if f"top{k}_accuracy" in results:
            print(f"  Top-{k}: {results[f'top{k}_accuracy']:.1%}")

    if detailed:
        print("\nPRECISION@K:")
        for k in [1, 3, 5, 10]:
            if f"precision@{k}" in results:
                print(f"  P@{k}: {results[f'precision@{k}']:.3f}")

        print("\nRECALL@K:")
        for k in [1, 3, 5, 10]:
            if f"recall@{k}" in results:
                print(f"  R@{k}: {results[f'recall@{k}']:.3f}")

        print("\nF1@K:")
        for k in [1, 3, 5, 10]:
            if f"f1@{k}" in results:
                print(f"  F1@{k}: {results[f'f1@{k}']:.3f}")

        print("\nNDCG@K (Ranking Quality):")
        for k in [1, 3, 5, 10]:
            if f"ndcg@{k}" in results:
                print(f"  NDCG@{k}: {results[f'ndcg@{k}']:.3f}")

    print("=" * 80 + "\n")
