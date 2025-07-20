import asyncio
import arxiv
import yaml
from datetime import datetime, timedelta
from typing import Dict, List
from database import ArticleDatabase


class StartupFetcher:
    """Handles fetching articles for all categories at startup."""
    
    def __init__(self, db: ArticleDatabase, config_file: str = "arxiv_config.yaml"):
        self.db = db
        self.config = self.load_config(config_file)
    
    def load_config(self, config_file: str) -> Dict:
        """Load configuration from YAML file."""
        try:
            with open(config_file, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            return {"categories": {}, "filters": {}}
    
    def should_fetch_category(self, category_code: str, hours_threshold: int = 6) -> bool:
        """Check if category should be fetched based on last fetch time."""
        fetch_info = self.db.get_category_fetch_info(category_code)
        
        if not fetch_info:
            return True  # Never fetched before
        
        last_fetched = datetime.fromisoformat(fetch_info['last_fetched'])
        threshold_time = datetime.now() - timedelta(hours=hours_threshold)
        
        return last_fetched < threshold_time
    
    def fetch_category_articles(self, category_code: str, category_name: str, max_results: int = 200) -> int:
        """Fetch articles for a specific category and store in database."""
        print(f"Fetching articles for {category_name} ({category_code})...")
        
        try:
            # Build query for category
            if "." not in category_code and "-" not in category_code:
                # Top-level category, search all subcategories
                query = f"cat:{category_code}.*"
            elif category_code in ["q-bio", "q-fin"]:
                # Special cases
                query = f"cat:{category_code}.*"
            else:
                # Specific subcategory
                query = f"cat:{category_code}"
            
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
                    if "." not in cat and "-" not in cat:
                        category_queries.append(f"cat:{cat}.*")
                    elif cat in ["q-bio", "q-fin"]:
                        category_queries.append(f"cat:{cat}.*")
                    else:
                        category_queries.append(f"cat:{cat}")
                
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
        
        # Fetch categories
        if self.config.get("categories"):
            print(f"\nFetching {len(self.config['categories'])} categories:")
            for category_name, category_code in self.config["categories"].items():
                if force or self.should_fetch_category(category_code):
                    added_count = self.fetch_category_articles(category_code, category_name)
                    results[f"category_{category_code}"] = added_count
                else:
                    print(f"Skipping {category_name} ({category_code}) - recently fetched")
                    results[f"category_{category_code}"] = 0
        
        # Fetch filters
        if self.config.get("filters"):
            print(f"\nFetching {len(self.config['filters'])} filters:")
            for filter_name, filter_config in self.config["filters"].items():
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
        
        # Calculate date filter
        from_date = datetime.now() - timedelta(days=days)
        
        # Fetch categories
        if self.config.get("categories"):
            for category_name, category_code in self.config["categories"].items():
                print(f"Fetching recent {category_name} articles...")
                try:
                    # Build query with date filter
                    if "." not in category_code and "-" not in category_code:
                        query = f"cat:{category_code}.*"
                    elif category_code in ["q-bio", "q-fin"]:
                        query = f"cat:{category_code}.*"
                    else:
                        query = f"cat:{category_code}"
                    
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
        if self.config.get("filters"):
            for filter_name, filter_config in self.config["filters"].items():
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
                            if "." not in cat and "-" not in cat:
                                category_queries.append(f"cat:{cat}.*")
                            elif cat in ["q-bio", "q-fin"]:
                                category_queries.append(f"cat:{cat}.*")
                            else:
                                category_queries.append(f"cat:{cat}")
                        
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


def main():
    """Command-line interface for testing the fetcher."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Fetch arXiv articles for configured categories")
    parser.add_argument("--force", action="store_true", help="Force fetch even if recently fetched")
    parser.add_argument("--recent", type=int, metavar="DAYS", help="Fetch only recent articles from last N days")
    parser.add_argument("--config", default="arxiv_config.yaml", help="Configuration file path")
    parser.add_argument("--db", default="arxiv_articles.db", help="Database file path")
    
    args = parser.parse_args()
    
    # Initialize database and fetcher
    db = ArticleDatabase(args.db)
    fetcher = StartupFetcher(db, args.config)
    
    # Migrate existing data if text files exist
    migration_stats = db.migrate_from_text_files("saved_articles.txt", "viewed_articles.txt")
    if migration_stats["saved_migrated"] > 0 or migration_stats["viewed_migrated"] > 0:
        print(f"Migrated {migration_stats['saved_migrated']} saved and {migration_stats['viewed_migrated']} viewed articles")
    
    # Fetch articles
    if args.recent:
        fetcher.fetch_recent_articles(days=args.recent)
    else:
        fetcher.fetch_all_categories(force=args.force)


if __name__ == "__main__":
    main() 