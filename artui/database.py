"""Database management for ArTui."""

import os
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Set
import arxiv
from .user_dirs import get_user_dirs


class ArticleDatabase:
    """Database manager for ArXiv articles with SQLite backend."""
    
    def __init__(self, db_path: Optional[str] = None, custom_user_dir: Optional[str] = None):
        # Initialize user directories
        self.user_dirs = get_user_dirs(custom_user_dir)
        
        # Use provided path or default to user data directory
        if db_path is None:
            self.db_path = self.user_dirs.database_file
        else:
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
                    updated_at TEXT NOT NULL,      -- Last update
                    notes_file_path TEXT           -- Path to notes file
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
            self._create_indexes(conn)
            
            # Run database migrations
            self._migrate_database()
    
    def _create_indexes(self, conn: sqlite3.Connection) -> None:
        """Create database indexes for better performance."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published_date)",
            "CREATE INDEX IF NOT EXISTS idx_articles_categories ON articles (categories)",
            "CREATE INDEX IF NOT EXISTS idx_status_saved ON article_status (is_saved)",
            "CREATE INDEX IF NOT EXISTS idx_status_viewed ON article_status (is_viewed)",
            "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags (name)",
            "CREATE INDEX IF NOT EXISTS idx_article_tags_article ON article_tags (article_id)",
            "CREATE INDEX IF NOT EXISTS idx_article_tags_tag ON article_tags (tag_id)",

        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
    
    def _migrate_database(self) -> None:
        """Run database migrations for schema updates."""
        with self.get_connection() as conn:
            # Check if citation_count column exists
            cursor = conn.execute("PRAGMA table_info(articles)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'citation_count' not in columns:
                conn.execute("ALTER TABLE articles ADD COLUMN citation_count INTEGER DEFAULT 0")
                
            if 'citations_updated_at' not in columns:
                conn.execute("ALTER TABLE articles ADD COLUMN citations_updated_at TEXT")

            if 'notes_file_path' not in columns:
                conn.execute("ALTER TABLE articles ADD COLUMN notes_file_path TEXT")
    
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
    
    def get_articles_by_category(self, category: str, feed_retention_days: Optional[int] = None) -> List[Dict]:
        """Get articles by category with status information, optionally filtered by feed retention."""
        with self.get_connection() as conn:
            retention_filter = self._get_feed_retention_filter(feed_retention_days)
            cursor = conn.execute(f"""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags

                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id

                WHERE EXISTS (
                    SELECT 1 FROM json_each(a.categories) 
                    WHERE json_each.value = ?
                ) AND {retention_filter}
                ORDER BY a.published_date DESC
            """, (category,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def search_articles(self, query: str, feed_retention_days: Optional[int] = None) -> List[Dict]:
        """Search articles by title, authors, or summary, optionally filtered by feed retention."""
        with self.get_connection() as conn:
            search_term = f"%{query}%"
            retention_filter = self._get_feed_retention_filter(feed_retention_days)
            cursor = conn.execute(f"""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags

                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id

                WHERE (a.title LIKE ? OR a.authors LIKE ? OR a.summary LIKE ?)
                  AND {retention_filter}
                ORDER BY a.published_date DESC
            """, (search_term, search_term, search_term))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def search_articles_in_categories(self, query: str, categories: List[str], feed_retention_days: Optional[int] = None) -> List[Dict]:
        """Search articles by title, authors, or summary, restricted to given categories, optionally filtered by feed retention."""
        if not categories:
            return self.search_articles(query, feed_retention_days)
        with self.get_connection() as conn:
            search_term = f"%{query}%"
            retention_filter = self._get_feed_retention_filter(feed_retention_days)
            # Build category conditions using JSON functions
            category_conditions = []
            params = []
            for cat in categories:
                category_conditions.append("EXISTS (SELECT 1 FROM json_each(a.categories) WHERE json_each.value = ?)")
                params.append(cat)
            category_clause = " OR ".join(category_conditions)
            sql = f'''
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags

                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id

                WHERE ({category_clause})
                  AND (a.title LIKE ? OR a.authors LIKE ? OR a.summary LIKE ?)
                  AND {retention_filter}
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
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_articles(self, feed_retention_days: Optional[int] = None) -> List[Dict]:
        """Get all articles from database, optionally filtered by feed retention."""        
        with self.get_connection() as conn:
            retention_filter = self._get_feed_retention_filter(feed_retention_days)
            cursor = conn.execute(f"""
                SELECT a.*, 
                       COALESCE(s.is_saved, 0) as is_saved, 
                       COALESCE(s.is_viewed, 0) as is_viewed, 
                       s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id
                WHERE {retention_filter}
                ORDER BY a.published_date DESC
            """)
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_articles_with_notes(self) -> List[Dict]:
        """Get all articles that have notes."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT a.*, s.is_saved, s.is_viewed, s.saved_at, s.viewed_at,
                       CASE WHEN at.article_id IS NOT NULL THEN 1 ELSE 0 END as has_tags

                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                LEFT JOIN (SELECT DISTINCT article_id FROM article_tags) at ON a.id = at.article_id

                WHERE a.notes_file_path IS NOT NULL
                ORDER BY a.published_date DESC
            """)
            
            return [dict(row) for row in cursor.fetchall()]
    
    def _get_feed_retention_filter(self, retention_days: Optional[int]) -> str:
        """Get SQL condition for feed retention filtering."""
        if retention_days is None:
            return "1=1"  # No filtering
        
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()
        return f"""
            (a.published_date >= '{cutoff_date}' 
             OR s.is_viewed IS NULL 
             OR s.is_viewed = 0)
        """
    
    # Status management methods
    
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
    
    # Count methods
    
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
    
    def get_feed_articles_count(self, feed_retention_days: Optional[int] = None) -> int:
        """Get count of articles in feed (less than retention period days old OR unread)."""
        with self.get_connection() as conn:
            retention_filter = self._get_feed_retention_filter(feed_retention_days)
            cursor = conn.execute(f"""
                SELECT COUNT(*) as count
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE {retention_filter}
            """)
            return cursor.fetchone()['count']
    
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
    
    def get_unread_count_with_notes(self) -> int:
        """Get count of unread articles that have notes."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE a.notes_file_path IS NOT NULL 
                AND (s.is_viewed IS NULL OR s.is_viewed = 0)
            """)
            return cursor.fetchone()['count']
    
    def get_unread_count_by_category(self, category: str, feed_retention_days: Optional[int] = None) -> int:
        """Get count of unread articles for a specific category, optionally filtered by feed retention."""
        with self.get_connection() as conn:
            retention_filter = self._get_feed_retention_filter(feed_retention_days)
            cursor = conn.execute(f"""
                SELECT COUNT(*) as count
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE EXISTS (
                    SELECT 1 FROM json_each(a.categories) 
                    WHERE json_each.value = ?
                ) AND (s.is_viewed IS NULL OR s.is_viewed = 0)
                  AND {retention_filter}
            """, (category,))
            return cursor.fetchone()['count']
    
    def get_unread_count_by_filter(self, filter_config: Dict, feed_retention_days: Optional[int] = None) -> int:
        """Get count of unread articles for a filter configuration, optionally filtered by feed retention."""
        if not filter_config:
            return 0
            
        with self.get_connection() as conn:
            retention_filter = self._get_feed_retention_filter(feed_retention_days)
            # If filter has categories specified
            if filter_config.get("categories"):
                category_conditions = []
                params = []
                
                for cat in filter_config["categories"]:
                    category_conditions.append("EXISTS (SELECT 1 FROM json_each(a.categories) WHERE json_each.value = ?)")
                    params.append(cat)
                
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
                        AND {retention_filter}
                    """, params + [f'%{query}%', f'%{query}%', f'%{query}%'])
                else:
                    cursor = conn.execute(f"""
                        SELECT COUNT(*) as count
                        FROM articles a
                        LEFT JOIN article_status s ON a.id = s.article_id
                        WHERE ({category_clause})
                        AND (s.is_viewed IS NULL OR s.is_viewed = 0)
                        AND {retention_filter}
                    """, params)
                    
            # If filter only has query (no categories)
            elif filter_config.get("query"):
                query = filter_config["query"].lower()
                cursor = conn.execute(f"""
                    SELECT COUNT(*) as count
                    FROM articles a
                    LEFT JOIN article_status s ON a.id = s.article_id
                    WHERE (LOWER(a.title) LIKE ? OR LOWER(a.authors) LIKE ? OR LOWER(a.summary) LIKE ?)
                    AND (s.is_viewed IS NULL OR s.is_viewed = 0)
                    AND {retention_filter}
                """, (f'%{query}%', f'%{query}%', f'%{query}%'))
            else:
                return 0
                
            return cursor.fetchone()['count']
    

    
    # Tag management methods
    
    def add_tag(self, name: str) -> int:
        """Add a new tag if it doesn't exist. Returns tag ID."""
        with self.get_connection() as conn:
            now = datetime.now().isoformat()
            try:
                cursor = conn.execute("""
                    INSERT INTO tags (name, created_at) VALUES (?, ?)
                """, (name, now))
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Tag already exists, get its ID
                cursor = conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
                result = cursor.fetchone()
                return result['id'] if result else None
    
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
            return [dict(row) for row in cursor.fetchall()]
    
    def add_article_tag(self, article_id: str, tag_name: str) -> bool:
        """Associate a tag with an article. Returns True if added.
        Automatically marks the article as saved when a tag is added."""
        tag_id = self.add_tag(tag_name)
        now = datetime.now().isoformat()
        
        with self.get_connection() as conn:
            try:
                # Insert the tag relationship
                conn.execute("""
                    INSERT INTO article_tags (article_id, tag_id, created_at)
                    VALUES (?, ?, ?)
                """, (article_id, tag_id, now))
                
                # Automatically mark article as saved when adding a tag
                # Do this within the same transaction to avoid database locks
                conn.execute("""
                    INSERT OR REPLACE INTO article_status (article_id, is_saved, is_viewed, saved_at, viewed_at)
                    VALUES (?, 1, 
                            COALESCE((SELECT is_viewed FROM article_status WHERE article_id = ?), 0),
                            ?,
                            (SELECT viewed_at FROM article_status WHERE article_id = ?))
                """, (article_id, article_id, now, article_id))
                
                return True
            except sqlite3.IntegrityError:
                # Relationship already exists
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
            return [row['name'] for row in cursor.fetchall()]
    
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
    
    def cleanup_old_unsaved_articles(self, retention_days: int) -> int:
        """Remove articles that are older than retention period AND not saved. Returns number of articles removed."""
        from datetime import datetime, timedelta
        
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()
        
        with self.get_connection() as conn:
            # First, get the IDs of articles to be deleted for cleanup of related data
            cursor = conn.execute("""
                SELECT a.id 
                FROM articles a
                LEFT JOIN article_status s ON a.id = s.article_id
                WHERE a.published_date < ? 
                AND (s.is_saved IS NULL OR s.is_saved = 0)
            """, (cutoff_date,))
            
            article_ids_to_delete = [row['id'] for row in cursor.fetchall()]
            
            if not article_ids_to_delete:
                return 0
            
            # Delete related data first (to maintain referential integrity)
            placeholders = ','.join('?' * len(article_ids_to_delete))
            
            # Delete article tags
            conn.execute(f"""
                DELETE FROM article_tags 
                WHERE article_id IN ({placeholders})
            """, article_ids_to_delete)
            
            # Delete article status
            conn.execute(f"""
                DELETE FROM article_status 
                WHERE article_id IN ({placeholders})
            """, article_ids_to_delete)
            
            # Delete articles
            cursor = conn.execute(f"""
                DELETE FROM articles 
                WHERE id IN ({placeholders})
            """, article_ids_to_delete)
            
            deleted_count = cursor.rowcount
            
            # Clean up orphaned tags after article deletion
            self.cleanup_orphan_tags()
            
            return deleted_count
    
    def article_has_tags(self, article_id: str) -> bool:
        """Check if an article has any tags."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM article_tags WHERE article_id = ? LIMIT 1
            """, (article_id,))
            return cursor.fetchone() is not None
    

    
    # Notes management methods
    
    def set_notes_path(self, article_id: str, path: str) -> bool:
        """Set the notes file path for an article.
        Automatically marks the article as saved when notes are added."""
        now = datetime.now().isoformat()
        
        with self.get_connection() as conn:
            # Update the notes path
            cursor = conn.execute("""
                UPDATE articles 
                SET notes_file_path = ?
                WHERE id = ?
            """, (path, article_id))
            
            # Automatically mark article as saved when adding notes
            # Do this within the same transaction to avoid database locks
            if cursor.rowcount > 0:
                conn.execute("""
                    INSERT OR REPLACE INTO article_status (article_id, is_saved, is_viewed, saved_at, viewed_at)
                    VALUES (?, 1, 
                            COALESCE((SELECT is_viewed FROM article_status WHERE article_id = ?), 0),
                            ?,
                            (SELECT viewed_at FROM article_status WHERE article_id = ?))
                """, (article_id, article_id, now, article_id))
            
            return cursor.rowcount > 0

    def get_notes_path(self, article_id: str) -> Optional[str]:
        """Get the notes file path for an article."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT notes_file_path FROM articles WHERE id = ?", (article_id,))
            row = cursor.fetchone()
            return row['notes_file_path'] if row else None

    def clear_notes_path(self, article_id: str) -> bool:
        """Clear the notes file path for an article."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE articles 
                SET notes_file_path = NULL
                WHERE id = ?
            """, (article_id,))
            return cursor.rowcount > 0
    
    # Category fetch tracking methods
    
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
    
    # Migration methods
    
    def migrate_from_text_files(self, saved_file: Optional[str] = None, viewed_file: Optional[str] = None) -> Dict[str, int]:
        """Migrate existing data from text files."""
        stats = {"saved_migrated": 0, "viewed_migrated": 0, "errors": 0}
        
        # Use default paths if not provided
        if saved_file is None:
            saved_file = "saved_articles.txt"
        if viewed_file is None:
            viewed_file = "viewed_articles.txt"
        
        # Check both current directory and user data directory
        possible_locations = [
            "",  # Current directory
            self.user_dirs.base_dir  # User data directory
        ]
        
        # Migrate saved articles
        for location in possible_locations:
            saved_path = os.path.join(location, saved_file) if location else saved_file
            try:
                with open(saved_path, "r") as f:
                    saved_ids = set(line.strip() for line in f if line.strip())
                
                for article_id in saved_ids:
                    try:
                        if self.mark_article_saved(article_id):
                            stats["saved_migrated"] += 1
                    except Exception:
                        stats["errors"] += 1
                break  # Success, don't try other locations
                        
            except FileNotFoundError:
                continue  # Try next location
        
        # Migrate viewed articles  
        for location in possible_locations:
            viewed_path = os.path.join(location, viewed_file) if location else viewed_file
            try:
                with open(viewed_path, "r") as f:
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
                break  # Success, don't try other locations
                        
            except FileNotFoundError:
                continue  # Try next location
        
        return stats
