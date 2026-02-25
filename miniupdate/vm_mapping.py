"""
VM mapping for miniupdate.

Maps Ansible inventory hosts to Proxmox VM IDs and nodes.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional, NamedTuple

import toml

logger = logging.getLogger(__name__)


class VMMapping(NamedTuple):
    """VM mapping information."""

    node: str
    vmid: int
    host_name: str
    max_snapshots: Optional[int] = None
    endpoint: Optional[str] = None  # Optional per-node Proxmox endpoint
    username: Optional[str] = None  # Optional per-node credentials
    password: Optional[str] = None  # Optional per-node credentials


class VMMapper:
    """Manages mapping between Ansible hosts and Proxmox VMs."""

    def __init__(self, mapping_path: Optional[str] = None):
        """
        Initialize VM mapper.

        Args:
            mapping_path: Path to VM mapping configuration file
        """
        self.mapping_path = self._find_mapping_path(mapping_path)
        self.mappings = self._load_mappings()

    def _find_mapping_path(self, mapping_path: Optional[str]) -> Path:
        """Find VM mapping configuration file path."""
        if mapping_path:
            return Path(mapping_path)

        # Check current directory
        current_mapping = Path("vm_mapping.toml")
        if current_mapping.exists():
            return current_mapping

        # Check home directory
        home_mapping = Path.home() / ".miniupdate" / "vm_mapping.toml"
        if home_mapping.exists():
            return home_mapping

        # Default to current directory (may not exist yet)
        return current_mapping

    def _load_mappings(self) -> Dict[str, VMMapping]:
        """Load VM mappings from configuration file."""
        mappings = {}

        if not self.mapping_path.exists():
            logger.warning(
                "VM mapping file not found at %s. VM operations will be disabled.",
                self.mapping_path,
            )
            return mappings

        try:
            with open(self.mapping_path, "r", encoding="utf-8") as f:
                config = toml.load(f)

            vms = config.get("vms", {})
            for host_name, vm_info in vms.items():
                if not isinstance(vm_info, dict):
                    logger.warning("Invalid VM mapping for %s: %s", host_name, vm_info)
                    continue

                node = vm_info.get("node")
                vmid = vm_info.get("vmid")
                max_snapshots = vm_info.get("max_snapshots")
                endpoint = vm_info.get("endpoint")  # Optional per-node endpoint
                username = vm_info.get("username")  # Optional per-node credentials
                password = vm_info.get("password")  # Optional per-node credentials

                if not node or not vmid:
                    logger.warning(
                        "Incomplete VM mapping for %s: missing node (%s) or vmid (%s)",
                        host_name,
                        node,
                        vmid,
                    )
                    continue

                try:
                    vmid = int(vmid)
                except ValueError:
                    logger.warning("Invalid vmid for %s: %s", host_name, vmid)
                    continue

                # Validate max_snapshots if provided
                if max_snapshots is not None:
                    try:
                        max_snapshots = int(max_snapshots)
                        if max_snapshots < 0:
                            logger.warning(
                                "Invalid max_snapshots for %s: must be >= 0", host_name
                            )
                            max_snapshots = None
                    except ValueError:
                        logger.warning(
                            "Invalid max_snapshots for %s: %s", host_name, max_snapshots
                        )
                        max_snapshots = None

                mappings[host_name] = VMMapping(
                    node=node,
                    vmid=vmid,
                    host_name=host_name,
                    max_snapshots=max_snapshots,
                    endpoint=endpoint,
                    username=username,
                    password=password,
                )

            logger.info("Loaded VM mappings for %s hosts", len(mappings))

            # logger.info(f"All loaded mappings: \n{str(mappings)}")
            # input("Press enter")

            return mappings

        except Exception as e:
            logger.error("Failed to load VM mappings from %s: %s", self.mapping_path, e)
            sys.exit(1)

    def get_vm_info(self, host_name: str) -> Optional[VMMapping]:
        """Get VM mapping for a host."""
        return self.mappings.get(host_name)

    def has_vm_mapping(self, host_name: str) -> bool:
        """Check if host has VM mapping."""
        return host_name in self.mappings

    def get_all_mappings(self) -> Dict[str, VMMapping]:
        """Get all VM mappings."""
        return self.mappings.copy()


def create_example_vm_mapping(path: str = "vm_mapping.toml.example") -> None:
    """Create an example VM mapping configuration file."""
    example_config = {
        # VM mappings - maps Ansible inventory host names to Proxmox VM IDs
        "vms": {
            "web1": {"node": "pve-node1", "vmid": 100},
            "web2": {
                "node": "pve-node1",
                "vmid": 101,
                "max_snapshots": 2,  # Optional: limit to 2 snapshots for capacity-limited storage
            },
            "db1": {"node": "pve-node2", "vmid": 200},
        }
    }

    with open(path, "w", encoding="utf-8") as f:
        # Write with comments
        f.write("# VM Mapping Configuration for miniupdate\n")
        f.write("# Maps Ansible inventory host names to Proxmox VM IDs and nodes\n")
        f.write(
            "# Optional: Set max_snapshots per VM to limit snapshot count "
            "for capacity-limited storage\n\n"
        )

        toml.dump(example_config, f)
