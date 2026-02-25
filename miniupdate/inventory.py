"""
Ansible inventory parsing for miniupdate.

Supports parsing YAML and INI format Ansible inventory files.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml

logger = logging.getLogger(__name__)


class Host:
    """Represents a host from the inventory."""

    def __init__(
        self,
        name: str,
        hostname: Optional[str] = None,
        port: int = 22,
        username: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.hostname = hostname or name
        self.port = port
        self.username = username
        self.variables = variables or {}

    def __repr__(self):
        return f"Host(name='{self.name}', hostname='{self.hostname}', port={self.port})"


class InventoryParser:
    """Parser for Ansible inventory files."""

    def __init__(self, inventory_path: str):
        self.inventory_path = Path(inventory_path)
        if not self.inventory_path.exists():
            raise FileNotFoundError(f"Inventory file not found: {inventory_path}")

    def parse(self) -> List[Host]:
        """Parse inventory file and return list of hosts."""
        if self.inventory_path.suffix.lower() in [".yml", ".yaml"]:
            return self._parse_yaml()
        if self.inventory_path.suffix.lower() in [
            ".ini",
            ".cfg",
            "",
        ] or self.inventory_path.name in ["hosts", "inventory"]:
            return self._parse_ini()
        # Try YAML first, then INI
        try:
            return self._parse_yaml()
        except Exception:
            return self._parse_ini()

    def _parse_yaml(self) -> List[Host]:
        """Parse YAML format inventory."""
        try:
            with open(self.inventory_path, "r", encoding="utf-8") as f:
                inventory = yaml.safe_load(f)
        except Exception as e:
            raise ValueError(f"Error parsing YAML inventory: {e}") from e

        hosts = []

        if not inventory:
            return hosts

        # Handle both modern and legacy formats
        if "all" in inventory:
            # Modern format: inventory has 'all' key
            all_section = inventory["all"]
            if "hosts" in all_section:
                hosts.extend(self._parse_yaml_hosts(all_section["hosts"]))
            if "children" in all_section:
                for _group_name, group_data in all_section["children"].items():
                    if "hosts" in group_data:
                        hosts.extend(self._parse_yaml_hosts(group_data["hosts"]))
        else:
            # Legacy format: groups are top-level keys
            for group_name, group_data in inventory.items():
                if isinstance(group_data, dict) and "hosts" in group_data:
                    hosts.extend(self._parse_yaml_hosts(group_data["hosts"]))

        return hosts

    def _parse_yaml_hosts(self, hosts_data: Dict[str, Any]) -> List[Host]:
        """Parse hosts section from YAML inventory."""
        hosts = []

        for host_name, host_vars in hosts_data.items():
            if host_vars is None:
                host_vars = {}

            hostname = host_vars.get("ansible_host", host_name)
            port = host_vars.get("ansible_port", 22)
            username = host_vars.get("ansible_user", host_vars.get("ansible_ssh_user"))

            host = Host(
                name=host_name,
                hostname=hostname,
                port=port,
                username=username,
                variables=host_vars,
            )
            hosts.append(host)

        return hosts

    def _parse_ini(self) -> List[Host]:
        """Parse INI format inventory."""
        hosts = []

        try:
            with open(self.inventory_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            raise ValueError(f"Error reading INI inventory: {e}") from e

        # Split into lines and process
        lines = content.split("\n")
        current_group = None

        for line in lines:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            # Group header
            if line.startswith("[") and line.endswith("]"):
                current_group = line[1:-1]
                continue

            # Skip group variables sections
            if current_group and ":vars" in current_group:
                continue

            # Parse host line
            host = self._parse_ini_host_line(line)
            if host:
                hosts.append(host)

        return hosts

    def _parse_ini_host_line(self, line: str) -> Optional[Host]:
        """Parse a single host line from INI format."""
        # Handle host with variables: hostname key=value key2=value2
        parts = line.split()
        if not parts:
            return None

        host_part = parts[0]
        variables = {}

        # Parse variables
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                variables[key] = value

        # Parse hostname and port
        if ":" in host_part:
            hostname, port_str = host_part.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                hostname = host_part
                port = 22
        else:
            hostname = host_part
            port = 22

        # Extract common ansible variables
        ansible_host = variables.get("ansible_host", hostname)
        ansible_port = int(variables.get("ansible_port", port))
        ansible_user = variables.get("ansible_user", variables.get("ansible_ssh_user"))

        return Host(
            name=hostname,
            hostname=ansible_host,
            port=ansible_port,
            username=ansible_user,
            variables=variables,
        )


def create_example_inventory(path: str = "inventory.yml.example") -> None:
    """Create an example inventory file."""
    example_inventory = {
        "all": {
            "hosts": {
                "web1": {"ansible_host": "192.168.1.10", "ansible_user": "ubuntu"},
                "web2": {"ansible_host": "192.168.1.11", "ansible_user": "ubuntu"},
                "db1": {
                    "ansible_host": "192.168.1.20",
                    "ansible_user": "root",
                    "ansible_port": 2222,
                },
            },
            "children": {
                "webservers": {"hosts": {"web1": {}, "web2": {}}},
                "databases": {"hosts": {"db1": {}}},
            },
        }
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(example_inventory, f, default_flow_style=False, indent=2)
