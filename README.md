# miniupdate

Minimal patch check script for virtual guests

A Python tool that SSHs to an inventory of hosts (Ansible format), identifies the OS, uses appropriate package managers to check for updates, and emails the results to sysadmins via SMTP.

## Features

- **Multi-OS Support**: Automatically detects OS and uses appropriate package manager
  - Ubuntu/Debian (apt)
  - Linux Mint (apt)
  - CentOS/RHEL (yum/dnf) 
  - Fedora (dnf)
  - openSUSE (zypper)
  - Arch Linux (pacman)
  - Alpine Linux (apk)
  - FreeBSD (pkg)
  - OpenBSD (pkg_add)
  - macOS (brew)

- **Proxmox VE Integration**: VM snapshot management for safe automated updates
  - Pre-update VM snapshots via Proxmox API
  - Automatic rollback on update failures
  - Configurable snapshot retention and cleanup

- **Automated Update Workflow**: Complete hands-off update process
  - System package updates with automatic reboot
  - Host availability verification after reboot
  - Intelligent rollback to snapshots on failures
  - Priority-based email alerts for critical issues

- **Ansible Integration**: Reads standard Ansible inventory files (YAML or INI format)
- **Security Focus**: Identifies and highlights security updates
- **Parallel Processing**: Checks multiple hosts simultaneously for faster execution
- **Email Reports**: Sends comprehensive HTML and text email reports via SMTP
- **Error Handling**: Graceful handling of connection failures and unsupported systems
- **Configurable**: TOML-based configuration for flexibility

## Installation

```bash
# Clone the repository
git clone https://github.com/SomethingGeneric/miniupdate.git
cd miniupdate

# Install dependencies
pip install -r requirements.txt

# Or install in development mode
pip install -e .
```

## Quick Start

1. **Create example configuration files:**
   ```bash
   python -m miniupdate.main init
   ```

2. **Configure your settings:**
   ```bash
   cp config.toml.example config.toml
   # Edit config.toml with your SMTP and SSH settings
   
   cp inventory.yml.example inventory.yml
   # Edit inventory.yml with your hosts
   ```

3. **Test configuration:**
   ```bash
   python -m miniupdate.main test-config
   ```

4. **Run a dry-run check:**
   ```bash
   python -m miniupdate.main check --dry-run
   ```

5. **Run the actual check and send email:**
   ```bash
   python -m miniupdate.main check
   ```

## Configuration

miniupdate supports flexible configuration management with multiple config file locations:

1. **Command line**: `python -m miniupdate.main -c /path/to/config.toml`
2. **Current directory**: `./config.toml`
3. **Global user config**: `~/.miniupdate/config.toml`

### Opt-Out Hosts Feature

miniupdate supports excluding specific hosts from automatic updates while still checking for available updates. This is useful for critical infrastructure hosts like Proxmox hypervisors that require manual update procedures.

#### Configuration

Add hosts to the opt-out list in your `config.toml`:

```toml
[updates]
apply_updates = true
opt_out_hosts = ["pve-host1", "pve-host2", "critical-db-server"]
```

#### Behavior

- **Check Command**: Opt-out hosts are checked for updates and included in reports, but marked as check-only
- **Update Command**: Opt-out hosts are checked for updates but no snapshots, updates, or reboots are performed
- **Email Reports**: Opt-out hosts appear in reports with their available updates listed
- **Logging**: Clear indicators when processing opt-out hosts

#### Use Cases

- **Proxmox Hypervisors**: Check for updates but handle them manually through the Proxmox web interface
- **Critical Servers**: Review updates before applying during maintenance windows
- **Legacy Systems**: Monitor update availability without risking automated changes

### config.toml

```toml
[email]
smtp_server = "smtp.gmail.com"
smtp_port = 587
use_tls = true
username = "your-email@example.com"
password = "your-app-password"
from_email = "your-email@example.com"  # Must be a valid email address for strict SMTP servers
to_email = ["sysadmin@example.com", "admin@example.com"]

[inventory]
# Local inventory file (relative to config file)
path = "inventory.yml"

# Alternative inventory path examples:
# Absolute path: path = "/etc/ansible/inventory.yml"
# Environment variable: path = "$ANSIBLE_INVENTORY_PATH/inventory.yml"
# External git repo: path = "~/git/infrastructure/ansible/inventory.yml"
# Corporate shared: path = "/shared/ansible-configs/production/inventory.yml"

format = "ansible"

[ssh]
timeout = 30
port = 22

[settings]
parallel_connections = 5
log_level = "INFO"
check_timeout = 120

[proxmox]
endpoint = "https://pve.example.com:8006"
username = "root@pam"
password = "your-proxmox-password"
verify_ssl = true
timeout = 30
vm_mapping_file = "vm_mapping.toml"

[updates]
apply_updates = true
reboot_after_updates = true
reboot_timeout = 300         # Time to wait for reboot command (5 minutes)
ping_timeout = 120          # Time to wait for host availability (2 minutes)
ping_interval = 5           # Check every 5 seconds
snapshot_name_prefix = "pre-update"
cleanup_snapshots = true
snapshot_retention_days = 7
# List of hosts to exclude from automatic updates (check-only mode)
opt_out_hosts = ["pve-host1", "pve-host2"]  # Hosts that will only be checked, not updated
```

