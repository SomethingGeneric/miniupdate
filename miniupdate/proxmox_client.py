"""
Proxmox API client for miniupdate.

Handles VM snapshots and management via Proxmox VE API.
"""

import logging
import time
from typing import Dict, Any, Optional, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class ProxmoxAPIError(Exception):
    """Exception for Proxmox API errors."""


class ProxmoxClient:
    """Proxmox VE API client for VM management."""

    def __init__(
        self,
        endpoint: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: int = 30,
    ):
        """
        Initialize Proxmox client.

        Args:
            endpoint: Proxmox VE API endpoint (e.g., https://pve.example.com:8006)
            username: Username (e.g., root@pam)
            password: Password or API token
            verify_ssl: Whether to verify SSL certificates
            timeout: Request timeout in seconds
        """
        self.endpoint = endpoint.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.ticket = None
        self.csrf_token = None

        # Setup session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        if not verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def authenticate(self) -> bool:
        """Authenticate with Proxmox API."""
        try:
            auth_url = f"{self.endpoint}/api2/json/access/ticket"
            auth_data = {"username": self.username, "password": self.password}

            response = self.session.post(
                auth_url, data=auth_data, verify=self.verify_ssl, timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()["data"]
                self.ticket = data["ticket"]
                self.csrf_token = data["CSRFPreventionToken"]

                # Set session headers
                self.session.headers.update({"CSRFPreventionToken": self.csrf_token})
                self.session.cookies.set("PVEAuthCookie", self.ticket)

                logger.info("Successfully authenticated to Proxmox at %s", self.endpoint)
                return True
            logger.error(
                "Authentication failed: %s - %s", response.status_code, response.text
            )
            return False

        except Exception as e:
            logger.error("Authentication error: %s", e)
            return False

    def _api_request(
        self, method: str, path: str, data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make authenticated API request."""
        if not self.ticket:
            if not self.authenticate():
                raise ProxmoxAPIError("Authentication failed")

        url = f"{self.endpoint}/api2/json{path}"

        try:
            if method.upper() == "GET":
                response = self.session.get(
                    url, params=data, verify=self.verify_ssl, timeout=self.timeout
                )
            elif method.upper() == "POST":
                response = self.session.post(
                    url, data=data, verify=self.verify_ssl, timeout=self.timeout
                )
            elif method.upper() == "DELETE":
                response = self.session.delete(
                    url, data=data, verify=self.verify_ssl, timeout=self.timeout
                )
            else:
                raise ProxmoxAPIError(f"Unsupported HTTP method: {method}")

            if response.status_code == 401:
                # Token expired, retry once after re-authentication
                logger.warning("API token expired, re-authenticating...")
                self.ticket = None
                if not self.authenticate():
                    raise ProxmoxAPIError("Re-authentication failed")
                return self._api_request(method, path, data)

            if response.status_code not in [200, 201]:
                raise ProxmoxAPIError(
                    f"API request failed: {response.status_code} - {response.text}"
                )

            return response.json()

        except requests.RequestException as e:
            raise ProxmoxAPIError(f"Request failed: {e}") from e

    def get_vm_status(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get VM status."""
        path = f"/nodes/{node}/qemu/{vmid}/status/current"
        return self._api_request("GET", path)

    def create_snapshot(
        self,
        node: str,
        vmid: int,
        snapname: str,
        description: str = "",
        include_ram: bool = False,
    ) -> Dict[str, Any]:
        """Create VM snapshot.

        Args:
            node: Proxmox node name
            vmid: VM ID
            snapname: Snapshot name
            description: Snapshot description
            include_ram: Whether to include RAM state in snapshot
                        (default: False for faster, more reliable snapshots)
        """
        path = f"/nodes/{node}/qemu/{vmid}/snapshot"
        data = {
            "snapname": snapname,
            "description": description
            or f"Automatic snapshot before updates - {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "vmstate": (
                1 if include_ram else 0
            ),  # 0 = exclude RAM state, 1 = include RAM state
        }

        snapshot_type = "with RAM" if include_ram else "without RAM"
        logger.info(
            "Creating snapshot '%s' (%s) for VM %s on node %s",
            snapname,
            snapshot_type,
            vmid,
            node,
        )
        return self._api_request("POST", path, data)

    def delete_snapshot(self, node: str, vmid: int, snapname: str) -> Dict[str, Any]:
        """Delete VM snapshot."""
        path = f"/nodes/{node}/qemu/{vmid}/snapshot/{snapname}"

        logger.info("Deleting snapshot '%s' for VM %s on node %s", snapname, vmid, node)
        return self._api_request("DELETE", path)

    def rollback_snapshot(self, node: str, vmid: int, snapname: str) -> Dict[str, Any]:
        """Rollback VM to snapshot."""
        path = f"/nodes/{node}/qemu/{vmid}/snapshot/{snapname}/rollback"

        logger.warning(
            "Rolling back VM %s on node %s to snapshot '%s'", vmid, node, snapname
        )
        return self._api_request("POST", path)

    def list_snapshots(self, node: str, vmid: int) -> List[Dict[str, Any]]:
        """List VM snapshots."""
        path = f"/nodes/{node}/qemu/{vmid}/snapshot"
        response = self._api_request("GET", path)
        return response.get("data", [])

    def wait_for_task(self, node: str, upid: str, timeout: int = 300) -> bool:
        """Wait for a Proxmox task to complete."""
        path = f"/nodes/{node}/tasks/{upid}/status"

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self._api_request("GET", path)
                task_data = response.get("data", {})

                status = task_data.get("status")
                if status == "stopped":
                    exitstatus = task_data.get("exitstatus")
                    if exitstatus == "OK":
                        logger.info("Task %s completed successfully", upid)
                        return True
                    logger.error("Task %s failed with status: %s", upid, exitstatus)
                    return False

                # Task still running
                time.sleep(2)

            except Exception as e:
                logger.warning("Error checking task status: %s", e)
                time.sleep(2)

        logger.error("Task %s timed out after %s seconds", upid, timeout)
        return False

    def start_vm(self, node: str, vmid: int, timeout: int = 30) -> bool:
        """Start/power on VM."""
        path = f"/nodes/{node}/qemu/{vmid}/status/start"

        try:
            logger.info("Starting VM %s on node %s", vmid, node)
            response = self._api_request("POST", path)

            # If response contains UPID (task ID), wait for it to complete
            if "data" in response and isinstance(response["data"], str):
                upid = response["data"]
                return self.wait_for_task(node, upid, timeout)

            return True

        except Exception as e:
            logger.error("Failed to start VM %s: %s", vmid, e)
            return False

    def reboot_vm(self, node: str, vmid: int, timeout: int = 30) -> bool:
        """Reboot VM."""
        path = f"/nodes/{node}/qemu/{vmid}/status/reboot"

        try:
            logger.info("Rebooting VM %s on node %s", vmid, node)
            response = self._api_request("POST", path)

            # If response contains UPID (task ID), wait for it to complete
            if "data" in response and isinstance(response["data"], str):
                upid = response["data"]
                return self.wait_for_task(node, upid, timeout)

            return True

        except Exception as e:
            logger.error("Failed to reboot VM %s: %s", vmid, e)
            return False
