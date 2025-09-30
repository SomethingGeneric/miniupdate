# GitHub Copilot Instructions for miniupdate

## Project Overview

miniupdate is a Python tool for automated system update management across multiple hosts with Proxmox VE integration. It:
- SSHs to hosts from Ansible inventory files
- Detects OS and package managers automatically
- Checks for and applies system updates
- Creates Proxmox VM snapshots before updates
- Sends comprehensive email reports via SMTP

## Architecture

### Core Components

- **config.py**: TOML-based configuration management. Config files can be in current directory or `~/.miniupdate/`
- **inventory.py**: Ansible inventory parser (YAML/INI formats) with support for external git repositories
- **ssh_manager.py**: SSH connection handling via paramiko
- **os_detector.py**: Multi-OS detection (Ubuntu, Debian, CentOS, RHEL, Fedora, openSUSE, Arch, Alpine, FreeBSD, macOS)
- **package_managers.py**: Package manager abstraction layer for apt, yum, dnf, zypper, pacman, apk, pkg, brew
- **host_checker.py**: Orchestrates update checking across hosts
- **update_automator.py**: Automated update workflow with snapshots and rollback
- **proxmox_client.py**: Proxmox VE API integration for VM snapshots
- **email_sender.py**: HTML/text email report generation and sending
- **vm_mapping.py**: Maps inventory hostnames to Proxmox VM IDs
- **main.py**: CLI interface using Click

### Key Workflows

1. **Check workflow**: Read-only update checking and email reporting
2. **Update workflow**: Automated updates with Proxmox snapshots, reboot handling, and rollback on failure
3. **Init workflow**: Creates example configuration files

## Coding Standards

### Python Style

- **Python Version**: 3.7+ (see setup.py for compatibility matrix)
- **Style**: Follow PEP 8 conventions
- **Docstrings**: Use triple-quoted strings for functions and classes
- **Type Hints**: Use typing module annotations where beneficial
- **Error Handling**: Use try/except with informative error messages

### Dependencies

Core dependencies (requirements.txt):
- `paramiko>=3.0.0` - SSH connections
- `PyYAML>=6.0` - Ansible inventory parsing
- `toml>=0.10.2` - Configuration files
- `click>=8.0.0` - CLI framework
- `requests>=2.25.0` - HTTP requests for Proxmox API

### Logging

- Use Python's `logging` module
- Log to both console (stdout) and file (`miniupdate.log`)
- Default level: INFO, configurable via config
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

## Configuration Files

### config.toml Structure

```toml
[email]
smtp_server = "smtp.gmail.com"
smtp_port = 587
use_tls = true
username = "your-email@example.com"
password = "your-app-password"
from_email = "your-email@example.com"
to_email = ["admin@example.com"]

[inventory]
path = "inventory.yml"  # Supports: relative paths, absolute paths, ~/home paths, $ENV_VAR expansion
format = "ansible"

[ssh]
timeout = 30
key_file = null
username = null
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
reboot_timeout = 300
ping_timeout = 120
ping_interval = 5
snapshot_name_prefix = "pre-update"
cleanup_snapshots = true
snapshot_retention_days = 7
opt_out_hosts = []  # Hosts to exclude from automated updates
```

### inventory.yml (Ansible format)

Supports standard Ansible inventory with hosts and groups. Can be stored in external git repositories.

### vm_mapping.toml

Maps inventory hostnames to Proxmox node/VM ID pairs:

```toml
[mapping]
"web-server-01" = { node = "pve1", vmid = 100 }
```

## Common Patterns

### Path Resolution

Config class supports multiple path patterns:
- Relative paths (relative to config file location)
- Absolute paths (`/etc/ansible/inventory.yml`)
- Home directory expansion (`~/git/infrastructure/inventory.yml`)
- Environment variable expansion (`$ANSIBLE_INVENTORY_PATH/inventory.yml`)

### Error Handling

- Gracefully handle SSH connection failures
- Continue processing other hosts on individual failures
- Log errors but don't crash the entire process
- Include error details in email reports

### Parallel Processing

- Use ThreadPoolExecutor for concurrent host operations
- Default: 5 parallel connections (configurable)
- Timeout-based termination for hung operations

## CLI Commands

```bash
# Create example configuration files
miniupdate init

# Check for updates (read-only)
miniupdate check [--dry-run] [-c config.toml] [-v]

# Apply automated updates with snapshots
miniupdate update [--dry-run] [-c config.toml] [-v]

# Test configuration
miniupdate test-config [-c config.toml]
```

## Testing

- No formal test suite currently exists
- Manual testing recommended:
  1. Create config files with `miniupdate init`
  2. Use `--dry-run` flag for safe testing
  3. Verify email reports are generated correctly
  4. Test SSH connectivity with `test-config` command

## Development Workflow

1. Install in development mode: `pip install -e .`
2. Create test configuration in a separate directory
3. Use `--dry-run` extensively during development
4. Check logs in `miniupdate.log` for debugging
5. Test email functionality separately before production use

## Important Notes

- **Security**: Never commit actual config.toml with credentials
- **Proxmox Integration**: VM snapshots require valid Proxmox credentials and VM mapping
- **SSH Keys**: Prefer SSH key authentication over passwords
- **Email**: Use app-specific passwords for Gmail/modern SMTP servers
- **Opt-out hosts**: Hosts in `opt_out_hosts` list are checked but never updated automatically
- **Unmapped hosts**: Hosts without VM mapping and not in opt-out list will trigger warnings

## When Making Changes

### Adding New OS Support

1. Add detection logic to `os_detector.py`
2. Implement package manager interface in `package_managers.py`
3. Test with actual system or VM
4. Update README.md with new OS in features list

### Adding New Configuration Options

1. Add to example config in `config.py:create_example_config()`
2. Add property to Config class
3. Update README.md configuration section
4. Handle backward compatibility for existing configs

### Modifying Email Reports

1. Update templates in `email_sender.py`
2. Maintain both HTML and plain text versions
3. Test rendering with various update scenarios
4. Ensure MIME multipart structure is preserved

### Working with Proxmox

1. Use `proxmox_client.py` for all API interactions
2. Handle API errors gracefully (connection, auth, operations)
3. Verify snapshot operations before updating
4. Implement proper cleanup for failed operations
