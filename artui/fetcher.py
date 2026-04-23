"""Article fetching functionality for ArTui."""

import arxiv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any

from .database import ArticleDatabase
from .config import ConfigManager


class ArticleFetcher:
    """Handles fetching articles from arXiv API."""
    
    def __init__(self, db: ArticleDatabase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        # Single shared client so the 3-second delay between requests is tracked
        # globally across all fetches, keeping us within arXiv's rate limit.
        self._client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)
    
    def should_fetch_category(self, category_code: str, hours_threshold: int = 6) -> bool:
        """Check if category should be fetched based on last fetch time."""
        fetch_info = self.db.get_category_fetch_info(category_code)
        
        if not fetch_info:
            return True  # Never fetched before
        
        last_fetched = datetime.fromisoformat(fetch_info['last_fetched'])
        threshold_time = datetime.now() - timedelta(hours=hours_threshold)
        
        return last_fetched < threshold_time
    
    # Top-level arXiv categories that contain a hyphen but still have dot-separated
    # sub-categories (e.g. astro-ph.CO, cond-mat.mes-hall).  These need the '.*'
    # wildcard so that fetching the parent returns all sub-category papers.
    _HYPHENATED_PARENT_CATEGORIES = frozenset([
        "astro-ph", "cond-mat", "q-bio", "q-fin",
    ])

    def _build_category_query(self, category_code: str) -> str:
        """Build arXiv query string for a category."""
        if "." not in category_code and "-" not in category_code:
            # Simple top-level category like 'cs', 'math', 'physics'
            return f"cat:{category_code}.*"
        elif category_code in self._HYPHENATED_PARENT_CATEGORIES:
            # Hyphenated top-level categories that have dot-separated sub-categories
            return f"cat:{category_code}.*"
        else:
            # Specific sub-category like 'hep-th', 'cs.AI', 'astro-ph.CO'
            return f"cat:{category_code}"
    
    def fetch_category_articles(self, category_code: str, category_name: str, max_results: int = 200) -> int:
        """Fetch articles for a specific category and store in database."""
        print(f"Fetching articles for {category_name} ({category_code})...")
        
        try:
            query = self._build_category_query(category_code)
            
            # Search arXiv
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate
            )
            
            articles = list(self._client.results(search))
            
            # Add articles to database
            added_count = self.db.add_articles_batch(articles)
            
            # Update fetch info
            self.db.update_category_fetch_info(category_code, category_name, len(articles))
            
            print(f"  Fetched {len(articles)} articles, {added_count} new articles added")
            return added_count
            
        except Exception as e:
            print(f"  Error fetching {category_name}: {e}")
            return 0
    
    def fetch_filter_articles(self, filter_name: str, filter_config: Dict, max_results: int = 200) -> int:
        """Fetch articles for a specific filter and store in database."""
        print(f"Fetching articles for filter: {filter_name}...")
        
        try:
            search_terms = []
            
            # Add query if specified
            if filter_config.get("query"):
                search_terms.append(f'all:"{filter_config["query"]}"')
            
            # Add categories if specified
            if filter_config.get("categories"):
                category_queries = []
                for cat in filter_config["categories"]:
                    category_queries.append(self._build_category_query(cat))
                
                if category_queries:
                    search_terms.append("(" + " OR ".join(category_queries) + ")")
            
            if not search_terms:
                print(f"  No search terms for filter {filter_name}")
                return 0
            
            query_string = " AND ".join(search_terms)
            
            # Search arXiv
            search = arxiv.Search(
                query=query_string,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate
            )
            
            articles = list(self._client.results(search))
            
            # Add articles to database
            added_count = self.db.add_articles_batch(articles)
            
            # Update fetch info for filter (using filter name as category code)
            self.db.update_category_fetch_info(f"filter_{filter_name}", filter_name, len(articles))
            
            print(f"  Fetched {len(articles)} articles, {added_count} new articles added")
            return added_count
            
        except Exception as e:
            print(f"  Error fetching filter {filter_name}: {e}")
            return 0
    
    def fetch_all_categories(self, force: bool = False) -> Dict[str, int]:
        """Fetch articles for all configured categories and filters."""
        print("Starting article fetch for all categories...")
        results = {}
        config = self.config_manager.get_config()
        
        # Fetch categories
        categories = config.get("categories", {})
        if categories:
            print(f"\nFetching {len(categories)} categories:")
            for category_name, category_code in categories.items():
                if force or self.should_fetch_category(category_code):
                    added_count = self.fetch_category_articles(category_code, category_name)
                    results[f"category_{category_code}"] = added_count
                else:
                    print(f"Skipping {category_name} ({category_code}) - recently fetched")
                    results[f"category_{category_code}"] = 0
        
        # Fetch filters
        filters = config.get("filters", {})
        if filters:
            print(f"\nFetching {len(filters)} filters:")
            for filter_name, filter_config in filters.items():
                filter_key = f"filter_{filter_name}"
                if force or self.should_fetch_category(filter_key):
                    added_count = self.fetch_filter_articles(filter_name, filter_config)
                    results[filter_key] = added_count
                else:
                    print(f"Skipping filter {filter_name} - recently fetched")
                    results[filter_key] = 0
        
        total_added = sum(results.values())
        total_articles = self.db.get_all_articles_count()
        
        print(f"\nFetch complete!")
        print(f"  Total new articles added: {total_added}")
        print(f"  Total articles in database: {total_articles}")
        print(f"  Saved articles: {self.db.get_saved_articles_count()}")
        
        return results
    
    def fetch_recent_articles(
        self,
        days: int = 7,
        max_per_category: int = 50,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, int]:
        """Fetch only recent articles from all categories and filters (lighter startup option)."""
        print(f"Fetching recent articles from last {days} days...")
        results = {}
        config = self.config_manager.get_config()
        request_delay = getattr(self._client, "delay_seconds", None)
        
        # Calculate date filter
        from_date = datetime.now() - timedelta(days=days)
        
        # Fetch categories
        categories = config.get("categories", {})
        filters = config.get("filters", {})
        total_batches = len(categories) + len(filters)
        completed_batches = 0

        def emit_progress(payload: Dict[str, Any]) -> None:
            if progress_callback:
                progress_callback(payload)

        emit_progress({
            "event": "refresh_started",
            "total_batches": total_batches,
            "completed_batches": completed_batches,
            "request_delay_seconds": request_delay,
            "days": days,
            "max_per_batch": max_per_category,
        })

        if categories:
            for category_name, category_code in categories.items():
                print(f"Fetching recent {category_name} articles...")
                emit_progress({
                    "event": "batch_started",
                    "batch_type": "category",
                    "batch_name": category_name,
                    "batch_code": category_code,
                    "total_batches": total_batches,
                    "completed_batches": completed_batches,
                    "request_delay_seconds": request_delay,
                })
                try:
                    query = self._build_category_query(category_code)
                    
                    search = arxiv.Search(
                        query=query,
                        max_results=max_per_category,
                        sort_by=arxiv.SortCriterion.SubmittedDate
                    )
                    
                    articles = []
                    for article in self._client.results(search):
                        if article.published.replace(tzinfo=None) >= from_date:
                            articles.append(article)
                        else:
                            break  # Articles are sorted by date, so we can stop
                    
                    if articles:
                        added_count = self.db.add_articles_batch(articles)
                        results[f"category_{category_code}"] = added_count
                        print(f"  Added {added_count} new recent articles")
                    else:
                        results[f"category_{category_code}"] = 0
                        print(f"  No new recent articles")
                    completed_batches += 1
                    emit_progress({
                        "event": "batch_completed",
                        "batch_type": "category",
                        "batch_name": category_name,
                        "batch_code": category_code,
                        "total_batches": total_batches,
                        "completed_batches": completed_batches,
                        "added_count": results[f"category_{category_code}"],
                        "request_delay_seconds": request_delay,
                    })
                        
                except Exception as e:
                    print(f"  Error: {e}")
                    results[f"category_{category_code}"] = 0
                    completed_batches += 1
                    emit_progress({
                        "event": "batch_completed",
                        "batch_type": "category",
                        "batch_name": category_name,
                        "batch_code": category_code,
                        "total_batches": total_batches,
                        "completed_batches": completed_batches,
                        "added_count": 0,
                        "request_delay_seconds": request_delay,
                        "error": str(e),
                    })
        
        # Fetch filters
        if filters:
            for filter_name, filter_config in filters.items():
                print(f"Fetching recent {filter_name} filter articles...")
                emit_progress({
                    "event": "batch_started",
                    "batch_type": "filter",
                    "batch_name": filter_name,
                    "batch_code": f"filter_{filter_name}",
                    "total_batches": total_batches,
                    "completed_batches": completed_batches,
                    "request_delay_seconds": request_delay,
                })
                try:
                    search_terms = []
                    
                    # Add query if specified
                    if filter_config.get("query"):
                        search_terms.append(f'all:"{filter_config["query"]}"')
                    
                    # Add categories if specified
                    if filter_config.get("categories"):
                        category_queries = []
                        for cat in filter_config["categories"]:
                            category_queries.append(self._build_category_query(cat))
                        
                        if category_queries:
                            search_terms.append("(" + " OR ".join(category_queries) + ")")
                    
                    if not search_terms:
                        print(f"  No search terms for filter {filter_name}")
                        results[f"filter_{filter_name}"] = 0
                        completed_batches += 1
                        emit_progress({
                            "event": "batch_completed",
                            "batch_type": "filter",
                            "batch_name": filter_name,
                            "batch_code": f"filter_{filter_name}",
                            "total_batches": total_batches,
                            "completed_batches": completed_batches,
                            "added_count": 0,
                            "request_delay_seconds": request_delay,
                        })
                        continue
                    
                    query_string = " AND ".join(search_terms)
                    
                    search = arxiv.Search(
                        query=query_string,
                        max_results=max_per_category,
                        sort_by=arxiv.SortCriterion.SubmittedDate
                    )
                    
                    articles = []
                    for article in self._client.results(search):
                        if article.published.replace(tzinfo=None) >= from_date:
                            articles.append(article)
                        else:
                            break  # Articles are sorted by date, so we can stop
                    
                    if articles:
                        added_count = self.db.add_articles_batch(articles)
                        results[f"filter_{filter_name}"] = added_count
                        print(f"  Added {added_count} new recent articles")
                    else:
                        results[f"filter_{filter_name}"] = 0
                        print(f"  No new recent articles")
                    completed_batches += 1
                    emit_progress({
                        "event": "batch_completed",
                        "batch_type": "filter",
                        "batch_name": filter_name,
                        "batch_code": f"filter_{filter_name}",
                        "total_batches": total_batches,
                        "completed_batches": completed_batches,
                        "added_count": results[f"filter_{filter_name}"],
                        "request_delay_seconds": request_delay,
                    })
                        
                except Exception as e:
                    print(f"  Error: {e}")
                    results[f"filter_{filter_name}"] = 0
                    completed_batches += 1
                    emit_progress({
                        "event": "batch_completed",
                        "batch_type": "filter",
                        "batch_name": filter_name,
                        "batch_code": f"filter_{filter_name}",
                        "total_batches": total_batches,
                        "completed_batches": completed_batches,
                        "added_count": 0,
                        "request_delay_seconds": request_delay,
                        "error": str(e),
                    })
        
        total_added = sum(results.values())
        print(f"\nRecent fetch complete! Added {total_added} new articles.")
        emit_progress({
            "event": "refresh_completed",
            "total_batches": total_batches,
            "completed_batches": completed_batches,
            "total_added": total_added,
            "request_delay_seconds": request_delay,
        })
        
        return results
    
    def search_arxiv(self, query: str, max_results: int = 100, sort_by: str = "relevance") -> List[arxiv.Result]:
        """Search arXiv directly for global search functionality.
        
        Args:
            query: Search query string (can include field-specific searches)
            max_results: Maximum number of results to return
            sort_by: Sort criteria - "relevance", "submitted_date", or "last_updated_date"
        """
        try:
            # Map sort_by string to arxiv.SortCriterion
            sort_mapping = {
                "relevance": arxiv.SortCriterion.Relevance,
                "submitted_date": arxiv.SortCriterion.SubmittedDate,
                "last_updated_date": arxiv.SortCriterion.LastUpdatedDate
            }
            
            sort_criterion = sort_mapping.get(sort_by, arxiv.SortCriterion.Relevance)
            
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=sort_criterion
            )
            
            results = list(self._client.results(search))
            
            return results
            
        except Exception as e:
            print(f"Error searching arXiv: {e}")
            return []
    
    def fetch_articles_by_ids(self, arxiv_ids: List[str]) -> List[arxiv.Result]:
        """Fetch specific arXiv articles by their IDs.
        
        Args:
            arxiv_ids: List of arXiv IDs (e.g., ['1234.5678', '2109.12345'])
            
        Returns:
            List of arxiv.Result objects for the found articles
        """
        if not arxiv_ids:
            return []
            
        try:
            # Use the id_list parameter to fetch articles directly by ID
            search = arxiv.Search(id_list=arxiv_ids)
            articles = list(self._client.results(search))
            
            print(f"Fetched {len(articles)} articles from {len(arxiv_ids)} requested IDs")
            
            return articles
            
        except Exception as e:
            print(f"Error fetching articles by IDs: {e}")
            return []