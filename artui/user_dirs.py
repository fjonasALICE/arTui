"""User directory management for ArTui."""

import os
from pathlib import Path
from typing import Optional
import shutil


class UserDirectoryManager:
    """Manages user data directories and file paths for ArTui."""
    
    # Default directory names
    DEFAULT_BASE_DIR_NAME = ".artui"
    CONFIG_FILE_NAME = "config.yaml"
    DATABASE_FILE_NAME = "arxiv_articles.db"
    ARTICLES_DIR_NAME = "articles"
    NOTES_DIR_NAME = "notes"
    
    def __init__(self, custom_base_dir: Optional[str] = None):
        """Initialize user directory manager.
        
        Args:
            custom_base_dir: Custom base directory path. If None, uses default location.
        """
        self._base_dir = None
        self._custom_base_dir = custom_base_dir
        self._ensure_base_directory()
    
    def _get_default_base_dir(self) -> str:
        """Get the default base directory for user data."""
        # Check for environment variable first
        env_dir = os.environ.get('ARTUI_DATA_DIR')
        if env_dir:
            return os.path.expanduser(env_dir)
        
        # Default to ~/.artui
        return os.path.expanduser(f"~/{self.DEFAULT_BASE_DIR_NAME}")
    
    def _ensure_base_directory(self) -> None:
        """Ensure the base directory exists and set up subdirectories."""
        if self._custom_base_dir:
            self._base_dir = os.path.expanduser(self._custom_base_dir)
        else:
            self._base_dir = self._get_default_base_dir()
        
        # Create base directory and subdirectories
        os.makedirs(self._base_dir, exist_ok=True)
        os.makedirs(self.articles_dir, exist_ok=True)
        os.makedirs(self.notes_dir, exist_ok=True)
    
    @property
    def base_dir(self) -> str:
        """Get the base user data directory."""
        return self._base_dir
    
    @property
    def config_file(self) -> str:
        """Get the path to the configuration file."""
        return os.path.join(self._base_dir, self.CONFIG_FILE_NAME)
    
    @property
    def database_file(self) -> str:
        """Get the path to the database file."""
        return os.path.join(self._base_dir, self.DATABASE_FILE_NAME)
    
    @property
    def articles_dir(self) -> str:
        """Get the path to the articles directory."""
        return os.path.join(self._base_dir, self.ARTICLES_DIR_NAME)
    
    @property
    def notes_dir(self) -> str:
        """Get the path to the notes directory."""
        return os.path.join(self._base_dir, self.NOTES_DIR_NAME)
    
    def get_notes_file_path(self, article_id: str, article_title: str) -> str:
        """Get a notes file path for an article.
        
        Args:
            article_id: The article ID
            article_title: The article title (for filename generation)
            
        Returns:
            Full path to the notes file
        """
        # Sanitize title for filename
        safe_title = "".join(c for c in article_title if c.isalnum() or c in ' ._-').rstrip()
        filename = f"{article_id}_{safe_title[:30]}.md"
        return os.path.join(self.notes_dir, filename)
    
    def migrate_from_current_directory(self) -> dict:
        """Migrate existing files from current directory to user data directory.
        
        Returns:
            Dictionary with migration statistics
        """
        stats = {
            "config_migrated": False,
            "database_migrated": False,
            "articles_migrated": 0,
            "notes_migrated": 0,
            "legacy_files_migrated": 0,
            "errors": []
        }
        
        current_dir = os.getcwd()
        
        # Migrate config file (try multiple possible names)
        config_candidates = [
            "arxiv_config.yaml",
            "config.yaml",
            ".artui_config.yaml"
        ]
        
        for config_name in config_candidates:
            config_path = os.path.join(current_dir, config_name)
            if os.path.exists(config_path) and not os.path.exists(self.config_file):
                try:
                    shutil.move(config_path, self.config_file)
                    stats["config_migrated"] = True
                    break
                except Exception as e:
                    stats["errors"].append(f"Failed to migrate {config_name}: {e}")
        
        # Migrate database file
        db_candidates = [
            "arxiv_articles.db",
            "articles.db",
            ".artui.db"
        ]
        
        for db_name in db_candidates:
            db_path = os.path.join(current_dir, db_name)
            if os.path.exists(db_path) and not os.path.exists(self.database_file):
                try:
                    shutil.move(db_path, self.database_file)
                    stats["database_migrated"] = True
                    break
                except Exception as e:
                    stats["errors"].append(f"Failed to migrate {db_name}: {e}")
        
        # Migrate articles directory
        articles_src = os.path.join(current_dir, "articles")
        if os.path.exists(articles_src) and os.path.isdir(articles_src):
            try:
                # Move all files from source to destination
                for item in os.listdir(articles_src):
                    src_path = os.path.join(articles_src, item)
                    dst_path = os.path.join(self.articles_dir, item)
                    
                    if os.path.isfile(src_path):
                        shutil.move(src_path, dst_path)
                        stats["articles_migrated"] += 1
                
                # Remove empty directory if all files were moved
                if not os.listdir(articles_src):
                    os.rmdir(articles_src)
                    
            except Exception as e:
                stats["errors"].append(f"Failed to migrate articles directory: {e}")
        
        # Migrate notes directory
        notes_src = os.path.join(current_dir, "notes")
        if os.path.exists(notes_src) and os.path.isdir(notes_src):
            try:
                # Move all files from source to destination
                for item in os.listdir(notes_src):
                    src_path = os.path.join(notes_src, item)
                    dst_path = os.path.join(self.notes_dir, item)
                    
                    if os.path.isfile(src_path):
                        shutil.move(src_path, dst_path)
                        stats["notes_migrated"] += 1
                
                # Remove empty directory if all files were moved
                if not os.listdir(notes_src):
                    os.rmdir(notes_src)
                    
            except Exception as e:
                stats["errors"].append(f"Failed to migrate notes directory: {e}")
        
        # Migrate legacy text files
        legacy_files = [
            "saved_articles.txt",
            "viewed_articles.txt"
        ]
        
        for legacy_file in legacy_files:
            legacy_path = os.path.join(current_dir, legacy_file)
            if os.path.exists(legacy_path):
                try:
                    dst_path = os.path.join(self._base_dir, legacy_file)
                    shutil.move(legacy_path, dst_path)
                    stats["legacy_files_migrated"] += 1
                except Exception as e:
                    stats["errors"].append(f"Failed to migrate {legacy_file}: {e}")
        
        return stats
    
    def get_info(self) -> dict:
        """Get information about the user directory setup.
        
        Returns:
            Dictionary with directory information
        """
        return {
            "base_dir": self._base_dir,
            "config_file": self.config_file,
            "database_file": self.database_file,
            "articles_dir": self.articles_dir,
            "notes_dir": self.notes_dir,
            "config_exists": os.path.exists(self.config_file),
            "database_exists": os.path.exists(self.database_file),
            "articles_count": len([f for f in os.listdir(self.articles_dir) 
                                 if os.path.isfile(os.path.join(self.articles_dir, f))]) if os.path.exists(self.articles_dir) else 0,
            "notes_count": len([f for f in os.listdir(self.notes_dir) 
                               if os.path.isfile(os.path.join(self.notes_dir, f))]) if os.path.exists(self.notes_dir) else 0,
        }


# Global instance - will be initialized when first imported
_user_dirs: Optional[UserDirectoryManager] = None


def get_user_dirs(custom_base_dir: Optional[str] = None) -> UserDirectoryManager:
    """Get the global UserDirectoryManager instance.
    
    Args:
        custom_base_dir: Custom base directory path. Only used on first call.
        
    Returns:
        UserDirectoryManager instance
    """
    global _user_dirs
    if _user_dirs is None:
        _user_dirs = UserDirectoryManager(custom_base_dir)
    return _user_dirs


def set_user_dirs(custom_base_dir: Optional[str] = None) -> UserDirectoryManager:
    """Set/reset the global UserDirectoryManager instance.
    
    Args:
        custom_base_dir: Custom base directory path.
        
    Returns:
        New UserDirectoryManager instance
    """
    global _user_dirs
    _user_dirs = UserDirectoryManager(custom_base_dir)
    return _user_dirs
