"""Hardware probing for local deployment model recommendations.

Provides cross-platform hardware sensing to detect physical machine capabilities
(RAM, CPU architecture, GPU model and VRAM). This is used to compute Fit Scores
for local LLM execution.

[INPUT]
- (none)

[OUTPUT]
- HardwareProfile: Data class containing detected hardware specs
- detect_hardware_profile: Function to run the detection

[POS]
Hardware sensing for local deployment.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

try:
    import psutil
except (ImportError, TypeError):
    psutil = None  # type: ignore[assignment]


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
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, timeout=2
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
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True, text=True, timeout=5
                )
                if res.returncode == 0:
                    output = res.stdout.lower()
                    
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
                                try:
                                    profile.gpu_vram_gb = float(vram_str.replace("GB", "").strip())
                                except ValueError:
                                    pass
                            elif "MB" in vram_str:
                                try:
                                    profile.gpu_vram_gb = float(vram_str.replace("MB", "").strip()) / 1024.0
                                except ValueError:
                                    pass
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
            capture_output=True, text=True, timeout=5
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
                        try:
                            profile.gpu_vram_gb = float(vram_str.replace("MiB", "").strip()) / 1024.0
                        except ValueError:
                            pass
            return  # Successfully found NVIDIA GPU
    except Exception:
        pass
        
    # Fallback to lshw for AMD/Intel
    try:
        res = subprocess.run(
            ["lshw", "-C", "display", "-short"],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            output = res.stdout.lower()
            if "amd" in output or "radeon" in output:
                profile.gpu_vendor = "amd"
                profile.has_gpu = True
                profile.gpu_name = "AMD Radeon GPU" # lshw -short doesn't always give clean names
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
            ["wmic", "path", "win32_VideoController", "get", "name"],
            capture_output=True, text=True, timeout=5
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
            ["wmic", "path", "win32_VideoController", "get", "AdapterRAM"],
            capture_output=True, text=True, timeout=5
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
        
        profile = HardwareProfile(
            os_type=os_type,  # type: ignore
            cpu_arch=cpu_arch,
            total_ram_gb=total_ram_gb
        )
        
        # OS-specific GPU detection
        if os_type == "macos":
            _detect_macos_hardware(profile)
        elif os_type == "linux":
            _detect_linux_hardware(profile)
        elif os_type == "windows":
            _detect_windows_hardware(profile)
            
        return profile
        
    except Exception as e:
        logger.error(f"Hardware profile detection encountered unexpected error: {e}")
        return None
