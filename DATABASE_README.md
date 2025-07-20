# ArXiv Reader Database Functionality

This document describes the new persistent database functionality added to the ArXiv reader application.

## Overview

The application now uses a SQLite database to:
- Store all ever-fetched articles (prevents duplicates)
- Track saved and viewed status for each article
- Fetch articles for all configured categories at startup
- Provide fast local search and filtering

## Database Schema

### Tables

1. **articles** - Stores article metadata
   - `id` (PRIMARY KEY): ArXiv ID (e.g., "2507.13213v1")
   - `entry_id`: Full ArXiv URL
   - `title`: Article title
   - `authors`: JSON array of author names
   - `summary`: Article abstract
   - `categories`: JSON array of categories
   - `published_date`: Publication date (ISO format)
   - `pdf_url`: URL to PDF file
   - `created_at`: When first fetched
   - `updated_at`: Last update timestamp

2. **article_status** - Tracks user interactions
   - `article_id` (PRIMARY KEY): Foreign key to articles.id
   - `is_saved`: Boolean (0/1) - saved by user
   - `is_viewed`: Boolean (0/1) - viewed by user
   - `saved_at`: Timestamp when saved
   - `viewed_at`: Timestamp when first viewed

3. **fetched_categories** - Tracks category fetch history
   - `category_code` (PRIMARY KEY): Category identifier
   - `category_name`: Human-readable category name
   - `last_fetched`: Timestamp of last fetch
   - `article_count`: Number of articles fetched

## Features

### Automatic Article Fetching

On application startup, the system automatically fetches recent articles (last 3 days) for all configured categories in the background. This ensures the local database is always up-to-date.

### Duplicate Prevention

Articles are only added once to the database. The system checks for existing articles by their ArXiv ID before adding new ones.

### Migration from Text Files

Existing data from `saved_articles.txt` and `viewed_articles.txt` is automatically migrated to the database on first run.

### Local Search and Filtering

All searches and filtering now happen locally against the database, making the application much faster and reducing API calls to ArXiv.

## Command Line Tools

### Startup Fetcher

Run the fetcher independently to populate or update the database:

```bash
# Fetch recent articles (last 7 days)
python3 startup_fetcher.py --recent 7

# Fetch all configured categories (full fetch)
python3 startup_fetcher.py

# Force fetch even if recently fetched
python3 startup_fetcher.py --force

# Use custom config file
python3 startup_fetcher.py --config my_config.yaml --db my_articles.db
```

## Database Operations

The `ArticleDatabase` class provides the following main operations:

- `add_article(article)` - Add single article
- `add_articles_batch(articles)` - Add multiple articles efficiently
- `get_articles_by_category(category)` - Get articles for specific category
- `search_articles(query)` - Full-text search
- `get_saved_articles()` - Get all saved articles
- `mark_article_saved/unsaved(article_id)` - Update saved status
- `mark_article_viewed(article_id)` - Mark as viewed

## Configuration

The database uses the existing `arxiv_config.yaml` configuration file to determine which categories and filters to fetch.

## File Structure

- `database.py` - Database operations and schema
- `startup_fetcher.py` - Article fetching functionality
- `main.py` - Updated main application with database integration
- `arxiv_articles.db` - SQLite database file (created automatically)

## Performance Benefits

1. **Faster searches** - Local database queries vs API calls
2. **Offline capability** - Browse previously fetched articles offline
3. **No duplicate fetching** - Articles are only fetched once
4. **Persistent state** - Saved/viewed status survives app restarts
5. **Batch operations** - Efficient bulk article processing

## Migration

The application automatically handles migration from the old text-file based system:

1. On first run, existing `saved_articles.txt` and `viewed_articles.txt` files are read
2. Data is imported into the database
3. Original text files are preserved but no longer used

## Troubleshooting

### Database Issues
If you encounter database issues, you can:
1. Delete the `arxiv_articles.db` file to reset
2. Re-run the application to rebuild from scratch
3. Use the fetcher tool to repopulate articles

### Performance Issues
- The database includes indexes on commonly queried columns
- For very large datasets, consider periodically cleaning old articles
- Search performance scales well with database size

### SSL Warnings
The urllib3 warnings about OpenSSL can be safely ignored - they don't affect functionality. 