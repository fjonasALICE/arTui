import arxiv
import yaml
import webbrowser
import os
import platform
import subprocess
import json
import requests
import pyperclip
import re
import sys

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header,
    Footer,
    DataTable,
    Button,
    Static,
    Input,
    Select,
    Tree,
    Checkbox,
    TextArea,
    MarkdownViewer,
    ListView,
    ListItem,
)
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual import work, events
import asyncio
from database import ArticleDatabase
from startup_fetcher import StartupFetcher
from typing import Optional
from pyinspirehep import Client


# Legacy file paths for migration
VIEWED_ARTICLES_FILE = "viewed_articles.txt"
SAVED_ARTICLES_FILE = "saved_articles.txt"


def debug_log(msg):
    """Write debug message to stderr and a debug file."""
    print(f"DEBUG: {msg}", file=sys.stderr, flush=True)
    with open("debug.log", "a") as f:
        f.write(f"DEBUG: {msg}\n")
        f.flush()

def load_config():
    """Load categories and filters from the YAML file."""
    try:
        with open("arxiv_config.yaml", "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {"categories": {}, "filters": {}}


class SelectionPopupScreen(ModalScreen):
    """Screen with a dropdown to select a view."""

    def __init__(self, options, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = options

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Select a View", id="selection_popup_title"),
            Select(self.options, prompt="Select...", id="selection_popup_select"),
            id="selection_popup_dialog",
        )

    def on_mount(self) -> None:
        self.query_one(Select).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        self.dismiss(event.value)


class BibtexPopupScreen(ModalScreen):
    """Screen to display bibtex citation information."""

    def __init__(self, bibtex_content, n_citations, inspire_link, article_title, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bibtex_content = bibtex_content
        self.n_citations = n_citations
        self.inspire_link = inspire_link
        self.article_title = article_title

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("[bold $primary]Inspire-HEP Information[/]", id="bibtex_popup_title"),
            Static(f"Article: {self.article_title[:60]}{'...' if len(self.article_title) > 60 else ''}", id="bibtex_article_title"),
            Static(f"Citations: {self.n_citations}", id="citation_count"),
            Static(f"Inspire Link: [@click=\"app.open_link('{self.inspire_link}')\"]{self.inspire_link}[/]", id="inspire_link"),
            Static("[bold $primary]BibTeX[/]", id="bibtex_label"),
            VerticalScroll(
                Static(self.bibtex_content, id="bibtex_content"),
                id="bibtex_scroll"
            ),
            Horizontal(
                Button("Copy BibTeX", variant="primary", id="bibtex_copy_button"),
                Button("Close", variant="primary", id="bibtex_close_button"),
                id="bibtex_buttons"
            ),
            id="bibtex_popup_dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#bibtex_close_button", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bibtex_close_button":
            self.dismiss()
        elif event.button.id == "bibtex_copy_button":
            import pyperclip
            pyperclip.copy(self.bibtex_content)
            self.notify("BibTeX copied to clipboard", timeout=2)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
class TagPopupScreen(ModalScreen):
    """Screen to manage tags for an article."""

    def __init__(self, article_id, article_title, existing_tags, all_tags, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.article_id = article_id
        self.article_title = article_title
        self.existing_tags = set(existing_tags) if existing_tags else set()
        self.all_tags = all_tags if all_tags else []
        self.checkboxes = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="tag_popup_dialog"):
            yield Static(f"Manage Tags", id="tag_popup_title")
            yield Static(f"Article: {self.article_title[:60]}{'...' if len(self.article_title) > 60 else ''}", 
                        id="tag_popup_article")
            
            # New tag input
            with Horizontal(id="new_tag_container"):
                yield Input(placeholder="Enter new tag name...", id="new_tag_input")
                yield Button("Add", variant="primary", id="add_tag_button")
            
            # Existing tags
            with VerticalScroll(id="tags_scroll"):
                if self.all_tags:
                    for tag_data in self.all_tags:
                        tag_name = tag_data['name']
                        sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag_name)
                        is_checked = tag_name in self.existing_tags
                        checkbox = Checkbox(f"{tag_name} ({tag_data['article_count']})", 
                                          value=is_checked, 
                                          id=f"tag_checkbox_{sanitized_tag_name}")
                        self.checkboxes[tag_name] = checkbox
                        yield checkbox
                else:
                    yield Static("No tags exist yet. Create one above.", id="no_tags_message")
            
            with Horizontal(id="tag_buttons"):
                yield Button("Save", variant="primary", id="save_tags_button")
                yield Button("Cancel", id="cancel_tags_button")

    def on_mount(self) -> None:
        self.query_one("#new_tag_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        print(f"DEBUG: TagPopupScreen button pressed: {event.button.id}")
        if event.button.id == "cancel_tags_button":
            print("DEBUG: Cancel button clicked")
            self.dismiss()
        elif event.button.id == "save_tags_button":
            print("DEBUG: Save button clicked, calling _save_tags")
            self._save_tags()
        elif event.button.id == "add_tag_button":
            print("DEBUG: Add button clicked")
            self._add_new_tag()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "new_tag_input":
            self._add_new_tag()

    def _add_new_tag(self) -> None:
        """Add a new tag and refresh the tag list."""
        print("DEBUG: _add_new_tag called")
        new_tag_input = self.query_one("#new_tag_input", Input)
        tag_name = new_tag_input.value.strip()
        print(f"DEBUG: New tag name: '{tag_name}'")
        
        if not tag_name:
            print("DEBUG: Empty tag name, returning")
            return
            
        # Check if tag already exists
        if any(tag['name'].lower() == tag_name.lower() for tag in self.all_tags):
            self.notify(f"Tag '{tag_name}' already exists", severity="warning")
            new_tag_input.value = ""
            print(f"DEBUG: Tag '{tag_name}' already exists")
            return
        
        # Add to all_tags list and create checkbox
        new_tag_data = {'name': tag_name, 'article_count': 0}
        self.all_tags.append(new_tag_data)
        print(f"DEBUG: Added to all_tags list: {new_tag_data}")
        
        # Create and add checkbox
        sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag_name)
        checkbox = Checkbox(f"{tag_name} (0)", value=True, id=f"tag_checkbox_{sanitized_tag_name}")
        self.checkboxes[tag_name] = checkbox
        print(f"DEBUG: Created checkbox for '{tag_name}', checked: {checkbox.value}")
        
        # Remove no tags message if it exists
        try:
            no_tags = self.query_one("#no_tags_message")
            no_tags.remove()
            print("DEBUG: Removed 'no tags' message")
        except:
            print("DEBUG: No 'no tags' message to remove")
            pass
            
        # Add checkbox to scroll area
        scroll_area = self.query_one("#tags_scroll", VerticalScroll)
        scroll_area.mount(checkbox)
        print("DEBUG: Mounted checkbox to scroll area")
        
        new_tag_input.value = ""
        self.notify(f"Added tag '{tag_name}'")

    def _save_tags(self) -> None:
        """Save the current tag selections."""
        print("DEBUG: _save_tags called")
        selected_tags = set()
        
        print(f"DEBUG: checkboxes: {list(self.checkboxes.keys())}")
        
        # Check which tags are selected
        for tag_name, checkbox in self.checkboxes.items():
            print(f"DEBUG: Tag '{tag_name}': value={checkbox.value}")
            if checkbox.value:
                selected_tags.add(tag_name)
        
        print(f"DEBUG: selected_tags: {selected_tags}")
        print(f"DEBUG: existing_tags: {self.existing_tags}")
        
        # Return the changes
        tags_to_add = selected_tags - self.existing_tags
        tags_to_remove = self.existing_tags - selected_tags
        
        print(f"DEBUG: tags_to_add: {tags_to_add}")
        print(f"DEBUG: tags_to_remove: {tags_to_remove}")
        
        self.dismiss((tags_to_add, tags_to_remove))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()


class NotesPopupScreen(ModalScreen):
    """Screen to display and edit notes for an article."""

    def __init__(self, notes_path: str, article_title: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notes_path = notes_path
        self.article_title = article_title
        self.original_content = ""
        self.text_area = None

    def compose(self) -> ComposeResult:
        # Read initial content
        if os.path.exists(self.notes_path):
            with open(self.notes_path, "r") as f:
                self.original_content = f.read()

        yield Vertical(
            Static(f"Notes for: {self.article_title[:60]}{'...' if len(self.article_title) > 60 else ''}", id="notes_popup_title"),
            TextArea(self.original_content, id="notes_text_area"),
            Horizontal(
                Button("Save", variant="primary", id="notes_save_button"),
                Button("Close", id="notes_close_button"),
                id="notes_buttons"
            ),
            id="notes_popup_dialog",
        )

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "notes_close_button":
            self.dismiss(None)
        elif event.button.id == "notes_save_button":
            new_content = self.query_one(TextArea).text
            with open(self.notes_path, "w") as f:
                f.write(new_content)
            self.dismiss(new_content)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class ArxivReader(App):
    """A Textual app to view arXiv articles."""

    CSS_PATH = "main.css"
    TITLE = "ArTui"
    # Set default theme (you can use "textual-dark", "textual-light", etc.)
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
        ("q", "quit", "Quit"),
    ]

    def on_key(self, event) -> None:
        """Debug key presses."""
        print(f"DEBUG: Key pressed: {event.key}")
        # Don't call super() to avoid interfering with normal key handling

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle menu item selection from list views."""
        # Deselect items in other list views
        for list_view in self.query(ListView):
            if list_view is not event.list_view:
                list_view.index = None

        new_selection = None
        item = event.item
        widget_id = item.id

        if not widget_id:
            return

        if self.current_selection == widget_id:
            # Toggle off if the same item is selected again
            self.current_selection = None
            event.list_view.index = None
            self.load_articles() # Reload to clear view
            return
        
        # Determine the new selection from the item's ID
        if widget_id.startswith("filter_"):
            new_selection = widget_id[len("filter_") :].replace("_", " ")
        elif widget_id.startswith("cat_"):
            new_selection = widget_id[len("cat_") :]
        elif widget_id.startswith("tag_"):
            if hasattr(item, 'original_tag_name'):
                new_selection = f"tag_{item.original_tag_name}"
            else:
                sanitized_id_part = widget_id[len('tag_'):]
                new_selection = f"tag_{sanitized_id_part}"
        elif widget_id == "all_articles_filter":
            debug_log("All articles item selected")
            new_selection = "all_articles_filter"
        elif widget_id == "saved_articles_filter":
            new_selection = "saved_articles_filter"
        elif widget_id == "unread_articles_filter":
            new_selection = "unread_articles_filter"

        if new_selection:
            self.current_selection = new_selection

            # Clear search input and uncheck global search when selecting a category
            search_input = self.query_one("#search_input", Input)
            search_input.value = ""
            self.current_query = ""
            
            global_search_checkbox = self.query_one("#global_search_checkbox", Checkbox)
            global_search_checkbox.value = False
            self.global_search_enabled = False

            # Refresh left panel counts when switching views to ensure they're up to date
            self.refresh_left_panel_counts()
            
            # Add notification to show what was selected
            if new_selection == "all_articles_filter":
                self.notify("Selected: All articles", timeout=2)
            
            self.load_articles()


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = load_config()
        self.search_results = []
        self.current_query = ""
        self.current_selection = None
        self.global_search_enabled = False # New attribute for global search
        self.current_results_from_global = False # Track if current results are from global search
        self.last_refresh_time = None # Track when manual refresh was last run
        # Set default theme (dark mode for nord-like appearance)
        self.dark = True
        self.theme = "monokai"
        # Initialize database (creates database file if it doesn't exist)
        self.db = ArticleDatabase()
        # Migrate existing data from text files
        migration_stats = self.db.migrate_from_text_files(SAVED_ARTICLES_FILE, VIEWED_ARTICLES_FILE)
        if migration_stats["saved_migrated"] > 0 or migration_stats["viewed_migrated"] > 0:
            print(f"Migrated {migration_stats['saved_migrated']} saved and {migration_stats['viewed_migrated']} viewed articles")
        # Initialize startup fetcher
        self.fetcher = StartupFetcher(self.db)

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        with Horizontal(id="main_app_container"):
            with VerticalScroll(id="left_pane"):
                # Get unread count for all articles and saved articles
                unread_count = self.db.get_unread_count()
                unread_text = f"Unread ({unread_count})" if unread_count > 0 else "Unread"
                
                saved_unread_count = self.db.get_unread_saved_count()
                saved_text = f"Saved Articles ({saved_unread_count})" if saved_unread_count > 0 else "Saved Articles"
                
                yield Static("My Vault", classes="pane_title")
                yield ListView(
                    ListItem(
                        Static("All articles"), 
                        id="all_articles_filter"
                    ),
                    ListItem(
                        Static(unread_text), 
                        id="unread_articles_filter"
                    ),
                    ListItem(
                        Static(saved_text), 
                        id="saved_articles_filter"
                    ),
                    id="saved_articles_list",
                )

                with Vertical(id="tags_container"):
                    all_tags = self.db.get_all_tags()
                    if all_tags:
                        yield Static("Tags", classes="pane_title")
                        tag_items = []
                        for tag in all_tags:
                            unread_count = self.db.get_unread_count_by_tag(tag['name'])
                            tag_text = f"{tag['name']} ({unread_count})" if unread_count > 0 else tag['name']
                            sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag['name'])
                            
                            tag_item = ListItem(
                                Static(tag_text),
                                id=f"tag_{sanitized_tag_name}",
                            )
                            tag_item.original_tag_name = tag['name']
                            tag_items.append(tag_item)
                        yield ListView(*tag_items, id="tags_list")

                with Vertical(id="filters_container"):
                    if self.config["filters"]:
                        yield Static("Filters", classes="pane_title")
                        filter_items = []
                        for name in self.config["filters"]:
                            filter_config = self.config["filters"][name]
                            unread_count = self.db.get_unread_count_by_filter(filter_config)
                            filter_text = f"{name} ({unread_count})" if unread_count > 0 else name
                            
                            filter_items.append(
                                ListItem(
                                    Static(filter_text),
                                    id=f"filter_{name.replace(' ', '_')}",
                                )
                            )
                        yield ListView(*filter_items, id="filters_list")

                with Vertical(id="categories_container"):
                    if self.config["categories"]:
                        yield Static("Categories", classes="pane_title")
                        category_items = []
                        for name, code in self.config["categories"].items():
                            unread_count = self.db.get_unread_count_by_category(code)
                            category_text = f"{name} ({unread_count})" if unread_count > 0 else name
                            
                            category_items.append(
                                ListItem(Static(category_text), id=f"cat_{code}")
                            )
                        yield ListView(*category_items, id="categories_list")

            with Vertical(id="right_pane"):
                yield Static("", id="header_status")
                with Horizontal(id="search_container"):
                    yield Input(placeholder="Enter query...", id="search_input")
                    yield Checkbox("Web Search", id="global_search_checkbox")
                with Horizontal(id="main_container"):
                    with Vertical(id="results_container"):
                        yield Static("Articles", id="results_title", classes="pane_title")
                        yield DataTable(id="results_table")
                    with Vertical(id="abstract_container"):
                        yield Static("Article View", id="abstract_title", classes="pane_title")
                        yield Static("No article selected", id="abstract_view")
        yield Footer()

    def update_results_title(self) -> None:
        """Update the results table title based on current selection."""
        try:
            results_title = self.query_one("#results_title", Static)
            
            # Check if we're showing global search results
            if self.current_results_from_global and self.current_query:
                title = "ArXiv Web Search"
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
                    elif self.current_selection.startswith("tag_"):
                        tag_name = self.current_selection[4:]  # Remove "tag_" prefix
                        title = f"Tag: {tag_name}"
                    elif self.current_selection in self.config.get("filters", {}):
                        title = f"Filter: {self.current_selection}"
                    elif self.current_selection in self.config.get("categories", {}).values():
                        # Find category name by code
                        for name, code in self.config["categories"].items():
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
            saved_text = f"Saved Articles ({saved_unread_count})" if saved_unread_count > 0 else "Saved Articles"
            try:
                saved_item = self.query_one("#saved_articles_filter", ListItem)
                saved_static = saved_item.query_one(Static)
                saved_static.update(saved_text)
            except Exception:
                pass
            
            # Update Tag counts
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
            
            # Update Filter counts
            if self.config["filters"]:
                for name in self.config["filters"]:
                    filter_config = self.config["filters"][name]
                    unread_count = self.db.get_unread_count_by_filter(filter_config)
                    filter_text = f"{name} ({unread_count})" if unread_count > 0 else name
                    
                    filter_widget_id = f"filter_{name.replace(' ', '_')}"
                    try:
                        filter_item = self.query_one(f"#{filter_widget_id}", ListItem)
                        filter_static = filter_item.query_one(Static)
                        filter_static.update(filter_text)
                    except Exception:
                        pass  # Widget might not exist yet
            
            # Update Category counts
            if self.config["categories"]:
                for name, code in self.config["categories"].items():
                    unread_count = self.db.get_unread_count_by_category(code)
                    category_text = f"{name} ({unread_count})" if unread_count > 0 else name
                    
                    try:
                        category_item = self.query_one(f"#cat_{code}", ListItem)
                        category_static = category_item.query_one(Static)
                        category_static.update(category_text)
                    except Exception:
                        pass  # Widget might not exist yet
                        
        except Exception as e:
            # Don't let count refresh errors break the app
            pass

    def on_mount(self) -> None:
        """Call after the app is mounted."""
        table = self.query_one("#results_table", DataTable)
        table.cursor_type = "row"
        table.add_column("S", width=3)
        table.add_column("Title")
        table.add_column("Authors", width=18)
        table.add_column("Published")
        table.add_column("Categories", width=20)



        # Automatically select "Unread" as the default view
        self.current_selection = "unread_articles_filter"
        
        # Deselect all ListViews first
        for list_view in self.query(ListView):
            list_view.index = None
        
        try:
            self.query_one("#saved_articles_list", ListView).index = 1  # Select second item (Unread)
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

    def on_mouse_enter(self, event: events.Enter) -> None:
        """Handle mouse enter events for hover effects."""
        pass

    def on_mouse_leave(self, event: events.Leave) -> None:
        """Handle mouse leave events for hover effects."""
        pass

    async def on_click(self, event: events.Click) -> None:
        """Handle menu item clicks."""
        pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        self.current_query = event.value
        # Refresh left panel counts when searching to ensure they're up to date
        self.refresh_left_panel_counts()
        self.load_articles()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle global search checkbox changes."""
        if event.checkbox.id == "global_search_checkbox":
            self.global_search_enabled = event.value
            # Refresh left panel counts when changing search mode
            self.refresh_left_panel_counts()
            # If there's a current query, re-run the search with new mode
            if self.current_query:
                self.load_articles()

    def load_articles(self) -> None:
        """Prepare for fetching articles and trigger the worker."""
        table = self.query_one("#results_table", DataTable)
        abstract_view = self.query_one("#abstract_view", Static)
        table.clear()
        abstract_view.update("No article selected")

        # Check if global search is enabled and we have a query
        if self.global_search_enabled and self.current_query:
            self.notify(f"Searching arXiv globally for: {self.current_query}")
            self.current_results_from_global = True
            self.update_results_title()
            self.fetch_articles_from_arxiv()
            return

        # selection_name = ""
        # if self.current_selection:
        #     if self.current_selection == "saved_articles_filter":
        #         selection_name = "Saved Articles"
        #     elif self.current_selection in self.config.get("filters", {}):
        #         selection_name = self.current_selection
        #     elif self.current_selection in self.config.get("categories", {}).values():
        #         for name, code in self.config["categories"].items():
        #             if code == self.current_selection:
        #                 selection_name = name
        #                 break
        #     if selection_name:
        #         self.notify(f"Fetching articles for: {selection_name}")

        if self.current_query:
            self.notify(f"Searching for: {self.current_query}")

        # Set flag to indicate results are from local database
        self.current_results_from_global = False
        # Update the results title to reflect current selection/query
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
            # Refresh left panel counts after manual refresh
            self.call_from_thread(self.refresh_left_panel_counts)
            # Update header status after refresh
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
        abstract_view = self.query_one("#abstract_view", Static)

        try:
            # Perform global arXiv search
            search = arxiv.Search(
                query=self.current_query,
                max_results=100,
                sort_by=arxiv.SortCriterion.Relevance
            )
            
            # Convert results to list
            arxiv_results = list(search.results())
            
            # Create article objects similar to database results
            self.search_results = []
            for result in arxiv_results:
                # Add status information (not saved, not viewed since from global search)
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
    def fetch_articles_from_db(self) -> None:
        """Worker to fetch and display articles from database."""
        abstract_view = self.query_one("#abstract_view", Static)

        try:
            if self.current_selection == "saved_articles_filter":
                # Fetch saved articles from database
                db_results = self.db.get_saved_articles()
            
            elif self.current_selection == "unread_articles_filter":
                # Fetch all unread articles from database
                if self.current_query:
                    # Search within unread articles
                    unread_results = self.db.get_unread_articles()
                    # Filter by search query
                    search_lower = self.current_query.lower()
                    db_results = [
                        result for result in unread_results 
                        if (search_lower in result['title'].lower() or 
                            search_lower in result['summary'].lower() or
                            search_lower in result['authors'].lower())
                    ]
                else:
                    # Just get all unread articles
                    db_results = self.db.get_unread_articles()
            
            elif self.current_selection == "all_articles_filter":
                # Fetch all articles from database
                if self.current_query:
                    # Search within all articles
                    db_results = self.db.search_articles(self.current_query)
                    self.call_from_thread(self.notify, f"Searched all articles with query: {self.current_query}, found {len(db_results)} results", timeout=3)
                else:
                    # Just get all articles (most recent first)
                    debug_log("About to call get_all_articles")
                    db_results = self.db.get_all_articles()
                    debug_log(f"get_all_articles returned {len(db_results)} articles")
                    self.call_from_thread(self.notify, f"Loaded {len(db_results)} total articles", timeout=3)
            
            elif self.current_query and not self.current_selection:
                # Text search across all articles
                db_results = self.db.search_articles(self.current_query)
            
            elif self.current_selection:
                if self.current_selection.startswith("tag_"):
                    # Handle tag selection
                    tag_name = self.current_selection[4:]  # Remove "tag_" prefix
                    if self.current_query:
                        # Search within tagged articles
                        tagged_results = self.db.get_articles_by_tag(tag_name)
                        # Filter by search query
                        search_lower = self.current_query.lower()
                        db_results = [
                            result for result in tagged_results 
                            if (search_lower in result['title'].lower() or 
                                search_lower in result['summary'].lower() or
                                search_lower in result['authors'].lower())
                        ]
                    else:
                        # Just get articles for this tag
                        db_results = self.db.get_articles_by_tag(tag_name)
                
                elif self.current_selection in self.config.get("filters", {}):
                    # Handle filter - search by filter criteria
                    filter_details = self.config["filters"][self.current_selection]
                    search_query = self.current_query or ""
                    filter_query = filter_details.get("query")
                    filter_categories = filter_details.get("categories")

                    # If both query and categories are present, use the new combined search
                    if (search_query or filter_query) and filter_categories:
                        # Combine user query and filter query if both exist
                        combined_query = search_query
                        if filter_query:
                            combined_query = f"{combined_query} {filter_query}".strip()
                        db_results = self.db.search_articles_in_categories(combined_query, filter_categories)
                    elif search_query or filter_query:
                        # Only query, no categories
                        combined_query = search_query or filter_query
                        db_results = self.db.search_articles(combined_query)
                    elif filter_categories:
                        # Only categories, no query
                        all_results = []
                        for cat in filter_categories:
                            cat_results = self.db.get_articles_by_category(cat)
                            all_results.extend(cat_results)
                        # Remove duplicates and sort by published date
                        seen = set()
                        unique_results = []
                        for result in all_results:
                            if result['id'] not in seen:
                                seen.add(result['id'])
                                unique_results.append(result)
                        db_results = sorted(unique_results, key=lambda x: x['published_date'], reverse=True)
                    else:
                        db_results = []

                elif self.current_selection in self.config.get("categories", {}).values():
                    # Handle category selection
                    if self.current_query:
                        # Search within category
                        category_results = self.db.get_articles_by_category(self.current_selection)
                        # Filter by search query
                        search_lower = self.current_query.lower()
                        db_results = [
                            result for result in category_results 
                            if (search_lower in result['title'].lower() or 
                                search_lower in result['summary'].lower() or
                                search_lower in result['authors'].lower())
                        ]
                    else:
                        # Just get articles for this category
                        db_results = self.db.get_articles_by_category(self.current_selection)
                else:
                    db_results = []
            else:
                db_results = []

            # Convert database results to a format similar to arxiv.Result objects
            self.search_results = self._convert_db_results_to_articles(db_results)
            
        except Exception as e:
            self.call_from_thread(
                abstract_view.update,
                f"[bold red]Error fetching articles from database:[/bold red]\n{e}",
            )
            self.search_results = []

        self.call_from_thread(self._populate_table)
        self.call_from_thread(self.query_one("#results_table").focus)

    def _convert_db_results_to_articles(self, db_results):
        """Convert database results to objects that work with existing UI code."""
        articles = []
        for result in db_results:
            # Create a simple object that mimics arxiv.Result
            class MockArticle:
                def __init__(self, db_result):
                    self.id = db_result['id']
                    self.entry_id = db_result['entry_id']
                    self.title = db_result['title']
                    self.summary = db_result['summary']
                    self.pdf_url = db_result['pdf_url']
                    
                    # Parse JSON fields
                    if isinstance(db_result['authors'], str):
                        author_names = json.loads(db_result['authors'])
                    else:
                        author_names = db_result['authors']
                    
                    if isinstance(db_result['categories'], str):
                        self.categories = json.loads(db_result['categories'])
                    else:
                        self.categories = db_result['categories']
                    
                    # Create mock author objects
                    self.authors = []
                    for name in author_names:
                        author = type('Author', (), {'name': name})()
                        self.authors.append(author)
                    
                    # Parse published date
                    from datetime import datetime
                    if 'T' in db_result['published_date']:
                        self.published = datetime.fromisoformat(db_result['published_date'].replace('Z', '+00:00'))
                    else:
                        self.published = datetime.fromisoformat(db_result['published_date'])
                    
                    # Add status information
                    self.is_saved = bool(db_result.get('is_saved', 0))
                    self.is_viewed = bool(db_result.get('is_viewed', 0))
                    self.has_tags = bool(db_result.get('has_tags', 0))
                    self.notes_file_path = db_result.get('notes_file_path')
                    self.has_note = bool(self.notes_file_path)
                
                def get_short_id(self):
                    return self.id
                
                def download_pdf(self, dirpath: str = ".") -> str:
                    """Download PDF file to specified directory."""
                    import requests
                    import os
                    
                    # Create filename from article ID
                    filename = f"{self.id}.{self.title[:50].replace('/', '_').replace(':', '_')}.pdf"
                    # Remove any problematic characters
                    filename = "".join(c for c in filename if c.isalnum() or c in '.-_')
                    filepath = os.path.join(dirpath, filename)
                    
                    # Download the PDF
                    response = requests.get(self.pdf_url, stream=True)
                    response.raise_for_status()
                    
                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    return filepath
            
            articles.append(MockArticle(result))
        
        return articles


    def _populate_table(self):
        """Populate the DataTable with search results."""
        table = self.query_one("#results_table", DataTable)
        for result in self.search_results:
            authors = ", ".join(author.name for author in result.authors)
            title = result.title

            if len(title) > 60:
                title = title[:57] + "..."

            if len(authors) > 18:
                authors = authors[:15] + "..."

            # Format categories
            categories = ", ".join(result.categories)
            if len(categories) > 20:
                categories = categories[:17] + "..."

            # Build status string with multiple indicators
            status_parts = []
            
            # For global search results, show nothing instead of read/unread status
            if self.current_results_from_global:
                status_parts.append(" ")
            else:
                # Use database status information
                if hasattr(result, 'is_saved') and result.is_saved:
                    status_parts.append("[red]s[/red]")
                elif hasattr(result, 'is_viewed') and result.is_viewed:
                    status_parts.append(" ")
                else:
                    status_parts.append("●")
            
            # Add tag indicator (only for local database results)
            if not self.current_results_from_global and hasattr(result, 'has_tags') and result.has_tags:
                status_parts.append("[blue]t[/blue]")
            
            # Add note indicator (only for local database results)
            if not self.current_results_from_global and hasattr(result, 'has_note') and result.has_note:
                status_parts.append("[green]n[/green]")

            # Join status parts or use first one if only one
            if len(status_parts) > 1:
                status = "".join(status_parts)
            else:
                status = status_parts[0] if status_parts else " "

            table.add_row(
                status, title, authors, result.published.strftime("%Y-%m-%d"), categories
            )
        
        # Refresh left panel counts after populating table
        self.refresh_left_panel_counts()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlighting in the DataTable."""
        abstract_view = self.query_one("#abstract_view", Static)
        table = self.query_one("#results_table", DataTable)

        if not self.search_results:
            return

        if event.cursor_row is not None and event.cursor_row < len(
            self.search_results
        ):
            selected_article = self.search_results[event.cursor_row]

            # Mark as viewed in database if not saved and not already viewed
            if (not (hasattr(selected_article, 'is_saved') and selected_article.is_saved) and
                not (hasattr(selected_article, 'is_viewed') and selected_article.is_viewed)):
                self.db.mark_article_viewed(selected_article.get_short_id())
                selected_article.is_viewed = True
                table.update_cell_at(Coordinate(event.cursor_row, 0), " ")
                # Refresh left panel counts since an article was just viewed
                self.refresh_left_panel_counts()

            summary = selected_article.summary.replace("\n", " ")
            authors = ", ".join(author.name for author in selected_article.authors)
            pdf_url = selected_article.pdf_url
            categories = ", ".join(selected_article.categories)
            
            # Get article tags
            article_id = selected_article.get_short_id()
            tags = self.db.get_article_tags(article_id)
            tags_display = ""
            if tags:
                tags_str = ", ".join(tags)
                tags_display = f"\n\n[bold]Tags:[/] {tags_str}"

            notes_display = ""
            if hasattr(selected_article, 'has_note') and selected_article.has_note:
                notes_display = f"\n\n[bold]Notes:[/] This article has notes ([@click=\"app.manage_notes()\"]view/edit[/])."

            content = (
                f"[bold]{selected_article.title}[/bold]\n\n"
                f"[italic]{authors}[/italic]\n\n"
                f"[bold]Categories:[/] {categories}\n\n"
                f"{summary}\n\n"
                f"Link: [@click=\"app.open_link('{pdf_url}')\"]{pdf_url}[/]"
                f"{tags_display}"
                f"{notes_display}"
            )

            abstract_view.update(content)
            
            # Refresh left panel counts on every article highlight to ensure they're always current
            self.refresh_left_panel_counts()
        else:
            abstract_view.update("No article selected")

    def action_open_link(self, url: str) -> None:
        """Open a URL in the default web browser."""
        webbrowser.open(url)

    def action_save_article(self) -> None:
        """Toggle save/unsave for the currently selected article."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
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
                        # Otherwise, update the status icon to preserve tags and notes indicators
                        self._update_table_row_status(cursor_row, selected_article)
                    
                    # Refresh left panel counts since an article was unsaved
                    self.refresh_left_panel_counts()
            else:
                # Article is not saved, so save it
                # For global search results, we need to add the article to database first
                if self.current_results_from_global:
                    # Add article to database (pass the article object directly)
                    try:
                        if not self.db.add_article(selected_article):
                            # Article already exists in database, that's fine
                            pass
                    except Exception as e:
                        self.notify(f"Error adding article to database: {e}", severity="error")
                        return
                
                # Now mark as saved (works for both database and newly added articles)
                if self.db.mark_article_saved(article_id):
                    selected_article.is_saved = True
                    self.notify(f"Saved {article_id}")
                    
                    # Always mark as viewed when saving (especially for global search results)
                    # This ensures articles saved from global search are not marked as unread
                    self.db.mark_article_viewed(article_id)
                    selected_article.is_viewed = True

                    table.update_cell_at(Coordinate(cursor_row, 0), "[red]s[/red]")
                    # Refresh left panel counts since an article was saved
                    self.refresh_left_panel_counts()


    def action_mark_unread(self) -> None:
        """Mark the currently selected article as unread."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            article_id = selected_article.get_short_id()

            # Only mark as unread if it's currently viewed and not saved
            if (hasattr(selected_article, 'is_viewed') and selected_article.is_viewed and 
                not (hasattr(selected_article, 'is_saved') and selected_article.is_saved)):
                if self.db.mark_article_unread(article_id):
                    selected_article.is_viewed = False
                    self.notify(f"Marked {article_id} as unread")
                    
                    table.update_cell_at(Coordinate(cursor_row, 0), "●")
                    # Refresh left panel counts since an article was marked unread
                    self.refresh_left_panel_counts()
            elif hasattr(selected_article, 'is_saved') and selected_article.is_saved:
                self.notify(f"Cannot mark saved article as unread")
            else:
                self.notify(f"Article is already unread")

    def action_download_and_open_pdf(self) -> None:
        """Download the PDF for the selected article and open it."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            self.download_and_open_worker(selected_article)

    def action_open_arxiv_link(self) -> None:
        """Open the arXiv link for the selected article in browser."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            article_id = selected_article.get_short_id()
            arxiv_url = f"https://arxiv.org/abs/{article_id}"
            webbrowser.open(arxiv_url)
            self.notify(f"Opened arXiv link for {article_id}")
        else:
            self.notify("No article selected", severity="warning")

    @work(exclusive=True, thread=True)
    def download_and_open_worker(self, selected_article: arxiv.Result) -> None:
        """Worker to download and open PDF."""
        article_id = selected_article.get_short_id()
        self.notify(f"Downloading {article_id}...", title="Download", timeout=10)

        articles_dir = "articles"
        try:
            os.makedirs(articles_dir, exist_ok=True)
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

    def action_show_selection_popup(self) -> None:
        """Show a popup to select a view (category, filter, or saved)."""
        options = [
            ("Unread", "special:unread_articles_filter"),
            ("Saved Articles", "special:saved_articles_filter")
        ]

        filter_options = [
            (f"Filter: {name}", f"filter:{name}") for name in self.config["filters"]
        ]

        category_options = [
            (f"Category: {name}", f"cat:{code}")
            for name, code in self.config["categories"].items()
        ]

        all_options = options + filter_options + category_options

        self.push_screen(
            SelectionPopupScreen(all_options), self.selection_popup_callback
        )

    def action_refresh_articles(self) -> None:
        """Manually refresh and fetch new articles."""
        self.notify("Refreshing articles...", title="Manual Refresh", timeout=3)
        self.manual_refresh_articles()



    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    def action_show_inspire_citation(self) -> None:
        """Show inspire-hep citation for the currently selected article."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            self.fetch_inspire_citation(selected_article)
        else:
            self.notify("No article selected", severity="warning")

    def action_manage_tags(self) -> None:
        """Show tag management popup for the currently selected article."""
        print("DEBUG: action_manage_tags called - 't' key was pressed")
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        print(f"DEBUG: cursor_row = {cursor_row}")
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            print(f"DEBUG: Selected article: {selected_article.get_short_id()}")
            self.show_tag_popup(selected_article)
        else:
            print(f"DEBUG: No valid article selected - cursor_row={cursor_row}, search_results length={len(self.search_results)}")
            self.notify("No article selected", severity="warning")

    def action_manage_notes(self) -> None:
        """Open the notes popup for the currently selected article."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            self.show_notes_popup(selected_article)
        else:
            self.notify("No article selected", severity="warning")

    def show_notes_popup(self, article) -> None:
        """Create and show the notes popup for an article."""
        article_id = article.get_short_id()
        notes_path_str = self.db.get_notes_path(article_id)

        if not notes_path_str:
            # Create a new notes file
            notes_dir = "notes"
            os.makedirs(notes_dir, exist_ok=True)
            
            # Sanitize title for filename
            safe_title = "".join(c for c in article.title if c.isalnum() or c in ' ._-').rstrip()
            filename = f"{article_id}_{safe_title[:30]}.md"
            notes_path_str = os.path.join(notes_dir, filename)
            
            # Create the file and update database
            with open(notes_path_str, "w") as f:
                f.write(f"# Notes for: {article.title}\n\n")
            
            self.db.set_notes_path(article_id, notes_path_str)

            # Update article object and table view
            article.notes_file_path = notes_path_str
            article.has_note = True
            table = self.query_one("#results_table", DataTable)
            if table.cursor_row is not None:
                self._update_table_row_status(table.cursor_row, article)

        self.push_screen(
            NotesPopupScreen(notes_path_str, article.title), 
            self.notes_popup_callback
        )

    def notes_popup_callback(self, result: Optional[str]) -> None:
        """Handle the result from the notes popup."""
        if result is not None:
            self.notify("Notes saved successfully!", timeout=2)
        else:
            self.notify("Notes closed without saving.", timeout=2)

    def show_tag_popup(self, article) -> None:
        """Show the tag management popup for an article."""
        article_id = article.get_short_id()
        print(f"DEBUG: show_tag_popup called for article {article_id}")
        existing_tags = self.db.get_article_tags(article_id)
        print(f"DEBUG: Existing tags for article: {existing_tags}")
        all_tags = self.db.get_all_tags()
        print(f"DEBUG: All tags in database: {[tag['name'] for tag in all_tags]}")
        
        self.push_screen(
            TagPopupScreen(article_id, article.title, existing_tags, all_tags),
            self.tag_popup_callback
        )

    def tag_popup_callback(self, result) -> None:
        """Handle the result from the tag popup."""
        print(f"DEBUG: tag_popup_callback called with result: {result}")
        
        if result is None:
            print("DEBUG: result is None, returning")
            return
            
        tags_to_add, tags_to_remove = result
        print(f"DEBUG: tags_to_add: {tags_to_add}, tags_to_remove: {tags_to_remove}")
        
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            article_id = selected_article.get_short_id()
            print(f"DEBUG: Processing article {article_id}")
            
            # For global search results, we need to add the article to database first
            if self.current_results_from_global:
                try:
                    if not self.db.add_article(selected_article):
                        # Article already exists in database, that's fine
                        pass
                except Exception as e:
                    self.notify(f"Error adding article to database: {e}", severity="error")
                    return
            
            # Remove tags
            for tag_name in tags_to_remove:
                print(f"DEBUG: Removing tag '{tag_name}' from article {article_id}")
                success = self.db.remove_article_tag(article_id, tag_name)
                print(f"DEBUG: Remove result: {success}")
            
            # Add tags
            for tag_name in tags_to_add:
                print(f"DEBUG: Adding tag '{tag_name}' to article {article_id}")
                success = self.db.add_article_tag(article_id, tag_name)
                print(f"DEBUG: Add result: {success}")
            
            # Cleanup any orphan tags
            if tags_to_remove:
                removed_count = self.db.cleanup_orphan_tags()
                if removed_count > 0:
                    self.notify(f"Removed {removed_count} unused tag(s).", timeout=3)

            # Update article's has_tags status
            if tags_to_add or tags_to_remove:
                selected_article.has_tags = self.db.article_has_tags(article_id)
                print(f"DEBUG: Article has_tags after update: {selected_article.has_tags}")
                
                # Update the table row status to show/hide "t" indicator
                self._update_table_row_status(cursor_row, selected_article)
                
                # Reload left panel to show new tags if any were created
                self.call_later(self.reload_left_panel)
                
                # Refresh all left panel counts since tagging could affect various counts
                self.refresh_left_panel_counts()
            
            if tags_to_add or tags_to_remove:
                self.notify(f"Updated tags for {article_id}")
        else:
            print(f"DEBUG: Invalid cursor_row: {cursor_row}, search_results length: {len(self.search_results)}")

    def _update_table_row_status(self, row_index: int, article) -> None:
        """Update the status column for a specific table row."""
        table = self.query_one("#results_table", DataTable)
        
        # Build status string with multiple indicators
        status_parts = []
        
        # Use database status information
        if hasattr(article, 'is_saved') and article.is_saved:
            status_parts.append("[red]s[/red]")
        elif hasattr(article, 'is_viewed') and article.is_viewed:
            status_parts.append(" ")
        else:
            status_parts.append("●")
        
        # Add tag indicator
        if hasattr(article, 'has_tags') and article.has_tags:
            status_parts.append("[blue]t[/blue]")
        
        # Add note indicator
        if hasattr(article, 'has_note') and article.has_note:
            status_parts.append("[green]n[/green]")

        # Join status parts or use first one if only one
        if len(status_parts) > 1:
            status = "".join(status_parts)
        else:
            status = status_parts[0] if status_parts else " "
            
        table.update_cell_at(Coordinate(row_index, 0), status)

    def reload_left_panel(self) -> None:
        """Update the tags section in the left panel to show new tags."""
        print("DEBUG: reload_left_panel called")
        
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
                    print(f"DEBUG: Adding new tag item: {tag['name']}")
                
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
            print("DEBUG: Created new tags_list with initial items")

        # Refresh all left panel counts since tagging operations could affect various counts
        self.refresh_left_panel_counts()
        
        self.notify("Tags updated successfully!", timeout=3)
        
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
                    article.title
                )
            )

        except Exception as e:
            self.call_from_thread(
                self.notify,
                f"Error fetching citation: {str(e)}",
                title="Inspire-HEP Error",
                severity="error",
                timeout=5
            )
        


    
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
            target_list_view_id = "saved_articles_list"
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

    def update_header_status(self) -> None:
        """Update the header status with article count and last refresh time."""
        try:
            header_status = self.query_one("#header_status", Static)
            
            # Get total article count from database
            total_articles = self.db.get_all_articles_count()
            status_text = f"Articles in Database: {total_articles}"
            
            # Add last refresh time if available
            if self.last_refresh_time:
                from datetime import datetime
                refresh_time = datetime.fromtimestamp(self.last_refresh_time)
                formatted_time = refresh_time.strftime("%Y-%m-%d %H:%M:%S")
                status_text += f"  |  Last refresh: {formatted_time}"
            
            header_status.update(status_text)
        except Exception:
            pass  # Don't let header status errors break the app


if __name__ == "__main__":
    app = ArxivReader()
    app.run() 