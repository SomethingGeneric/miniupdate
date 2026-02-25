"""
SSH connection manager for miniupdate.

Handles SSH connections to remote hosts and command execution.
"""

import logging
import os
import socket
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import paramiko

from .inventory import Host

logger = logging.getLogger(__name__)


class SSHConnection:
    """Manages SSH connection to a single host."""

    def __init__(self, host: Host, ssh_config: Dict[str, Any]):
        self.host = host
        self.ssh_config = ssh_config
        self.client = None
        self.connected = False

    def connect(
        self,
        username: Optional[str] = None,
        key_file: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30,
    ) -> bool:
        """
        Connect to the host via SSH.

        Args:
            username: SSH username (overrides config and host settings)
            key_file: Path to SSH private key file
            password: SSH password (if not using key auth)
            timeout: Connection timeout in seconds

        Returns:
            True if connection successful, False otherwise
        """
        # Determine connection parameters
        final_username = (
            username
            or self.host.username
            or self.ssh_config.get("username")
            or os.getenv("USER", "root")
        )

        final_key_file = key_file or self.ssh_config.get("key_file")
        final_timeout = timeout or self.ssh_config.get("timeout", 30)

        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Prepare connection arguments
            connect_kwargs = {
                "hostname": self.host.hostname,
                "port": self.host.port,
                "username": final_username,
                "timeout": final_timeout,
                "look_for_keys": True,
                "allow_agent": True,
            }

            # Add authentication
            if final_key_file and Path(final_key_file).exists():
                connect_kwargs["key_filename"] = final_key_file
            elif password:
                connect_kwargs["password"] = password

            logger.debug(
                "Connecting to %s:%s as %s",
                self.host.hostname,
                self.host.port,
                final_username,
            )
            self.client.connect(**connect_kwargs)
            self.connected = True
            logger.info("Successfully connected to %s", self.host.name)
            return True

        except (
            paramiko.AuthenticationException,
            paramiko.SSHException,
            socket.error,
            Exception,
        ) as e:
            logger.error("Failed to connect to %s: %s", self.host.name, e)
            self.connected = False
            return False

    def execute_command(self, command: str, timeout: int = 60) -> Tuple[int, str, str]:
        """
        Execute a command on the remote host.

        Args:
            command: Command to execute
            timeout: Command timeout in seconds

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        if not self.connected or not self.client:
            raise RuntimeError(f"Not connected to {self.host.name}")

        try:
            logger.debug("Executing command on %s: %s", self.host.name, command)
            _stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)

            exit_code = stdout.channel.recv_exit_status()
            stdout_data = stdout.read().decode("utf-8", errors="replace")
            stderr_data = stderr.read().decode("utf-8", errors="replace")

            logger.debug("Command finished with exit code %s", exit_code)
            return exit_code, stdout_data, stderr_data

        except Exception as e:
            logger.error("Error executing command on %s: %s", self.host.name, e)
            return -1, "", str(e)

    def disconnect(self):
        """Disconnect from the host."""
        if self.client:
            try:
                self.client.close()
                logger.debug("Disconnected from %s", self.host.name)
            except Exception as e:
                logger.warning("Error disconnecting from %s: %s", self.host.name, e)
            finally:
                self.client = None
                self.connected = False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


class SSHManager:
    """Manages SSH connections to multiple hosts."""

    def __init__(self, ssh_config: Dict[str, Any]):
        self.ssh_config = ssh_config
        self.connections = {}

    def connect_to_host(self, host: Host, **kwargs) -> Optional[SSHConnection]:
        """
        Connect to a single host.

        Args:
            host: Host to connect to
            **kwargs: Additional connection parameters

        Returns:
            SSHConnection object if successful, None otherwise
        """
        connection = SSHConnection(host, self.ssh_config)

        if connection.connect(**kwargs):
            self.connections[host.name] = connection
            return connection

        return None

    def connect_to_hosts(self, hosts: list, **kwargs) -> Dict[str, SSHConnection]:
        """
        Connect to multiple hosts.

        Args:
            hosts: List of Host objects
            **kwargs: Additional connection parameters

        Returns:
            Dictionary mapping host names to SSHConnection objects
        """
        successful_connections = {}

        for host in hosts:
            connection = self.connect_to_host(host, **kwargs)
            if connection:
                successful_connections[host.name] = connection

        logger.info("Connected to %s/%s hosts", len(successful_connections), len(hosts))
        return successful_connections

    def execute_on_host(
        self, host_name: str, command: str, **kwargs
    ) -> Tuple[int, str, str]:
        """
        Execute command on a specific host.

        Args:
            host_name: Name of the host
            command: Command to execute
            **kwargs: Additional execution parameters

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        if host_name not in self.connections:
            raise ValueError(f"Not connected to host: {host_name}")

        return self.connections[host_name].execute_command(command, **kwargs)

    def execute_on_all_hosts(
        self, command: str, **kwargs
    ) -> Dict[str, Tuple[int, str, str]]:
        """
        Execute command on all connected hosts.

        Args:
            command: Command to execute
            **kwargs: Additional execution parameters

        Returns:
            Dictionary mapping host names to (exit_code, stdout, stderr) tuples
        """
        results = {}

        for host_name, connection in self.connections.items():
            try:
                results[host_name] = connection.execute_command(command, **kwargs)
            except Exception as e:
                logger.error("Error executing command on %s: %s", host_name, e)
                results[host_name] = (-1, "", str(e))

        return results

    def disconnect_all(self):
        """Disconnect from all hosts."""
        for connection in self.connections.values():
            connection.disconnect()
        self.connections.clear()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect_all()
