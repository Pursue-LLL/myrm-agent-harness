"""Tests for dev port sniffer utility in code_execution."""

from myrm_agent_harness.toolkits.code_execution.utils.port_sniffer import (
    sniff_ports_from_text,
)


def test_sniff_vite_and_next_dev() -> None:
    log_text = """
    > my-app@0.1.0 dev
    > vite

      VITE v5.4.2  ready in 238 ms

      ➜  Local:   http://localhost:5173/
      ➜  Network: use --host to expose
      ➜  press h + enter to show help
    """
    ports = sniff_ports_from_text(log_text)
    assert len(ports) == 1
    assert ports[0].port == 5173
    assert ports[0].protocol == "http"
    assert ports[0].url == "http://localhost:5173"


def test_sniff_uvicorn_fastapi() -> None:
    log_text = """
    INFO:     Will watch for changes in these directories: ['/app']
    INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
    INFO:     Started reloader process [12345] using StatReload
    """
    ports = sniff_ports_from_text(log_text)
    assert len(ports) == 1
    assert ports[0].port == 8000
    assert ports[0].process_name == "uvicorn"


def test_sniff_flask() -> None:
    log_text = """
     * Serving Flask app 'app.py'
     * Debug mode: on
    WARNING: This is a development server. Do not use it in a production deployment.
     * Running on http://127.0.0.1:5000
    Press CTRL+C to quit
    """
    ports = sniff_ports_from_text(log_text)
    assert len(ports) == 1
    assert ports[0].port == 5000
    assert ports[0].process_name == "flask"


def test_sniff_python_http_server() -> None:
    log_text = "Serving HTTP on 0.0.0.0 port 8080 (http://0.0.0.0:8080/) ..."
    ports = sniff_ports_from_text(log_text)
    assert len(ports) == 1
    assert ports[0].port == 8080
    assert ports[0].process_name == "python-http"


def test_sniff_node_server() -> None:
    log_text = "Express app listening on port 4000\nDatabase connected."
    ports = sniff_ports_from_text(log_text)
    assert len(ports) == 1
    assert ports[0].port == 4000


def test_sniff_deduplication_and_bounds() -> None:
    log_text = """
    Local: http://localhost:3000
    Listening on http://localhost:3000
    Invalid port: http://localhost:999999
    Another service: http://localhost:8888
    """
    ports = sniff_ports_from_text(log_text)
    port_numbers = [p.port for p in ports]
    assert port_numbers == [3000, 8888]
    assert 999999 not in port_numbers


def test_sniff_empty_or_no_match() -> None:
    assert sniff_ports_from_text("") == []
    assert sniff_ports_from_text("   \n\t  ") == []
    assert sniff_ports_from_text("compiling src/index.ts ... done with 0 errors") == []
