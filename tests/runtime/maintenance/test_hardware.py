from unittest.mock import MagicMock, patch

from myrm_agent_harness.runtime.maintenance.hardware import (
    HardwareProfile,
    _detect_linux_hardware,
    _detect_macos_hardware,
    _detect_windows_hardware,
    _lookup_bandwidth,
    detect_hardware_profile,
)


def test_hardware_profile_dataclass():
    profile = HardwareProfile(
        os_type="macos",
        cpu_arch="arm64",
        total_ram_gb=16.0,
        free_disk_gb=100.0,
        has_gpu=True,
        gpu_name="Apple M1",
        gpu_vram_gb=16.0,
        gpu_vendor="apple",
        is_unified_memory=True,
    )
    assert profile.os_type == "macos"
    assert profile.cpu_arch == "arm64"
    assert profile.total_ram_gb == 16.0
    assert profile.free_disk_gb == 100.0
    assert profile.has_gpu is True
    assert profile.gpu_name == "Apple M1"
    assert profile.gpu_vram_gb == 16.0
    assert profile.gpu_vendor == "apple"
    assert profile.is_unified_memory is True
    assert profile.memory_bandwidth_gbps is None  # default


# --- _lookup_bandwidth tests ---

def test_lookup_bandwidth_apple_m2_pro():
    result = _lookup_bandwidth("Apple M2 Pro")
    assert result == 200.0


def test_lookup_bandwidth_apple_m2():
    # "M2 Pro" key is longer and wins over "M2" when "M2 Pro" is in name
    result = _lookup_bandwidth("Apple M2")
    assert result == 100.0


def test_lookup_bandwidth_nvidia_rtx4090():
    result = _lookup_bandwidth("NVIDIA GeForce RTX 4090")
    assert result == 1008.0


def test_lookup_bandwidth_nvidia_rtx4070ti():
    # "RTX 4070 Ti" should match before "RTX 4070"
    result = _lookup_bandwidth("NVIDIA GeForce RTX 4070 Ti")
    assert result == 504.0


def test_lookup_bandwidth_amd_rx7900xtx():
    result = _lookup_bandwidth("AMD Radeon RX 7900 XTX")
    assert result == 960.0


def test_lookup_bandwidth_unknown_gpu():
    result = _lookup_bandwidth("Some Unknown GPU XYZ")
    assert result is None


def test_lookup_bandwidth_none_input():
    assert _lookup_bandwidth(None) is None


def test_lookup_bandwidth_empty_string():
    assert _lookup_bandwidth("") is None


def test_lookup_bandwidth_case_insensitive():
    # Keys are matched case-insensitively
    result = _lookup_bandwidth("apple m4 pro")
    assert result == 273.0


# --- memory_bandwidth_gbps integration tests ---

@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil")
@patch("myrm_agent_harness.runtime.maintenance.hardware.platform")
@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_hardware_profile_populates_bandwidth(mock_run, mock_platform, mock_psutil):
    """detect_hardware_profile() should set memory_bandwidth_gbps via _lookup_bandwidth."""
    mock_platform.system.return_value = "Darwin"
    mock_platform.machine.return_value = "arm64"

    mock_virtual_memory = MagicMock()
    mock_virtual_memory.total = 36 * (1024**3)
    mock_psutil.virtual_memory.return_value = mock_virtual_memory

    mock_disk_usage = MagicMock()
    mock_disk_usage.free = 50 * (1024**3)
    mock_psutil.disk_usage.return_value = mock_disk_usage

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "Apple M2 Max"
    mock_run.return_value = mock_res

    profile = detect_hardware_profile()

    assert profile is not None
    assert profile.gpu_name == "Apple M2 Max"
    assert profile.memory_bandwidth_gbps == 400.0


@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil")
@patch("myrm_agent_harness.runtime.maintenance.hardware.platform")
@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_hardware_profile_unknown_gpu_bandwidth_is_none(mock_run, mock_platform, mock_psutil):
    """Unknown GPU should leave memory_bandwidth_gbps as None."""
    mock_platform.system.return_value = "Darwin"
    mock_platform.machine.return_value = "arm64"

    mock_virtual_memory = MagicMock()
    mock_virtual_memory.total = 16 * (1024**3)
    mock_psutil.virtual_memory.return_value = mock_virtual_memory

    mock_disk_usage = MagicMock()
    mock_disk_usage.free = 100 * (1024**3)
    mock_psutil.disk_usage.return_value = mock_disk_usage

    mock_res = MagicMock()
    mock_res.returncode = 1  # sysctl fails
    mock_res.stdout = ""
    mock_run.return_value = mock_res

    profile = detect_hardware_profile()

    assert profile is not None
    assert profile.gpu_name == "Apple Silicon"
    assert profile.memory_bandwidth_gbps is None

