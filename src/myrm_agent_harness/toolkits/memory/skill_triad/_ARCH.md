# Memory Skill Triad & Scope Physical Isolation Architecture (_ARCH.md)

## 1. 模块定位
本模块提供记忆 SKILL 三件套（API 手册 / CLI 机器信封 / 集成缝合流水线）规范与物理 Scope 强隔离引擎。对标 `mnemosyne 8.0.0` 零依赖本地优先架构，彻底解决传统记忆系统在多租户穿透、锁争用、降级不可见与命令行交互死锁问题。

## 2. 核心职责
- **物理 Scope 强隔离 (`scope_partition.py`)**：基于长度前缀（Length-Prefixed）排序键计算 SHA-256 唯一命名空间哈希，为每个租户/会话组合派生独立物理目录与独立 SQLite 数据库文件，彻底根除跨 Scope 穿透与数据库写锁争用；
- **Provider 可见降级状态机 (`degradation.py`)**：核心零外部依赖；外部嵌入/向量服务故障时透明降级为内置词法模式并在 `describe()` 中显式透出替补原因；支持 `strict_providers` 严格断言模式；
- **CLI 机器信封协议 (`cli_envelope.py`)**：面向智能体 Tool Loop 提供标准化 JSON Envelope 输出；错误强制走 stdout JSON 并携带结构化错误码与非零退出码；在 Agent 模式下自动旁路确认（Auto-Assumed Confirmation），杜绝交互死锁；
- **集成四步缝合检验器 (`pipeline.py`)**：规范化 4 问前置调查、临时目录往返自检（Failing Round-Trip Test First）与 Prompt 读前注入缝 / 答后持久化写接缝校验；
- **统一门面 (`facade.py`)**：对外提供轻量、单例的高性能统一调用入口。

## 3. 依赖规则
- 仅依赖标准库（`hashlib`, `pathlib`, `json`, `dataclasses`, `typing`）与底层轻量工具；
- 严禁任何 `typing.Any`；
- 禁止反向依赖业务层（`myrm-agent-server` 或 Web 层）。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Memory Skill Triad and Physical Scope Isolation exports. | ✅ |
| `cli_envelope.py` | Envelope | CLI machine envelope protocol and JSON serialization. | ✅ |
| `degradation.py` | StateMachine | Provider visible degradation state machine with transparent fallback. | ✅ |
| `facade.py` | Facade | Unified stateless facade and singleton injection for Skill Triad. | ✅ |
| `models.py` | Models | Strongly-typed domain models and contracts for Skill Triad. | ✅ |
| `pipeline.py` | Pipeline | Four-step integration stitching and round-trip verification pipeline. | ✅ |
| `scope_partition.py` | Partition | Physical scope length-prefixed SHA-256 partition engine. | ✅ |