### vm_mapping.toml

Maps Ansible inventory host names to Proxmox VM IDs and nodes:

```toml
# VM Mapping Configuration for miniupdate
# Maps Ansible inventory host names to Proxmox VM IDs and nodes
# Optional: Set max_snapshots per VM to limit snapshot count for capacity-limited storage

[vms.web1]
node = "pve-node1"
vmid = 100

[vms.web2] 
node = "pve-node1"
vmid = 101
# Optional: Limit to 2 snapshots for VMs on capacity-limited storage (e.g., small SSDs)
max_snapshots = 2

[vms.db1]
node = "pve-node2"
vmid = 200

# Example: Standalone Proxmox node with dedicated endpoint
# For non-clustered Proxmox nodes, specify per-node connection details
[vms.app1]
node = "bingus"
vmid = 300
# Per-node endpoint for standalone (non-clustered) Proxmox nodes
endpoint = "https://bingus.example.com:8006"
username = "root@pam"              # Optional: defaults to global config
password = "node-specific-password"  # Optional: defaults to global config
```

**Proxmox Cluster vs Standalone Nodes:**

- **Clustered Nodes**: If your Proxmox nodes are in a cluster, you only need the global `endpoint` in `config.toml`. All nodes can be managed through a single API connection.
- **Standalone Nodes**: For independent Proxmox servers (not in a cluster), specify per-node `endpoint`, `username`, and `password` in the VM mapping. This allows managing VMs across multiple isolated Proxmox installations.

**Per-Host Snapshot Quota:**
- Use `max_snapshots` to set a maximum number of automated snapshots per VM
- When set, miniupdate will keep only the N newest snapshots and delete older ones
- Useful for VMs on capacity-limited storage backends (e.g., small SSDs)
- Takes precedence over the default snapshot limit
- **If not set, miniupdate defaults to keeping the 5 newest snapshots** to prevent unbounded growth
- Time-based retention (`snapshot_retention_days`) provides additional cleanup after the count limit

### inventory.yml (Ansible Format)

```yaml
all:
  hosts:
    web1:
      ansible_host: 192.168.1.10
      ansible_user: ubuntu
    web2:
      ansible_host: 192.168.1.11
      ansible_user: ubuntu
    db1:
      ansible_host: 192.168.1.20
      ansible_user: root
      ansible_port: 2222
  children:
    webservers:
      hosts:
        web1: {}
        web2: {}
    databases:
      hosts:
        db1: {}
```

## Using External Git Repositories for Inventory

miniupdate supports using Ansible inventory files from external git repositories, making it perfect for centralized infrastructure management:

### Setup with External Git Repository

1. **Clone your infrastructure repository:**
   ```bash
   git clone https://github.com/yourorg/infrastructure.git ~/git/infrastructure
   ```

2. **Create global config:**
   ```bash
   mkdir -p ~/.miniupdate
   ```

3. **Configure global config (`~/.miniupdate/config.toml`):**
   ```toml
   [email]
   smtp_server = "smtp.company.com"
   # ... your email settings

   [inventory]
   # Point to your external git repository
   path = "~/git/infrastructure/ansible/inventory.yml"
   format = "ansible"
   ```

4. **Update inventory automatically:**
   ```bash
   # Add to cron or CI/CD pipeline
   cd ~/git/infrastructure && git pull
   python -m miniupdate.main check
   ```

### Configuration Path Examples

```toml
[inventory]
# Relative to config file
path = "inventory.yml"

# Absolute path
path = "/etc/ansible/inventory.yml"

# Using environment variables
path = "$ANSIBLE_INVENTORY_PATH/production.yml"

# External git repository
path = "~/git/infrastructure/ansible/inventory.yml"

# Corporate shared filesystem
path = "/shared/ansible-configs/production/inventory.yml"

# Multiple environment support via environment variable
path = "$HOME/git/infrastructure/${ENVIRONMENT}/inventory.yml"
```

## Usage

### Commands