@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil")
@patch("myrm_agent_harness.runtime.maintenance.hardware.platform")
@patch("myrm_agent_harness.runtime.maintenance.hardware._detect_macos_hardware")
def test_detect_hardware_profile_macos(mock_detect_macos, mock_platform, mock_psutil):
    mock_platform.system.return_value = "Darwin"
    mock_platform.machine.return_value = "arm64"

    mock_virtual_memory = MagicMock()
    mock_virtual_memory.total = 16 * (1024**3)
    mock_psutil.virtual_memory.return_value = mock_virtual_memory

    mock_disk_usage = MagicMock()
    mock_disk_usage.free = 100 * (1024**3)
    mock_psutil.disk_usage.return_value = mock_disk_usage

    profile = detect_hardware_profile()

    assert profile is not None
    assert profile.os_type == "macos"
    assert profile.cpu_arch == "arm64"
    assert profile.total_ram_gb == 16.0
    assert profile.free_disk_gb == 100.0
    mock_detect_macos.assert_called_once_with(profile)

@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil")
@patch("myrm_agent_harness.runtime.maintenance.hardware.platform")
@patch("myrm_agent_harness.runtime.maintenance.hardware._detect_linux_hardware")
def test_detect_hardware_profile_linux(mock_detect_linux, mock_platform, mock_psutil):
    mock_platform.system.return_value = "Linux"
    mock_platform.machine.return_value = "x86_64"

    mock_virtual_memory = MagicMock()
    mock_virtual_memory.total = 32 * (1024**3)
    mock_psutil.virtual_memory.return_value = mock_virtual_memory

    mock_disk_usage = MagicMock()
    mock_disk_usage.free = 200 * (1024**3)
    mock_psutil.disk_usage.return_value = mock_disk_usage

    profile = detect_hardware_profile()

    assert profile is not None
    assert profile.os_type == "linux"
    assert profile.cpu_arch == "x86_64"
    assert profile.total_ram_gb == 32.0
    assert profile.free_disk_gb == 200.0
    mock_detect_linux.assert_called_once_with(profile)

@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil")
@patch("myrm_agent_harness.runtime.maintenance.hardware.platform")
@patch("myrm_agent_harness.runtime.maintenance.hardware._detect_windows_hardware")
def test_detect_hardware_profile_windows(mock_detect_windows, mock_platform, mock_psutil):
    mock_platform.system.return_value = "Windows"
    mock_platform.machine.return_value = "AMD64"

    mock_virtual_memory = MagicMock()
    mock_virtual_memory.total = 64 * (1024**3)
    mock_psutil.virtual_memory.return_value = mock_virtual_memory

    mock_disk_usage = MagicMock()
    mock_disk_usage.free = 50 * (1024**3)
    mock_psutil.disk_usage.return_value = mock_disk_usage

    profile = detect_hardware_profile()

    assert profile is not None
    assert profile.os_type == "windows"
    assert profile.cpu_arch == "AMD64"
    assert profile.total_ram_gb == 64.0
    assert profile.free_disk_gb == 50.0
    mock_detect_windows.assert_called_once_with(profile)

