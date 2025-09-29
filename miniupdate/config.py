"""
Configuration management for miniupdate.

Handles loading and parsing of TOML configuration files containing
email credentials and inventory paths.
"""

import toml
from pathlib import Path
from typing import Dict, Any, Optional
import os


class Config:
    """Configuration manager for miniupdate."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to configuration file. If None, looks for config.toml
                        in current directory or ~/.miniupdate/config.toml
        """
        self.config_path = self._find_config_path(config_path)
        self.config = self._load_config()
    
    def _find_config_path(self, config_path: Optional[str]) -> Path:
        """Find configuration file path."""
        if config_path:
            return Path(config_path)
        
        # Check current directory
        current_config = Path("config.toml")
        if current_config.exists():
            return current_config
        
        # Check home directory
        home_config = Path.home() / ".miniupdate" / "config.toml"
        if home_config.exists():
            return home_config
        
        # Default to current directory config.toml (may not exist yet)
        return current_config
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from TOML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found at {self.config_path}. "
                f"Please create a config.toml file or see config.toml.example"
            )
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return toml.load(f)
        except Exception as e:
            raise ValueError(f"Error parsing configuration file: {e}")
    
    @property
    def smtp_config(self) -> Dict[str, Any]:
        """Get SMTP configuration."""
        if 'email' not in self.config:
            raise ValueError("No [email] section found in configuration")
        
        email_config = self.config['email']
        required_fields = ['smtp_server', 'smtp_port', 'from_email', 'to_email']
        
        for field in required_fields:
            if field not in email_config:
                raise ValueError(f"Missing required email configuration: {field}")
        
        return email_config
    
    @property
    def inventory_path(self) -> str:
        """Get Ansible inventory path with environment variable expansion."""
        if 'inventory' not in self.config:
            raise ValueError("No [inventory] section found in configuration")
        
        inventory_config = self.config['inventory']
        if 'path' not in inventory_config:
            raise ValueError("Missing required inventory path")
        
        raw_path = inventory_config['path']
        
        # Expand environment variables
        expanded_path = os.path.expandvars(raw_path)
        
        # Expand user home directory (~)
        expanded_path = os.path.expanduser(expanded_path)
        
        # Convert to absolute path if it's relative (unless it's already absolute)
        path_obj = Path(expanded_path)
        if not path_obj.is_absolute():
            # Make relative to the config file directory if config is not in current dir
            if self.config_path.parent != Path.cwd():
                path_obj = self.config_path.parent / path_obj
        
        return str(path_obj)
    
    @property
    def ssh_config(self) -> Dict[str, Any]:
        """Get SSH configuration."""
        return self.config.get('ssh', {})
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key."""
        return self.config.get(key, default)


def create_example_config(path: str = "config.toml.example") -> None:
    """Create an example configuration file."""
    example_config = {
        "email": {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "use_tls": True,
            "username": "your-email@example.com",
            "password": "your-app-password",
            "from_email": "your-email@example.com",
            "to_email": ["sysadmin@example.com", "admin@example.com"]
        },
        "inventory": {
            # Local inventory file (relative to config file)
            "path": "inventory.yml",
            
            # Alternative examples (uncomment one):
            # Absolute path
            # "path": "/etc/ansible/inventory.yml",
            
            # Path using environment variable
            # "path": "$ANSIBLE_INVENTORY_PATH/inventory.yml",
            
            # Path to external git repository
            # "path": "~/git/infrastructure/ansible/inventory.yml",
            
            # Corporate shared inventory
            # "path": "/shared/ansible-configs/production/inventory.yml",
            
            "format": "ansible"
        },
        "ssh": {
            "timeout": 30,
            "key_file": None,
            "username": None,
            "port": 22
        },
        "settings": {
            "parallel_connections": 5,
            "log_level": "INFO",
            "check_timeout": 120
        }
    }
    
    with open(path, 'w', encoding='utf-8') as f:
        toml.dump(example_config, f)