"""
Package manager interfaces for miniupdate.

Provides unified interface for checking updates across different package managers.
"""

import re
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Optional
from .ssh_manager import SSHConnection
from .os_detector import OSInfo


logger = logging.getLogger(__name__)


class PackageUpdate:
    """Represents a package update."""
    
    def __init__(self, name: str, current_version: str, 
                 available_version: str, repository: str = "",
                 security: bool = False, description: str = ""):
        self.name = name
        self.current_version = current_version
        self.available_version = available_version
        self.repository = repository
        self.security = security  # Whether this is a security update
        self.description = description
    
    def __str__(self):
        security_marker = " [SECURITY]" if self.security else ""
        return f"{self.name}: {self.current_version} -> {self.available_version}{security_marker}"
    
    def __repr__(self):
        return (f"PackageUpdate(name='{self.name}', "
                f"current='{self.current_version}', "
                f"available='{self.available_version}', "
                f"security={self.security})")


class PackageManager(ABC):
    """Abstract base class for package managers."""
    
    def __init__(self, connection: SSHConnection, os_info: OSInfo):
        self.connection = connection
        self.os_info = os_info
    
    @abstractmethod
    def check_updates(self) -> List[PackageUpdate]:
        """Check for available package updates."""
        pass
    
    @abstractmethod
    def refresh_cache(self) -> bool:
        """Refresh package cache/metadata."""
        pass
    
    @abstractmethod
    def apply_updates(self) -> bool:
        """Apply all available updates."""
        pass


