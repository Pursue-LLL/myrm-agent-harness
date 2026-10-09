# test_report_compressor/

## Overview
Structured test report payload compressor normalizing JUnit XML, pytest-json, and Jest JSON into dense failure-first summaries.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports test report compressor types, parsers, renderer, and master facade suite. | — |
| `report_compressor_types.py` | Types | Domain contracts, enums, normalized report model, and configuration definitions. | — |
| `report_format_detector.py` | Core | Fast header and key-based format detection for XML and JSON test reports. | ✅ |
| `report_parsers.py` | Core | Wire format parsers for JUnit XML, pytest JSON, Jest JSON, and stack frame trimmer. | ✅ |
| `report_renderer.py` | Core | Standardized failure-prioritized test execution summary text renderer. | ✅ |
| `test_report_compressor_suite.py` | Core | Master facade coordinating format detection, parsing, and failure-first compression. | ✅ |
