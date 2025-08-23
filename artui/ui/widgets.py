"""Custom widgets for ArTui."""

from textual.widgets import DataTable
from textual.coordinate import Coordinate
from textual import events
from typing import List, Dict, Any, Optional
from datetime import datetime


class ArticleTableWidget(DataTable):
    """Enhanced DataTable widget for displaying articles with sorting functionality."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cursor_type = "row"
        self.setup_columns()
        self.articles_data = []  # Store original article data for sorting
        self.current_is_global_search = False  # Track search type
        self.sort_column = None  # Track current sort column
        self.sort_reverse = False  # Track sort direction
    
    def setup_columns(self) -> None:
        """Setup table columns."""
        self.add_column("S", width=3)  # Status
        self.add_column("Title")
        self.add_column("Authors", width=18)
        self.add_column("Published")
        self.add_column("Categories", width=20)
    
    def populate_articles(self, articles: List[Any], is_global_search: bool = False) -> None:
        """Populate table with articles and store data for sorting."""
        self.clear()
        self.articles_data = articles.copy()  # Store original data
        self.current_is_global_search = is_global_search
        
        # Reset sort state when new data is loaded
        self.sort_column = None
        self.sort_reverse = False
        
        self._populate_table_rows(articles, is_global_search)
    
    def _populate_table_rows(self, articles: List[Any], is_global_search: bool = False) -> None:
        """Internal method to populate table rows from article data."""
        self.clear()
        
        for article in articles:
            authors = ", ".join(author.name for author in article.authors)
            title = article.title
            
            if len(title) > 60:
                title = title[:57] + "..."
            
            if len(authors) > 18:
                authors = authors[:15] + "..."
            
            # Format categories
            categories = ", ".join(article.categories)
            if len(categories) > 20:
                categories = categories[:17] + "..."
            
            # Build status string with multiple indicators
            status = self._build_status_string(article, is_global_search)
            
            self.add_row(
                status, title, authors, 
                article.published.strftime("%Y-%m-%d"), 
                categories
            )
    
    def _build_status_string(self, article: Any, is_global_search: bool) -> str:
        """Build status string for article row."""
        status_parts = []
        
        # For global search results, show nothing instead of read/unread status
        if is_global_search:
            status_parts.append(" ")
        else:
            # Use database status information
            if hasattr(article, 'is_saved') and article.is_saved:
                status_parts.append("[red]s[/red]")
            elif hasattr(article, 'is_viewed') and article.is_viewed:
                status_parts.append(" ")
            else:
                status_parts.append("●")
        

        
        # Add tag indicator (only for local database results)
        if not is_global_search and hasattr(article, 'has_tags') and article.has_tags:
            status_parts.append("[blue]t[/blue]")
        
        # Add note indicator (only for local database results)
        if not is_global_search and hasattr(article, 'has_note') and article.has_note:
            status_parts.append("[green]n[/green]")
        
        # Join status parts or use first one if only one
        if len(status_parts) > 1:
            return "".join(status_parts)
        else:
            return status_parts[0] if status_parts else " "
    
    def update_row_status(self, row_index: int, article: Any, is_global_search: bool = False) -> None:
        """Update the status column for a specific table row."""
        status = self._build_status_string(article, is_global_search)
        self.update_cell_at(Coordinate(row_index, 0), status)
    
    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle header clicks for sorting."""
        column_key = event.column_key
        column_index = event.column_index
        
        # Don't sort by status column
        if column_index == 0:
            return
        
        # Determine if we're reversing the sort
        if self.sort_column == column_index:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column_index
            self.sort_reverse = False
        
        # Sort the articles data
        sorted_articles = self._sort_articles(self.articles_data, column_index, self.sort_reverse)
        
        # Store current cursor position to try to maintain selection
        current_cursor_row = self.cursor_coordinate.row if self.cursor_coordinate else 0
        current_article_id = None
        if current_cursor_row < len(self.articles_data):
            current_article = self.articles_data[current_cursor_row]
            current_article_id = getattr(current_article, 'id', None)
        
        # Repopulate the table with sorted data
        self._populate_table_rows(sorted_articles, self.current_is_global_search)
        
        # Try to maintain cursor position on the same article
        if current_article_id:
            for i, article in enumerate(sorted_articles):
                if getattr(article, 'id', None) == current_article_id:
                    self.move_cursor(row=i)
                    break
        
        # Update the stored articles data to reflect new order
        self.articles_data = sorted_articles
    
    def _sort_articles(self, articles: List[Any], column_index: int, reverse: bool = False) -> List[Any]:
        """Sort articles by the specified column."""
        def get_sort_key(article):
            try:
                if column_index == 1:  # Title
                    return article.title.lower()
                elif column_index == 2:  # Authors
                    authors = ", ".join(author.name for author in article.authors)
                    return authors.lower()
                elif column_index == 3:  # Published date
                    return article.published
                elif column_index == 4:  # Categories
                    categories = ", ".join(article.categories)
                    return categories.lower()
                else:
                    return ""
            except (AttributeError, TypeError):
                return ""
        
        return sorted(articles, key=get_sort_key, reverse=reverse)
    
    def get_article_at_row(self, row_index: int) -> Optional[Any]:
        """Get the article data for a specific table row, accounting for sorting."""
        if 0 <= row_index < len(self.articles_data):
            return self.articles_data[row_index]
        return None
