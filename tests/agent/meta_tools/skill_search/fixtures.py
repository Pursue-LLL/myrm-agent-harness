"""Shared fixtures for skill search tests

Provides comprehensive mock skills covering all categories in the Golden Dataset.
"""

from myrm_agent_harness.backends.skills.types import SkillMetadata


def create_comprehensive_mock_skills() -> list[SkillMetadata]:
    """Create comprehensive mock skills for testing

    Returns 100+ skills covering all categories:
    - Railway/Transportation
    - Messaging/Communication
    - Weather/Climate
    - Database/Storage
    - Payment/Financial
    - Cloud/Infrastructure
    - Monitoring/Observability
    - Authentication/Security
    - Development/Testing
    - And more...
    """
    return [
        # Railway/Transportation
        SkillMetadata(
            name="12306_skill",
            storage_skill_id="12306",
            description="12306 railway ticket booking service for China railways train",
        ),
        SkillMetadata(
            name="railway_ticket_booking",
            storage_skill_id="railway",
            description="Book railway tickets online, check availability and prices for train travel",
        ),
        SkillMetadata(
            name="ticket_query",
            storage_skill_id="ticket_query",
            description="Query ticket availability and schedules for various transportation",
        ),
        SkillMetadata(
            name="flight_booking",
            storage_skill_id="flight",
            description="Book flight tickets and manage airline reservations",
        ),
        SkillMetadata(
            name="hotel_booking", storage_skill_id="hotel", description="Book hotel rooms and accommodations for travel"
        ),
        # Messaging/Communication
        SkillMetadata(
            name="whatsapp_send_message",
            storage_skill_id="whatsapp_send",
            description="Send WhatsApp messages to contacts for communication",
        ),
        SkillMetadata(
            name="whatsapp_receive_message",
            storage_skill_id="whatsapp_receive",
            description="Receive and read WhatsApp messages",
        ),
        SkillMetadata(name="sms_send", storage_skill_id="sms", description="Send SMS text messages for communication"),
        SkillMetadata(name="email_send", storage_skill_id="email", description="Send email messages for communication"),
        SkillMetadata(name="smtp_send", storage_skill_id="smtp", description="Send emails via SMTP protocol"),
        SkillMetadata(
            name="sendgrid_email", storage_skill_id="sendgrid", description="Send emails using SendGrid API service"
        ),
        SkillMetadata(
            name="slack_send_message", storage_skill_id="slack_send", description="Send messages to Slack channels"
        ),
        SkillMetadata(
            name="slack_channel", storage_skill_id="slack_channel", description="Manage Slack channels and workspaces"
        ),
        SkillMetadata(
            name="slack_bot", storage_skill_id="slack_bot", description="Create and manage Slack bots for automation"
        ),
        SkillMetadata(
            name="telegram_bot", storage_skill_id="telegram_bot", description="Create and manage Telegram bots"
        ),
        SkillMetadata(name="chatbot", storage_skill_id="chatbot", description="Build conversational chatbots"),
        SkillMetadata(
            name="push_notification",
            storage_skill_id="push_notification",
            description="Send push notifications to mobile devices",
        ),
        SkillMetadata(
            name="notification",
            storage_skill_id="notification",
            description="Send notifications through various channels",
        ),
        # Weather/Climate
        SkillMetadata(
            name="weather_forecast",
            storage_skill_id="weather",
            description="Get weather forecast and current conditions for climate data",
        ),
        SkillMetadata(
            name="weather_api",
            storage_skill_id="weather_api",
            description="Weather API integration for climate and meteorological data",
        ),
        # Database/Storage
        SkillMetadata(
            name="postgres_query",
            storage_skill_id="postgres_query",
            description="Execute PostgreSQL database queries and manage data",
        ),
        SkillMetadata(
            name="postgres_backup", storage_skill_id="postgres_backup", description="Backup PostgreSQL database data"
        ),
        SkillMetadata(
            name="postgres_admin",
            storage_skill_id="postgres_admin",
            description="PostgreSQL database administration and management",
        ),
        SkillMetadata(name="mysql_query", storage_skill_id="mysql_query", description="Execute MySQL database queries"),
        SkillMetadata(name="mysql_backup", storage_skill_id="mysql_backup", description="Backup MySQL database data"),
        SkillMetadata(
            name="mongodb_query",
            storage_skill_id="mongodb_query",
            description="Execute MongoDB database queries for NoSQL data",
        ),
        SkillMetadata(
            name="database_admin",
            storage_skill_id="database_admin",
            description="Database administration and management for db systems",
        ),
        # Redis/Cache
        SkillMetadata(
            name="redis_cache",
            storage_skill_id="redis_cache",
            description="Redis caching for fast data access and storage",
        ),
        SkillMetadata(name="redis_pubsub", storage_skill_id="redis_pubsub", description="Redis pub/sub messaging"),
        SkillMetadata(
            name="redis_queue", storage_skill_id="redis_queue", description="Redis queue for background job processing"
        ),
        SkillMetadata(name="memcached_cache", storage_skill_id="memcached", description="Memcached caching system"),
        SkillMetadata(name="local_cache", storage_skill_id="local_cache", description="Local in-memory cache for data"),
        # Cloud/AWS
        SkillMetadata(
            name="aws_s3",
            storage_skill_id="aws_s3",
            description="AWS S3 cloud storage service for file upload and data",
        ),
        SkillMetadata(name="aws_ec2", storage_skill_id="aws_ec2", description="AWS EC2 cloud compute instances"),
        SkillMetadata(name="aws_lambda", storage_skill_id="aws_lambda", description="AWS Lambda serverless functions"),
        SkillMetadata(name="s3_upload", storage_skill_id="s3_upload", description="Upload files to S3 cloud storage"),
        SkillMetadata(name="s3_backup", storage_skill_id="s3_backup", description="Backup data to S3 storage"),
        SkillMetadata(
            name="cloud_storage",
            storage_skill_id="cloud_storage",
            description="Cloud storage services for file and data upload",
        ),
        SkillMetadata(
            name="file_storage",
            storage_skill_id="file_storage",
            description="File storage and management system for data store",
        ),
        SkillMetadata(
            name="file_upload", storage_skill_id="file_upload", description="Upload files to storage systems"
        ),
        # Container/Kubernetes
        SkillMetadata(
            name="docker_container",
            storage_skill_id="docker_container",
            description="Docker container management and runtime for pod deployment",
        ),
        SkillMetadata(
            name="docker_image", storage_skill_id="docker_image", description="Build and manage Docker images"
        ),
        SkillMetadata(
            name="docker_compose",
            storage_skill_id="docker_compose",
            description="Docker Compose for multi-container orchestration",
        ),
        SkillMetadata(
            name="docker_deploy",
            storage_skill_id="docker_deploy",
            description="Deploy applications using Docker containers",
        ),
        SkillMetadata(
            name="k8s_deployment",
            storage_skill_id="k8s_deployment",
            description="Kubernetes deployment and application orchestration for pod management",
        ),
        SkillMetadata(
            name="k8s_service",
            storage_skill_id="k8s_service",
            description="Kubernetes service networking and load balancing",
        ),
        SkillMetadata(
            name="k8s_pod", storage_skill_id="k8s_pod", description="Kubernetes pod management and container runtime"
        ),
        SkillMetadata(
            name="k8s_autoscaling",
            storage_skill_id="k8s_autoscaling",
            description="Kubernetes horizontal pod autoscaling for scaling",
        ),
        SkillMetadata(
            name="container_runtime",
            storage_skill_id="container_runtime",
            description="Container runtime environment for pod execution",
        ),
        SkillMetadata(
            name="swarm_orchestration", storage_skill_id="swarm", description="Docker Swarm container orchestration"
        ),
        # Payment/Financial
        SkillMetadata(
            name="stripe_payment",
            storage_skill_id="stripe_payment",
            description="Stripe payment processing and transactions for pay",
        ),
        SkillMetadata(
            name="stripe_subscription",
            storage_skill_id="stripe_subscription",
            description="Stripe subscription management",
        ),
        SkillMetadata(
            name="stripe_invoice",
            storage_skill_id="stripe_invoice",
            description="Stripe invoice generation and billing",
        ),
        SkillMetadata(
            name="paypal_payment",
            storage_skill_id="paypal",
            description="PayPal payment processing for pay transactions",
        ),
        SkillMetadata(
            name="alipay_payment", storage_skill_id="alipay", description="Alipay payment processing for Chinese users"
        ),
        SkillMetadata(name="wechat_pay", storage_skill_id="wechat_pay", description="WeChat Pay payment processing"),
        SkillMetadata(
            name="payment_gateway",
            storage_skill_id="payment_gateway",
            description="Payment gateway integration for transactions and pay processing",
        ),
        # GitHub/Code
        SkillMetadata(
            name="github_api",
            storage_skill_id="github_api",
            description="GitHub API integration for repository management",
        ),
        SkillMetadata(
            name="github_search", storage_skill_id="github_search", description="Search GitHub repositories and code"
        ),
        SkillMetadata(
            name="github_repo", storage_skill_id="github_repo", description="Manage GitHub repositories and code repo"
        ),
        SkillMetadata(
            name="code_search", storage_skill_id="code_search", description="Search code across repositories"
        ),
        SkillMetadata(
            name="grep_search", storage_skill_id="grep_search", description="Search text and code using grep patterns"
        ),
        SkillMetadata(
            name="git_repository",
            storage_skill_id="git_repository",
            description="Git repository management for code repo",
        ),
        SkillMetadata(
            name="code_repo", storage_skill_id="code_repo", description="Code repository management and version control"
        ),
        # Monitoring/Observability
        SkillMetadata(
            name="prometheus_monitor",
            storage_skill_id="prometheus",
            description="Prometheus monitoring and metrics collection for system observability",
        ),
        SkillMetadata(
            name="grafana_dashboard",
            storage_skill_id="grafana",
            description="Grafana dashboard for monitoring and visualization",
        ),
        SkillMetadata(
            name="alerting",
            storage_skill_id="alerting",
            description="System alerting and notification for monitoring and alarm",
        ),
        SkillMetadata(
            name="log_analysis",
            storage_skill_id="log_analysis",
            description="Analyze application logs to find errors and patterns",
        ),
        SkillMetadata(
            name="elasticsearch_logs",
            storage_skill_id="elasticsearch_logs",
            description="Elasticsearch log storage and search for log analysis",
        ),
        SkillMetadata(
            name="kibana_logs", storage_skill_id="kibana_logs", description="Kibana log visualization and analysis"
        ),
        SkillMetadata(name="logging", storage_skill_id="logging", description="Application logging and log management"),
        SkillMetadata(
            name="metrics_collection",
            storage_skill_id="metrics_collection",
            description="Collect system and application metrics for monitoring",
        ),
        SkillMetadata(
            name="tracing",
            storage_skill_id="tracing",
            description="Distributed tracing for system observability and trace analysis",
        ),
        SkillMetadata(
            name="distributed_tracing",
            storage_skill_id="distributed_tracing",
            description="Distributed tracing across microservices for trace",
        ),
        SkillMetadata(
            name="opentelemetry",
            storage_skill_id="opentelemetry",
            description="OpenTelemetry instrumentation for tracing and metrics",
        ),
        SkillMetadata(
            name="error_tracking",
            storage_skill_id="error_tracking",
            description="Track and analyze application errors and exceptions",
        ),
        # Authentication/Security
        SkillMetadata(
            name="oauth_auth",
            storage_skill_id="oauth",
            description="OAuth authentication and authorization for user auth",
        ),
        SkillMetadata(name="jwt_auth", storage_skill_id="jwt", description="JWT token authentication for user auth"),
        SkillMetadata(
            name="session_auth", storage_skill_id="session", description="Session-based authentication for user auth"
        ),
        SkillMetadata(
            name="authentication",
            storage_skill_id="authentication",
            description="User authentication and identity verification for auth",
        ),
        SkillMetadata(name="encryption", storage_skill_id="encryption", description="Data encryption for security"),
        # Task Scheduling
        SkillMetadata(
            name="cron_job",
            storage_skill_id="cron",
            description="Schedule cron jobs for task automation and background job",
        ),
        SkillMetadata(
            name="celery_task",
            storage_skill_id="celery",
            description="Celery distributed task queue for background job processing",
        ),
        SkillMetadata(
            name="task_scheduler", storage_skill_id="task_scheduler", description="Task scheduling and job management"
        ),
        SkillMetadata(
            name="background_job",
            storage_skill_id="background_job",
            description="Background job processing and task execution",
        ),
        SkillMetadata(
            name="workflow_automation",
            storage_skill_id="workflow",
            description="Workflow automation and task orchestration",
        ),
        # API/Integration
        SkillMetadata(
            name="rest_api", storage_skill_id="rest_api", description="RESTful API development and integration"
        ),
        SkillMetadata(
            name="graphql_api", storage_skill_id="graphql", description="GraphQL API development and queries"
        ),
        SkillMetadata(
            name="api_gateway",
            storage_skill_id="api_gateway",
            description="API gateway for service routing and management",
        ),
        SkillMetadata(
            name="api_integration",
            storage_skill_id="api_integration",
            description="Third-party API integration and service connection",
        ),
        SkillMetadata(
            name="webhook_integration",
            storage_skill_id="webhook",
            description="Webhook integration for event-driven communication",
        ),
        SkillMetadata(
            name="third_party_api",
            storage_skill_id="third_party_api",
            description="Third-party API integration and management",
        ),
        # Configuration/Management
        SkillMetadata(
            name="config_management",
            storage_skill_id="config_management",
            description="Configuration management and settings for config",
        ),
        SkillMetadata(
            name="env_vars",
            storage_skill_id="env_vars",
            description="Environment variables configuration and management",
        ),
        SkillMetadata(
            name="secrets_management",
            storage_skill_id="secrets",
            description="Secrets and credentials management for config security",
        ),
        # Testing
        SkillMetadata(name="unit_test", storage_skill_id="unit_test", description="Unit testing for software quality"),
        SkillMetadata(
            name="integration_test",
            storage_skill_id="integration_test",
            description="Integration testing for system components",
        ),
        SkillMetadata(
            name="e2e_test", storage_skill_id="e2e_test", description="End-to-end testing for complete workflows"
        ),
        # Deployment/Infrastructure
        SkillMetadata(
            name="heroku_deploy", storage_skill_id="heroku", description="Deploy applications to Heroku platform"
        ),
        SkillMetadata(
            name="load_balancer",
            storage_skill_id="load_balancer",
            description="Load balancing for scaling and traffic distribution",
        ),
        SkillMetadata(
            name="horizontal_scaling",
            storage_skill_id="horizontal_scaling",
            description="Horizontal scaling for system capacity and scaling",
        ),
        # Message Queue
        SkillMetadata(
            name="rabbitmq_queue",
            storage_skill_id="rabbitmq",
            description="RabbitMQ message queue for async processing",
        ),
        SkillMetadata(
            name="message_queue",
            storage_skill_id="message_queue",
            description="Message queue systems for async communication and msg processing",
        ),
        # Data Analytics
        SkillMetadata(
            name="data_analytics",
            storage_skill_id="data_analytics",
            description="Data analytics and business intelligence for data insights",
        ),
        SkillMetadata(
            name="elasticsearch_search",
            storage_skill_id="elasticsearch_search",
            description="Elasticsearch full-text search and analytics",
        ),
        # Reliability
        SkillMetadata(
            name="health_check",
            storage_skill_id="health_check",
            description="Health check endpoints for system reliability",
        ),
        SkillMetadata(
            name="circuit_breaker",
            storage_skill_id="circuit_breaker",
            description="Circuit breaker pattern for reliability and fault tolerance",
        ),
        SkillMetadata(
            name="retry_mechanism",
            storage_skill_id="retry_mechanism",
            description="Automatic retry mechanism for reliability",
        ),
        # Microservices
        SkillMetadata(
            name="microservice",
            storage_skill_id="microservice",
            description="Microservice architecture and service development",
        ),
        SkillMetadata(
            name="service_mesh",
            storage_skill_id="service_mesh",
            description="Service mesh for microservice networking and communication",
        ),
        # Network
        SkillMetadata(
            name="network_config", storage_skill_id="network_config", description="Network configuration and management"
        ),
        SkillMetadata(
            name="vpc_network", storage_skill_id="vpc_network", description="VPC network setup and configuration"
        ),
        # Data Sync
        SkillMetadata(
            name="data_sync", storage_skill_id="data_sync", description="Data synchronization across systems for sync"
        ),
        SkillMetadata(
            name="file_sync", storage_skill_id="file_sync", description="File synchronization and replication for sync"
        ),
        SkillMetadata(
            name="database_sync",
            storage_skill_id="database_sync",
            description="Database synchronization and replication for sync",
        ),
        # Contact Management
        SkillMetadata(
            name="contact_management",
            storage_skill_id="contact_management",
            description="Manage contacts and address book",
        ),
        # Stats
        SkillMetadata(
            name="stats", storage_skill_id="stats", description="Statistical analysis and metrics for metric collection"
        ),
        # Alarm
        SkillMetadata(name="alarm", storage_skill_id="alarm", description="System alarm and alert notifications"),
        # Data Store
        SkillMetadata(
            name="data_store",
            storage_skill_id="data_store",
            description="Data storage and persistence for store operations",
        ),
    ]
