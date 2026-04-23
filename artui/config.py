"""Configuration management for ArTui."""

import copy
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

    @staticmethod
    def _warn_config(message: str) -> None:
        """Emit a lightweight warning for non-fatal config issues."""
        print(f"Warning: Config normalization: {message}")
    
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
        self.is_first_run = False
    
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
                loaded = yaml.safe_load(f)
                if loaded is None:
                    loaded = {}
                elif not isinstance(loaded, dict):
                    self._warn_config(
                        f"expected a mapping at config root, got {type(loaded).__name__}; using defaults"
                    )
                    loaded = {}
                self._config = loaded
        except FileNotFoundError:
            self._config = {}
            self.is_first_run = True
            self.create_default_config()
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file {self.config_path}: {e}")
        
        # Merge with defaults (deep copy to avoid mutating class-level DEFAULT_CONFIG)
        config = copy.deepcopy(self.DEFAULT_CONFIG)
        config.update(self._config)
        self._config = self._normalize_config(config)
        
        return self._config

    def _normalize_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize config values into safe runtime shapes."""
        default_retention_days = self.DEFAULT_CONFIG["feed_retention_days"]

        retention_days = config.get("feed_retention_days", default_retention_days)
        if not isinstance(retention_days, int) or retention_days <= 0:
            self._warn_config(
                f"'feed_retention_days' must be a positive integer; using default {default_retention_days}"
            )
            retention_days = default_retention_days
        config["feed_retention_days"] = retention_days

        raw_categories = config.get("categories", {})
        normalized_categories: Dict[str, str] = {}
        if raw_categories is None:
            self._warn_config("'categories' is null; treating as empty mapping")
            raw_categories = {}
        elif not isinstance(raw_categories, dict):
            self._warn_config(
                f"'categories' must be a mapping, got {type(raw_categories).__name__}; treating as empty mapping"
            )
            raw_categories = {}

        for display_name, category_code in raw_categories.items():
            if not isinstance(display_name, str) or not isinstance(category_code, str):
                self._warn_config(
                    f"dropping category entry with non-string key/value: {display_name!r} -> {category_code!r}"
                )
                continue
            clean_name = display_name.strip()
            clean_code = category_code.strip()
            if not clean_name or not clean_code:
                self._warn_config(
                    f"dropping category entry with empty name or code: {display_name!r} -> {category_code!r}"
                )
                continue
            normalized_categories[clean_name] = clean_code
        config["categories"] = normalized_categories

        raw_filters = config.get("filters", {})
        normalized_filters: Dict[str, Dict[str, Any]] = {}
        if raw_filters is None:
            self._warn_config("'filters' is null; treating as no filters")
            raw_filters = {}
        elif not isinstance(raw_filters, dict):
            self._warn_config(
                f"'filters' must be a mapping, got {type(raw_filters).__name__}; treating as no filters"
            )
            raw_filters = {}

        for filter_name, filter_config in raw_filters.items():
            if not isinstance(filter_name, str) or not filter_name.strip():
                self._warn_config(f"dropping filter with invalid name: {filter_name!r}")
                continue
            clean_name = filter_name.strip()

            if filter_config is None:
                self._warn_config(f"filter '{clean_name}' is null; treating as empty definition")
                filter_config = {}
            elif not isinstance(filter_config, dict):
                self._warn_config(
                    f"filter '{clean_name}' must be a mapping, got {type(filter_config).__name__}; treating as empty definition"
                )
                filter_config = {}

            raw_filter_categories = filter_config.get("categories", [])
            normalized_filter_categories = []
            if raw_filter_categories is None:
                normalized_filter_categories = []
            elif isinstance(raw_filter_categories, str):
                normalized_filter_categories = [raw_filter_categories.strip()] if raw_filter_categories.strip() else []
            elif isinstance(raw_filter_categories, list):
                for category in raw_filter_categories:
                    if isinstance(category, str) and category.strip():
                        normalized_filter_categories.append(category.strip())
                    else:
                        self._warn_config(
                            f"dropping invalid category value in filter '{clean_name}': {category!r}"
                        )
            else:
                self._warn_config(
                    f"'categories' in filter '{clean_name}' must be a list/string/null; treating as empty list"
                )
                normalized_filter_categories = []

            raw_query = filter_config.get("query")
            normalized_query = ""
            if raw_query is None:
                normalized_query = ""
            elif isinstance(raw_query, str):
                normalized_query = raw_query.strip()
            else:
                self._warn_config(
                    f"'query' in filter '{clean_name}' must be a string/null; ignoring value {raw_query!r}"
                )
                normalized_query = ""

            if not normalized_filter_categories and not normalized_query:
                self._warn_config(
                    f"dropping empty filter '{clean_name}' (no categories and no query)"
                )
                continue

            normalized_filter_config: Dict[str, Any] = {
                "categories": normalized_filter_categories
            }
            if normalized_query:
                normalized_filter_config["query"] = normalized_query
            normalized_filters[clean_name] = normalized_filter_config

        config["filters"] = normalized_filters
        return config
    
    def create_default_config(self) -> None:
        """Create default configuration file."""
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        
        with open(self.config_path, "w") as f:
            yaml.dump(self.DEFAULT_CONFIG, f, default_flow_style=False, indent=2)
        
        print(f"Created default configuration file: {self.config_path}")
    
    def get_categories(self) -> Dict[str, str]:
        """Get configured categories."""
        config = self.load_config()
        categories = config.get("categories")
        if isinstance(categories, dict):
            return categories
        return {}
    
    def get_filters(self) -> Dict[str, Dict[str, Any]]:
        """Get configured filters."""
        config = self.load_config()
        filters = config.get("filters")
        if isinstance(filters, dict):
            return filters
        return {}
    
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
