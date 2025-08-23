"""Command-line interface for ArTui."""

import argparse
import sys
from typing import Optional

from .app import ArxivReaderApp
from .database import ArticleDatabase
from .config import ConfigManager
from .fetcher import ArticleFetcher
from .user_dirs import get_user_dirs, set_user_dirs


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="artui",
        description="ArTui - A Terminal User Interface for browsing arXiv papers"
    )
    
    parser.add_argument(
        "--version", 
        action="version", 
        version="%(prog)s 1.0.0"
    )
    
    parser.add_argument(
        "--config", 
        type=str,
        help="Path to configuration file (default: arxiv_config.yaml)"
    )
    
    parser.add_argument(
        "--db", 
        type=str,
        help="Path to database file (default: uses user data directory)"
    )
    
    parser.add_argument(
        "--user-dir",
        type=str,
        help="Custom user data directory (default: ~/.artui or $ARTUI_DATA_DIR)"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Main TUI command (default)
    tui_parser = subparsers.add_parser("tui", help="Launch the TUI application (default)")
    tui_parser.add_argument(
        "--theme",
        choices=["monokai", "textual-dark", "textual-light"],
        default="monokai",
        help="UI theme to use"
    )
    
    # Fetch command
    fetch_parser = subparsers.add_parser("fetch", help="Fetch articles from arXiv")
    fetch_parser.add_argument(
        "--force", 
        action="store_true",
        help="Force fetch even if recently fetched"
    )
    fetch_parser.add_argument(
        "--recent", 
        type=int, 
        metavar="DAYS",
        help="Fetch only recent articles from last N days"
    )
    
    # Config command
    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_subparsers = config_parser.add_subparsers(dest="config_action", help="Config actions")
    
    config_subparsers.add_parser("init", help="Create default configuration file")
    config_subparsers.add_parser("show", help="Show current configuration")
    config_subparsers.add_parser("validate", help="Validate configuration file")
    
    # Database command
    db_parser = subparsers.add_parser("db", help="Database management")
    db_subparsers = db_parser.add_subparsers(dest="db_action", help="Database actions")
    
    db_subparsers.add_parser("info", help="Show database statistics")
    db_subparsers.add_parser("migrate", help="Migrate from old text files")
    
    # User directory command
    userdir_parser = subparsers.add_parser("userdir", help="User directory management")
    userdir_subparsers = userdir_parser.add_subparsers(dest="userdir_action", help="User directory actions")
    
    userdir_subparsers.add_parser("info", help="Show user directory information")
    userdir_subparsers.add_parser("migrate", help="Migrate existing data to user directory")
    
    return parser


def cmd_tui(args) -> int:
    """Launch the TUI application."""
    try:
        # Initialize user directories if custom path provided
        if hasattr(args, 'user_dir') and args.user_dir:
            set_user_dirs(args.user_dir)
        
        app = ArxivReaderApp(
            config_path=args.config,
            db_path=args.db,
            custom_user_dir=getattr(args, 'user_dir', None)
        )
        app.theme = args.theme
        app.run()
        return 0
    except KeyboardInterrupt:
        print("\nExiting...")
        return 0
    except Exception as e:
        print(f"Error launching TUI: {e}", file=sys.stderr)
        return 1


def cmd_fetch(args) -> int:
    """Fetch articles from arXiv."""
    try:
        # Initialize user directories if custom path provided
        custom_user_dir = getattr(args, 'user_dir', None)
        if custom_user_dir:
            set_user_dirs(custom_user_dir)
        
        config_manager = ConfigManager(args.config, custom_user_dir)
        db = ArticleDatabase(args.db, custom_user_dir)
        fetcher = ArticleFetcher(db, config_manager)
        
        # Migrate existing data if text files exist
        migration_stats = db.migrate_from_text_files()
        if migration_stats["saved_migrated"] > 0 or migration_stats["viewed_migrated"] > 0:
            print(f"Migrated {migration_stats['saved_migrated']} saved and {migration_stats['viewed_migrated']} viewed articles")
        
        # Run cleanup routine to remove old unsaved articles
        try:
            config = config_manager.get_config()
            retention_days = config.get("feed_retention_days", 30)
            deleted_count = db.cleanup_old_unsaved_articles(retention_days)
            
            if deleted_count > 0:
                print(f"Cleanup: Removed {deleted_count} old unsaved articles (older than {retention_days} days)")
        except Exception as e:
            print(f"Warning: Cleanup routine failed: {e}")
        
        # Fetch articles
        if args.recent:
            results = fetcher.fetch_recent_articles(days=args.recent)
        else:
            results = fetcher.fetch_all_categories(force=args.force)
        
        total_new = sum(results.values())
        print(f"\nFetch complete! Added {total_new} new articles.")
        return 0
        
    except Exception as e:
        print(f"Error fetching articles: {e}", file=sys.stderr)
        return 1


def cmd_config(args) -> int:
    """Handle configuration commands."""
    try:
        # Initialize user directories if custom path provided
        custom_user_dir = getattr(args, 'user_dir', None)
        if custom_user_dir:
            set_user_dirs(custom_user_dir)
        
        config_manager = ConfigManager(args.config, custom_user_dir)
        
        if args.config_action == "init":
            config_manager.create_default_config()
            print(f"Created default configuration at: {config_manager.config_path}")
            
        elif args.config_action == "show":
            config = config_manager.get_config()
            import yaml
            print(yaml.dump(config, default_flow_style=False, indent=2))
            
        elif args.config_action == "validate":
            try:
                config = config_manager.load_config()
                print("Configuration is valid!")
                print(f"Found {len(config.get('categories', {}))} categories and {len(config.get('filters', {}))} filters")
            except Exception as e:
                print(f"Configuration validation failed: {e}", file=sys.stderr)
                return 1
                
        else:
            print("No config action specified. Use --help for options.")
            return 1
            
        return 0
        
    except Exception as e:
        print(f"Error with configuration: {e}", file=sys.stderr)
        return 1


def cmd_db(args) -> int:
    """Handle database commands."""
    try:
        # Initialize user directories if custom path provided
        custom_user_dir = getattr(args, 'user_dir', None)
        if custom_user_dir:
            set_user_dirs(custom_user_dir)
        
        db = ArticleDatabase(args.db, custom_user_dir)
        
        if args.db_action == "info":
            total_articles = db.get_all_articles_count()
            saved_articles = db.get_saved_articles_count()
            unread_articles = db.get_unread_count()
            
            print("Database Statistics:")
            print(f"  Total articles: {total_articles}")
            print(f"  Saved articles: {saved_articles}")
            print(f"  Unread articles: {unread_articles}")
            
            # Tag statistics
            tags = db.get_all_tags()
            print(f"  Total tags: {len(tags)}")
            if tags:
                print("  Top tags:")
                for tag in sorted(tags, key=lambda x: x['article_count'], reverse=True)[:5]:
                    print(f"    {tag['name']}: {tag['article_count']} articles")
                    
        elif args.db_action == "migrate":
            stats = db.migrate_from_text_files()
            print("Migration complete!")
            print(f"  Migrated {stats['saved_migrated']} saved articles")
            print(f"  Migrated {stats['viewed_migrated']} viewed articles")
            if stats['errors'] > 0:
                print(f"  {stats['errors']} errors occurred during migration")
                
        else:
            print("No database action specified. Use --help for options.")
            return 1
            
        return 0
        
    except Exception as e:
        print(f"Error with database: {e}", file=sys.stderr)
        return 1


def cmd_userdir(args) -> int:
    """Handle user directory commands."""
    try:
        # Initialize user directories if custom path provided
        custom_user_dir = getattr(args, 'user_dir', None)
        if custom_user_dir:
            set_user_dirs(custom_user_dir)
        
        user_dirs = get_user_dirs(custom_user_dir)
        
        if args.userdir_action == "info":
            info = user_dirs.get_info()
            print("User Directory Information:")
            print(f"  Base directory: {info['base_dir']}")
            print(f"  Config file: {info['config_file']} ({'exists' if info['config_exists'] else 'missing'})")
            print(f"  Database file: {info['database_file']} ({'exists' if info['database_exists'] else 'missing'})")
            print(f"  Articles directory: {info['articles_dir']} ({info['articles_count']} files)")
            print(f"  Notes directory: {info['notes_dir']} ({info['notes_count']} files)")
            
        elif args.userdir_action == "migrate":
            print("Migrating existing data to user directory...")
            stats = user_dirs.migrate_from_current_directory()
            
            print("Migration complete!")
            if stats["config_migrated"]:
                print("  ✓ Configuration file migrated")
            if stats["database_migrated"]:
                print("  ✓ Database file migrated")
            if stats["articles_migrated"] > 0:
                print(f"  ✓ {stats['articles_migrated']} article files migrated")
            if stats["notes_migrated"] > 0:
                print(f"  ✓ {stats['notes_migrated']} notes files migrated")
            if stats["legacy_files_migrated"] > 0:
                print(f"  ✓ {stats['legacy_files_migrated']} legacy files migrated")
            
            if stats["errors"]:
                print("\nErrors during migration:")
                for error in stats["errors"]:
                    print(f"  ✗ {error}")
                    
            if not any([stats["config_migrated"], stats["database_migrated"], 
                       stats["articles_migrated"], stats["notes_migrated"], 
                       stats["legacy_files_migrated"]]):
                print("  No files found to migrate")
                
        else:
            print("No user directory action specified. Use --help for options.")
            return 1
            
        return 0
        
    except Exception as e:
        print(f"Error with user directory: {e}", file=sys.stderr)
        return 1


def main() -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()
    
    # If no command specified, default to TUI
    if not args.command:
        args.command = "tui"
        args.theme = "monokai"
    
    # Route to appropriate command handler
    if args.command == "tui":
        return cmd_tui(args)
    elif args.command == "fetch":
        return cmd_fetch(args)
    elif args.command == "config":
        return cmd_config(args)
    elif args.command == "db":
        return cmd_db(args)
    elif args.command == "userdir":
        return cmd_userdir(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
