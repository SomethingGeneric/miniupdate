"""
Main CLI application for miniupdate.

Orchestrates the process of checking updates across hosts and sending email reports.
"""

import click
import logging
import sys
from pathlib import Path
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import Config, create_example_config
from .inventory import InventoryParser, create_example_inventory
from .ssh_manager import SSHManager
from .os_detector import OSDetector
from .package_managers import get_package_manager
from .email_sender import EmailSender, UpdateReport


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('miniupdate.log')
    ]
)
logger = logging.getLogger(__name__)


def process_host(host, ssh_config, timeout=120):
    """Process a single host - detect OS and check for updates."""
    logger.info(f"Processing host: {host.name}")
    
    try:
        with SSHManager(ssh_config) as ssh_manager:
            # Connect to host
            connection = ssh_manager.connect_to_host(host, timeout=timeout)
            if not connection:
                return UpdateReport(host, None, [], error="Failed to connect via SSH")
            
            # Detect OS
            os_detector = OSDetector(connection)
            os_info = os_detector.detect_os()
            
            if not os_info:
                return UpdateReport(host, None, [], error="Failed to detect operating system")
            
            # Get package manager
            package_manager = get_package_manager(connection, os_info)
            if not package_manager:
                return UpdateReport(host, os_info, [], 
                                  error=f"Unsupported package manager: {os_info.package_manager}")
            
            # Refresh package cache
            logger.info(f"Refreshing package cache on {host.name}")
            if not package_manager.refresh_cache():
                logger.warning(f"Failed to refresh package cache on {host.name}")
            
            # Check for updates
            logger.info(f"Checking for updates on {host.name}")
            updates = package_manager.check_updates()
            
            logger.info(f"Found {len(updates)} updates on {host.name} "
                       f"({sum(1 for u in updates if u.security)} security)")
            
            return UpdateReport(host, os_info, updates)
            
    except Exception as e:
        logger.error(f"Error processing host {host.name}: {e}")
        return UpdateReport(host, None, [], error=str(e))


@click.group()
@click.option('--config', '-c', help='Configuration file path')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, config, verbose):
    """miniupdate - Minimal patch check script for virtual guests."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config


@cli.command()
@click.option('--parallel', '-p', default=5, help='Number of parallel connections')
@click.option('--timeout', '-t', default=120, help='SSH timeout in seconds')
@click.option('--dry-run', is_flag=True, help='Show what would be done without sending email')
@click.pass_context
def check(ctx, parallel, timeout, dry_run):
    """Check for updates on all hosts and send email report."""
    try:
        # Load configuration
        config = Config(ctx.obj.get('config_path'))
        logger.info(f"Loaded configuration from {config.config_path}")
        
        # Parse inventory
        inventory_parser = InventoryParser(config.inventory_path)
        hosts = inventory_parser.parse()
        logger.info(f"Loaded {len(hosts)} hosts from inventory")
        
        if not hosts:
            logger.error("No hosts found in inventory")
            return 1
        
        # Process hosts in parallel
        logger.info(f"Processing {len(hosts)} hosts with {parallel} parallel connections")
        reports = []
        
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            # Submit all host processing tasks
            future_to_host = {
                executor.submit(process_host, host, config.ssh_config, timeout): host
                for host in hosts
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_host):
                host = future_to_host[future]
                try:
                    report = future.result()
                    reports.append(report)
                    
                    # Log summary for this host
                    if report.error:
                        logger.warning(f"{host.name}: ERROR - {report.error}")
                    elif report.has_security_updates:
                        logger.warning(f"{host.name}: {len(report.security_updates)} SECURITY updates, "
                                     f"{len(report.regular_updates)} regular updates")
                    elif report.has_updates:
                        logger.info(f"{host.name}: {len(report.updates)} updates available")
                    else:
                        logger.info(f"{host.name}: No updates needed")
                        
                except Exception as e:
                    logger.error(f"Host {host.name} processing failed: {e}")
                    reports.append(UpdateReport(host, None, [], error=str(e)))
        
        # Generate summary
        total_hosts = len(reports)
        hosts_with_updates = sum(1 for r in reports if r.has_updates)
        hosts_with_security = sum(1 for r in reports if r.has_security_updates)
        hosts_with_errors = sum(1 for r in reports if r.error)
        
        logger.info(f"\nSUMMARY:")
        logger.info(f"Total hosts checked: {total_hosts}")
        logger.info(f"Hosts with updates: {hosts_with_updates}")
        logger.info(f"Hosts with security updates: {hosts_with_security}")
        logger.info(f"Hosts with errors: {hosts_with_errors}")
        
        # Send email report
        if not dry_run:
            logger.info("Sending email report...")
            email_sender = EmailSender(config.smtp_config)
            
            if email_sender.send_update_report(reports):
                logger.info("Email report sent successfully")
            else:
                logger.error("Failed to send email report")
                return 1
        else:
            logger.info("Dry run - email report not sent")
        
        return 0
        
    except Exception as e:
        logger.error(f"Application error: {e}")
        return 1


@cli.command()
@click.option('--config-file', default='config.toml.example', help='Example config file name')
@click.option('--inventory-file', default='inventory.yml.example', help='Example inventory file name')
def init(config_file, inventory_file):
    """Create example configuration and inventory files."""
    try:
        # Create example config
        if Path(config_file).exists():
            if not click.confirm(f"{config_file} already exists. Overwrite?"):
                logger.info(f"Skipped creating {config_file}")
            else:
                create_example_config(config_file)
                logger.info(f"Created example configuration: {config_file}")
        else:
            create_example_config(config_file)
            logger.info(f"Created example configuration: {config_file}")
        
        # Create example inventory
        if Path(inventory_file).exists():
            if not click.confirm(f"{inventory_file} already exists. Overwrite?"):
                logger.info(f"Skipped creating {inventory_file}")
            else:
                create_example_inventory(inventory_file)
                logger.info(f"Created example inventory: {inventory_file}")
        else:
            create_example_inventory(inventory_file)
            logger.info(f"Created example inventory: {inventory_file}")
        
        logger.info("\nNext steps:")
        logger.info(f"1. Copy {config_file} to config.toml and edit with your settings")
        logger.info(f"2. Copy {inventory_file} to inventory.yml and add your hosts")
        logger.info("3. Run 'miniupdate check --dry-run' to test")
        logger.info("4. Run 'miniupdate check' to check updates and send email")
        
    except Exception as e:
        logger.error(f"Failed to create example files: {e}")
        return 1


@cli.command()
@click.pass_context
def test_config(ctx):
    """Test configuration file and connectivity."""
    try:
        config = Config(ctx.obj.get('config_path'))
        logger.info(f"✓ Configuration loaded from {config.config_path}")
        
        # Test SMTP config
        smtp_config = config.smtp_config
        logger.info(f"✓ SMTP configuration loaded")
        logger.info(f"  Server: {smtp_config['smtp_server']}:{smtp_config['smtp_port']}")
        logger.info(f"  From: {smtp_config['from_email']}")
        logger.info(f"  To: {smtp_config['to_email']}")
        
        # Test inventory
        inventory_parser = InventoryParser(config.inventory_path)
        hosts = inventory_parser.parse()
        logger.info(f"✓ Inventory loaded: {len(hosts)} hosts")
        
        for host in hosts[:5]:  # Show first 5 hosts
            logger.info(f"  - {host.name} ({host.hostname}:{host.port})")
        if len(hosts) > 5:
            logger.info(f"  ... and {len(hosts) - 5} more")
        
        logger.info("Configuration appears valid!")
        
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        return 1


def main():
    """Main entry point."""
    try:
        cli()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()