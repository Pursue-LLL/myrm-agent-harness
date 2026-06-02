from unittest.mock import mock_open, patch

import pytest

from myrm_agent_harness.runtime.maintenance.protocols import SystemLoadLevel
from myrm_agent_harness.runtime.maintenance.sensors import DeviceLoadSensor


class TestDeviceLoadSensor:
    @pytest.fixture
    def sensor(self):
        # Use alpha=0.5 for easier math in tests
        return DeviceLoadSensor(ema_alpha=0.5)

    @patch("myrm_agent_harness.runtime.maintenance.sensors.psutil")
    @patch("os.path.exists")
    def test_fallback_to_psutil(self, mock_exists, mock_psutil, sensor):
        # Mock not in container
        mock_exists.return_value = False
        mock_psutil.cpu_percent.return_value = 50.0
        mock_psutil.virtual_memory.return_value.percent = 60.0

        snapshot = sensor.read()
        assert snapshot.cpu_percent == 50.0
        assert snapshot.memory_percent == 60.0
        assert snapshot.level == SystemLoadLevel.NORMAL

        # Test EMA on second read
        mock_psutil.cpu_percent.return_value = 100.0
        snapshot2 = sensor.read()
        # EMA = 0.5 * 100 + 0.5 * 50 = 75.0
        assert snapshot2.cpu_percent == 75.0

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_cgroup_v2_memory(self, mock_file, mock_exists, sensor):
        def exists_side_effect(path):
            return path in [
                "/sys/fs/cgroup/memory.current",
                "/sys/fs/cgroup/memory.max",
            ]

        mock_exists.side_effect = exists_side_effect

        def open_side_effect(path, *args, **kwargs):
            if path == "/sys/fs/cgroup/memory.current":
                return mock_open(read_data="1048576")()  # 1MB
            elif path == "/sys/fs/cgroup/memory.max":
                return mock_open(read_data="2097152")()  # 2MB
            return mock_open()()

        mock_file.side_effect = open_side_effect

        cgroup_cpu, cgroup_mem = sensor._get_cgroup_metrics()
        assert cgroup_mem == 50.0
        assert cgroup_cpu is None

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_cgroup_v1_memory(self, mock_file, mock_exists, sensor):
        def exists_side_effect(path):
            return path in [
                "/sys/fs/cgroup/memory/memory.usage_in_bytes",
                "/sys/fs/cgroup/memory/memory.limit_in_bytes",
            ]

        mock_exists.side_effect = exists_side_effect

        def open_side_effect(path, *args, **kwargs):
            if path == "/sys/fs/cgroup/memory/memory.usage_in_bytes":
                return mock_open(read_data="1048576")()  # 1MB
            elif path == "/sys/fs/cgroup/memory/memory.limit_in_bytes":
                return mock_open(read_data="4194304")()  # 4MB
            return mock_open()()

        mock_file.side_effect = open_side_effect

        cgroup_cpu, cgroup_mem = sensor._get_cgroup_metrics()
        assert cgroup_mem == 25.0
        assert cgroup_cpu is None

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    @patch("time.monotonic")
    def test_cgroup_v2_cpu(self, mock_time, mock_file, mock_exists, sensor):
        def exists_side_effect(path):
            return path in ["/sys/fs/cgroup/cpu.stat", "/sys/fs/cgroup/cpu.max"]

        mock_exists.side_effect = exists_side_effect

        # First read
        mock_time.return_value = 100.0

        def open_side_effect_1(path, *args, **kwargs):
            if path == "/sys/fs/cgroup/cpu.max":
                return mock_open(read_data="100000 100000")()  # 1 CPU
            elif path == "/sys/fs/cgroup/cpu.stat":
                return mock_open(read_data="usage_usec 1000000\n")()
            return mock_open()()

        mock_file.side_effect = open_side_effect_1

        cgroup_cpu, cgroup_mem = sensor._get_cgroup_metrics()
        assert cgroup_cpu is None  # First read returns None for CPU delta

        # Second read, 1 second later, used 0.5 CPU seconds
        mock_time.return_value = 101.0

        def open_side_effect_2(path, *args, **kwargs):
            if path == "/sys/fs/cgroup/cpu.max":
                return mock_open(read_data="100000 100000")()  # 1 CPU
            elif path == "/sys/fs/cgroup/cpu.stat":
                return mock_open(read_data="usage_usec 1500000\n")()  # +0.5s
            return mock_open()()

        mock_file.side_effect = open_side_effect_2

        cgroup_cpu, _cgroup_mem = sensor._get_cgroup_metrics()
        assert cgroup_cpu == 50.0  # 0.5s used in 1.0s wall time on 1 CPU
