"""Article fetching functionality for ArTui."""

import arxiv
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .database import ArticleDatabase
from .config import ConfigManager


class ArticleFetcher:
    """Handles fetching articles from arXiv API."""
    
    def __init__(self, db: ArticleDatabase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
    
    def should_fetch_category(self, category_code: str, hours_threshold: int = 6) -> bool:
        """Check if category should be fetched based on last fetch time."""
        fetch_info = self.db.get_category_fetch_info(category_code)
        
        if not fetch_info:
            return True  # Never fetched before
        
        last_fetched = datetime.fromisoformat(fetch_info['last_fetched'])
        threshold_time = datetime.now() - timedelta(hours=hours_threshold)
        
        return last_fetched < threshold_time
    
    def _build_category_query(self, category_code: str) -> str:
        """Build arXiv query string for a category."""
        if "." not in category_code and "-" not in category_code:
            # Top-level category, search all subcategories
            return f"cat:{category_code}.*"
        elif category_code in ["q-bio", "q-fin"]:
            # Special cases
            return f"cat:{category_code}.*"
        else:
            # Specific subcategory
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
            
            articles = list(search.results())
            
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
            
            articles = list(search.results())
            
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
    
    def fetch_recent_articles(self, days: int = 7, max_per_category: int = 50) -> Dict[str, int]:
        """Fetch only recent articles from all categories and filters (lighter startup option)."""
        print(f"Fetching recent articles from last {days} days...")
        results = {}
        config = self.config_manager.get_config()
        
        # Calculate date filter
        from_date = datetime.now() - timedelta(days=days)
        
        # Fetch categories
        categories = config.get("categories", {})
        if categories:
            for category_name, category_code in categories.items():
                print(f"Fetching recent {category_name} articles...")
                try:
                    query = self._build_category_query(category_code)
                    
                    search = arxiv.Search(
                        query=query,
                        max_results=max_per_category,
                        sort_by=arxiv.SortCriterion.SubmittedDate
                    )
                    
                    articles = []
                    for article in search.results():
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
                        
                except Exception as e:
                    print(f"  Error: {e}")
                    results[f"category_{category_code}"] = 0
        
        # Fetch filters
        filters = config.get("filters", {})
        if filters:
            for filter_name, filter_config in filters.items():
                print(f"Fetching recent {filter_name} filter articles...")
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
                        continue
                    
                    query_string = " AND ".join(search_terms)
                    
                    search = arxiv.Search(
                        query=query_string,
                        max_results=max_per_category,
                        sort_by=arxiv.SortCriterion.SubmittedDate
                    )
                    
                    articles = []
                    for article in search.results():
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
                        
                except Exception as e:
                    print(f"  Error: {e}")
                    results[f"filter_{filter_name}"] = 0
        
        total_added = sum(results.values())
        print(f"\nRecent fetch complete! Added {total_added} new articles.")
        
        return results
    
    def search_arxiv(self, query: str, max_results: int = 100) -> List[arxiv.Result]:
        """Search arXiv directly for global search functionality."""
        try:
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance
            )
            
            return list(search.results())
            
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
            
            # Create a client and fetch results
            client = arxiv.Client()
            articles = list(client.results(search))
            
            print(f"Fetched {len(articles)} articles from {len(arxiv_ids)} requested IDs")
            
            return articles
            
        except Exception as e:
            print(f"Error fetching articles by IDs: {e}")
            return []