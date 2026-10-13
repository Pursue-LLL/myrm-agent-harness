# observability/diagnostics/fleet_telemetry/

## 架构概述

分布式机队节点六态精细化健康遥测与模型上游配额耗尽诊断子包。彻底区分网络断开、网关停止、沙箱崩溃与模型 API 欠费（Provider Quota Issue），打破粗粒度「连接失败」传统报错。上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 子包顶级符号导出与统一接口 | ✅ |
| `models.py` | 模型 | 六态枚举 (`FleetNodeState`)、五阶段探针枚举 (`ProbeStage`) 与结构化诊断报告契约 (`FleetDiagnosisReport`) | ✅ |
| `provider_quota.py` | 核心 | 模型上游异常与配额耗尽分类器 (`classify_provider_error`)，精准识别 402 余额不足、429 速率限制、401 密钥失效与 503 集群过载 | ✅ |
| `evaluator.py` | 引擎 | 五级渐进式排障流水线 (`FleetSixStateDiagnoser`)：物理网络 ➔ 凭据鉴权 ➔ 网关守护 ➔ 沙箱执行器 ➔ 模型提供商配额 | ✅ |

## 六态诊断状态机对照

| 状态枚举 | 含义 | 触发条件 / 根因 | 排障指引 |
|---------|------|----------------|---------|
| `ONLINE` | 全绿就绪 | 5 级探针全部通过 | 就绪，可随时调度执行任务 |
| `OFFLINE` | 物理离线 | TCP Socket 无法建立连接或超时 | 检查目标主机电源、网络及防火墙端口放行 |
| `MISCONFIGURED` | 配置/凭据失效 | 网络通但 Token/SSH 鉴权握手失败 | 核对节点配置的主机密钥与 TLS 证书 |
| `GATEWAY_STOPPED` | 网关守护停止 | 网络通但端口被拒绝或 HTTP 404/502 | 在远端终端执行 `./myrm start` 启动服务 |
| `RUNNER_BROKEN` | 执行器/沙箱损坏 | 网关通但 Docker 沙箱或代码解释器异常 | 重启远程 Docker 守护进程或清理挂起容器 |
| `PROVIDER_UNAVAILABLE` | 上游配额耗尽/限流 | 网关通但模型 API 返回 402/429 欠费停服 | 登录模型服务商控制台充值或配置备用模型 |
