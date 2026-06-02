# reranker/

## Overview
Reranker Service Toolkit.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Reranker Service Toolkit. | — |
| base.py | Core | Reranker contract layer. Declares the abstract interface and result type that every | ✅ |
| cloud_reranker.py | Core | Cloud reranker backend. Translates the abstract RerankerService interface into real | ✅ |
| factory.py | Core | Reranker factory. Centralises reranker-service instantiation and ensures process-wide | ✅ |
