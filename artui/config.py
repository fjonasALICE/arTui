"""Configuration management for ArTui."""

import os
import yaml
from typing import Dict, Any, Optional
from pathlib import Path
from .user_dirs import get_user_dirs


class ConfigManager:
    """Manages configuration loading and default values for ArTui."""
    
    DEFAULT_CONFIG = {
        "feed_retention_days": 30,  # Articles older than this are hidden from feed views unless unread
        "categories": {
            "HEP Experiments": "hep-ex",
            "HEP Theory": "hep-th", 
            "HEP Phenomenology": "hep-ph",
            "Nuclear Experiments": "nucl-ex",
        },
        "filters": {
            "ALICE": {
                "categories": ["hep-ex", "hep-ph"],
                "query": "ALICE"
            },
            "Heavy-Ion Physics": {
                "categories": ["hep-ex", "hep-ph"],
                "query": "qgp OR quark gluon plasma OR quark-gluon plasma OR heavy-ion"
            }
        }
    }
    
    def __init__(self, config_path: Optional[str] = None, custom_user_dir: Optional[str] = None):
        """Initialize config manager.
        
        Args:
            config_path: Path to config file. If None, uses default locations.
            custom_user_dir: Custom user data directory. If None, uses default.
        """
        # Initialize user directories first
        self.user_dirs = get_user_dirs(custom_user_dir)
        
        if config_path is None:
            config_path = self._find_config_file()
        
        self.config_path = config_path
        self._config = None
    
    def _find_config_file(self) -> str:
        """Find configuration file in standard locations."""
        # First, check the user data directory (preferred location)
        user_config_path = self.user_dirs.config_file
        if os.path.exists(user_config_path):
            return user_config_path
        
        # For backward compatibility, check legacy locations
        legacy_paths = [
            "arxiv_config.yaml",  # Current directory (legacy)
            os.path.expanduser("~/.config/artui/config.yaml"),
            os.path.expanduser("~/.artui/config.yaml"),
        ]
        
        for path in legacy_paths:
            if os.path.exists(path):
                return path
                
        # Return user data directory path for creation
        return user_config_path
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file or return defaults."""
        if self._config is not None:
            return self._config
            
        try:
            with open(self.config_path, "r") as f:
                self._config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self._config = {}
            self.create_default_config()
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file {self.config_path}: {e}")
        
        # Merge with defaults
        config = self.DEFAULT_CONFIG.copy()
        config.update(self._config)
        self._config = config
        
        return self._config
    
    def create_default_config(self) -> None:
        """Create default configuration file."""
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        
        with open(self.config_path, "w") as f:
            yaml.dump(self.DEFAULT_CONFIG, f, default_flow_style=False, indent=2)
        
        print(f"Created default configuration file: {self.config_path}")
    
    def get_categories(self) -> Dict[str, str]:
        """Get configured categories."""
        config = self.load_config()
        return config.get("categories", {})
    
    def get_filters(self) -> Dict[str, Dict[str, Any]]:
        """Get configured filters."""
        config = self.load_config()
        return config.get("filters", {})
    
    def get_config(self) -> Dict[str, Any]:
        """Get full configuration."""
        return self.load_config()
    
    def reload_config(self) -> Dict[str, Any]:
        """Force reload configuration from file."""
        self._config = None
        return self.load_config()


def load_config(config_path: Optional[str] = None, custom_user_dir: Optional[str] = None) -> Dict[str, Any]:
    """Convenience function to load configuration.
    
    Args:
        config_path: Path to config file. If None, uses default locations.
        custom_user_dir: Custom user data directory. If None, uses default.
        
    Returns:
        Configuration dictionary.
    """
    manager = ConfigManager(config_path, custom_user_dir)
    return manager.load_config()
