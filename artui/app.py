"""Main ArTui application."""

import os
import re
import sys
import webbrowser
import platform
import subprocess
from typing import Optional, List, Dict, Any

import arxiv
import requests
import pyperclip
from pyinspirehep import Client

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, DataTable, Button, Static, Input, 
    Checkbox, ListView, ListItem
)
from textual.coordinate import Coordinate
from textual import work, events

from .database import ArticleDatabase
from .config import ConfigManager
from .fetcher import ArticleFetcher
from .user_dirs import get_user_dirs
from .ui.screens import (
    SelectionPopupScreen, BibtexPopupScreen, 
    TagPopupScreen, NotesPopupScreen, AdvancedSearchPopupScreen
)
from .ui.widgets import ArticleTableWidget
from .ui.utils import convert_db_results_to_articles, debug_log


# Legacy file paths for migration
VIEWED_ARTICLES_FILE = "viewed_articles.txt"
SAVED_ARTICLES_FILE = "saved_articles.txt"


class ArxivReaderApp(App):
    """A Textual app to view arXiv articles."""

    CSS_PATH = "main.css"
    TITLE = "ArTui"
    ENABLE_COMMAND_PALETTE = False
    
    BINDINGS = [
        ("s", "save_article", "Save/Unsave"),
        ("u", "mark_unread", "Mark Unread"),
        ("o", "download_and_open_pdf", "Open PDF"),
        ("l", "open_arxiv_link", "Open arXiv Link"),
        ("f", "focus_search", "Find"),
        ("g", "global_search_and_focus", "Web Search"),
        ("c", "show_selection_popup", "Select View"),
        ("r", "refresh_articles", "Refresh"),
        ("i", "show_inspire_citation", "Show INSPIRE Citation"),
        ("t", "manage_tags", "Manage Tags"),

        ("n", "manage_notes", "Notes"),
        ("x", "mark_all_read", "Mark All Read"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config_path: Optional[str] = None, db_path: Optional[str] = None, 
                 custom_user_dir: Optional[str] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize user directories first
        self.user_dirs = get_user_dirs(custom_user_dir)
        
        # Initialize managers
        self.config_manager = ConfigManager(config_path, custom_user_dir)
        self.db = ArticleDatabase(db_path, custom_user_dir)
        self.fetcher = ArticleFetcher(self.db, self.config_manager)
        
        # Application state
        self.search_results = []
        self.current_query = ""
        self.current_selection = None
        self.global_search_enabled = False
        self.current_results_from_global = False
        self.current_results_type = None  # 'references', 'citations', or None
        self.last_refresh_time = None
        self.advanced_search_params = None
        
        # Set default theme
        self.dark = True
        self.theme = "monokai"
        
        # Migrate existing data from text files
        migration_stats = self.db.migrate_from_text_files()
        if migration_stats["saved_migrated"] > 0 or migration_stats["viewed_migrated"] > 0:
            print(f"Migrated {migration_stats['saved_migrated']} saved and {migration_stats['viewed_migrated']} viewed articles")
        
        # Run cleanup routine to remove old unsaved articles
        self._run_cleanup_routine()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        with Horizontal(id="main_app_container"):
            with VerticalScroll(id="left_pane"):
                yield from self._create_left_panel()
            
            with Vertical(id="right_pane"):
                yield Static("", id="header_status")
                with Horizontal(id="search_container"):
                    yield Input(placeholder="Enter query...", id="search_input")
                    yield Checkbox("Web Search", id="global_search_checkbox")
                    yield Button("Advanced", id="advanced_search_button")
                with Horizontal(id="main_container"):
                    with Vertical(id="results_container"):
                        yield Static("Articles", id="results_title", classes="pane_title")
                        yield ArticleTableWidget(id="results_table")
                    with Vertical(id="abstract_container"):
                        yield Static("Article View", id="abstract_title", classes="pane_title")
                        with VerticalScroll(id="abstract_view"):
                            yield Static("No article selected", id="abstract_content")
        yield Footer()

    def _create_left_panel(self):
        """Create the left panel widgets."""
        # Get unread counts
        unread_count = self.db.get_unread_count()
        unread_text = f"Unread ({unread_count})" if unread_count > 0 else "Unread"
        
        saved_unread_count = self.db.get_unread_saved_count()
        saved_text = f"Saved ({saved_unread_count})" if saved_unread_count > 0 else "Saved"
        
        # Feed section
        yield Static("Feed", classes="section_title_header")
        with Vertical(id="feed_container", classes="section_container"):
            yield ListView(
                ListItem(Static("All articles"), id="all_articles_filter"),
                ListItem(Static(unread_text), id="unread_articles_filter"),
                id="feed_articles_list",
            )

            # Filters subsection under Feed
            config = self.config_manager.get_config()
            retention_days = config.get("feed_retention_days", 30)
            filters = config.get("filters", {})
            if filters:
                with Vertical(id="filters_container"):
                    yield Static("Filters", classes="pane_title sub_title")
                    filter_items = []
                    for name, filter_config in filters.items():
                        unread_count = self.db.get_unread_count_by_filter(filter_config, retention_days)
                        filter_text = f"{name} ({unread_count})" if unread_count > 0 else name
                        
                        filter_items.append(
                            ListItem(Static(filter_text), id=f"filter_{name.replace(' ', '_')}")
                        )
                    yield ListView(*filter_items, id="filters_list")

            # Categories subsection under Feed
            categories = config.get("categories", {})
            if categories:
                with Vertical(id="categories_container"):
                    yield Static("Categories", classes="pane_title sub_title")
                    category_items = []
                    for name, code in categories.items():
                        unread_count = self.db.get_unread_count_by_category(code, retention_days)
                        category_text = f"{name} ({unread_count})" if unread_count > 0 else name
                        
                        category_items.append(
                            ListItem(Static(category_text), id=f"cat_{code}")
                        )
                    yield ListView(*category_items, id="categories_list")

        # Library section
        yield Static("Library", classes="section_title_header")
        with Vertical(id="library_container", classes="section_container"):
            # Get notes count for display
            notes_unread_count = self.db.get_unread_count_with_notes()
            notes_text = f"Notes ({notes_unread_count})" if notes_unread_count > 0 else "Notes"
            
            yield ListView(
                ListItem(Static(saved_text), id="saved_articles_filter"),
                ListItem(Static(notes_text), id="notes_articles_filter"),
                id="library_articles_list",
            )



            # Tags subsection under Library
            with Vertical(id="tags_container"):
                all_tags = self.db.get_all_tags()
                if all_tags:
                    yield Static("Tags", classes="pane_title sub_title")
                    tag_items = []
                    for tag in all_tags:
                        unread_count = self.db.get_unread_count_by_tag(tag['name'])
                        tag_text = f"{tag['name']} ({unread_count})" if unread_count > 0 else tag['name']
                        sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag['name'])
                        
                        tag_item = ListItem(Static(tag_text), id=f"tag_{sanitized_tag_name}")
                        tag_item.original_tag_name = tag['name']
                        tag_items.append(tag_item)
                    yield ListView(*tag_items, id="tags_list")

    def on_mount(self) -> None:
        """Call after the app is mounted."""
        table = self.query_one("#results_table", ArticleTableWidget)

        # Automatically select "Unread" as the default view
        self.current_selection = "unread_articles_filter"
        
        # Deselect all ListViews first
        for list_view in self.query(ListView):
            list_view.index = None
        
        try:
            self.query_one("#feed_articles_list", ListView).index = 1  # Select second item (Unread)
            self.load_articles()
        except Exception:
            pass  # List view or item not found

        self.notify("Refreshing articles...", title="Manual Refresh", timeout=3)
        self.manual_refresh_articles()

        # Set initial state of global search checkbox
        global_search_checkbox = self.query_one("#global_search_checkbox", Checkbox)
        global_search_checkbox.value = self.global_search_enabled
        
        # Update header status on mount
        self.update_header_status()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle menu item selection from list views."""
        # Deselect items in other list views
        for list_view in self.query(ListView):
            if list_view is not event.list_view:
                list_view.index = None



        item = event.item
        widget_id = item.id

        if not widget_id:
            return

        if self.current_selection == widget_id:
            # Toggle off if the same item is selected again
            self.current_selection = None
            event.list_view.index = None
            self.load_articles()
            return
        
        # Determine the new selection from the item's ID
        new_selection = self._parse_selection_id(widget_id, item)
        
        if new_selection:
            self.current_selection = new_selection

            # Clear search input and uncheck global search when selecting a category
            search_input = self.query_one("#search_input", Input)
            search_input.value = ""
            self.current_query = ""
            
            global_search_checkbox = self.query_one("#global_search_checkbox", Checkbox)
            global_search_checkbox.value = False
            self.global_search_enabled = False

            # Refresh left panel counts when switching views
            self.refresh_left_panel_counts()
            
            # Add notification to show what was selected
            if new_selection == "all_articles_filter":
                self.notify("Selected: All articles", timeout=2)
            
            self.load_articles()



    def _run_cleanup_routine(self):
        """Run cleanup routine to remove old unsaved articles."""
        try:
            config = self.config_manager.get_config()
            retention_days = config.get("feed_retention_days", 30)
            
            deleted_count = self.db.cleanup_old_unsaved_articles(retention_days)
            
            if deleted_count > 0:
                print(f"Cleanup: Removed {deleted_count} old unsaved articles (older than {retention_days} days)")
                
        except Exception as e:
            # Don't let cleanup errors prevent app startup
            print(f"Warning: Cleanup routine failed: {e}")

    def _parse_selection_id(self, widget_id: str, item) -> Optional[str]:
        """Parse widget ID to determine selection."""
        if widget_id.startswith("filter_"):
            return widget_id[len("filter_"):].replace("_", " ")
        elif widget_id.startswith("cat_"):
            return widget_id[len("cat_"):]

        elif widget_id.startswith("tag_"):
            if hasattr(item, 'original_tag_name'):
                return f"tag_{item.original_tag_name}"
            else:
                sanitized_id_part = widget_id[len('tag_'):]
                return f"tag_{sanitized_id_part}"
        elif widget_id in ["all_articles_filter", "saved_articles_filter", "unread_articles_filter", "notes_articles_filter"]:
            return widget_id
        return None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        self.current_query = event.value
        self.refresh_left_panel_counts()
        self.load_articles()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle global search checkbox changes."""
        if event.checkbox.id == "global_search_checkbox":
            self.global_search_enabled = event.value
            self.refresh_left_panel_counts()
            # If there's a current query, re-run the search with new mode
            if self.current_query:
                self.load_articles()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "advanced_search_button":
            self.action_show_advanced_search()

    def load_articles(self) -> None:
        """Prepare for fetching articles and trigger the worker."""
        table = self.query_one("#results_table", ArticleTableWidget)
        abstract_view = self.query_one("#abstract_content", Static)
        table.clear()
        abstract_view.update("No article selected")

        # Check if global search is enabled and we have a query
        if self.global_search_enabled and self.current_query:
            self.notify(f"Searching arXiv globally for: {self.current_query}")
            self.current_results_from_global = True
            self.update_results_title()
            self.fetch_articles_from_arxiv()
            return

        if self.current_query:
            self.notify(f"Searching for: {self.current_query}")

        # Set flag to indicate results are from local database
        self.current_results_from_global = False
        self.current_results_type = None
        self.update_results_title()
        self.fetch_articles_from_db()

    @work(exclusive=True, thread=True)
    def manual_refresh_articles(self) -> None:
        """Manual refresh task to fetch new articles and reload current view."""
        try:
            # Record refresh time
            import time
            self.last_refresh_time = time.time()
            
            # Fetch recent articles (same as startup)
            results = self.fetcher.fetch_recent_articles(days=7, max_per_category=100)
            total_new = sum(results.values())
            
            # Reload the current view to show new articles
            self.call_from_thread(self.load_articles)
            self.call_from_thread(self.refresh_left_panel_counts)
            self.call_from_thread(self.update_header_status)
            
            if total_new > 0:
                self.call_from_thread(
                    self.notify, 
                    f"Refresh complete! Added {total_new} new articles", 
                    title="Manual Refresh", 
                    timeout=5
                )
            else:
                self.call_from_thread(
                    self.notify, 
                    "Refresh complete! No new articles found", 
                    title="Manual Refresh", 
                    timeout=3
                )
        except Exception as e:
            self.call_from_thread(
                self.notify,
                f"Refresh error: {e}",
                title="Error",
                severity="warning",
                timeout=5
            )

    @work(exclusive=True, thread=True)
    def fetch_articles_from_arxiv(self) -> None:
        """Worker to fetch articles directly from arXiv API for global search."""
        abstract_view = self.query_one("#abstract_content", Static)

        try:
            # Use the fetcher to search arXiv
            arxiv_results = self.fetcher.search_arxiv(self.current_query, max_results=100)
            
            # Add status information (not saved, not viewed since from global search)
            self.search_results = []
            for result in arxiv_results:
                result.is_saved = False
                result.is_viewed = False
                self.search_results.append(result)
                
        except Exception as e:
            self.call_from_thread(
                abstract_view.update,
                f"[bold red]Error fetching articles from arXiv:[/bold red]\n{e}",
            )
            self.search_results = []

        self.call_from_thread(self._populate_table)
        self.call_from_thread(self.query_one("#results_table").focus)
    
    @work(exclusive=True, thread=True)
    def fetch_articles_from_arxiv_advanced(self, search_params: Dict[str, Any]) -> None:
        """Worker to fetch articles from arXiv using advanced search parameters."""
        abstract_view = self.query_one("#abstract_content", Static)

        try:
            # Use the fetcher to search arXiv with advanced parameters
            arxiv_results = self.fetcher.search_arxiv(
                query=search_params["query"],
                max_results=search_params["max_results"],
                sort_by=search_params["sort_by"]
            )
            
            # Add status information (not saved, not viewed since from global search)
            self.search_results = []
            for result in arxiv_results:
                result.is_saved = False
                result.is_viewed = False
                self.search_results.append(result)
                
        except Exception as e:
            self.call_from_thread(
                abstract_view.update,
                f"[bold red]Error fetching articles from arXiv:[/bold red]\n{e}",
            )
            self.search_results = []

        # Clear the table before populating with new results
        self.call_from_thread(self.query_one("#results_table").clear)
        self.call_from_thread(self._populate_table)
        self.call_from_thread(self.query_one("#results_table").focus)
    
    @work(exclusive=True, thread=True)
    def fetch_articles_by_references(self, inspire_ids: List[int]) -> None:
        """Worker to fetch articles by INSPIRE-HEP reference IDs."""
        from .ui.utils import get_arxiv_ids_from_inspire_ids
        
        # Get table and abstract view references
        table = self.query_one("#results_table", ArticleTableWidget)
        abstract_view = self.query_one("#abstract_content", Static)

        try:
            # Convert INSPIRE IDs to arXiv IDs
            self.call_from_thread(
                self.notify, 
                f"Converting {len(inspire_ids)} reference IDs to arXiv IDs...", 
                timeout=3
            )
            
            arxiv_ids = get_arxiv_ids_from_inspire_ids(inspire_ids)
            
            if not arxiv_ids:
                self.call_from_thread(
                    self.notify,
                    "No arXiv IDs found for the references",
                    severity="warning",
                    timeout=5
                )
                return
            
            # Fetch articles by arXiv IDs
            arxiv_results = self.fetcher.fetch_articles_by_ids(arxiv_ids)
            
            # Add status information (not saved, not viewed since from references)
            self.search_results = []
            for result in arxiv_results:
                result.is_saved = False
                result.is_viewed = False
                self.search_results.append(result)
            
            # Set flag to indicate results are from references (similar to global search)
            self.current_results_from_global = True
            self.current_results_type = "references"
            self.current_query = ""  # Clear search query since this is reference-based
            
            self.call_from_thread(
                self.notify,
                f"Found {len(self.search_results)} reference articles",
                timeout=3
            )
                
        except Exception as e:
            self.call_from_thread(table.clear)
            self.call_from_thread(
                abstract_view.update,
                f"[bold red]Error fetching reference articles:[/bold red]\n{e}",
            )
            self.search_results = []

        # Clear loading indicator and populate table with real results
        self.call_from_thread(table.clear)
        self.call_from_thread(self._populate_table)
        self.call_from_thread(self.update_results_title)
        self.call_from_thread(self.refresh_left_panel_counts)
        self.call_from_thread(self.query_one("#results_table").focus)
    
    @work(exclusive=True, thread=True)
    def fetch_articles_by_citations(self, inspire_id: int) -> None:
        """Worker to fetch articles that cite the given INSPIRE-HEP record."""
        from .ui.utils import get_citing_articles_from_inspire_id
        
        # Get table and abstract view references
        table = self.query_one("#results_table", ArticleTableWidget)
        abstract_view = self.query_one("#abstract_content", Static)

        try:
            # Get arXiv IDs of citing articles
            self.call_from_thread(
                self.notify, 
                f"Finding articles that cite this paper...", 
                timeout=3
            )
            
            arxiv_ids = get_citing_articles_from_inspire_id(inspire_id, max_results=100)
            
            if not arxiv_ids:
                self.call_from_thread(
                    self.notify,
                    "No citing articles with arXiv IDs found",
                    severity="warning",
                    timeout=5
                )
                return
            
            # Fetch articles by arXiv IDs
            arxiv_results = self.fetcher.fetch_articles_by_ids(arxiv_ids)
            
            # Add status information (not saved, not viewed since from citations)
            self.search_results = []
            for result in arxiv_results:
                result.is_saved = False
                result.is_viewed = False
                self.search_results.append(result)
            
            # Set flag to indicate results are from citations (similar to global search)
            self.current_results_from_global = True
            self.current_results_type = "citations"
            self.current_query = ""  # Clear search query since this is citation-based
            
            self.call_from_thread(
                self.notify,
                f"Found {len(self.search_results)} citing articles",
                timeout=3
            )
                
        except Exception as e:
            self.call_from_thread(table.clear)
            self.call_from_thread(
                abstract_view.update,
                f"[bold red]Error fetching citing articles:[/bold red]\n{e}",
            )
            self.search_results = []

        # Clear loading indicator and populate table with real results
        self.call_from_thread(table.clear)
        self.call_from_thread(self._populate_table)
        self.call_from_thread(self.update_results_title)
        self.call_from_thread(self.refresh_left_panel_counts)
        self.call_from_thread(self.query_one("#results_table").focus)
    
    @work(exclusive=True, thread=True) 
    def fetch_articles_from_db(self) -> None:
        """Worker to fetch and display articles from database."""
        abstract_view = self.query_one("#abstract_content", Static)

        try:
            db_results = self._get_db_results()
            self.search_results = convert_db_results_to_articles(db_results)
            
        except Exception as e:
            self.call_from_thread(
                abstract_view.update,
                f"[bold red]Error fetching articles from database:[/bold red]\n{e}",
            )
            self.search_results = []

        self.call_from_thread(self._populate_table)
        self.call_from_thread(self.query_one("#results_table").focus)

    def _get_db_results(self) -> List[Dict[str, Any]]:
        """Get database results based on current selection and query."""
        config = self.config_manager.get_config()
        retention_days = config.get("feed_retention_days", 30)
        
        # Library selections (no feed retention applied)
        if self.current_selection == "saved_articles_filter":
            if self.current_query:
                saved_results = self.db.get_saved_articles()
                return self._filter_results_by_query(saved_results)
            else:
                return self.db.get_saved_articles()
        
        # Feed selections (apply feed retention)
        elif self.current_selection == "unread_articles_filter":
            if self.current_query:
                unread_results = self.db.get_unread_articles()
                return self._filter_results_by_query(unread_results)
            else:
                return self.db.get_unread_articles()
        
        elif self.current_selection == "all_articles_filter":
            if self.current_query:
                db_results = self.db.search_articles(self.current_query, retention_days)
                self.call_from_thread(self.notify, f"Searched feed articles with query: {self.current_query}, found {len(db_results)} results", timeout=3)
                return db_results
            else:
                db_results = self.db.get_all_articles(retention_days)
                self.call_from_thread(self.notify, f"Loaded {len(db_results)} feed articles (retention: {retention_days} days)", timeout=3)
                return db_results
        
        elif self.current_selection == "notes_articles_filter":
            if self.current_query:
                notes_results = self.db.get_articles_with_notes()
                return self._filter_results_by_query(notes_results)
            else:
                return self.db.get_articles_with_notes()
        
        elif self.current_query and not self.current_selection:
            return self.db.search_articles(self.current_query, retention_days)
        
        elif self.current_selection:
            return self._handle_special_selections(config, retention_days)
        
        return []

    def _filter_results_by_query(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter results by search query."""
        search_lower = self.current_query.lower()
        return [
            result for result in results 
            if (search_lower in result['title'].lower() or 
                search_lower in result['summary'].lower() or
                search_lower in result['authors'].lower())
        ]

    def _handle_special_selections(self, config: Dict[str, Any], retention_days: int) -> List[Dict[str, Any]]:
        """Handle special selections like tags, filters, and categories."""
        if self.current_selection.startswith("tag_"):
            tag_name = self.current_selection[4:]  # Remove "tag_" prefix
            if self.current_query:
                tagged_results = self.db.get_articles_by_tag(tag_name)
                return self._filter_results_by_query(tagged_results)
            else:
                return self.db.get_articles_by_tag(tag_name)
        
        elif self.current_selection in config.get("filters", {}):
            filter_details = config["filters"][self.current_selection]
            search_query = self.current_query or ""
            filter_query = filter_details.get("query")
            filter_categories = filter_details.get("categories")

            if (search_query or filter_query) and filter_categories:
                combined_query = search_query
                if filter_query:
                    combined_query = f"{combined_query} {filter_query}".strip()
                return self.db.search_articles_in_categories(combined_query, filter_categories, retention_days)
            elif search_query or filter_query:
                combined_query = search_query or filter_query
                return self.db.search_articles(combined_query, retention_days)
            elif filter_categories:
                return self._get_articles_from_categories(filter_categories, retention_days)
            else:
                return []

        elif self.current_selection in config.get("categories", {}).values():
            if self.current_query:
                category_results = self.db.get_articles_by_category(self.current_selection, retention_days)
                return self._filter_results_by_query(category_results)
            else:
                self.call_from_thread(self.notify, f"Fetching feed articles for category: {self.current_selection} (retention: {retention_days} days)")
                return self.db.get_articles_by_category(self.current_selection, retention_days)
        
        return []

    def _get_articles_from_categories(self, filter_categories: List[str], retention_days: int) -> List[Dict[str, Any]]:
        """Get articles from multiple categories and remove duplicates."""
        all_results = []
        for cat in filter_categories:
            cat_results = self.db.get_articles_by_category(cat, retention_days)
            all_results.extend(cat_results)
        
        # Remove duplicates and sort by published date
        seen = set()
        unique_results = []
        for result in all_results:
            if result['id'] not in seen:
                seen.add(result['id'])
                unique_results.append(result)
        
        return sorted(unique_results, key=lambda x: x['published_date'], reverse=True)

    def _populate_table(self):
        """Populate the DataTable with search results."""
        table = self.query_one("#results_table", ArticleTableWidget)
        table.populate_articles(self.search_results, self.current_results_from_global)
        
        # Refresh left panel counts after populating table
        self.refresh_left_panel_counts()



    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlighting in the DataTable."""
        abstract_view = self.query_one("#abstract_content", Static)
        table = self.query_one("#results_table", ArticleTableWidget)

        if not self.search_results:
            return

        if event.cursor_row is not None:
            # Use the table's method to get the correct article after sorting
            selected_article = table.get_article_at_row(event.cursor_row)
            
            if selected_article is None:
                return

            # Mark as viewed in database if not saved and not already viewed
            if (not (hasattr(selected_article, 'is_saved') and selected_article.is_saved) and
                not (hasattr(selected_article, 'is_viewed') and selected_article.is_viewed)):
                self.db.mark_article_viewed(selected_article.get_short_id())
                selected_article.is_viewed = True
                
                # Update the status in the table using the correct article
                status = table._build_status_string(selected_article, table.current_is_global_search)
                table.update_cell_at(Coordinate(event.cursor_row, 0), status)
                self.refresh_left_panel_counts()

            # Display article information
            self._display_article_info(selected_article, abstract_view)
        else:
            abstract_view.update("No article selected")

    def _display_article_info(self, article, abstract_view):
        """Display article information in the abstract view."""
        summary = article.summary.replace("\n", " ")
        authors = ", ".join(author.name for author in article.authors)
        pdf_url = article.pdf_url
        categories = ", ".join(article.categories)
        
        # Get article tags
        article_id = article.get_short_id()
        tags = self.db.get_article_tags(article_id)
        tags_display = ""
        if tags:
            tags_str = ", ".join(tags)
            tags_display = f"\n\n[bold]Tags:[/] {tags_str}"
        


        notes_display = ""
        if hasattr(article, 'has_note') and article.has_note:
            notes_display = f"\n\n[bold]Notes:[/] This article has notes ([@click=\"app.manage_notes()\"]view/edit[/])."

        content = (
            f"[bold]{article.title}[/bold]\n\n"
            f"[italic]{authors}[/italic]\n\n"
            f"[bold]Categories:[/] {categories}\n\n"
            f"{summary}\n\n"
            f"Link: [@click=\"app.open_link('{pdf_url}')\"]{pdf_url}[/]"
            f"{tags_display}"
            f"{notes_display}"
        )

        abstract_view.update(content)

    # Action methods
    
    def action_open_link(self, url: str) -> None:
        """Open a URL in the default web browser."""
        webbrowser.open(url)

    def action_save_article(self) -> None:
        """Toggle save/unsave for the currently selected article."""
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            article_id = selected_article.get_short_id()

            # Check if article is currently saved
            if hasattr(selected_article, 'is_saved') and selected_article.is_saved:
                # Article is saved, so unsave it
                if self.db.mark_article_unsaved(article_id):
                    selected_article.is_saved = False
                    self.notify(f"Removed {article_id} from saved list.")

                    # If we are in the saved articles view, just reload the whole list
                    if self.current_selection == "saved_articles_filter":
                        self.load_articles()
                    else:
                        # Otherwise, update the status icon
                        self._update_table_row_status(cursor_row, selected_article)
                    
                    self.refresh_left_panel_counts()
            else:
                # Article is not saved, so save it
                # For global search results, we need to add the article to database first
                if self.current_results_from_global:
                    try:
                        if not self.db.add_article(selected_article):
                            pass  # Article already exists in database, that's fine
                    except Exception as e:
                        self.notify(f"Error adding article to database: {e}", severity="error")
                        return
                
                # Now mark as saved
                if self.db.mark_article_saved(article_id):
                    selected_article.is_saved = True
                    self.notify(f"Saved {article_id}")
                    
                    # Always mark as viewed when saving
                    self.db.mark_article_viewed(article_id)
                    selected_article.is_viewed = True

                    status = table._build_status_string(selected_article, table.current_is_global_search)
                    table.update_cell_at(Coordinate(cursor_row, 0), status)
                    self.refresh_left_panel_counts()

    def action_mark_unread(self) -> None:
        """Mark the currently selected article as unread."""
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            article_id = selected_article.get_short_id()

            # Only mark as unread if it's currently viewed and not saved
            if (hasattr(selected_article, 'is_viewed') and selected_article.is_viewed and 
                not (hasattr(selected_article, 'is_saved') and selected_article.is_saved)):
                if self.db.mark_article_unread(article_id):
                    selected_article.is_viewed = False
                    self.notify(f"Marked {article_id} as unread")
                    
                    status = table._build_status_string(selected_article, table.current_is_global_search)
                    table.update_cell_at(Coordinate(cursor_row, 0), status)
                    self.refresh_left_panel_counts()
            elif hasattr(selected_article, 'is_saved') and selected_article.is_saved:
                self.notify(f"Cannot mark saved article as unread")
            else:
                self.notify(f"Article is already unread")

    def action_mark_all_read(self) -> None:
        """Mark all articles currently displayed in the results table as read."""
        if not self.search_results:
            self.notify("No articles to mark as read", severity="warning")
            return

        table = self.query_one("#results_table", ArticleTableWidget)
        marked_count = 0
        skipped_count = 0

        for row_index, article in enumerate(self.search_results):
            article_id = article.get_short_id()

            # For global search results, we need to add the article to database first
            if self.current_results_from_global:
                try:
                    if not self.db.add_article(article):
                        pass  # Article already exists in database, that's fine
                except Exception as e:
                    self.notify(f"Error adding article {article_id} to database: {e}", severity="error")
                    continue

            # Only mark as viewed if it's not already viewed and not saved
            if not (hasattr(article, 'is_viewed') and article.is_viewed):
                if self.db.mark_article_viewed(article_id):
                    article.is_viewed = True
                    marked_count += 1
                    
                    # Update table cell - only if not saved
                    if not (hasattr(article, 'is_saved') and article.is_saved):
                        self._update_table_row_status(row_index, article)
            else:
                skipped_count += 1

        self.refresh_left_panel_counts()

        # Provide user feedback
        if marked_count > 0:
            if skipped_count > 0:
                self.notify(f"Marked {marked_count} articles as read ({skipped_count} already read)")
            else:
                self.notify(f"Marked all {marked_count} articles as read")
        else:
            self.notify("All articles were already read")

    def action_download_and_open_pdf(self) -> None:
        """Download the PDF for the selected article and open it."""
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            self.download_and_open_worker(selected_article)

    def action_open_arxiv_link(self) -> None:
        """Open the arXiv link for the selected article in browser."""
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            article_id = selected_article.get_short_id()
            arxiv_url = f"https://arxiv.org/abs/{article_id}"
            webbrowser.open(arxiv_url)
            self.notify(f"Opened arXiv link for {article_id}")
        else:
            self.notify("No article selected", severity="warning")

    @work(exclusive=True, thread=True)
    def download_and_open_worker(self, selected_article) -> None:
        """Worker to download and open PDF."""
        article_id = selected_article.get_short_id()
        self.notify(f"Downloading {article_id}...", title="Download", timeout=10)

        articles_dir = self.user_dirs.articles_dir
        try:
            # Directory is already created by UserDirectoryManager
            filepath = selected_article.download_pdf(dirpath=articles_dir)

            system = platform.system()
            if system == "Darwin":  # macOS
                subprocess.run(["open", filepath], check=True)
            elif system == "Windows":
                os.startfile(filepath)
            else:  # linux variants
                subprocess.run(["xdg-open", filepath], check=True)

            self.notify(f"Opened {article_id}.pdf", title="Success")
        except Exception as e:
            self.notify(
                f"Error downloading or opening PDF: {e}",
                title="Error",
                severity="error",
            )

    def action_focus_search(self) -> None:
        """Focus the search input."""
        self.query_one("#search_input", Input).focus()

    def action_global_search_and_focus(self) -> None:
        """Enable global search and focus the search input."""
        # Enable global search
        self.global_search_enabled = True
        global_search_checkbox = self.query_one("#global_search_checkbox", Checkbox)
        global_search_checkbox.value = True
        
        # Focus the search input
        self.query_one("#search_input", Input).focus()

    def action_show_advanced_search(self) -> None:
        """Show the advanced search popup."""
        self.push_screen(AdvancedSearchPopupScreen(), self.advanced_search_callback)

    def action_show_selection_popup(self) -> None:
        """Show a popup to select a view (category, filter, or saved)."""
        config = self.config_manager.get_config()
        
        options = [
            ("Unread", "special:unread_articles_filter"),
            ("Saved", "special:saved_articles_filter")
        ]

        filter_options = [
            (f"Filter: {name}", f"filter:{name}") for name in config.get("filters", {})
        ]

        category_options = [
            (f"Category: {name}", f"cat:{code}")
            for name, code in config.get("categories", {}).items()
        ]

        all_options = options + filter_options + category_options

        self.push_screen(
            SelectionPopupScreen(all_options), self.selection_popup_callback
        )

    def action_refresh_articles(self) -> None:
        """Manually refresh and fetch new articles."""
        self.notify("Refreshing articles...", title="Manual Refresh", timeout=3)
        self.manual_refresh_articles()

    def action_show_inspire_citation(self) -> None:
        """Show inspire-hep citation for the currently selected article."""
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            self.fetch_inspire_citation(selected_article)
        else:
            self.notify("No article selected", severity="warning")

    def action_manage_tags(self) -> None:
        """Show tag management popup for the currently selected article."""
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            self.show_tag_popup(selected_article)
        else:
            self.notify("No article selected", severity="warning")



    def action_manage_notes(self) -> None:
        """Open the notes popup for the currently selected article."""
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            self.show_notes_popup(selected_article)
        else:
            self.notify("No article selected", severity="warning")

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    # Popup and worker methods
    
    def show_notes_popup(self, article) -> None:
        """Create and show the notes popup for an article."""
        article_id = article.get_short_id()
        notes_path_str = self.db.get_notes_path(article_id)

        if not notes_path_str:
            # Create a new notes file using user directory manager
            notes_path_str = self.user_dirs.get_notes_file_path(article_id, article.title)
            
            # Create the file and update database
            with open(notes_path_str, "w") as f:
                f.write(f"# Notes for: {article.title}\n\n")
            
            self.db.set_notes_path(article_id, notes_path_str)

            # Update article object and table view
            article.notes_file_path = notes_path_str
            article.has_note = True
            table = self.query_one("#results_table", ArticleTableWidget)
            if table.cursor_row is not None:
                self._update_table_row_status(table.cursor_row, article)

        self.push_screen(
            NotesPopupScreen(notes_path_str, article.title), 
            self.notes_popup_callback
        )

    def notes_popup_callback(self, result: Optional[str]) -> None:
        """Handle the result from the notes popup."""
        if result is not None:
            # When notes are saved, update the UI to reflect the saved status
            # (the article is automatically marked as saved in set_notes_path)
            table = self.query_one("#results_table", ArticleTableWidget)
            cursor_row = table.cursor_row
            if cursor_row is not None:
                selected_article = table.get_article_at_row(cursor_row)
                if selected_article is not None:
                    selected_article.is_saved = True
                    self._update_table_row_status(cursor_row, selected_article)
            
            self.notify("Notes saved successfully! Article automatically marked as saved.", timeout=3)
        else:
            self.notify("Notes closed without saving.", timeout=2)

    def show_tag_popup(self, article) -> None:
        """Show the tag management popup for an article."""
        article_id = article.get_short_id()
        existing_tags = self.db.get_article_tags(article_id)
        all_tags = self.db.get_all_tags()
        
        self.push_screen(
            TagPopupScreen(article_id, article.title, existing_tags, all_tags),
            self.tag_popup_callback
        )



    def tag_popup_callback(self, result) -> None:
        """Handle the result from the tag popup."""
        if result is None:
            return
            
        tags_to_add, tags_to_remove = result
        
        table = self.query_one("#results_table", ArticleTableWidget)
        cursor_row = table.cursor_row
        
        if cursor_row is not None:
            selected_article = table.get_article_at_row(cursor_row)
            if selected_article is None:
                return
            article_id = selected_article.get_short_id()
            
            # For global search results, we need to add the article to database first
            if self.current_results_from_global:
                try:
                    if not self.db.add_article(selected_article):
                        pass  # Article already exists in database, that's fine
                except Exception as e:
                    self.notify(f"Error adding article to database: {e}", severity="error")
                    return
            
            # Remove tags
            for tag_name in tags_to_remove:
                self.db.remove_article_tag(article_id, tag_name)
            
            # Add tags (this automatically marks article as saved)
            tags_added = False
            for tag_name in tags_to_add:
                if self.db.add_article_tag(article_id, tag_name):
                    tags_added = True
            
            # Cleanup any orphan tags
            if tags_to_remove:
                removed_count = self.db.cleanup_orphan_tags()
                if removed_count > 0:
                    self.notify(f"Removed {removed_count} unused tag(s).", timeout=3)

            # Update article's has_tags and saved status
            if tags_to_add or tags_to_remove:
                selected_article.has_tags = self.db.article_has_tags(article_id)
                
                # If tags were added, the article is now saved (done automatically in add_article_tag)
                if tags_added:
                    selected_article.is_saved = True
                
                # Update the table row status to show/hide "t" and "s" indicators
                self._update_table_row_status(cursor_row, selected_article)
                
                # Reload left panel to show new tags if any were created
                self.call_later(self.reload_left_panel)
                
                # Refresh all left panel counts
                self.refresh_left_panel_counts()
            
            if tags_to_add or tags_to_remove:
                if tags_added:
                    self.notify(f"Updated tags for {article_id}. Article automatically marked as saved.", timeout=3)
                else:
                    self.notify(f"Updated tags for {article_id}")



    def bibtex_popup_callback(self, result) -> None:
        """Handle the result from the bibtex popup."""
        if result is None:
            return
        
        # Check if this is a search_references or search_citations action
        if isinstance(result, tuple) and len(result) == 2:
            action, data = result
            if action == "search_references":
                inspire_ids = data
                # Clear any current selection and search
                self.current_selection = None
                self.current_query = ""
                
                # Deselect all list views
                for list_view in self.query(ListView):
                    list_view.index = None
                
                # Clear search input and disable global search checkbox
                search_input = self.query_one("#search_input", Input)
                search_input.value = ""
                global_search_checkbox = self.query_one("#global_search_checkbox", Checkbox)
                global_search_checkbox.value = False
                self.global_search_enabled = False
                
                # Clear table and show loading state immediately
                table = self.query_one("#results_table", ArticleTableWidget)
                abstract_view = self.query_one("#abstract_content", Static)
                table.clear()
                abstract_view.update("Loading reference articles...")
                self.search_results = []
                
                # Add loading indicator to table
                table.clear()
                table.add_row("⏳", "[italic]Loading reference articles...[/italic]", "[dim]Please wait[/dim]", "[dim]Fetching...[/dim]", "[dim]...[/dim]")
                
                # Set flags for reference mode
                self.current_results_from_global = True
                self.current_results_type = "references"
                self.update_results_title()
                
                # Trigger the references fetch
                self.fetch_articles_by_references(inspire_ids)
            
            elif action == "search_citations":
                inspire_id = data
                # Clear any current selection and search
                self.current_selection = None
                self.current_query = ""
                
                # Deselect all list views
                for list_view in self.query(ListView):
                    list_view.index = None
                
                # Clear search input and disable global search checkbox
                search_input = self.query_one("#search_input", Input)
                search_input.value = ""
                global_search_checkbox = self.query_one("#global_search_checkbox", Checkbox)
                global_search_checkbox.value = False
                self.global_search_enabled = False
                
                # Clear table and show loading state immediately
                table = self.query_one("#results_table", ArticleTableWidget)
                abstract_view = self.query_one("#abstract_content", Static)
                table.clear()
                abstract_view.update("Loading citing articles...")
                self.search_results = []
                
                # Add loading indicator to table
                table.clear()
                table.add_row("⏳", "[italic]Loading citing articles...[/italic]", "[dim]Please wait[/dim]", "[dim]Fetching...[/dim]", "[dim]...[/dim]")
                
                # Set flags for citation mode
                self.current_results_from_global = True
                self.current_results_type = "citations"
                self.update_results_title()
                
                # Trigger the citations fetch
                self.fetch_articles_by_citations(inspire_id)



    @work(exclusive=True, thread=True)
    def fetch_inspire_citation(self, article) -> None:
        """Worker to fetch bibtex citation from inspire-hep."""
        article_id = article.get_short_id()
        self.call_from_thread(
            self.notify, 
            f"Fetching citation for {article_id}...", 
            title="Inspire-HEP", 
            timeout=5
        )

        # get literature entry
        client = Client()
        try:
            base_article_id = article_id.split('v')[0] if 'v' in article_id else article_id
            search_url = f"https://inspirehep.net/api/literature?q=arxiv:{base_article_id}&format=json"
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data.get('hits') or len(data['hits']['hits']) == 0:
                self.call_from_thread(
                    self.notify,
                    f"No citation found for {base_article_id}",
                    title="Inspire-HEP", 
                    severity="warning",
                    timeout=5
                )
                return
            # Get inspire ID from first result
            inspire_id = data['hits']['hits'][0]['metadata'].get('control_number')
            literature_entry = client.get_literature_object(str(inspire_id))
            n_citations = literature_entry.get_citation_count()
            n_citations_text = f"Citations: {n_citations}"
            self.call_from_thread(
                self.notify,
                n_citations_text,
                title="Inspire-HEP",
                timeout=5
            )
            references = literature_entry.get_references_ids()
            print(references)
            # Get bibtex entry
            bibtex_url = f"https://inspirehep.net/api/literature?q=arxiv:{base_article_id}&format=bibtex"
            bibtex_response = requests.get(bibtex_url, timeout=10)
            bibtex_response.raise_for_status()
            
            bibtex_content = bibtex_response.text

            inspire_link = f"https://inspirehep.net/literature/{inspire_id}"
            
            # Copy to clipboard
            pyperclip.copy(bibtex_content)
            
            # Notify user
            self.call_from_thread(
                self.notify,
                "BibTeX citation copied to clipboard!",
                title="Inspire-HEP",
                timeout=5
            )
            # Show the bibtex popup
            self.call_from_thread(
                self.push_screen,
                BibtexPopupScreen(
                    bibtex_content,
                    n_citations,
                    inspire_link,
                    article.title,
                    references,
                    inspire_id
                ),
                self.bibtex_popup_callback
            )

        except Exception as e:
            self.call_from_thread(
                self.notify,
                f"Error fetching citation: {str(e)}",
                title="Inspire-HEP Error",
                severity="error",
                timeout=5
            )
    
    def advanced_search_callback(self, search_params):
        """Callback for when advanced search is completed."""
        print(f"DEBUG: Advanced search callback called with params: {search_params}")
        if not search_params:
            print("DEBUG: No search params, returning")
            return
        
        # Clear any current selection and search
        self.current_selection = None
        
        # Deselect all list views
        for list_view in self.query(ListView):
            list_view.index = None
        
        # Set the search parameters
        self.current_query = search_params["query"]
        self.advanced_search_params = search_params
        
        # Update search input with the formatted query
        search_input = self.query_one("#search_input", Input)
        search_input.value = search_params["query"]
        
        # Enable global search mode
        global_search_checkbox = self.query_one("#global_search_checkbox", Checkbox)
        global_search_checkbox.value = True
        self.global_search_enabled = True
        
        # Set flags for global search results
        self.current_results_from_global = True
        self.current_results_type = None
        
        # Update title and trigger search
        self.update_results_title()
        self.refresh_left_panel_counts()
        
        # Clear table and show loading
        table = self.query_one("#results_table", ArticleTableWidget)
        abstract_view = self.query_one("#abstract_content", Static)
        table.clear()
        abstract_view.update("Loading search results...")
        self.search_results = []
        
        # Add loading indicator
        table.clear()
        table.add_row("⏳", "[italic]Searching arXiv...[/italic]", "[dim]Please wait[/dim]", "[dim]Fetching...[/dim]", "[dim]...[/dim]")
        
        # Notify user
        max_results = search_params["max_results"]
        sort_by = search_params["sort_by"]
        fields = search_params["selected_fields"]
        field_text = "all fields" if "all" in fields else ", ".join(fields)
        
        self.notify(f"Advanced search: {max_results} results, sorted by {sort_by}, searching {field_text}")
        
        # Debug: Log the actual query being used
        debug_log(f"Advanced search query: '{search_params['query']}', max_results: {max_results}")
        
        # Trigger the search
        self.fetch_articles_from_arxiv_advanced(search_params)

    def selection_popup_callback(self, selection_value):
        """Callback for when a view is selected from the popup."""
        if not selection_value:
            return

        # Deselect any currently selected button first
        for list_view in self.query(ListView):
            list_view.index = None

        value_type, value = selection_value.split(":", 1)

        target_list_view_id = ""
        target_item_id = ""

        if value_type == "special":
            self.current_selection = value
            if value == "saved_articles_filter":
                target_list_view_id = "library_articles_list"
            else:
                target_list_view_id = "feed_articles_list"
            target_item_id = value
        elif value_type == "filter":
            self.current_selection = value
            target_list_view_id = "filters_list"
            target_item_id = f"filter_{value.replace(' ', '_')}"
        elif value_type == "cat":
            self.current_selection = value
            target_list_view_id = "categories_list"
            target_item_id = f"cat_{value}"

        if target_list_view_id and target_item_id:
            try:
                target_list_view = self.query_one(f"#{target_list_view_id}", ListView)
                # Find the item index by its ID
                for i, item in enumerate(target_list_view.children):
                    if item.id == target_item_id:
                        target_list_view.index = i
                        break
            except Exception:
                pass # It might not exist

        self.load_articles()

    # Utility methods
    
    def update_results_title(self) -> None:
        """Update the results table title based on current selection."""
        try:
            results_title = self.query_one("#results_title", Static)
            
            # Check if we're showing global search results
            if self.current_results_from_global and self.current_query:
                title = "ArXiv Web Search"
            elif self.current_results_from_global and not self.current_query:
                if self.current_results_type == "references":
                    title = "Reference Articles"
                elif self.current_results_type == "citations":
                    title = "Citing Articles"
                else:
                    title = "External Articles"
            else:
                # Default title
                title = "Articles"
                
                if self.current_selection:
                    if self.current_selection == "all_articles_filter":
                        title = "All Articles"
                    elif self.current_selection == "unread_articles_filter":
                        title = "Unread Articles"
                    elif self.current_selection == "saved_articles_filter":
                        title = "Saved Articles"
                    elif self.current_selection == "notes_articles_filter":
                        title = "Articles with Notes"

                    elif self.current_selection.startswith("tag_"):
                        tag_name = self.current_selection[4:]  # Remove "tag_" prefix
                        title = f"Tag: {tag_name}"
                    elif self.current_selection in self.config_manager.get_filters():
                        title = f"Filter: {self.current_selection}"
                    else:
                        # Check categories
                        config = self.config_manager.get_config()
                        categories = config.get("categories", {})
                        for name, code in categories.items():
                            if code == self.current_selection:
                                title = f"Category: {name}"
                                break
                
                # Add search info if there's a query (for local search only)
                if self.current_query and not self.current_results_from_global:
                    title += f" - Search: {self.current_query}"
            
            results_title.update(title)
        except Exception:
            pass  # Don't let title update errors break the app

    def refresh_left_panel_counts(self) -> None:
        """Update the unread counts in the left panel."""
        try:
            # Update All articles count
            try:
                all_count = self.db.get_all_articles_count()
                all_text = f"All articles"
                all_item = self.query_one("#all_articles_filter", ListItem)
                all_static = all_item.query_one(Static)
                all_static.update(all_text)
            except Exception:
                pass
                
            # Update Unread count
            unread_count = self.db.get_unread_count()
            unread_text = f"Unread ({unread_count})" if unread_count > 0 else "Unread"
            try:
                unread_item = self.query_one("#unread_articles_filter", ListItem)
                unread_static = unread_item.query_one(Static)
                unread_static.update(unread_text)
            except Exception:
                pass
            
            # Update Saved Articles count
            saved_unread_count = self.db.get_unread_saved_count()
            saved_text = f"Saved ({saved_unread_count})" if saved_unread_count > 0 else "Saved"
            try:
                saved_item = self.query_one("#saved_articles_filter", ListItem)
                saved_static = saved_item.query_one(Static)
                saved_static.update(saved_text)
            except Exception:
                pass
            
            # Update Notes count
            notes_unread_count = self.db.get_unread_count_with_notes()
            notes_text = f"Notes ({notes_unread_count})" if notes_unread_count > 0 else "Notes"
            try:
                notes_item = self.query_one("#notes_articles_filter", ListItem)
                notes_static = notes_item.query_one(Static)
                notes_static.update(notes_text)
            except Exception:
                pass
            

            self._update_tag_counts()
            self._update_filter_counts()
            self._update_category_counts()
                        
        except Exception as e:
            # Don't let count refresh errors break the app
            pass





    def _update_tag_counts(self):
        """Update tag counts in the left panel."""
        all_tags = self.db.get_all_tags()
        for tag in all_tags:
            unread_count = self.db.get_unread_count_by_tag(tag['name'])
            tag_text = f"{tag['name']} ({unread_count})" if unread_count > 0 else tag['name']
            sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag['name'])
            
            tag_widget_id = f"tag_{sanitized_tag_name}"
            try:
                tag_item = self.query_one(f"#{tag_widget_id}", ListItem)
                tag_static = tag_item.query_one(Static)
                tag_static.update(tag_text)
            except Exception:
                pass  # Widget might not exist yet

    def _update_filter_counts(self):
        """Update filter counts in the left panel."""
        config = self.config_manager.get_config()
        retention_days = config.get("feed_retention_days", 30)
        filters = config.get("filters", {})
        for name, filter_config in filters.items():
            unread_count = self.db.get_unread_count_by_filter(filter_config, retention_days)
            filter_text = f"{name} ({unread_count})" if unread_count > 0 else name
            
            filter_widget_id = f"filter_{name.replace(' ', '_')}"
            try:
                filter_item = self.query_one(f"#{filter_widget_id}", ListItem)
                filter_static = filter_item.query_one(Static)
                filter_static.update(filter_text)
            except Exception:
                pass  # Widget might not exist yet

    def _update_category_counts(self):
        """Update category counts in the left panel."""
        config = self.config_manager.get_config()
        retention_days = config.get("feed_retention_days", 30)
        categories = config.get("categories", {})
        for name, code in categories.items():
            unread_count = self.db.get_unread_count_by_category(code, retention_days)
            category_text = f"{name} ({unread_count})" if unread_count > 0 else name
            
            try:
                category_item = self.query_one(f"#cat_{code}", ListItem)
                category_static = category_item.query_one(Static)
                category_static.update(category_text)
            except Exception:
                pass  # Widget might not exist yet

    def _update_table_row_status(self, row_index: int, article) -> None:
        """Update the status column for a specific table row."""
        table = self.query_one("#results_table", ArticleTableWidget)
        status = table._build_status_string(article, table.current_is_global_search)
        table.update_cell_at(Coordinate(row_index, 0), status)

    def reload_left_panel(self) -> None:
        """Update the tags section in the left panel to show new tags."""
        tags_container = self.query_one("#tags_container", Vertical)
        all_tags = self.db.get_all_tags()
        
        # Check if tags_list exists
        existing_tags_list = tags_container.query("#tags_list")
        
        if not all_tags:
            # If no tags exist, remove tags list if it exists
            if existing_tags_list:
                existing_tags_list[0].remove()
            # Remove title if it exists and no other content
            title_widgets = tags_container.query(".pane_title")
            if title_widgets and not tags_container.query("#tags_list"):
                title_widgets[0].remove()
            return
        
        # Ensure "Tags" title exists
        if not tags_container.query(".pane_title"):
            tags_container.mount(Static("Tags", classes="pane_title"), before=0)
        
        if existing_tags_list:
            # Update existing tags list
            tags_list_view = existing_tags_list[0]
            current_selection_index = tags_list_view.index
            selected_item_id = None
            if current_selection_index is not None and current_selection_index < len(tags_list_view.children):
                selected_item_id = tags_list_view.children[current_selection_index].id
            
            # Get current tag items in the list
            current_tag_ids = set(item.id for item in tags_list_view.children)
            
            # Build new tag items
            new_tag_items = []
            new_selection_index = None
            
            for i, tag in enumerate(all_tags):
                unread_count = self.db.get_unread_count_by_tag(tag['name'])
                tag_text = f"{tag['name']} ({unread_count})" if unread_count > 0 else tag['name']
                sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag['name'])
                item_id = f"tag_{sanitized_tag_name}"
                
                if item_id not in current_tag_ids:
                    # This is a new tag, create the item
                    tag_item = ListItem(Static(tag_text), id=item_id)
                    tag_item.original_tag_name = tag['name']
                    new_tag_items.append(tag_item)
                
                if item_id == selected_item_id:
                    new_selection_index = i
            
            # Add new tag items to the list
            for tag_item in new_tag_items:
                tags_list_view.mount(tag_item)
            
            # Update selection if needed
            if new_selection_index is not None:
                tags_list_view.index = new_selection_index
        
        else:
            # Create tags list for the first time
            tag_items = []
            for tag in all_tags:
                unread_count = self.db.get_unread_count_by_tag(tag['name'])
                tag_text = f"{tag['name']} ({unread_count})" if unread_count > 0 else tag['name']
                sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag['name'])
                
                tag_item = ListItem(Static(tag_text), id=f"tag_{sanitized_tag_name}")
                tag_item.original_tag_name = tag['name']
                tag_items.append(tag_item)
            
            new_tags_list = ListView(*tag_items, id="tags_list")
            tags_container.mount(new_tags_list)

        # Refresh all left panel counts since tagging operations could affect various counts
        self.refresh_left_panel_counts()
        
        self.notify("Tags updated successfully!", timeout=3)



    def update_header_status(self) -> None:
        """Update the header status with feed and library counts and last refresh time."""
        try:
            header_status = self.query_one("#header_status", Static)
            
            # Get retention period from config
            config = self.config_manager.get_config()
            retention_days = config.get("feed_retention_days", 30)
            
            # Get feed and library counts
            feed_count = self.db.get_feed_articles_count(retention_days)
            library_count = self.db.get_saved_articles_count()
            
            status_text = f"Feed: {feed_count} articles  Library: {library_count} articles"
            
            # Add last refresh time if available
            if self.last_refresh_time:
                from datetime import datetime
                refresh_time = datetime.fromtimestamp(self.last_refresh_time)
                formatted_time = refresh_time.strftime("%Y-%m-%d %H:%M:%S")
                status_text += f"  |  Last refresh: {formatted_time}"
            
            header_status.update(status_text)
        except Exception:
            pass  # Don't let header status errors break the app
