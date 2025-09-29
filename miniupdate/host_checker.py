"""
Host availability checker for miniupdate.

Provides utilities to check if hosts are reachable via ping and SSH.
"""

import subprocess
import logging
import time
from typing import Optional
from .ssh_manager import SSHManager
from .inventory import Host

logger = logging.getLogger(__name__)


class HostChecker:
    """Checks host availability via ping and SSH."""
    
    def __init__(self, ssh_config: dict):
        """
        Initialize host checker.
        
        Args:
            ssh_config: SSH configuration dictionary
        """
        self.ssh_config = ssh_config
    
    def ping_host(self, hostname: str, timeout: int = 5) -> bool:
        """
        Check if host responds to ping.
        
        Args:
            hostname: Hostname or IP address to ping
            timeout: Ping timeout in seconds
            
        Returns:
            True if host responds to ping, False otherwise
        """
        try:
            # Use ping command with timeout
            cmd = ['ping', '-c', '1', '-W', str(timeout), hostname]
            result = subprocess.run(cmd, capture_output=True, timeout=timeout + 2)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return False
    
    def wait_for_host_availability(self, host: Host, max_wait_time: int = 120, 
                                 check_interval: int = 5, use_ssh: bool = True) -> bool:
        """
        Wait for host to become available.
        
        Args:
            host: Host object to check
            max_wait_time: Maximum time to wait in seconds
            check_interval: Time between checks in seconds
            use_ssh: Whether to also check SSH connectivity
            
        Returns:
            True if host becomes available, False if timeout
        """
        logger.info(f"Waiting for {host.name} to become available (timeout: {max_wait_time}s)")
        
        start_time = time.time()
        attempt = 0
        
        while time.time() - start_time < max_wait_time:
            attempt += 1
            elapsed = int(time.time() - start_time)
            
            logger.debug(f"Checking {host.name} availability - attempt {attempt} ({elapsed}s elapsed)")
            
            # First check ping
            if not self.ping_host(host.hostname):
                logger.debug(f"{host.name} not responding to ping")
                time.sleep(check_interval)
                continue
            
            logger.debug(f"{host.name} responding to ping")
            
            # If SSH check is requested, verify SSH connectivity
            if use_ssh:
                if self._check_ssh_connectivity(host):
                    logger.info(f"{host.name} is available (ping + SSH) after {elapsed}s")
                    return True
                else:
                    logger.debug(f"{host.name} ping OK but SSH not ready")
            else:
                logger.info(f"{host.name} is available (ping only) after {elapsed}s")
                return True
            
            time.sleep(check_interval)
        
        elapsed = int(time.time() - start_time)
        logger.warning(f"{host.name} did not become available within {elapsed}s")
        return False
    
    def _check_ssh_connectivity(self, host: Host) -> bool:
        """
        Check if SSH connection to host is possible.
        
        Args:
            host: Host to check SSH connectivity
            
        Returns:
            True if SSH connection successful, False otherwise
        """
        try:
            with SSHManager(self.ssh_config) as ssh_manager:
                connection = ssh_manager.connect_to_host(host, timeout=10)
                if connection:
                    # Test basic command execution
                    exit_code, _, _ = connection.execute_command('echo test', timeout=5)
                    return exit_code == 0
                return False
        except Exception as e:
            logger.debug(f"SSH connectivity check failed for {host.name}: {e}")
            return False
    
    def reboot_host_via_ssh(self, host: Host, timeout: int = 30) -> bool:
        """
        Reboot host via SSH.
        
        Args:
            host: Host to reboot
            timeout: SSH timeout in seconds
            
        Returns:
            True if reboot command was sent successfully, False otherwise
        """
        try:
            with SSHManager(self.ssh_config) as ssh_manager:
                connection = ssh_manager.connect_to_host(host, timeout=timeout)
                if not connection:
                    logger.error(f"Failed to connect to {host.name} for reboot")
                    return False
                
                logger.info(f"Sending reboot command to {host.name}")
                
                # Send reboot command (don't wait for response as connection will drop)
                exit_code, stdout, stderr = connection.execute_command(
                    'shutdown -r now || reboot', 
                    timeout=5  # Short timeout as system will reboot
                )
                
                # Command may not return exit code due to immediate reboot
                logger.info(f"Reboot command sent to {host.name}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to reboot {host.name} via SSH: {e}")
            return False