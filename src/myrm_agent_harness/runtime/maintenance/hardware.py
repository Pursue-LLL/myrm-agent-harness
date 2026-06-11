"""Hardware probing for local deployment model recommendations.

Provides cross-platform hardware sensing to detect physical machine capabilities
(RAM, CPU architecture, GPU model and VRAM, memory bandwidth). This is used to
compute Fit Scores and estimated Tokens/s for local LLM execution.

[INPUT]
- (none)

[OUTPUT]
- HardwareProfile: Data class containing detected hardware specs
- detect_hardware_profile: Function to run the detection

[POS]
Hardware sensing for local deployment.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

try:
    import psutil
except (ImportError, TypeError):
    psutil = None  # type: ignore[assignment]

# GPU memory bandwidth lookup table (GB/s, theoretical peak).
# Keys are substrings matched case-insensitively against the GPU name.
# Longer keys take priority (longest-match wins).
# Source: vendor datasheets; Apple Silicon values are unified memory bandwidth.
_GPU_BANDWIDTH: dict[str, float] = {
    # NVIDIA RTX 50 series (Blackwell)
    "RTX 5090": 1792.0,
    "RTX 5080": 960.0,
    "RTX 5070 Ti": 896.0,
    "RTX 5070": 672.0,
    "RTX 5060 Ti": 448.0,
    "RTX 5060": 336.0,
    # NVIDIA RTX 40 series (Ada Lovelace)
    "RTX 4090": 1008.0,
    "RTX 4080 SUPER": 736.0,
    "RTX 4080": 716.8,
    "RTX 4070 Ti SUPER": 672.0,
    "RTX 4070 Ti": 504.0,
    "RTX 4070 SUPER": 504.0,
    "RTX 4070": 504.0,
    "RTX 4060 Ti": 288.0,
    "RTX 4060": 272.0,
    # NVIDIA RTX 30 series (Ampere)
    "RTX 3090 Ti": 1008.0,
    "RTX 3090": 936.2,
    "RTX 3080 Ti": 912.4,
    "RTX 3080": 760.3,
    "RTX 3070 Ti": 608.3,
    "RTX 3070": 448.0,
    "RTX 3060 Ti": 448.0,
    "RTX 3060": 360.0,
    "RTX 3050": 224.0,
    # NVIDIA RTX 20 series (Turing)
    "RTX 2080 Ti": 616.0,
    "RTX 2080 SUPER": 496.0,
    "RTX 2080": 448.0,
    "RTX 2070 SUPER": 448.0,
    "RTX 2070": 448.0,
    "RTX 2060 SUPER": 448.0,
    "RTX 2060": 336.0,
    # NVIDIA GTX 16 series (Turing)
    "GTX 1660 Ti": 288.0,
    "GTX 1660 SUPER": 336.0,
    "GTX 1660": 192.0,
    "GTX 1650": 128.0,
    # NVIDIA Data Center / Professional
    "H200": 4800.0,
    "H100": 3350.0,
    "MI300X": 5300.0,
    "A100 80GB": 2039.0,
    "A100 40GB": 1555.0,
    "A100": 1555.0,
    "DGX Spark": 273.0,
    "GB10": 273.0,
    "A6000": 768.0,
    "A5000": 768.0,
    "A4000": 448.0,
    "L40S": 864.0,
    "L40": 864.0,
    "L4": 300.0,
    "T4": 320.0,
    "V100": 900.0,
    "P100": 732.0,
    "RTX A3000 Laptop": 264.0,
    # NVIDIA Legacy (Kepler, GTX 700/900)
    "GTX 780": 288.4,
    "GTX 770": 224.3,
    "GTX 760": 192.2,
    # AMD Discrete (RDNA 3 / 4)
    "RX 9070 XT": 640.0,
    "RX 9070": 560.0,
    "RX 9060 XT": 320.0,
    "RX 7900 XTX": 960.0,
    "RX 7900 XT": 800.0,
    "RX 7800 XT": 624.0,
    "RX 7700 XT": 432.0,
    "RX 7600": 288.0,
    "RX 6950 XT": 576.0,
    "RX 6900 XT": 512.0,
    "RX 6800 XT": 512.0,
    "RX 6800": 512.0,
    "RX 6750 XT": 432.0,
    "RX 6700 XT": 384.0,
    "RX 6700": 320.0,
    "RX 6650 XT": 256.0,
    "RX 6600 XT": 256.0,
    "RX 6600": 224.0,
    # AMD APU / Integrated (Ryzen AI / Radeon)
    "Ryzen AI MAX+ 395": 256.0,
    "Ryzen AI MAX 395": 256.0,
    "Radeon 890M": 120.0,
    "Radeon 880M": 120.0,
    "Radeon 860M": 90.0,
    "Radeon 840M": 60.0,
    "Radeon 780M": 90.0,
    "Radeon 760M": 75.0,
    "Radeon 740M": 60.0,
    "Radeon 680M": 75.0,
    "Radeon 660M": 55.0,
    "Radeon 8060S": 256.0,
    "Radeon 8050S": 256.0,
    "Strix Halo": 256.0,
    "MI250X": 3276.0,
    "MI210": 1638.0,
    # Apple Silicon (unified memory bandwidth, GB/s)
    "M5 Max": 614.0,
    "M5 Pro": 307.0,
    "M5": 153.0,
    "M4 Ultra": 819.2,
    "M4 Max": 546.0,
    "M4 Pro": 273.0,
    "M4": 120.0,
    "M3 Ultra": 800.0,
    "M3 Max": 400.0,
    "M3 Pro": 150.0,
    "M3": 100.0,
    "M2 Ultra": 800.0,
    "M2 Max": 400.0,
    "M2 Pro": 200.0,
    "M2": 100.0,
    "M1 Ultra": 800.0,
    "M1 Max": 400.0,
    "M1 Pro": 200.0,
    "M1": 68.25,
}


# Pre-sorted keys (longest first) so substring matching always picks the most
# specific entry (e.g. "M2 Pro" wins over "M2", "RTX 4070 Ti" over "RTX 4070").
_GPU_BANDWIDTH_KEYS_BY_LEN: tuple[str, ...] = tuple(sorted(_GPU_BANDWIDTH, key=len, reverse=True))


def _lookup_bandwidth(gpu_name: str | None) -> float | None:
    """Look up GPU memory bandwidth (GB/s) by GPU name substring matching.

    Longest-key-first matching ensures more specific entries win
    (e.g. "M2 Pro" before "M2").  Returns None for unknown GPUs.
    """
    if not gpu_name:
        return None
    name_lower = gpu_name.lower()
    for key in _GPU_BANDWIDTH_KEYS_BY_LEN:
        if key.lower() in name_lower:
            return _GPU_BANDWIDTH[key]
    return None


@dataclass
class HardwareProfile:
    """Snapshot of physical hardware capabilities."""

    os_type: Literal["macos", "windows", "linux", "unknown"]
    cpu_arch: str
    total_ram_gb: float

    # GPU Info (can be None if detection fails or no GPU)
    has_gpu: bool = False
    gpu_name: str | None = None
    gpu_vram_gb: float | None = None
    gpu_vendor: Literal["apple", "nvidia", "amd", "intel", "unknown"] = "unknown"

    # Apple Silicon specific (Unified Memory)
    is_unified_memory: bool = False

    # Disk Info
    free_disk_gb: float | None = None

    # Memory bandwidth in GB/s (used for Tokens/s estimation).
    # None if GPU/chip is unknown or not in the lookup table.
    memory_bandwidth_gbps: float | None = None


def _detect_macos_hardware(profile: HardwareProfile) -> None:
    """Detect hardware on macOS using system_profiler."""
    try:
        # Check if Apple Silicon
        if profile.cpu_arch.lower() in ("arm64", "aarch64"):
            profile.gpu_vendor = "apple"
            profile.is_unified_memory = True
            profile.has_gpu = True

            # For Apple Silicon, VRAM is essentially the total RAM (unified)
            # We reserve some for the OS, but the theoretical max is close to total RAM
            profile.gpu_vram_gb = profile.total_ram_gb

            # Try to get the specific chip name (e.g., "Apple M2 Max")
            try:
                res = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0 and res.stdout.strip():
                    profile.gpu_name = res.stdout.strip()
                else:
                    profile.gpu_name = "Apple Silicon"
            except Exception:
                profile.gpu_name = "Apple Silicon"

        else:
            # Intel Mac
            profile.is_unified_memory = False
            try:
                res = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=5
                )
                if res.returncode == 0:
                    # Extract GPU name
                    for line in res.stdout.splitlines():
                        if "Chipset Model:" in line:
                            profile.gpu_name = line.split(":", 1)[1].strip()
                            profile.has_gpu = True
                            if "amd" in profile.gpu_name.lower() or "radeon" in profile.gpu_name.lower():
                                profile.gpu_vendor = "amd"
                            elif "intel" in profile.gpu_name.lower():
                                profile.gpu_vendor = "intel"
                            break

                    # Extract VRAM
                    for line in res.stdout.splitlines():
                        if "VRAM (Total):" in line or "VRAM (Dynamic, Max):" in line:
                            vram_str = line.split(":", 1)[1].strip()
                            if "GB" in vram_str:
                                with contextlib.suppress(ValueError):
                                    profile.gpu_vram_gb = float(vram_str.replace("GB", "").strip())
                                break
                            elif "MB" in vram_str:
                                with contextlib.suppress(ValueError):
                                    profile.gpu_vram_gb = float(vram_str.replace("MB", "").strip()) / 1024.0
                                break
            except Exception as e:
                logger.debug(f"macOS Intel GPU detection failed: {e}")

    except Exception as e:
        logger.warning(f"macOS hardware detection failed: {e}")


def _detect_linux_hardware(profile: HardwareProfile) -> None:
    """Detect hardware on Linux using nvidia-smi or lspci."""
    profile.is_unified_memory = False

    # Try nvidia-smi first
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            lines = res.stdout.strip().splitlines()
            if lines:
                parts = lines[0].split(",")
                if len(parts) >= 2:
                    profile.gpu_name = parts[0].strip()
                    profile.gpu_vendor = "nvidia"
                    profile.has_gpu = True

                    vram_str = parts[1].strip()
                    if "MiB" in vram_str:
                        with contextlib.suppress(ValueError):
                            profile.gpu_vram_gb = float(vram_str.replace("MiB", "").strip()) / 1024.0
            return  # Successfully found NVIDIA GPU
    except Exception:
        pass

    # Fallback to lshw for AMD/Intel
    try:
        res = subprocess.run(["lshw", "-C", "display", "-short"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            output = res.stdout.lower()
            if "amd" in output or "radeon" in output:
                profile.gpu_vendor = "amd"
                profile.has_gpu = True
                profile.gpu_name = "AMD Radeon GPU"  # lshw -short doesn't always give clean names
            elif "intel" in output:
                profile.gpu_vendor = "intel"
                profile.has_gpu = True
                profile.gpu_name = "Intel Integrated Graphics"

            # Getting VRAM without nvidia-smi or rocm-smi is hard on Linux,
            # we leave it None to let the caller fallback to RAM heuristics
    except Exception:
        pass


def _detect_windows_hardware(profile: HardwareProfile) -> None:
    """Detect hardware on Windows using wmic."""
    profile.is_unified_memory = False

    try:
        # Get GPU Name
        res_name = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name"], capture_output=True, text=True, timeout=5
        )
        if res_name.returncode == 0:
            lines = [line.strip() for line in res_name.stdout.splitlines() if line.strip()]
            if len(lines) > 1:
                # Skip header 'Name'
                profile.gpu_name = lines[1]
                profile.has_gpu = True

                name_lower = profile.gpu_name.lower()
                if "nvidia" in name_lower:
                    profile.gpu_vendor = "nvidia"
                elif "amd" in name_lower or "radeon" in name_lower:
                    profile.gpu_vendor = "amd"
                elif "intel" in name_lower:
                    profile.gpu_vendor = "intel"

        # Get VRAM
        res_vram = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "AdapterRAM"], capture_output=True, text=True, timeout=5
        )
        if res_vram.returncode == 0:
            lines = [line.strip() for line in res_vram.stdout.splitlines() if line.strip()]
            if len(lines) > 1:
                try:
                    # AdapterRAM is in bytes
                    ram_bytes = int(lines[1])
                    # wmic AdapterRAM often caps at 4GB (2^32-1) due to 32-bit integer limits in WMI for some drivers
                    # If it's exactly 4294967296 or similar, it might be inaccurate, but we use it as a baseline
                    profile.gpu_vram_gb = ram_bytes / (1024.0**3)
                except ValueError:
                    pass

    except Exception as e:
        logger.debug(f"Windows hardware detection failed: {e}")


def detect_hardware_profile() -> HardwareProfile | None:
    """
    Detect physical hardware capabilities.

    Returns None if basic detection fails (e.g., psutil missing).
    Never raises exceptions.
    """
    if psutil is None:
        logger.warning("psutil not available, cannot detect hardware profile")
        return None

    try:
        # Basic OS and CPU info
        system = platform.system().lower()
        if system == "darwin":
            os_type = "macos"
        elif system == "windows":
            os_type = "windows"
        elif system == "linux":
            os_type = "linux"
        else:
            os_type = "unknown"

        cpu_arch = platform.machine()

        # Total RAM in GB
        total_ram_gb = psutil.virtual_memory().total / (1024.0**3)

        # Free Disk Space in GB (check user home directory)
        free_disk_gb = psutil.disk_usage(os.path.expanduser("~")).free / (1024.0**3)

        profile = HardwareProfile(
            os_type=os_type,  # type: ignore
            cpu_arch=cpu_arch,
            total_ram_gb=total_ram_gb,
            free_disk_gb=free_disk_gb,
        )

        # OS-specific GPU detection
        if os_type == "macos":
            _detect_macos_hardware(profile)
        elif os_type == "linux":
            _detect_linux_hardware(profile)
        elif os_type == "windows":
            _detect_windows_hardware(profile)

        # Populate memory bandwidth from GPU name lookup table
        profile.memory_bandwidth_gbps = _lookup_bandwidth(profile.gpu_name)

        return profile

    except Exception as e:
        logger.error(f"Hardware profile detection encountered unexpected error: {e}")
        return None
