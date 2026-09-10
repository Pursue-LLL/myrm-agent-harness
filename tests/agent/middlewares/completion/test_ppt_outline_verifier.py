"""Unit tests for PPT reporting plan outline quality gate verifier."""

import pytest
from myrm_agent_harness.agent.middlewares.completion.ppt_outline_verifier import (
    check_ppt_outline_quality,
    is_ppt_reporting_task,
)


def test_is_ppt_reporting_task():
    assert is_ppt_reporting_task("帮我规划一份 Q3 财务汇报 PPT 大纲", "")
    assert is_ppt_reporting_task("Create a 5-slide pitch deck presentation", "")
    assert not is_ppt_reporting_task("写一段 Python 快速排序代码", "def quicksort(arr):")


def test_ppt_outline_compliant():
    user_text = "生成一份年度技术规划汇报 PPT 大纲"
    assistant_text = """
### Slide 1: 2026 技术战略愿景
- 核心观点：全面转向云原生与自主可控架构
- 视觉呈现：架构演化路线图（架构图）
- 要点：
  1. 统一基础设施
  2. 提升研发吞吐

### Slide 2: 核心指标与业务收益
- 核心观点：单位算力成本下降 35%，P99 延迟缩短至 100ms
- 视觉呈现：KPI 指标对比柱状图与数据看板
- 要点：
  1. 成本优化
  2. 吞吐提升

### Slide 3: 组织协同与实施节奏
- 核心观点：分三期渐进式迁移，确保业务零中断
- 视觉呈现：实施甘特图与里程碑表格
- 要点：
  1. Q1 灰度验证
  2. Q2 全量上线
"""
    result = check_ppt_outline_quality(user_text, assistant_text)
    assert result is None, f"Expected compliant outline to pass, got: {result}"


def test_ppt_outline_verbose_headline_blocked():
    user_text = "请给出 PPT 大纲"
    assistant_text = """
### Slide 1: 这是一个非常冗长且没有经过精炼的幻灯片标题完全违反了六字标题和反文字墙的基本设计原则
- 核心观点：系统升级
- 视觉呈现：柱状图

### Slide 2: 另外一页关于具体执行细节的详细补充说明汇报
- 核心观点：推进平稳
- 视觉呈现：表格
"""
    result = check_ppt_outline_quality(user_text, assistant_text)
    assert result is not None
    assert "headline is too verbose" in result


def test_ppt_outline_missing_visual_anchor_blocked():
    user_text = "生成 PPT 汇报方案"
    assistant_text = """
### Slide 1: 战略背景
- 核心观点：市场竞争加剧
- 阐述行业趋势与现状

### Slide 2: 应对方案
- 核心观点：加大研发投入
- 阐述未来规划与投入
"""
    result = check_ppt_outline_quality(user_text, assistant_text)
    assert result is not None
    assert "lacks concrete visual or data anchors" in result


def test_ppt_outline_missing_thesis_blocked():
    user_text = "汇报 PPT 大纲"
    assistant_text = """
### Slide 1: 市场分析
- 行业概况
- 竞品动态
- 视觉呈现：图表

### Slide 2: 产品规划
- 路线图
- 架构图
- 视觉呈现：表格

### Slide 3: 团队分工
- 人员列表
- 视觉呈现：卡片
"""
    result = check_ppt_outline_quality(user_text, assistant_text)
    assert result is not None
    assert "explicit thesis statements" in result
