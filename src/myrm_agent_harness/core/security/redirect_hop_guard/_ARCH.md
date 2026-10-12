# redirect_hop_guard/

## Overview

Redirect Private Address Hop Revalidation Suite. Complete suite providing hop-by-hop private network and metadata revalidation for browser navigations and redirect chains.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Redirect Private Address Hop Revalidation Suite — Complete suite providing hop-by-hop private network and metadata revalidation for browser navigations and redirect chains. | ✅ |
| facade.py | Core | Facade for Redirect Private Address Hop Revalidation Suite — Main entry point for redirect private address hop revalidation in harness. Maintains audit record history and coordinates evaluators and interceptors. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| hop_evaluator.py | Core | Hop evaluation engine for redirect and subresource network security — Pure-python hop safety inspector. Determines whether a URL is an internal, cloud metadata (IMDS), loopback, or link-local address and assigns disposition. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| route_interceptor.py | Core | Playwright Route interceptor for hop-by-hop private address revalidation — Integrates with browser networking layer to abort private network hops, reset document tabs to about:blank on illegal redirects, and record audits. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| types.py | Core | Type definitions for Redirect Private Address Hop Revalidation Suite — Core schema definitions for browser redirect hop revalidation. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
