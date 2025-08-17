"""Custom widgets for ArTui."""

from textual.widgets import DataTable
from textual.coordinate import Coordinate
from typing import List, Dict, Any


class ArticleTableWidget(DataTable):
    """Enhanced DataTable widget for displaying articles."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cursor_type = "row"
        self.setup_columns()
    
    def setup_columns(self) -> None:
        """Setup table columns."""
        self.add_column("S", width=3)  # Status
        self.add_column("Title")
        self.add_column("Authors", width=18)
        self.add_column("Published")
        self.add_column("Categories", width=20)
    
    def populate_articles(self, articles: List[Any], is_global_search: bool = False) -> None:
        """Populate table with articles."""
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
