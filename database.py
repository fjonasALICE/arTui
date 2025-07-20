import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Set
import arxiv


class ArticleDatabase:
    """Database manager for ArXiv articles with SQLite backend."""
    
    def __init__(self, db_path: str = "arxiv_articles.db"):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self) -> None:
        """Initialize database tables."""
        with self.get_connection() as conn:
            # Articles table - stores all article metadata
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,           -- ArXiv ID like "2507.13213v1"
                    entry_id TEXT NOT NULL,        -- Full ArXiv URL
                    title TEXT NOT NULL,
                    authors TEXT NOT NULL,         -- JSON array of author names
                    summary TEXT NOT NULL,
                    categories TEXT NOT NULL,      -- JSON array of categories
                    published_date TEXT NOT NULL,  -- ISO date string
                    pdf_url TEXT NOT NULL,
                    created_at TEXT NOT NULL,      -- When first fetched
                    updated_at TEXT NOT NULL       -- Last update
                )
            """)
            
            # Article status table - tracks user interactions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS article_status (
                    article_id TEXT PRIMARY KEY,
                    is_saved INTEGER DEFAULT 0,    -- 0/1 for boolean
                    is_viewed INTEGER DEFAULT 0,   -- 0/1 for boolean
                    saved_at TEXT,                 -- ISO datetime when saved
                    viewed_at TEXT,                -- ISO datetime when first viewed
                    FOREIGN KEY (article_id) REFERENCES articles (id)
                )
            """)
            
            # Categories table - tracks which categories we've fetched
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fetched_categories (
                    category_code TEXT PRIMARY KEY,
                    category_name TEXT NOT NULL,
                    last_fetched TEXT NOT NULL,    -- ISO datetime of last fetch
                    article_count INTEGER DEFAULT 0
                )
            """)
            
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_categories ON articles (categories)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_saved ON article_status (is_saved)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_viewed ON article_status (is_viewed)")
    
    def article_exists(self, article_id: str) -> bool:
        """Check if article already exists in database."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,))
            return cursor.fetchone() is not None
    
    def add_article(self, article: arxiv.Result) -> bool:
        """Add article to database if it doesn't exist. Returns True if added."""
        article_id = article.get_short_id()
        
        if self.article_exists(article_id):
            return False
        
        authors = json.dumps([author.name for author in article.authors])
        categories = json.dumps(article.categories)
        now = datetime.now().isoformat()
        
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO articles (
                    id, entry_id, title, authors, summary, categories,
                    published_date, pdf_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article_id,
                article.entry_id,
                article.title,
                authors,
                article.summary,
                categories,
                article.published.isoformat(),
                article.pdf_url,
                now,
                now
            ))
            
            # Initialize article status
            conn.execute("""
                INSERT INTO article_status (article_id, is_saved, is_viewed)
                VALUES (?, 0, 0)
            """, (article_id,))
        
        return True
    
    def add_articles_batch(self, articles: List[arxiv.Result]) -> int:
        """Add multiple articles in batch. Returns number of new articles added."""
        added_count = 0
        
        with self.get_connection() as conn:
            for article in articles:
                article_id = article.get_short_id()
                
                # Check if exists
                cursor = conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,))
                if cursor.fetchone() is not None:
                    continue
                
                authors = json.dumps([author.name for author in article.authors])
                categories = json.dumps(article.categories)
                now = datetime.now().isoformat()
                
                try:
                    conn.execute("""
                        INSERT INTO articles (
                            id, entry_id, title, authors, summary, categories,
                            published_date, pdf_url, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        article_id,
                        article.entry_id,
                        article.title,
                        authors,
                        article.summary,
                        categories,
                        article.published.isoformat(),
                        article.pdf_url,
                        now,
                        now
                    ))
                    
                    # Initialize article status
                    conn.execute("""
                        INSERT INTO article_status (article_id, is_saved, is_viewed)
                        VALUES (?, 0, 0)
                    """, (article_id,))
                    
                    added_count += 1
                    
                except sqlite3.IntegrityError:
                    # Handle race conditions
                    continue
        
        return added_count
    
    def get_articles_by_category(self, category: str, limit: int = 100) -> List[Dict]:
        """Get articles by category with status information."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE a.categories LIKE ?
                ORDER BY a.published_date DESC
                LIMIT ?
            """, (f'%"{category}"%', limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def search_articles(self, query: str, limit: int = 100) -> List[Dict]:
        """Search articles by title, authors, or summary."""
        with self.get_connection() as conn:
            search_term = f"%{query}%"
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE a.title LIKE ? OR a.authors LIKE ? OR a.summary LIKE ?
                ORDER BY a.published_date DESC
                LIMIT ?
            """, (search_term, search_term, search_term, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_saved_articles(self) -> List[Dict]:
        """Get all saved articles."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at
                FROM articles a
                INNER JOIN article_status s ON a.id = s.article_id
                WHERE s.is_saved = 1
                ORDER BY s.saved_at DESC
            """)
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_articles_by_ids(self, article_ids: List[str]) -> List[Dict]:
        """Get articles by list of IDs."""
        if not article_ids:
            return []
        
        placeholders = ",".join("?" * len(article_ids))
        with self.get_connection() as conn:
            cursor = conn.execute(f"""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE a.id IN ({placeholders})
                ORDER BY a.published_date DESC
            """, article_ids)
            
            return [dict(row) for row in cursor.fetchall()]
    
    def mark_article_viewed(self, article_id: str) -> None:
        """Mark article as viewed."""
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE article_status 
                SET is_viewed = 1, viewed_at = ?
                WHERE article_id = ? AND is_viewed = 0
            """, (now, article_id))
    
    def mark_article_saved(self, article_id: str) -> bool:
        """Mark article as saved. Returns True if status changed."""
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            # Check current status
            cursor = conn.execute("""
                SELECT is_saved FROM article_status WHERE article_id = ?
            """, (article_id,))
            
            row = cursor.fetchone()
            if row is None:
                # Article not in status table, create entry
                conn.execute("""
                    INSERT INTO article_status (article_id, is_saved, is_viewed, saved_at)
                    VALUES (?, 1, 0, ?)
                """, (article_id, now))
                return True
            
            if row['is_saved'] == 1:
                return False  # Already saved
            
            # Mark as saved
            conn.execute("""
                UPDATE article_status 
                SET is_saved = 1, saved_at = ?
                WHERE article_id = ?
            """, (now, article_id))
            return True
    
    def mark_article_unsaved(self, article_id: str) -> bool:
        """Remove saved status from article. Returns True if status changed."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE article_status 
                SET is_saved = 0, saved_at = NULL
                WHERE article_id = ? AND is_saved = 1
            """, (article_id,))
            
            return cursor.rowcount > 0
    
    def mark_article_unread(self, article_id: str) -> bool:
        """Mark article as unread (remove viewed status). Returns True if status changed."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE article_status 
                SET is_viewed = 0, viewed_at = NULL
                WHERE article_id = ? AND is_viewed = 1
            """, (article_id,))
            
            return cursor.rowcount > 0
    
    def get_article_status(self, article_id: str) -> Dict:
        """Get status information for an article."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT is_saved, is_viewed, saved_at, viewed_at
                FROM article_status
                WHERE article_id = ?
            """, (article_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            else:
                return {"is_saved": 0, "is_viewed": 0, "saved_at": None, "viewed_at": None}
    
    def update_category_fetch_info(self, category_code: str, category_name: str, article_count: int) -> None:
        """Update information about when a category was last fetched."""
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO fetched_categories 
                (category_code, category_name, last_fetched, article_count)
                VALUES (?, ?, ?, ?)
            """, (category_code, category_name, now, article_count))
    
    def get_category_fetch_info(self, category_code: str) -> Optional[Dict]:
        """Get information about when a category was last fetched."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM fetched_categories WHERE category_code = ?
            """, (category_code,))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_articles_count(self) -> int:
        """Get total number of articles in database."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) as count FROM articles")
            return cursor.fetchone()['count']
    
    def get_saved_articles_count(self) -> int:
        """Get number of saved articles."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count FROM article_status WHERE is_saved = 1
            """)
            return cursor.fetchone()['count']
    
    def migrate_from_text_files(self, saved_file: str, viewed_file: str) -> Dict[str, int]:
        """Migrate existing data from text files."""
        stats = {"saved_migrated": 0, "viewed_migrated": 0, "errors": 0}
        
        # Migrate saved articles
        try:
            with open(saved_file, "r") as f:
                saved_ids = set(line.strip() for line in f if line.strip())
            
            for article_id in saved_ids:
                try:
                    if self.mark_article_saved(article_id):
                        stats["saved_migrated"] += 1
                except Exception:
                    stats["errors"] += 1
                    
        except FileNotFoundError:
            pass
        
        # Migrate viewed articles  
        try:
            with open(viewed_file, "r") as f:
                viewed_urls = set(line.strip() for line in f if line.strip())
            
            for entry_url in viewed_urls:
                try:
                    # Extract article ID from URL
                    if "abs/" in entry_url:
                        article_id = entry_url.split("abs/")[-1]
                        self.mark_article_viewed(article_id)
                        stats["viewed_migrated"] += 1
                except Exception:
                    stats["errors"] += 1
                    
        except FileNotFoundError:
            pass
        
        return stats

    def get_unread_count_by_category(self, category: str) -> int:
        """Get count of unread articles for a specific category."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE a.categories LIKE ? AND (s.is_viewed IS NULL OR s.is_viewed = 0)
            """, (f'%"{category}"%',))
            return cursor.fetchone()['count']
    
    def get_unread_count_by_filter(self, filter_config: Dict) -> int:
        """Get count of unread articles for a filter configuration."""
        if not filter_config:
            return 0
            
        with self.get_connection() as conn:
            # If filter has categories specified
            if filter_config.get("categories"):
                category_conditions = []
                params = []
                
                for cat in filter_config["categories"]:
                    category_conditions.append("a.categories LIKE ?")
                    params.append(f'%"{cat}"%')
                
                category_clause = " OR ".join(category_conditions)
                
                # If filter also has a query, combine with search
                if filter_config.get("query"):
                    query = filter_config["query"].lower()
                    cursor = conn.execute(f"""
                        SELECT COUNT(*) as count
                        FROM articles a
                        LEFT JOIN article_status s ON a.id = s.article_id
                        WHERE ({category_clause})
                        AND (LOWER(a.title) LIKE ? OR LOWER(a.authors) LIKE ? OR LOWER(a.summary) LIKE ?)
                        AND (s.is_viewed IS NULL OR s.is_viewed = 0)
                    """, params + [f'%{query}%', f'%{query}%', f'%{query}%'])
                else:
                    cursor = conn.execute(f"""
                        SELECT COUNT(*) as count
                        FROM articles a
                        LEFT JOIN article_status s ON a.id = s.article_id
                        WHERE ({category_clause})
                        AND (s.is_viewed IS NULL OR s.is_viewed = 0)
                    """, params)
                    
            # If filter only has query (no categories)
            elif filter_config.get("query"):
                query = filter_config["query"].lower()
                cursor = conn.execute("""
                    SELECT COUNT(*) as count
                    FROM articles a
                    LEFT JOIN article_status s ON a.id = s.article_id
                    WHERE (LOWER(a.title) LIKE ? OR LOWER(a.authors) LIKE ? OR LOWER(a.summary) LIKE ?)
                    AND (s.is_viewed IS NULL OR s.is_viewed = 0)
                """, (f'%{query}%', f'%{query}%', f'%{query}%'))
            else:
                return 0
                
            return cursor.fetchone()['count']
    
    def get_unread_saved_count(self) -> int:
        """Get count of unread saved articles."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM articles a
                INNER JOIN article_status s ON a.id = s.article_id
                WHERE s.is_saved = 1 AND (s.is_viewed IS NULL OR s.is_viewed = 0)
            """)
            return cursor.fetchone()['count'] 