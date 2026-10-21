"""Task Graph Critical Path Pruning and Early Exit Optimization Suite.

Topological DAG compilation, concurrent execution wave slicing, information
sufficiency early exit gates, and high-purity in-flight prompt context pruning.

[INPUT]
- dag_dependency_compiler
- early_exit_evaluator
- parallel_dag_executor
- task_graph_types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Task Graph Critical Path Pruning and Early Exit Optimization Suite.
"""

from .dag_dependency_compiler import DAGDependencyCompiler
from .early_exit_evaluator import EarlyExitEvaluator
from .parallel_dag_executor import ParallelDAGExecutor
from .task_graph_types import (
    DAGCompilationResult,
    DAGExecutionMetrics,
    EarlyExitVerdict,
    ExecutionWave,
    TaskNode,
    TaskStatus,
)

__all__ = [
    "DAGCompilationResult",
    "DAGDependencyCompiler",
    "DAGExecutionMetrics",
    "EarlyExitEvaluator",
    "EarlyExitVerdict",
    "ExecutionWave",
    "ParallelDAGExecutor",
    "TaskNode",
    "TaskStatus",
]
