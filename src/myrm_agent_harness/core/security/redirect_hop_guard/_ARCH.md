# redirect_hop_guard/

## Overview

Redirect Private Address Hop Revalidation Suite. Literal-host private network and cloud metadata classification for browser navigations, the browser context filter and web_fetch redirect chains. It only judges a URL; enforcement (route aborts, tab resets, request refusal) lives with each caller.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Redirect Private Address Hop Revalidation Suite — re-exports the hop models, the evaluator and the explicit-origin grants. | ✅ |
| hop_evaluator.py | Core | Hop evaluation engine for redirect and subresource network security — pure-python inspector that classifies the literal host as internal, cloud metadata (IMDS), loopback or link-local and assigns a disposition. Origins in the supplied grants relax the private-network rules; cloud metadata is never relaxed. | ✅ |
| origin_grants.py | Core | Private-network origins a local-mode session was explicitly sent to — pure data (scheme, host, port), consumed by the evaluator. | ✅ |
| types.py | Core | Type definitions for the suite — hop disposition enum and per-hop evaluation result. | ✅ |
