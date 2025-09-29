"""
Update automation for miniupdate with Proxmox integration.

Handles the complete workflow: snapshot -> update -> reboot -> verify -> cleanup/revert.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, NamedTuple
from enum import Enum

from .config import Config
from .inventory import Host
from .ssh_manager import SSHManager
from .os_detector import OSDetector
from .package_managers import get_package_manager, PackageUpdate
from .proxmox_client import ProxmoxClient, ProxmoxAPIError
from .vm_mapping import VMMapper, VMMapping
from .host_checker import HostChecker
from .email_sender import UpdateReport

logger = logging.getLogger(__name__)


class UpdateResult(Enum):
    """Update operation results."""
    SUCCESS = "success"
    OPT_OUT = "opt_out"
    NO_UPDATES = "no_updates"
    FAILED_SNAPSHOT = "failed_snapshot"
    FAILED_UPDATES = "failed_updates"  
    FAILED_REBOOT = "failed_reboot"
    FAILED_AVAILABILITY = "failed_availability"
    REVERTED = "reverted"
    REVERT_FAILED = "revert_failed"


class AutomatedUpdateReport(NamedTuple):
    """Report for automated update process."""
    host: Host
    vm_mapping: Optional[VMMapping]
    update_report: UpdateReport
    result: UpdateResult
    snapshot_name: Optional[str]
    error_details: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]


class UpdateAutomator:
    """Handles automated update workflow with Proxmox integration."""
    
    def __init__(self, config: Config):
        """
        Initialize update automator.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.proxmox_config = config.proxmox_config
        self.update_config = config.update_config
        self.ssh_config = config.ssh_config
        
        # Initialize components
        self.proxmox_client = None
        self.vm_mapper = None
        self.host_checker = HostChecker(self.ssh_config)
        
        # Setup Proxmox client if configured
        if self.proxmox_config:
            try:
                self.proxmox_client = ProxmoxClient(
                    endpoint=self.proxmox_config['endpoint'],
                    username=self.proxmox_config['username'],
                    password=self.proxmox_config['password'],
                    verify_ssl=self.proxmox_config.get('verify_ssl', True),
                    timeout=self.proxmox_config.get('timeout', 30)
                )
                
                # Setup VM mapper
                vm_mapping_file = self.proxmox_config.get('vm_mapping_file')
                self.vm_mapper = VMMapper(vm_mapping_file)
                
                logger.info("Proxmox integration enabled")
            except Exception as e:
                logger.error(f"Failed to initialize Proxmox client: {e}")
                self.proxmox_client = None
        else:
            logger.info("Proxmox integration disabled - no configuration provided")
    
    def process_host_automated_update(self, host: Host, timeout: int = 120) -> AutomatedUpdateReport:
        """
        Process automated updates for a single host.
        
        Args:
            host: Host to process
            timeout: SSH timeout for operations
            
        Returns:
            AutomatedUpdateReport with results
        """
        start_time = datetime.now()
        snapshot_name = None
        vm_mapping = None
        
        logger.info(f"Starting automated update process for {host.name}")
        
        try:
            # Get VM mapping if available
            if self.vm_mapper:
                vm_mapping = self.vm_mapper.get_vm_info(host.name)
                if not vm_mapping:
                    logger.warning(f"No VM mapping found for {host.name} - snapshots disabled")
            
            # Connect to host and check updates
            with SSHManager(self.ssh_config) as ssh_manager:
                connection = ssh_manager.connect_to_host(host, timeout=timeout)
                if not connection:
                    return AutomatedUpdateReport(
                        host=host,
                        vm_mapping=vm_mapping,
                        update_report=UpdateReport(host, None, [], error="Failed to connect via SSH"),
                        result=UpdateResult.FAILED_UPDATES,
                        snapshot_name=None,
                        error_details="SSH connection failed",
                        start_time=start_time,
                        end_time=datetime.now()
                    )
                
                # Detect OS and get package manager
                os_detector = OSDetector(connection)
                os_info = os_detector.detect_os()
                
                if not os_info:
                    return AutomatedUpdateReport(
                        host=host,
                        vm_mapping=vm_mapping,
                        update_report=UpdateReport(host, None, [], error="Failed to detect OS"),
                        result=UpdateResult.FAILED_UPDATES,
                        snapshot_name=None,
                        error_details="OS detection failed",
                        start_time=start_time,
                        end_time=datetime.now()
                    )
                
                package_manager = get_package_manager(connection, os_info)
                if not package_manager:
                    return AutomatedUpdateReport(
                        host=host,
                        vm_mapping=vm_mapping,
                        update_report=UpdateReport(host, os_info, [], 
                                                 error=f"Unsupported package manager: {os_info.package_manager}"),
                        result=UpdateResult.FAILED_UPDATES,
                        snapshot_name=None,
                        error_details=f"Unsupported package manager: {os_info.package_manager}",
                        start_time=start_time,
                        end_time=datetime.now()
                    )
                
                # Refresh cache and check for updates
                logger.info(f"Checking for updates on {host.name}")
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    if package_manager.refresh_cache():
                        break
                    logger.warning(f"Failed to refresh package cache on {host.name} (attempt {attempt}/{max_retries})")
                    if attempt < max_retries:
                        import time
                        time.sleep(5)
                else:
                    error_details = f"Failed to refresh package cache on {host.name} after {max_retries} attempts"
                    logger.error(error_details)
                    return AutomatedUpdateReport(
                        host=host,
                        vm_mapping=vm_mapping,
                        update_report=UpdateReport(host, os_info, [], error=error_details),
                        result=UpdateResult.FAILED_UPDATES,
                        snapshot_name=None,
                        error_details=error_details,
                        start_time=start_time,
                        end_time=datetime.now()
                    )
                updates = package_manager.check_updates()
                update_report = UpdateReport(host, os_info, updates)
                
                # Check if this host is in the opt-out list
                opt_out_hosts = self.config.update_opt_out_hosts
                is_opt_out_host = host.name in opt_out_hosts
                
                # If host is in opt-out list or update application is disabled, just return check results
                if is_opt_out_host or not self.update_config.get('apply_updates', False):
                    if is_opt_out_host:
                        logger.info(f"Host {host.name} is in opt-out list - only checking updates")
                        result = UpdateResult.OPT_OUT
                    else:
                        logger.info(f"Update application disabled - only checking updates on {host.name}")
                        result = UpdateResult.OPT_OUT  # Treat global disable same as opt-out
                    return AutomatedUpdateReport(
                        host=host,
                        vm_mapping=vm_mapping,
                        update_report=update_report,
                        result=result,
                        snapshot_name=None,
                        error_details=None,
                        start_time=start_time,
                        end_time=datetime.now()
                    )
                
                # If no updates available, nothing to do
                if not updates:
                    logger.info(f"No updates available for {host.name}")
                    return AutomatedUpdateReport(
                        host=host,
                        vm_mapping=vm_mapping,
                        update_report=update_report,
                        result=UpdateResult.NO_UPDATES,
                        snapshot_name=None,
                        error_details=None,
                        start_time=start_time,
                        end_time=datetime.now()
                    )
                
                logger.info(f"Found {len(updates)} updates for {host.name} "
                           f"({sum(1 for u in updates if u.security)} security)")
                
                # Create snapshot if Proxmox is configured and VM mapping exists
                if self.proxmox_client and vm_mapping:
                    snapshot_name = self._create_snapshot(vm_mapping, start_time)
                    if not snapshot_name:
                        return AutomatedUpdateReport(
                            host=host,
                            vm_mapping=vm_mapping,
                            update_report=update_report,
                            result=UpdateResult.FAILED_SNAPSHOT,
                            snapshot_name=None,
                            error_details="Failed to create VM snapshot",
                            start_time=start_time,
                            end_time=datetime.now()
                        )
                
                # Apply updates
                logger.info(f"Applying {len(updates)} updates on {host.name}")
                if not package_manager.apply_updates():
                    error_details = "Failed to apply package updates"
                    
                    # Revert snapshot if available
                    if snapshot_name and self.proxmox_client and vm_mapping:
                        if self._revert_snapshot(vm_mapping, snapshot_name):
                            result = UpdateResult.REVERTED
                            error_details += " - reverted to snapshot"
                        else:
                            result = UpdateResult.REVERT_FAILED
                            error_details += " - CRITICAL: snapshot revert also failed"
                    else:
                        result = UpdateResult.FAILED_UPDATES
                    
                    return AutomatedUpdateReport(
                        host=host,
                        vm_mapping=vm_mapping,
                        update_report=update_report,
                        result=result,
                        snapshot_name=snapshot_name,
                        error_details=error_details,
                        start_time=start_time,
                        end_time=datetime.now()
                    )
                
                logger.info(f"Successfully applied updates on {host.name}")
                
                # Reboot if configured (only for hosts that actually received updates)
                if self.update_config.get('reboot_after_updates', False):
                    logger.info(f"Reboot after updates is enabled - proceeding with reboot for {host.name}")
                    reboot_result = self._handle_reboot_and_verification(
                        host, vm_mapping, snapshot_name, start_time
                    )
                    if reboot_result:
                        return reboot_result
                else:
                    logger.info(f"Reboot after updates is disabled - skipping reboot for {host.name}")
                
                # Clean up snapshot if successful and configured
                if (snapshot_name and self.proxmox_client and vm_mapping and 
                    self.update_config.get('cleanup_snapshots', False)):
                    self._cleanup_old_snapshots(vm_mapping)
                
                return AutomatedUpdateReport(
                    host=host,
                    vm_mapping=vm_mapping,
                    update_report=update_report,
                    result=UpdateResult.SUCCESS,
                    snapshot_name=snapshot_name,
                    error_details=None,
                    start_time=start_time,
                    end_time=datetime.now()
                )
                
        except Exception as e:
            logger.error(f"Unexpected error processing {host.name}: {e}")
            return AutomatedUpdateReport(
                host=host,
                vm_mapping=vm_mapping,
                update_report=UpdateReport(host, None, [], error=str(e)),
                result=UpdateResult.FAILED_UPDATES,
                snapshot_name=snapshot_name,
                error_details=f"Unexpected error: {e}",
                start_time=start_time,
                end_time=datetime.now()
            )
    
    def _create_snapshot(self, vm_mapping: VMMapping, start_time: datetime) -> Optional[str]:
        """Create VM snapshot before updates."""
        prefix = self.update_config.get('snapshot_name_prefix', 'pre-update')
        timestamp = start_time.strftime('%Y%m%d-%H%M%S')
        snapshot_name = f"{prefix}-{timestamp}"
        
        try:
            if not self.proxmox_client.authenticate():
                logger.error("Failed to authenticate to Proxmox")
                return None
            
            response = self.proxmox_client.create_snapshot(
                vm_mapping.node,
                vm_mapping.vmid,
                snapshot_name,
                f"Pre-update snapshot created by miniupdate at {start_time}",
                include_ram=False  # Exclude RAM for faster, more reliable snapshots
            )
            
            # Wait for snapshot task to complete if UPID is returned
            if 'data' in response and isinstance(response['data'], str):
                upid = response['data']
                if self.proxmox_client.wait_for_task(vm_mapping.node, upid, timeout=300):
                    logger.info(f"Snapshot {snapshot_name} created successfully for VM {vm_mapping.vmid}")
                    return snapshot_name
                else:
                    logger.error(f"Snapshot creation task failed for VM {vm_mapping.vmid}")
                    return None
            else:
                # Some versions might complete immediately
                logger.info(f"Snapshot {snapshot_name} created for VM {vm_mapping.vmid}")
                return snapshot_name
                
        except Exception as e:
            logger.error(f"Failed to create snapshot for VM {vm_mapping.vmid}: {e}")
            return None
    
    def _revert_snapshot(self, vm_mapping: VMMapping, snapshot_name: str) -> bool:
        """Revert VM to snapshot."""
        try:
            logger.warning(f"Reverting VM {vm_mapping.vmid} to snapshot {snapshot_name}")
            
            response = self.proxmox_client.rollback_snapshot(
                vm_mapping.node,
                vm_mapping.vmid,
                snapshot_name
            )
            
            # Wait for rollback task to complete if UPID is returned
            if 'data' in response and isinstance(response['data'], str):
                upid = response['data']
                if self.proxmox_client.wait_for_task(vm_mapping.node, upid, timeout=300):
                    logger.warning(f"VM {vm_mapping.vmid} reverted to snapshot {snapshot_name}")
                    return True
                else:
                    logger.error(f"Snapshot rollback task failed for VM {vm_mapping.vmid}")
                    return False
            else:
                logger.warning(f"VM {vm_mapping.vmid} reverted to snapshot {snapshot_name}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to revert VM {vm_mapping.vmid} to snapshot {snapshot_name}: {e}")
            return False
    
    def _handle_reboot_and_verification(self, host: Host, vm_mapping: Optional[VMMapping], 
                                      snapshot_name: Optional[str], start_time: datetime) -> Optional[AutomatedUpdateReport]:
        """Handle host reboot and availability verification."""
        reboot_timeout = self.update_config.get('reboot_timeout', 300)
        ping_timeout = self.update_config.get('ping_timeout', 120)
        
        # Reboot the host
        logger.info(f"Rebooting {host.name}")
        if not self.host_checker.reboot_host_via_ssh(host, timeout=30):
            error_details = "Failed to send reboot command"
            
            # Revert snapshot if available
            if snapshot_name and self.proxmox_client and vm_mapping:
                if self._revert_snapshot(vm_mapping, snapshot_name):
                    result = UpdateResult.REVERTED
                    error_details += " - reverted to snapshot"
                else:
                    result = UpdateResult.REVERT_FAILED
                    error_details += " - CRITICAL: snapshot revert also failed"
            else:
                result = UpdateResult.FAILED_REBOOT
            
            return AutomatedUpdateReport(
                host=host,
                vm_mapping=vm_mapping,
                update_report=UpdateReport(host, None, []),
                result=result,
                snapshot_name=snapshot_name,
                error_details=error_details,
                start_time=start_time,
                end_time=datetime.now()
            )
        
        # Wait for system to go down
        logger.info(f"Waiting for {host.name} to reboot...")
        time.sleep(10)  # Give time for reboot to initiate
        
        # Wait for system to come back up
        if not self.host_checker.wait_for_host_availability(
            host, max_wait_time=ping_timeout, check_interval=5, use_ssh=True
        ):
            error_details = f"Host did not become available within {ping_timeout} seconds after reboot"
            
            # Revert snapshot if available
            if snapshot_name and self.proxmox_client and vm_mapping:
                if self._revert_snapshot(vm_mapping, snapshot_name):
                    result = UpdateResult.REVERTED
                    error_details += " - reverted to snapshot"
                else:
                    result = UpdateResult.REVERT_FAILED
                    error_details += " - CRITICAL: snapshot revert also failed"
            else:
                result = UpdateResult.FAILED_AVAILABILITY
            
            return AutomatedUpdateReport(
                host=host,
                vm_mapping=vm_mapping,
                update_report=UpdateReport(host, None, []),
                result=result,
                snapshot_name=snapshot_name,
                error_details=error_details,
                start_time=start_time,
                end_time=datetime.now()
            )
        
        logger.info(f"Host {host.name} is back online after reboot")
        return None  # Success - no error report needed
    
    def _cleanup_old_snapshots(self, vm_mapping: VMMapping):
        """Clean up old automated snapshots."""
        try:
            retention_days = self.update_config.get('snapshot_retention_days', 7)
            prefix = self.update_config.get('snapshot_name_prefix', 'pre-update')
            
            snapshots = self.proxmox_client.list_snapshots(vm_mapping.node, vm_mapping.vmid)
            cutoff_time = datetime.now() - timedelta(days=retention_days)
            
            for snapshot in snapshots:
                snap_name = snapshot.get('name', '')
                if not snap_name.startswith(prefix):
                    continue  # Skip non-automated snapshots
                
                # Extract timestamp from snapshot name (format: prefix-YYYYMMDD-HHMMSS)
                try:
                    timestamp_str = snap_name[len(prefix) + 1:]  # Remove prefix and dash
                    snap_time = datetime.strptime(timestamp_str, '%Y%m%d-%H%M%S')
                    
                    if snap_time < cutoff_time:
                        logger.info(f"Deleting old snapshot {snap_name} for VM {vm_mapping.vmid}")
                        self.proxmox_client.delete_snapshot(vm_mapping.node, vm_mapping.vmid, snap_name)
                        
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not parse snapshot timestamp for {snap_name}: {e}")
                    continue
                    
        except Exception as e:
            logger.warning(f"Failed to cleanup old snapshots for VM {vm_mapping.vmid}: {e}")