- `init` - Create example configuration, inventory, and VM mapping files
- `check` - Check for updates on all hosts and send email report (read-only)
- `update` - Apply updates with Proxmox snapshot integration (automated updates)
- `test-config` - Test configuration file and connectivity

### Options

- `-c, --config` - Specify configuration file path
- `-v, --verbose` - Enable verbose logging
- `-p, --parallel` - Number of parallel connections (default: 5)
- `-t, --timeout` - SSH timeout in seconds (default: 120)
- `--dry-run` - Show what would be done without applying changes

### Examples

```bash
# Use custom config file
python -m miniupdate.main -c /etc/miniupdate/config.toml check

# Run with verbose logging and custom parallelism
python -m miniupdate.main -v check -p 10

# Test run without sending email or applying updates
python -m miniupdate.main check --dry-run

# Apply automated updates with snapshots
python -m miniupdate.main update

# Test automated update workflow without applying changes
python -m miniupdate.main update --dry-run

# Extended timeout for slow connections
python -m miniupdate.main update -t 300
```

## SSH Authentication

miniupdate supports multiple SSH authentication methods:

1. **SSH Agent** (default, most secure)
2. **SSH Key Files** (specify in config.toml)
3. **Username/Password** (less secure, not recommended)

For best security, use SSH agent or key-based authentication.

## Automated Update Workflow

The `update` command provides a complete automated update workflow with Proxmox integration:

### Update Process
1. **Pre-flight checks**: Connects to hosts, detects OS, checks for available updates
2. **Snapshot creation**: Creates VM snapshots via Proxmox API (if configured)
3. **Update application**: Applies all available system updates
4. **Reboot**: Automatically reboots the system if configured
5. **Availability verification**: Waits for host to come back online with ping/SSH checks
6. **Cleanup or rollback**: Either cleans up old snapshots or reverts on failure

### Safety Features
- **Snapshot rollback**: Automatically reverts VMs to pre-update state on any failure
- **Availability monitoring**: Verifies hosts come back online after reboot
- **Parallel processing**: Updates multiple hosts simultaneously with configurable limits
- **Comprehensive logging**: Detailed logs of all operations and timings
- **Priority email alerts**: 🚨 URGENT notifications for critical failures

### Email Notifications
- **Success**: ✅ Lists successfully applied updates
- **Warnings**: ⚠️ Reports hosts that were reverted to snapshots  
- **Critical**: 🚨 URGENT alerts when snapshot revert fails (requires immediate attention)

### Configuration Options
- `apply_updates`: Enable/disable actual update application (vs. check-only)
- `reboot_after_updates`: Automatically reboot after applying updates
- `ping_timeout`: How long to wait for host availability (default: 2 minutes)
- `snapshot_name_prefix`: Prefix for automated snapshots
- `cleanup_snapshots`: Remove old snapshots after successful updates
- `snapshot_retention_days`: Time-based cleanup for snapshots older than N days
- **Default snapshot limit**: Keeps 5 newest snapshots per VM (override with `max_snapshots` in vm_mapping.toml)

## Email Reports

The tool generates comprehensive email reports with:

- **Summary Statistics**: Total hosts, updates available, security updates
- **Individual Host Details**: OS information, available updates, errors
- **Security Highlighting**: Security updates are clearly marked
- **HTML and Text Formats**: Works with all email clients

## Logging

Logs are written to both console and `miniupdate.log` file. Use `-v` flag for verbose logging to help with troubleshooting.

## Error Handling

The tool gracefully handles:
- SSH connection failures
- Unsupported operating systems
- Package manager errors
- Network timeouts
- Email delivery failures

Failed hosts are reported in the email with error details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Security Considerations

- Store SSH keys securely and use SSH agent when possible
- Use app-specific passwords for email authentication
- Consider using encrypted storage for configuration files
- Regularly rotate credentials
- Monitor email reports for security updates

## Troubleshooting

### Email Delivery Issues

1. **SMTP Connection Failures**
   - Verify host accessibility: `telnet smtp_server smtp_port`
   - Check SSH keys and agent
   - Ensure correct username and port

2. **Package Manager Errors**
   - Verify user has sufficient privileges
   - Check network connectivity on remote hosts
   - Update package cache manually if needed

3. **Email Delivery Issues**
   - Verify SMTP settings and credentials
   - Check firewall rules for SMTP ports
   - Test with a simple email client first
   - For strict SMTP servers (like maddy): ensure proper sender email format

4. **Permission Errors**
   - Ensure SSH user has sudo/root access where needed
   - Some package managers require elevated privileges

### Debug Mode

Run with verbose logging to get detailed information:
```bash
python -m miniupdate.main -v check --dry-run
```

Check the `miniupdate.log` file for additional details.