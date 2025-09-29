# miniupdate

Minimal patch check script for virtual guests

A Python tool that SSHs to an inventory of hosts (Ansible format), identifies the OS, uses appropriate package managers to check for updates, and emails the results to sysadmins via SMTP.

## Features

- **Multi-OS Support**: Automatically detects OS and uses appropriate package manager
  - Ubuntu/Debian (apt)
  - CentOS/RHEL (yum/dnf) 
  - Fedora (dnf)
  - openSUSE (zypper)
  - Arch Linux (pacman)
  - Alpine Linux (apk)
  - FreeBSD (pkg)
  - macOS (brew)

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
```

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

- `init` - Create example configuration and inventory files
- `check` - Check for updates on all hosts and send email report
- `test-config` - Test configuration file and connectivity

### Options

- `-c, --config` - Specify configuration file path
- `-v, --verbose` - Enable verbose logging
- `-p, --parallel` - Number of parallel connections (default: 5)
- `-t, --timeout` - SSH timeout in seconds (default: 120)
- `--dry-run` - Show what would be done without sending email

### Examples

```bash
# Use custom config file
python -m miniupdate.main -c /etc/miniupdate/config.toml check

# Run with verbose logging and custom parallelism
python -m miniupdate.main -v check -p 10

# Test run without sending email
python -m miniupdate.main check --dry-run

# Extended timeout for slow connections
python -m miniupdate.main check -t 300
```

## SSH Authentication

miniupdate supports multiple SSH authentication methods:

1. **SSH Agent** (default, most secure)
2. **SSH Key Files** (specify in config.toml)
3. **Username/Password** (less secure, not recommended)

For best security, use SSH agent or key-based authentication.

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