@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil", None)
def test_detect_hardware_profile_no_psutil():
    profile = detect_hardware_profile()
    assert profile is None

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_macos_hardware_arm64(mock_run):
    profile = HardwareProfile(os_type="macos", cpu_arch="arm64", total_ram_gb=16.0)

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "Apple M1 Pro"
    mock_run.return_value = mock_res

    _detect_macos_hardware(profile)

    assert profile.gpu_vendor == "apple"
    assert profile.is_unified_memory is True
    assert profile.has_gpu is True
    assert profile.gpu_vram_gb == 16.0
    assert profile.gpu_name == "Apple M1 Pro"

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_linux_hardware_nvidia(mock_run):
    profile = HardwareProfile(os_type="linux", cpu_arch="x86_64", total_ram_gb=32.0)

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "NVIDIA GeForce RTX 4090, 24564 MiB"
    mock_run.return_value = mock_res

    _detect_linux_hardware(profile)

    assert profile.is_unified_memory is False
    assert profile.gpu_vendor == "nvidia"
    assert profile.has_gpu is True
    assert profile.gpu_name == "NVIDIA GeForce RTX 4090"
    assert profile.gpu_vram_gb == 24564 / 1024.0

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_macos_hardware_intel(mock_run):
    profile = HardwareProfile(os_type="macos", cpu_arch="x86_64", total_ram_gb=16.0)

    def side_effect(*args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "Chipset Model: AMD Radeon Pro 5500M\nVRAM (Total): 8 GB"
        return mock_res

    mock_run.side_effect = side_effect

    _detect_macos_hardware(profile)

    assert profile.is_unified_memory is False
    assert profile.has_gpu is True
    assert profile.gpu_vendor == "amd"
    assert profile.gpu_name == "AMD Radeon Pro 5500M"
    assert profile.gpu_vram_gb == 8.0

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_macos_hardware_intel_mb(mock_run):
    profile = HardwareProfile(os_type="macos", cpu_arch="x86_64", total_ram_gb=16.0)

    def side_effect(*args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "Chipset Model: Intel Iris Plus Graphics\nVRAM (Dynamic, Max): 1536 MB"
        return mock_res

    mock_run.side_effect = side_effect

    _detect_macos_hardware(profile)

    assert profile.is_unified_memory is False
    assert profile.has_gpu is True
    assert profile.gpu_vendor == "intel"
    assert profile.gpu_name == "Intel Iris Plus Graphics"
    assert profile.gpu_vram_gb == 1536 / 1024.0

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_linux_hardware_amd(mock_run):
    profile = HardwareProfile(os_type="linux", cpu_arch="x86_64", total_ram_gb=32.0)

    def side_effect(*args, **kwargs):
        mock_res = MagicMock()
        if "nvidia-smi" in args[0]:
            mock_res.returncode = 1
        elif "lshw" in args[0]:
            mock_res.returncode = 0
            mock_res.stdout = "Advanced Micro Devices, Inc. [AMD/ATI] Radeon RX 7900 XTX"
        return mock_res

    mock_run.side_effect = side_effect

    _detect_linux_hardware(profile)

    assert profile.is_unified_memory is False
    assert profile.gpu_vendor == "amd"
    assert profile.has_gpu is True
    assert profile.gpu_name == "AMD Radeon GPU"

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_linux_hardware_intel(mock_run):
    profile = HardwareProfile(os_type="linux", cpu_arch="x86_64", total_ram_gb=32.0)

    def side_effect(*args, **kwargs):
        mock_res = MagicMock()
        if "nvidia-smi" in args[0]:
            mock_res.returncode = 1
        elif "lshw" in args[0]:
            mock_res.returncode = 0
            mock_res.stdout = "Intel Corporation UHD Graphics"
        return mock_res

    mock_run.side_effect = side_effect

    _detect_linux_hardware(profile)

    assert profile.is_unified_memory is False
    assert profile.gpu_vendor == "intel"
    assert profile.has_gpu is True
    assert profile.gpu_name == "Intel Integrated Graphics"

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_windows_hardware_amd(mock_run):
    profile = HardwareProfile(os_type="windows", cpu_arch="AMD64", total_ram_gb=32.0)

    def side_effect(*args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "name" in args[0]:
            mock_res.stdout = "Name\nAMD Radeon RX 6800\n"
        elif "AdapterRAM" in args[0]:
            mock_res.stdout = "AdapterRAM\n17179869184\n"
        return mock_res

    mock_run.side_effect = side_effect

    _detect_windows_hardware(profile)

    assert profile.is_unified_memory is False
    assert profile.gpu_vendor == "amd"
    assert profile.has_gpu is True
    assert profile.gpu_name == "AMD Radeon RX 6800"
    assert profile.gpu_vram_gb == 17179869184 / (1024**3)

@patch("myrm_agent_harness.runtime.maintenance.hardware.subprocess.run")
def test_detect_windows_hardware_intel(mock_run):
    profile = HardwareProfile(os_type="windows", cpu_arch="AMD64", total_ram_gb=32.0)

    def side_effect(*args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "name" in args[0]:
            mock_res.stdout = "Name\nIntel(R) UHD Graphics\n"
        elif "AdapterRAM" in args[0]:
            mock_res.stdout = "AdapterRAM\n1073741824\n"
        return mock_res

    mock_run.side_effect = side_effect

    _detect_windows_hardware(profile)

    assert profile.is_unified_memory is False
    assert profile.gpu_vendor == "intel"
    assert profile.has_gpu is True
    assert profile.gpu_name == "Intel(R) UHD Graphics"
    assert profile.gpu_vram_gb == 1073741824 / (1024**3)

@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil")
@patch("myrm_agent_harness.runtime.maintenance.hardware.platform")
@patch("myrm_agent_harness.runtime.maintenance.hardware._detect_macos_hardware")
def test_detect_hardware_profile_unknown_os(mock_detect, mock_platform, mock_psutil):
    mock_platform.system.return_value = "FreeBSD"
    mock_platform.machine.return_value = "amd64"

    mock_virtual_memory = MagicMock()
    mock_virtual_memory.total = 16 * (1024**3)
    mock_psutil.virtual_memory.return_value = mock_virtual_memory

    mock_disk_usage = MagicMock()
    mock_disk_usage.free = 100 * (1024**3)
    mock_psutil.disk_usage.return_value = mock_disk_usage

    profile = detect_hardware_profile()

    assert profile is not None
    assert profile.os_type == "unknown"
    mock_detect.assert_not_called()

@patch("myrm_agent_harness.runtime.maintenance.hardware.psutil")
def test_detect_hardware_profile_exception(mock_psutil):
    mock_psutil.virtual_memory.side_effect = Exception("Test Exception")
    profile = detect_hardware_profile()
    assert profile is None