class AptPackageManager(PackageManager):
    """Package manager for APT (Debian/Ubuntu)."""
    
    def refresh_cache(self) -> bool:
        """Refresh APT cache."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'apt-get update -qq', timeout=300
            )
            return exit_code == 0
        except Exception as e:
            logger.error(f"Failed to refresh APT cache: {e}")
            return False
    
    def check_updates(self) -> List[PackageUpdate]:
        """Check for APT package updates."""
        updates = []
        
        try:
            # Get list of upgradable packages
            exit_code, stdout, stderr = self.connection.execute_command(
                'apt list --upgradable 2>/dev/null | grep -v "WARNING"', 
                timeout=120
            )
            
            if exit_code != 0:
                logger.warning(f"APT list command failed: {stderr}")
                return updates
            
            # Parse output
            for line in stdout.strip().split('\n'):
                if not line.strip() or 'Listing...' in line:
                    continue
                
                update = self._parse_apt_line(line)
                if update:
                    updates.append(update)
            
            # Check for security updates
            self._mark_security_updates(updates)
            
        except Exception as e:
            logger.error(f"Failed to check APT updates: {e}")
        
        return updates
    
    def _parse_apt_line(self, line: str) -> Optional[PackageUpdate]:
        """Parse a single line from apt list --upgradable."""
        # Format: package/repo version arch [upgradable from: old_version]
        match = re.match(r'^([^/]+)/([^\s]+)\s+([^\s]+)\s+([^\s]+)(?:\s+\[upgradable from:\s+([^\]]+)\])?', line)
        
        if not match:
            return None
        
        package_name = match.group(1)
        repository = match.group(2)
        available_version = match.group(3)
        current_version = match.group(5) if match.group(5) else "unknown"
        
        return PackageUpdate(
            name=package_name,
            current_version=current_version,
            available_version=available_version,
            repository=repository
        )
    
    def _mark_security_updates(self, updates: List[PackageUpdate]):
        """Mark security updates by checking security repository."""
        security_repos = ['-security', '-updates']
        
        for update in updates:
            if any(sec_repo in update.repository for sec_repo in security_repos):
                update.security = True
    
    def apply_updates(self) -> bool:
        """Apply all available APT updates."""
        try:
            # Update package cache first
            if not self.refresh_cache():
                logger.error("Failed to refresh package cache before applying updates")
                return False
            
            # Apply updates non-interactively
            exit_code, stdout, stderr = self.connection.execute_command(
                'DEBIAN_FRONTEND=noninteractive apt-get upgrade -y', 
                timeout=1800  # 30 minutes for updates
            )
            
            if exit_code == 0:
                logger.info("Successfully applied APT updates")
                return True
            else:
                logger.error(f"Failed to apply APT updates: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying APT updates: {e}")
            return False


class YumPackageManager(PackageManager):
    """Package manager for YUM (CentOS/RHEL 7 and older)."""
    
    def refresh_cache(self) -> bool:
        """Refresh YUM cache."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'yum clean all && yum makecache fast', timeout=300
            )
            return exit_code == 0
        except Exception as e:
            logger.error(f"Failed to refresh YUM cache: {e}")
            return False
    
    def check_updates(self) -> List[PackageUpdate]:
        """Check for YUM package updates."""
        updates = []
        
        try:
            # Get list of available updates
            exit_code, stdout, stderr = self.connection.execute_command(
                'yum check-update --quiet', timeout=120
            )
            
            # yum check-update returns 100 if updates are available, 0 if none
            if exit_code not in [0, 100]:
                logger.warning(f"YUM check-update failed: {stderr}")
                return updates
            
            if exit_code == 100:  # Updates available
                updates = self._parse_yum_output(stdout)
                self._mark_security_updates(updates)
        
        except Exception as e:
            logger.error(f"Failed to check YUM updates: {e}")
        
        return updates
    
    def _parse_yum_output(self, output: str) -> List[PackageUpdate]:
        """Parse YUM check-update output."""
        updates = []
        
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('Loaded plugins') or line.startswith('Loading mirror'):
                continue
            
            parts = line.split()
            if len(parts) >= 3:
                package_arch = parts[0]
                available_version = parts[1]
                repository = parts[2]
                
                # Extract package name (remove .arch suffix)
                if '.' in package_arch:
                    package_name = package_arch.rsplit('.', 1)[0]
                else:
                    package_name = package_arch
                
                # Get current version (this is simplified - would need rpm query for exact version)
                current_version = "installed"
                
                update = PackageUpdate(
                    name=package_name,
                    current_version=current_version,
                    available_version=available_version,
                    repository=repository
                )
                updates.append(update)
        
        return updates
    
    def _mark_security_updates(self, updates: List[PackageUpdate]):
        """Mark security updates using yum security plugin."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'yum --security check-update --quiet', timeout=120
            )
            
            if exit_code == 100:  # Security updates available
                security_packages = set()
                for line in stdout.strip().split('\n'):
                    parts = line.strip().split()
                    if len(parts) >= 1:
                        package_arch = parts[0]
                        if '.' in package_arch:
                            package_name = package_arch.rsplit('.', 1)[0]
                        else:
                            package_name = package_arch
                        security_packages.add(package_name)
                
                # Mark matching updates as security updates
                for update in updates:
                    if update.name in security_packages:
                        update.security = True
        
        except Exception as e:
            logger.debug(f"Could not check YUM security updates: {e}")
    
    def apply_updates(self) -> bool:
        """Apply all available YUM updates."""
        try:
            # Update package cache first
            if not self.refresh_cache():
                logger.error("Failed to refresh package cache before applying updates")
                return False
            
            # Apply updates non-interactively
            exit_code, stdout, stderr = self.connection.execute_command(
                'yum update -y', 
                timeout=1800  # 30 minutes for updates
            )
            
            if exit_code == 0:
                logger.info("Successfully applied YUM updates")
                return True
            else:
                logger.error(f"Failed to apply YUM updates: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying YUM updates: {e}")
            return False


class DnfPackageManager(PackageManager):
    """Package manager for DNF (Fedora, CentOS/RHEL 8+)."""
    
    def refresh_cache(self) -> bool:
        """Refresh DNF cache."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'dnf clean all && dnf makecache', timeout=300
            )
            return exit_code == 0
        except Exception as e:
            logger.error(f"Failed to refresh DNF cache: {e}")
            return False
    
    def check_updates(self) -> List[PackageUpdate]:
        """Check for DNF package updates."""
        updates = []
        
        try:
            # Get list of available updates
            exit_code, stdout, stderr = self.connection.execute_command(
                'dnf check-update --quiet', timeout=120
            )
            
            # dnf check-update returns 100 if updates are available
            if exit_code not in [0, 100]:
                logger.warning(f"DNF check-update failed: {stderr}")
                return updates
            
            if exit_code == 100:  # Updates available
                updates = self._parse_dnf_output(stdout)
                self._mark_security_updates(updates)
        
        except Exception as e:
            logger.error(f"Failed to check DNF updates: {e}")
        
        return updates
    
    def _parse_dnf_output(self, output: str) -> List[PackageUpdate]:
        """Parse DNF check-update output."""
        # DNF output format is similar to YUM
        return YumPackageManager._parse_yum_output(self, output)
    
    def _mark_security_updates(self, updates: List[PackageUpdate]):
        """Mark security updates using dnf security plugin."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'dnf --security check-update --quiet', timeout=120
            )
            
            if exit_code == 100:  # Security updates available
                security_packages = set()
                for line in stdout.strip().split('\n'):
                    parts = line.strip().split()
                    if len(parts) >= 1:
                        package_arch = parts[0]
                        if '.' in package_arch:
                            package_name = package_arch.rsplit('.', 1)[0]
                        else:
                            package_name = package_arch
                        security_packages.add(package_name)
                
                # Mark matching updates as security updates
                for update in updates:
                    if update.name in security_packages:
                        update.security = True
        
        except Exception as e:
            logger.debug(f"Could not check DNF security updates: {e}")
    
    def apply_updates(self) -> bool:
        """Apply all available DNF updates."""
        try:
            # Update package cache first
            if not self.refresh_cache():
                logger.error("Failed to refresh package cache before applying updates")
                return False
            
            # Apply updates non-interactively
            exit_code, stdout, stderr = self.connection.execute_command(
                'dnf update -y', 
                timeout=1800  # 30 minutes for updates
            )
            
            if exit_code == 0:
                logger.info("Successfully applied DNF updates")
                return True
            else:
                logger.error(f"Failed to apply DNF updates: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying DNF updates: {e}")
            return False


class ZypperPackageManager(PackageManager):
    """Package manager for Zypper (openSUSE)."""
    
    def refresh_cache(self) -> bool:
        """Refresh Zypper cache."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'zypper --quiet refresh', timeout=300
            )
            return exit_code == 0
        except Exception as e:
            logger.error(f"Failed to refresh Zypper cache: {e}")
            return False
    
    def check_updates(self) -> List[PackageUpdate]:
        """Check for Zypper package updates."""
        updates = []
        
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'zypper --quiet list-updates', timeout=120
            )
            
            if exit_code != 0:
                logger.warning(f"Zypper list-updates failed: {stderr}")
                return updates
            
            updates = self._parse_zypper_output(stdout)
        
        except Exception as e:
            logger.error(f"Failed to check Zypper updates: {e}")
        
        return updates
    
    def _parse_zypper_output(self, output: str) -> List[PackageUpdate]:
        """Parse Zypper list-updates output."""
        updates = []
        
        for line in output.strip().split('\n'):
            if line.startswith('v |'):  # Update line
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 5:
                    package_name = parts[2]
                    current_version = parts[3]
                    available_version = parts[4]
                    repository = parts[1] if len(parts) > 5 else ""
                    
                    update = PackageUpdate(
                        name=package_name,
                        current_version=current_version,
                        available_version=available_version,
                        repository=repository
                    )
                    updates.append(update)
        
        return updates
    
    def apply_updates(self) -> bool:
        """Apply all available Zypper updates."""
        try:
            # Update package cache first
            if not self.refresh_cache():
                logger.error("Failed to refresh package cache before applying updates")
                return False
            
            # Apply updates non-interactively
            exit_code, stdout, stderr = self.connection.execute_command(
                'zypper --non-interactive update', 
                timeout=1800  # 30 minutes for updates
            )
            
            if exit_code == 0:
                logger.info("Successfully applied Zypper updates")
                return True
            else:
                logger.error(f"Failed to apply Zypper updates: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying Zypper updates: {e}")
            return False


