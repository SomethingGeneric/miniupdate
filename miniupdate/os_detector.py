"""
OS detection for miniupdate.

Detects the operating system and distribution of remote hosts.
"""

import logging
from typing import Optional, Dict, Tuple

from .ssh_manager import SSHConnection


logger = logging.getLogger(__name__)


class OSInfo:
    """Container for OS information."""

    def __init__(
        self,
        os_family: str,
        distribution: str,
        version: str,
        package_manager: str,
        architecture: str = "unknown",
    ):
        self.os_family = os_family  # linux, darwin, windows, etc.
        self.distribution = distribution  # ubuntu, centos, debian, etc.
        self.version = version
        self.package_manager = package_manager  # apt, yum, dnf, pacman, etc.
        self.architecture = architecture

    def __str__(self):
        return f"{self.distribution} {self.version} ({self.os_family}, {self.package_manager})"

    def __repr__(self):
        return (
            f"OSInfo(os_family='{self.os_family}', distribution='{self.distribution}', "
            f"version='{self.version}', package_manager='{self.package_manager}')"
        )


class OSDetector:
    """Detects operating system information on remote hosts."""

    # Package manager detection commands
    PACKAGE_MANAGERS = {
        "apt": ["/usr/bin/apt", "/usr/bin/apt-get"],
        "yum": ["/usr/bin/yum", "/bin/yum"],
        "dnf": ["/usr/bin/dnf", "/bin/dnf"],
        "zypper": ["/usr/bin/zypper"],
        "pacman": ["/usr/bin/pacman"],
        "apk": ["/sbin/apk"],
        "pkg": ["/usr/sbin/pkg"],  # FreeBSD
        "pkg_add": ["/usr/sbin/pkg_add"],  # OpenBSD
        "brew": ["/usr/local/bin/brew", "/opt/homebrew/bin/brew"],  # macOS
    }

    # OS family detection patterns
    OS_PATTERNS = {
        "ubuntu": ("linux", "apt"),
        "debian": ("linux", "apt"),
        "linuxmint": ("linux", "apt"),
        "mint": ("linux", "apt"),
        "centos": ("linux", "yum"),
        "rhel": ("linux", "yum"),
        "red hat": ("linux", "yum"),
        "fedora": ("linux", "dnf"),
        "opensuse": ("linux", "zypper"),
        "suse": ("linux", "zypper"),
        "arch": ("linux", "pacman"),
        "manjaro": ("linux", "pacman"),
        "alpine": ("linux", "apk"),
        "freebsd": ("freebsd", "pkg"),
        "openbsd": ("openbsd", "pkg_add"),
        "darwin": ("darwin", "brew"),
        "macos": ("darwin", "brew"),
    }

    def __init__(self, connection: SSHConnection):
        self.connection = connection

    def detect_os(self) -> Optional[OSInfo]:
        """
        Detect operating system information.

        Returns:
            OSInfo object with detected information, or None if detection fails
        """
        try:
            # Get basic system information
            uname_info = self._get_uname_info()
            os_release_info = self._get_os_release_info()
            lsb_info = self._get_lsb_info()

            # Determine OS family and distribution
            os_family, distribution, version = self._parse_os_info(
                uname_info, os_release_info, lsb_info
            )

            # Detect package manager
            package_manager = self._detect_package_manager(distribution)

            # Get architecture
            architecture = self._get_architecture(uname_info)

            os_info = OSInfo(
                os_family=os_family,
                distribution=distribution,
                version=version,
                package_manager=package_manager,
                architecture=architecture,
            )

            logger.info("Detected OS on %s: %s", self.connection.host.name, os_info)
            return os_info

        except Exception as e:
            logger.error("Failed to detect OS on %s: %s", self.connection.host.name, e)
            return None

    def _get_uname_info(self) -> Dict[str, str]:
        """Get uname information."""
        exit_code, stdout, _stderr = self.connection.execute_command("uname -a")
        if exit_code != 0:
            return {}

        uname_output = stdout.strip()
        parts = uname_output.split()

        return {
            "kernel_name": parts[0] if len(parts) > 0 else "",
            "hostname": parts[1] if len(parts) > 1 else "",
            "kernel_release": parts[2] if len(parts) > 2 else "",
            "kernel_version": parts[3] if len(parts) > 3 else "",
            "machine": parts[4] if len(parts) > 4 else "",
            "full": uname_output,
        }

    def _get_os_release_info(self) -> Dict[str, str]:
        """Get information from /etc/os-release."""
        exit_code, stdout, _stderr = self.connection.execute_command(
            "cat /etc/os-release 2>/dev/null || true"
        )
        if exit_code != 0 or not stdout.strip():
            return {}

        os_release = {}
        for line in stdout.strip().split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                # Remove quotes
                value = value.strip("\"'")
                os_release[key] = value

        return os_release

    def _get_lsb_info(self) -> Dict[str, str]:
        """Get LSB information."""
        exit_code, stdout, _stderr = self.connection.execute_command(
            "lsb_release -a 2>/dev/null || true"
        )
        if exit_code != 0 or not stdout.strip():
            return {}

        lsb_info = {}
        for line in stdout.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                lsb_info[key.strip()] = value.strip()

        return lsb_info

    def _parse_os_info(
        self,
        uname_info: Dict[str, str],
        os_release_info: Dict[str, str],
        lsb_info: Dict[str, str],
    ) -> Tuple[str, str, str]:
        """Parse OS information from various sources."""
        # Default values
        os_family = "unknown"
        distribution = "unknown"
        version = "unknown"

        # Try os-release first (most reliable on modern systems)
        if os_release_info:
            if "ID" in os_release_info:
                distribution = os_release_info["ID"].lower()
            elif "NAME" in os_release_info:
                distribution = os_release_info["NAME"].lower()

            if "VERSION_ID" in os_release_info:
                version = os_release_info["VERSION_ID"]
            elif "VERSION" in os_release_info:
                version = os_release_info["VERSION"]

        # Fallback to LSB info
        if distribution == "unknown" and lsb_info:
            if "Distributor ID" in lsb_info:
                distribution = lsb_info["Distributor ID"].lower()
            if "Release" in lsb_info:
                version = lsb_info["Release"]

        # Fallback to uname for macOS/Darwin/BSD systems
        if distribution == "unknown" and uname_info:
            kernel_name = uname_info.get("kernel_name", "").lower()
            if kernel_name == "darwin":
                distribution = "macos"
                version = uname_info.get("kernel_release", "unknown")
            elif kernel_name == "freebsd":
                distribution = "freebsd"
                version = uname_info.get("kernel_release", "unknown")
            elif kernel_name == "openbsd":
                distribution = "openbsd"
                version = uname_info.get("kernel_release", "unknown")

        # Determine OS family from distribution
        for pattern, (family, _) in self.OS_PATTERNS.items():
            if pattern in distribution.lower():
                os_family = family
                break

        # Clean up distribution name
        distribution = self._normalize_distribution_name(distribution)

        # Set version for rolling release distributions
        if distribution in ["arch", "manjaro"] and version == "unknown":
            version = "rolling"

        return os_family, distribution, version

    def _normalize_distribution_name(self, distribution: str) -> str:
        """Normalize distribution name."""
        distribution = distribution.lower().strip()

        # Handle common variations
        if "red hat" in distribution or "redhat" in distribution:
            return "rhel"
        if "centos" in distribution:
            return "centos"
        if "ubuntu" in distribution:
            return "ubuntu"
        if (
            "linuxmint" in distribution
            or "linux mint" in distribution
            or distribution == "mint"
        ):
            return "linuxmint"
        if "debian" in distribution:
            return "debian"
        if "fedora" in distribution:
            return "fedora"
        if "opensuse" in distribution or "suse" in distribution:
            return "opensuse"
        if "arch" in distribution:
            return "arch"
        if "manjaro" in distribution:
            return "manjaro"
        if "alpine" in distribution:
            return "alpine"
        if "freebsd" in distribution:
            return "freebsd"
        if "openbsd" in distribution:
            return "openbsd"
        if "darwin" in distribution or "macos" in distribution:
            return "macos"

        return distribution

    def _detect_package_manager(self, distribution: str) -> str:
        """Detect package manager based on distribution and available commands."""
        # First try based on known distribution patterns
        for pattern, (_, default_pm) in self.OS_PATTERNS.items():
            if pattern in distribution.lower():
                # Verify the package manager exists
                if self._check_package_manager_exists(default_pm):
                    return default_pm

        # Fallback: check for available package managers
        for pm_name, _commands in self.PACKAGE_MANAGERS.items():
            if self._check_package_manager_exists(pm_name):
                return pm_name

        return "unknown"

    def _check_package_manager_exists(self, pm_name: str) -> bool:
        """Check if a package manager exists on the system."""
        if pm_name not in self.PACKAGE_MANAGERS:
            return False

        for command_path in self.PACKAGE_MANAGERS[pm_name]:
            exit_code, _, _ = self.connection.execute_command(f"test -x {command_path}")
            if exit_code == 0:
                return True

        return False

    def _get_architecture(self, uname_info: Dict[str, str]) -> str:
        """Get system architecture."""
        if "machine" in uname_info:
            arch = uname_info["machine"]
            # Normalize common architectures
            if arch in ["x86_64", "amd64"]:
                return "x86_64"
            if arch in ["i386", "i686"]:
                return "i386"
            if arch.startswith("arm"):
                return "arm"
            if arch.startswith("aarch64"):
                return "arm64"
            else:
                return arch

        return "unknown"
