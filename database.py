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
                    citation_count INTEGER DEFAULT 0,  -- Number of citations
                    citations_updated_at TEXT,     -- When citations were last fetched
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
            
            # Tags table - stores unique tags
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Article tags table - many-to-many relationship between articles and tags
            conn.execute("""
                CREATE TABLE IF NOT EXISTS article_tags (
                    article_id TEXT NOT NULL,
                    tag_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (article_id, tag_id),
                    FOREIGN KEY (article_id) REFERENCES articles (id),
                    FOREIGN KEY (tag_id) REFERENCES tags (id)
                )
            """)
            
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_categories ON articles (categories)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_saved ON article_status (is_saved)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_viewed ON article_status (is_viewed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_name ON tags (name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_article_tags_article ON article_tags (article_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_article_tags_tag ON article_tags (tag_id)")
            
            # Verify tables were created
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"DEBUG: Database tables: {tables}")
            
            # Check if tags table has the right structure
            cursor = conn.execute("PRAGMA table_info(tags)")
            tag_columns = [col[1] for col in cursor.fetchall()]
            print(f"DEBUG: Tags table columns: {tag_columns}")
            
            # Check if article_tags table has the right structure
            cursor = conn.execute("PRAGMA table_info(article_tags)")
            article_tags_columns = [col[1] for col in cursor.fetchall()]
            print(f"DEBUG: Article_tags table columns: {article_tags_columns}")
            
            # Run database migrations
            self._migrate_database()
    
    def _migrate_database(self) -> None:
        """Run database migrations for schema updates."""
        with self.get_connection() as conn:
            # Check if citation_count column exists
            cursor = conn.execute("PRAGMA table_info(articles)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'citation_count' not in columns:
                # Add citation_count column
                conn.execute("ALTER TABLE articles ADD COLUMN citation_count INTEGER DEFAULT 0")
                
            if 'citations_updated_at' not in columns:
                # Add citations_updated_at column
                conn.execute("ALTER TABLE articles ADD COLUMN citations_updated_at TEXT")

            if 'notes_file_path' not in columns:
                # Add notes_file_path column
                conn.execute("ALTER TABLE articles ADD COLUMN notes_file_path TEXT")
    
    def article_exists(self, article_id: str) -> bool:
        """Check if article already exists in database."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,))
            return cursor.fetchone() is not None
    
    def set_notes_path(self, article_id: str, path: str) -> bool:
        """Set the notes file path for an article."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE articles 
                SET notes_file_path = ?
                WHERE id = ?
            """, (path, article_id))
            return cursor.rowcount > 0

    def get_notes_path(self, article_id: str) -> Optional[str]:
        """Get the notes file path for an article."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT notes_file_path FROM articles WHERE id = ?", (article_id,))
            row = cursor.fetchone()
            return row['notes_file_path'] if row else None
    
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
                    published_date, pdf_url, citation_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article_id,
                article.entry_id,
                article.title,
                authors,
                article.summary,
                categories,
                article.published.isoformat(),
                article.pdf_url,
                0,  # Initialize citation count to 0
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
                            published_date, pdf_url, citation_count, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        article_id,
                        article.entry_id,
                        article.title,
                        authors,
                        article.summary,
                        categories,
                        article.published.isoformat(),
                        article.pdf_url,
                        0,  # Initialize citation count to 0
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
    
    def get_articles_by_category(self, category: str) -> List[Dict]:
        """Get articles by category with status information."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
                WHERE a.categories LIKE ?
                ORDER BY a.published_date DESC
            """, (f'%"{category}"%'))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def search_articles(self, query: str) -> List[Dict]:
        """Search articles by title, authors, or summary."""
        with self.get_connection() as conn:
            search_term = f"%{query}%"
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
                WHERE a.title LIKE ? OR a.authors LIKE ? OR a.summary LIKE ?
                ORDER BY a.published_date DESC
            """, (search_term, search_term, search_term))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def search_articles_in_categories(self, query: str, categories: List[str]) -> List[Dict]:
        """Search articles by title, authors, or summary, restricted to given categories."""
        if not categories:
            return self.search_articles(query)
        with self.get_connection() as conn:
            search_term = f"%{query}%"
            # Build category conditions
            category_conditions = []
            params = []
            for cat in categories:
                category_conditions.append("a.categories LIKE ?")
                params.append(f'%"{cat}"%')
            category_clause = " OR ".join(category_conditions)
            sql = f'''
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
                WHERE ({category_clause})
                  AND (a.title LIKE ? OR a.authors LIKE ? OR a.summary LIKE ?)
                ORDER BY a.published_date DESC
            '''
            params += [search_term, search_term, search_term]
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_saved_articles(self) -> List[Dict]:
        """Get all saved articles."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                INNER JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
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
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
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

    def update_citation_count(self, article_id: str, citation_count: int) -> bool:
        """Update citation count for an article."""
        with self.get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute("""
                UPDATE articles 
                SET citation_count = ?, citations_updated_at = ?
                WHERE id = ?
            """, (citation_count, now, article_id))
            return cursor.rowcount > 0

    def get_articles_needing_citation_update(self, days_old: int = 7) -> List[Dict]:
        """Get articles that need citation count updates (haven't been updated in X days)."""
        with self.get_connection() as conn:
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=days_old)).isoformat()
            
            cursor = conn.execute("""
                SELECT id, title, entry_id
                FROM articles 
                WHERE citations_updated_at IS NULL 
                   OR citations_updated_at < ?
                ORDER BY published_date DESC
            """, (cutoff_date,))
            
            return [dict(row) for row in cursor.fetchall()]

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

    # Tag-related methods
    
    def add_tag(self, name: str) -> int:
        """Add a new tag if it doesn't exist. Returns tag ID."""
        with self.get_connection() as conn:
            now = datetime.now().isoformat()
            try:
                cursor = conn.execute("""
                    INSERT INTO tags (name, created_at) VALUES (?, ?)
                """, (name, now))
                tag_id = cursor.lastrowid
                print(f"DEBUG: Created new tag '{name}' with ID {tag_id}")
                return tag_id
            except sqlite3.IntegrityError:
                # Tag already exists, get its ID
                cursor = conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
                result = cursor.fetchone()
                if result:
                    tag_id = result['id']
                    print(f"DEBUG: Found existing tag '{name}' with ID {tag_id}")
                    return tag_id
                else:
                    print(f"DEBUG: ERROR - Tag '{name}' should exist but wasn't found")
                    raise
    
    def get_all_tags(self) -> List[Dict]:
        """Get all tags sorted by name."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT t.*, COUNT(at.article_id) as article_count
                FROM tags t
                LEFT JOIN article_tags at ON t.id = at.tag_id
                GROUP BY t.id, t.name, t.created_at
                ORDER BY t.name
            """)
            results = [dict(row) for row in cursor.fetchall()]
            print(f"DEBUG: get_all_tags() returned {len(results)} tags: {[r['name'] for r in results]}")
            return results
    
    def add_article_tag(self, article_id: str, tag_name: str) -> bool:
        """Associate a tag with an article. Returns True if added."""
        print(f"DEBUG: add_article_tag called with article_id={article_id}, tag_name={tag_name}")
        tag_id = self.add_tag(tag_name)
        print(f"DEBUG: Got tag_id {tag_id} for tag '{tag_name}'")
        now = datetime.now().isoformat()
        
        with self.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO article_tags (article_id, tag_id, created_at)
                    VALUES (?, ?, ?)
                """, (article_id, tag_id, now))
                print(f"DEBUG: Successfully linked article {article_id} to tag '{tag_name}' (ID: {tag_id})")
                return True
            except sqlite3.IntegrityError as e:
                # Relationship already exists
                print(f"DEBUG: Article-tag relationship already exists: {e}")
                return False
    
    def remove_article_tag(self, article_id: str, tag_name: str) -> bool:
        """Remove a tag from an article. Returns True if removed."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM article_tags 
                WHERE article_id = ? AND tag_id = (
                    SELECT id FROM tags WHERE name = ?
                )
            """, (article_id, tag_name))
            return cursor.rowcount > 0
    
    def get_article_tags(self, article_id: str) -> List[str]:
        """Get all tags for a specific article."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT t.name
                FROM tags t
                INNER JOIN article_tags at ON t.id = at.tag_id
                WHERE at.article_id = ?
                ORDER BY t.name
            """, (article_id,))
            tags = [row['name'] for row in cursor.fetchall()]
            print(f"DEBUG: get_article_tags for {article_id}: {tags}")
            return tags
    
    def get_articles_by_tag(self, tag_name: str) -> List[Dict]:
        """Get articles with a specific tag."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       1 as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                INNER JOIN article_tags at ON a.id = at.article_id
                INNER JOIN tags t ON at.tag_id = t.id
                WHERE t.name = ?
                ORDER BY a.published_date DESC
            """, (tag_name,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_unread_count_by_tag(self, tag_name: str) -> int:
        """Get count of unread articles for a specific tag."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                INNER JOIN article_tags at ON a.id = at.article_id
                INNER JOIN tags t ON at.tag_id = t.id
                WHERE t.name = ? AND (s.is_viewed IS NULL OR s.is_viewed = 0)
            """, (tag_name,))
            return cursor.fetchone()['count']
    
    def cleanup_orphan_tags(self) -> int:
        """Remove tags that are no longer associated with any articles. Returns number of tags removed."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM tags
                WHERE id NOT IN (SELECT DISTINCT tag_id FROM article_tags)
            """)
            return cursor.rowcount
    
    def article_has_tags(self, article_id: str) -> bool:
        """Check if an article has any tags."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM article_tags WHERE article_id = ? LIMIT 1
            """, (article_id,))
            return cursor.fetchone() is not None

    def get_unread_articles(self) -> List[Dict]:
        """Get all unread articles."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
                WHERE s.is_viewed IS NULL OR s.is_viewed = 0
                ORDER BY a.published_date DESC
            """)
            
            results = [dict(row) for row in cursor.fetchall()]
            return results
    
    def get_unread_count(self) -> int:
        """Get count of all unread articles."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE s.is_viewed IS NULL OR s.is_viewed = 0
            """)
            return cursor.fetchone()['count']
    
    def get_all_articles(self) -> List[Dict]:
        """Get all articles from database, regardless of status."""        
        with self.get_connection() as conn:
            # Simple query - just get all articles with basic status info
            cursor = conn.execute("""
                SELECT a.*, 
                       COALESCE(s.is_saved, 0) as is_saved, 
                       COALESCE(s.is_viewed, 0) as is_viewed, 
                       s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
                ORDER BY a.published_date DESC
            """)
            
            results = [dict(row) for row in cursor.fetchall()]
            
            return results 