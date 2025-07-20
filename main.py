import arxiv
import yaml
import webbrowser
import os
import platform
import subprocess
import json
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
)
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual import work, events
import asyncio
from database import ArticleDatabase
from startup_fetcher import StartupFetcher


# Legacy file paths for migration
VIEWED_ARTICLES_FILE = "viewed_articles.txt"
SAVED_ARTICLES_FILE = "saved_articles.txt"


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


class ArxivReader(App):
    """A Textual app to view arXiv articles."""

    CSS_PATH = "main.css"
    BINDINGS = [
        ("ctrl+d", "toggle_dark", "Toggle dark mode"),
        ("s", "save_article", "Save"),
        ("d", "remove_saved_article", "Un-save Article"),
        ("u", "mark_unread", "Mark Unread"),
        ("o", "download_and_open_pdf", "Open PDF"),
        ("f", "focus_search", "Find"),
        ("c", "show_selection_popup", "Select View"),
        ("r", "refresh_articles", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = load_config()
        self.search_results = []
        self.current_query = ""
        self.current_selection = None
        # Initialize database
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
                # Get unread count for saved articles
                saved_unread_count = self.db.get_unread_saved_count()
                saved_text = f"Saved Articles ({saved_unread_count})" if saved_unread_count > 0 else "Saved Articles"
                
                yield Static(
                    saved_text,
                    id="saved_articles_filter",
                    classes="menu_item",
                )

                if self.config["filters"]:
                    yield Static("Filters", classes="pane_title")
                    for name in self.config["filters"]:
                        # Get unread count for this filter
                        filter_config = self.config["filters"][name]
                        unread_count = self.db.get_unread_count_by_filter(filter_config)
                        filter_text = f"{name} ({unread_count})" if unread_count > 0 else name
                        
                        yield Static(
                            filter_text,
                            id=f"filter_{name.replace(' ', '_')}",
                            classes="menu_item",
                        )

                if self.config["categories"]:
                    yield Static("Categories", classes="pane_title")
                    for name, code in self.config["categories"].items():
                        # Get unread count for this category
                        unread_count = self.db.get_unread_count_by_category(code)
                        category_text = f"{name} ({unread_count})" if unread_count > 0 else name
                        
                        yield Static(
                            category_text, id=f"cat_{code}", classes="menu_item"
                        )

            with Vertical(id="right_pane"):
                yield Input(placeholder="Enter query...", id="search_input")
                with Horizontal(id="main_container"):
                    yield DataTable(id="results_table")
                    yield Static("No article selected", id="abstract_view")
        yield Footer()

    def refresh_left_panel_counts(self) -> None:
        """Update the unread counts in the left panel."""
        try:
            # Update Saved Articles count
            saved_unread_count = self.db.get_unread_saved_count()
            saved_text = f"Saved Articles ({saved_unread_count})" if saved_unread_count > 0 else "Saved Articles"
            saved_widget = self.query_one("#saved_articles_filter", Static)
            saved_widget.update(saved_text)
            
            # Update Filter counts
            if self.config["filters"]:
                for name in self.config["filters"]:
                    filter_config = self.config["filters"][name]
                    unread_count = self.db.get_unread_count_by_filter(filter_config)
                    filter_text = f"{name} ({unread_count})" if unread_count > 0 else name
                    
                    filter_widget_id = f"filter_{name.replace(' ', '_')}"
                    try:
                        filter_widget = self.query_one(f"#{filter_widget_id}", Static)
                        filter_widget.update(filter_text)
                    except Exception:
                        pass  # Widget might not exist yet
            
            # Update Category counts
            if self.config["categories"]:
                for name, code in self.config["categories"].items():
                    unread_count = self.db.get_unread_count_by_category(code)
                    category_text = f"{name} ({unread_count})" if unread_count > 0 else name
                    
                    try:
                        category_widget = self.query_one(f"#cat_{code}", Static)
                        category_widget.update(category_text)
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
        table.add_columns("Title", "Authors", "Published")

        # Start background fetch of articles
        self.startup_fetch_articles()

        # Also trigger the same refresh as the 'r' shortcut
        self.manual_refresh_articles()

        # Automatically load the first filter or category
        if self.config.get("filters"):
            first_selection_name = next(iter(self.config["filters"]))
            self.current_selection = first_selection_name
            button_id = f"filter_{first_selection_name.replace(' ', '_')}"
            try:
                button_to_select = self.query_one(f"#{button_id}", Static)
                button_to_select.add_class("selected")
                self.load_articles()
            except Exception:
                pass  # Button not found
        elif self.config.get("categories"):
            first_category_name = next(iter(self.config["categories"]))
            first_category_code = self.config["categories"][first_category_name]
            self.current_selection = first_category_code
            button_id = f"cat_{first_category_code}"
            try:
                button_to_select = self.query_one(f"#{button_id}", Static)
                button_to_select.add_class("selected")
                self.load_articles()
            except Exception:
                pass  # Button not found

    def on_mouse_enter(self, event: events.Enter) -> None:
        """Handle mouse enter events for hover effects."""
        try:
            if "menu_item" in event.control.classes:
                event.control.add_class("hover")
        except Exception:
            return

    def on_mouse_leave(self, event: events.Leave) -> None:
        """Handle mouse leave events for hover effects."""
        try:
            if "menu_item" in event.control.classes:
                event.control.remove_class("hover")
        except Exception:
            return

    async def on_click(self, event: events.Click) -> None:
        """Handle menu item clicks."""
        try:
            if not event.control or "menu_item" not in event.control.classes:
                return
        except Exception:
            return

        widget = event.control
        widget_id = widget.id
        if not widget_id:
            return

        # Visual feedback for the click
        widget.add_class("clicked")
        await asyncio.sleep(0.1)  # Keep the highlight for a moment
        widget.remove_class("clicked")

        new_selection = None
        if widget_id.startswith("filter_"):
            new_selection = widget_id[len("filter_") :].replace("_", " ")
        elif widget_id.startswith("cat_"):
            new_selection = widget_id[len("cat_") :]
        elif widget_id == "saved_articles_filter":
            new_selection = "saved_articles_filter"

        if new_selection:
            if self.current_selection == new_selection:
                # Toggle off
                self.current_selection = None
                widget.remove_class("selected")
            else:
                self.current_selection = new_selection
                # Highlight the selected button
                for item in self.query(".menu_item.selected"):
                    item.remove_class("selected")
                widget.add_class("selected")

            self.load_articles()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        self.current_query = event.value
        self.load_articles()

    def load_articles(self) -> None:
        """Prepare for fetching articles and trigger the worker."""
        table = self.query_one("#results_table", DataTable)
        abstract_view = self.query_one("#abstract_view", Static)
        table.clear()
        abstract_view.update("No article selected")

        selection_name = ""
        if self.current_selection:
            if self.current_selection == "saved_articles_filter":
                selection_name = "Saved Articles"
            elif self.current_selection in self.config.get("filters", {}):
                selection_name = self.current_selection
            elif self.current_selection in self.config.get("categories", {}).values():
                for name, code in self.config["categories"].items():
                    if code == self.current_selection:
                        selection_name = name
                        break
            if selection_name:
                self.notify(f"Fetching articles for: {selection_name}")

        elif self.current_query:
            self.notify(f"Searching for: {self.current_query}")

        self.fetch_articles_from_db()

    @work(exclusive=True, thread=True)
    def startup_fetch_articles(self) -> None:
        """Background task to fetch articles for all categories at startup."""
        try:
            self.call_from_thread(
                self.notify, 
                "Fetching latest articles in background...", 
                title="Startup", 
                timeout=3
            )
            # Fetch recent articles (lighter startup option)
            results = self.fetcher.fetch_recent_articles(days=7, max_per_category=100)
            total_new = sum(results.values())
            if total_new > 0:
                self.call_from_thread(
                    self.notify, 
                    f"Added {total_new} new articles to database", 
                    title="Fetch Complete", 
                    timeout=5
                )
        except Exception as e:
            self.call_from_thread(
                self.notify,
                f"Background fetch error: {e}",
                title="Error",
                severity="warning",
                timeout=5
            )

    @work(exclusive=True, thread=True)
    def manual_refresh_articles(self) -> None:
        """Manual refresh task to fetch new articles and reload current view."""
        try:
            # Fetch recent articles (same as startup)
            results = self.fetcher.fetch_recent_articles(days=7, max_per_category=100)
            total_new = sum(results.values())
            
            # Reload the current view to show new articles
            self.call_from_thread(self.load_articles)
            # Refresh left panel counts after manual refresh
            self.call_from_thread(self.refresh_left_panel_counts)
            
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
    def fetch_articles_from_db(self) -> None:
        """Worker to fetch and display articles from database."""
        abstract_view = self.query_one("#abstract_view", Static)

        try:
            if self.current_selection == "saved_articles_filter":
                # Fetch saved articles from database
                db_results = self.db.get_saved_articles()
            
            elif self.current_query and not self.current_selection:
                # Text search across all articles
                db_results = self.db.search_articles(self.current_query, limit=100)
            
            elif self.current_selection:
                if self.current_selection in self.config.get("filters", {}):
                    # Handle filter - search by filter criteria
                    filter_details = self.config["filters"][self.current_selection]
                    search_query = self.current_query or ""
                    
                    if filter_details.get("query"):
                        if search_query:
                            search_query = f"{search_query} {filter_details['query']}"
                        else:
                            search_query = filter_details["query"]
                    
                    if search_query:
                        db_results = self.db.search_articles(search_query, limit=100)
                    elif filter_details.get("categories"):
                        # Get articles by categories
                        all_results = []
                        for cat in filter_details["categories"]:
                            cat_results = self.db.get_articles_by_category(cat, limit=50)
                            all_results.extend(cat_results)
                        # Remove duplicates and sort by published date
                        seen = set()
                        unique_results = []
                        for result in all_results:
                            if result['id'] not in seen:
                                seen.add(result['id'])
                                unique_results.append(result)
                        db_results = sorted(unique_results, key=lambda x: x['published_date'], reverse=True)[:100]
                    else:
                        db_results = []

                elif self.current_selection in self.config.get("categories", {}).values():
                    # Handle category selection
                    if self.current_query:
                        # Search within category
                        category_results = self.db.get_articles_by_category(self.current_selection, limit=200)
                        # Filter by search query
                        search_lower = self.current_query.lower()
                        db_results = [
                            result for result in category_results 
                            if (search_lower in result['title'].lower() or 
                                search_lower in result['summary'].lower() or
                                search_lower in result['authors'].lower())
                        ][:100]
                    else:
                        # Just get articles for this category
                        db_results = self.db.get_articles_by_category(self.current_selection, limit=100)
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

            if len(authors) > 40:
                authors = authors[:37] + "..."

            # Use database status information
            if hasattr(result, 'is_saved') and result.is_saved:
                status = "[red]s[/red]"
            elif hasattr(result, 'is_viewed') and result.is_viewed:
                status = " "
            else:
                status = "●"

            table.add_row(
                status, title, authors, result.published.strftime("%Y-%m-%d")
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
            
            content = (
                f"[bold]{selected_article.title}[/bold]\n\n"
                f"[italic]{authors}[/italic]\n\n"
                f"[bold]Categories:[/] {categories}\n\n"
                f"{summary}\n\n"
                f"Link: [@click=\"app.open_link('{pdf_url}')\"]{pdf_url}[/]"
            )

            abstract_view.update(content)
        else:
            abstract_view.update("No article selected")

    def action_open_link(self, url: str) -> None:
        """Open a URL in the default web browser."""
        webbrowser.open(url)

    def action_save_article(self) -> None:
        """Save the currently selected article."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            article_id = selected_article.get_short_id()

            if not (hasattr(selected_article, 'is_saved') and selected_article.is_saved):
                if self.db.mark_article_saved(article_id):
                    selected_article.is_saved = True
                    self.notify(f"Saved {article_id}")
                    
                    # Also mark as viewed
                    if not (hasattr(selected_article, 'is_viewed') and selected_article.is_viewed):
                        self.db.mark_article_viewed(article_id)
                        selected_article.is_viewed = True

                    table.update_cell_at(Coordinate(cursor_row, 0), "[red]s[/red]")
                    # Refresh left panel counts since an article was saved
                    self.refresh_left_panel_counts()

    def action_remove_saved_article(self) -> None:
        """Remove the currently selected article from the saved list."""
        table = self.query_one("#results_table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is not None and 0 <= cursor_row < len(self.search_results):
            selected_article = self.search_results[cursor_row]
            article_id = selected_article.get_short_id()

            if hasattr(selected_article, 'is_saved') and selected_article.is_saved:
                if self.db.mark_article_unsaved(article_id):
                    selected_article.is_saved = False
                    self.notify(f"Removed {article_id} from saved list.")

                    # If we are in the saved articles view, just reload the whole list
                    if self.current_selection == "saved_articles_filter":
                        self.load_articles()
                    else:
                        # Otherwise, just update the status icon to "viewed"
                        table.update_cell_at(Coordinate(cursor_row, 0), " ")
                    
                    # Refresh left panel counts since an article was unsaved
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

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

    def action_focus_search(self) -> None:
        """Focus the search input."""
        self.query_one("#search_input", Input).focus()

    def action_show_selection_popup(self) -> None:
        """Show a popup to select a view (category, filter, or saved)."""
        options = [("Saved Articles", "special:saved_articles_filter")]

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

    def selection_popup_callback(self, selection_value):
        """Callback for when a view is selected from the popup."""
        if not selection_value:
            return

        # Deselect any currently selected button first
        for btn in self.query(".category_button.selected"):
            btn.remove_class("selected")

        value_type, value = selection_value.split(":", 1)

        button_id_to_select = ""

        if value_type == "special":
            self.current_selection = value  # e.g., "saved_articles_filter"
            button_id_to_select = f"#{value}"  # e.g., "#saved_articles_filter"
        elif value_type == "filter":
            self.current_selection = value  # e.g., "Machine Learning"
            button_id_to_select = (
                f"#filter_{value.replace(' ', '_')}"  # e.g., "#filter_Machine_Learning"
            )
        elif value_type == "cat":
            self.current_selection = value  # e.g., "cs.AI"
            button_id_to_select = f"#cat_{value}"  # e.g., "#cat_cs.AI"

        if button_id_to_select:
            try:
                button_to_select = self.query_one(button_id_to_select)
                button_to_select.add_class("selected")
            except Exception:
                # This could happen if an ID is malformed, but the logic seems robust.
                pass

        self.load_articles()


if __name__ == "__main__":
    app = ArxivReader()
    app.run() 