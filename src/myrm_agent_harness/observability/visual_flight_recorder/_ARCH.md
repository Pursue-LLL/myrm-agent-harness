# visual_flight_recorder/

## Overview
智能体视觉故障黑匣子录制器与卡顿状态短循环切片回放套件 (Visual Failure Flight Recorder & Stuck-State Short-Loop Playback Suite)。
在后台常驻维护滚动 15 秒（5fps，最多 75 帧）极低开销的环形内存缓冲区，当智能体遭遇工具超时、元素定位失败、死循环或页面卡顿静止时，毫秒级将崩溃前的帧序列缝合成带时间轴的故障切片，与 TraceID 强绑定并记录结构化根因类型。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | 导出 VisualFrame, FlightRecorderConfig, VisualFailureSlice, VisualFlightRecorder 等核心类型与单例工厂 | ✅ |
| `models.py` | Models | 视觉帧、环形录制配置与故障切片归档 Pydantic 强类型模型 | ✅ |
| `recorder.py` | Engine | 线程安全环形缓冲区管理、卡顿停滞检测、截断切片生成与切片历史查询引擎 | ✅ |