class PackmanPackageManager(PackageManager):
    """Package manager for Pacman (Arch Linux)."""
    
    def refresh_cache(self) -> bool:
        """Refresh Pacman cache."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'pacman -Sy', timeout=300
            )
            return exit_code == 0
        except Exception as e:
            logger.error(f"Failed to refresh Pacman cache: {e}")
            return False
    
    def check_updates(self) -> List[PackageUpdate]:
        """Check for Pacman package updates."""
        updates = []
        
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'pacman -Qu', timeout=120
            )
            
            if exit_code not in [0, 1]:  # 1 means no updates
                logger.warning(f"Pacman query failed: {stderr}")
                return updates
            
            if exit_code == 0:  # Updates available
                updates = self._parse_pacman_output(stdout)
        
        except Exception as e:
            logger.error(f"Failed to check Pacman updates: {e}")
        
        return updates
    
    def _parse_pacman_output(self, output: str) -> List[PackageUpdate]:
        """Parse Pacman -Qu output."""
        updates = []
        
        for line in output.strip().split('\n'):
            if '->' in line:
                parts = line.split('->')
                if len(parts) == 2:
                    left_part = parts[0].strip()
                    available_version = parts[1].strip()
                    
                    # Extract package name and current version
                    name_version = left_part.split()
                    if len(name_version) >= 2:
                        package_name = name_version[0]
                        current_version = name_version[1]
                    else:
                        package_name = left_part
                        current_version = "unknown"
                    
                    update = PackageUpdate(
                        name=package_name,
                        current_version=current_version,
                        available_version=available_version
                    )
                    updates.append(update)
        
        return updates
    
    def apply_updates(self) -> bool:
        """Apply all available Pacman updates."""
        try:
            # Update package cache first
            if not self.refresh_cache():
                logger.error("Failed to refresh package cache before applying updates")
                return False
            
            # Apply updates non-interactively
            exit_code, stdout, stderr = self.connection.execute_command(
                'pacman -Su --noconfirm', 
                timeout=1800  # 30 minutes for updates
            )
            
            if exit_code == 0:
                logger.info("Successfully applied Pacman updates")
                return True
            else:
                logger.error(f"Failed to apply Pacman updates: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying Pacman updates: {e}")
            return False


class PkgPackageManager(PackageManager):
    """Package manager for FreeBSD pkg."""
    
    def refresh_cache(self) -> bool:
        """Refresh pkg cache."""
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'pkg update', timeout=300
            )
            return exit_code == 0
        except Exception as e:
            logger.error(f"Failed to refresh pkg cache: {e}")
            return False
    
    def check_updates(self) -> List[PackageUpdate]:
        """Check for pkg package updates."""
        updates = []
        
        try:
            exit_code, stdout, stderr = self.connection.execute_command(
                'pkg version -vL=', timeout=120
            )
            
            if exit_code != 0:
                logger.warning(f"pkg version command failed: {stderr}")
                return updates
            
            updates = self._parse_pkg_output(stdout)
            # FreeBSD pkg doesn't have built-in security update marking like apt
            # Would need to check against security advisories separately
            
        except Exception as e:
            logger.error(f"Failed to check pkg updates: {e}")
        
        return updates
    
    def _parse_pkg_output(self, output: str) -> List[PackageUpdate]:
        """Parse pkg version -vL= output."""
        updates = []
        
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Format: package-version < needs updating (port has version)
            if '<' in line and 'needs updating' in line:
                # Extract package name and versions
                parts = line.split('<')
                if len(parts) >= 2:
                    left_part = parts[0].strip()
                    right_part = parts[1].strip()
                    
                    # Parse package-version
                    if '-' in left_part:
                        # Split on last dash to separate package name from version
                        last_dash = left_part.rfind('-')
                        package_name = left_part[:last_dash]
                        current_version = left_part[last_dash + 1:]
                    else:
                        package_name = left_part
                        current_version = "unknown"
                    
                    # Extract available version from right part
                    # Format: "needs updating (port has 1.2.3)"
                    match = re.search(r'port has ([^)]+)', right_part)
                    if match:
                        available_version = match.group(1)
                    else:
                        available_version = "unknown"
                    
                    update = PackageUpdate(
                        name=package_name,
                        current_version=current_version,
                        available_version=available_version,
                        repository="ports"
                    )
                    updates.append(update)
        
        return updates
    
    def apply_updates(self) -> bool:
        """Apply all available pkg updates."""
        try:
            # Update package cache first
            if not self.refresh_cache():
                logger.error("Failed to refresh package cache before applying updates")
                return False
            
            # Apply updates non-interactively
            exit_code, stdout, stderr = self.connection.execute_command(
                'pkg upgrade -y', 
                timeout=1800  # 30 minutes for updates
            )
            
            if exit_code == 0:
                logger.info("Successfully applied pkg updates")
                return True
            else:
                logger.error(f"Failed to apply pkg updates: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying pkg updates: {e}")
            return False


def get_package_manager(connection: SSHConnection, os_info: OSInfo) -> Optional[PackageManager]:
    """Get appropriate package manager instance for the OS."""
    manager_map = {
        'apt': AptPackageManager,
        'yum': YumPackageManager,
        'dnf': DnfPackageManager,
        'zypper': ZypperPackageManager,
        'pacman': PackmanPackageManager,
        'pkg': PkgPackageManager,
    }
    
    pm_class = manager_map.get(os_info.package_manager)
    if pm_class:
        return pm_class(connection, os_info)
    
    logger.warning(f"Unsupported package manager: {os_info.package_manager}")
    return None