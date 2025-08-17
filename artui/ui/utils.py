"""UI utility classes and functions."""

import os
import json
from datetime import datetime
from typing import Dict, Any, List


class MockArticle:
    """Mock article object that mimics arxiv.Result for database results."""
    
    def __init__(self, db_result: Dict[str, Any]):
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
        if 'T' in db_result['published_date']:
            self.published = datetime.fromisoformat(db_result['published_date'].replace('Z', '+00:00'))
        else:
            self.published = datetime.fromisoformat(db_result['published_date'])
        
        # Add status information
        self.is_saved = bool(db_result.get('is_saved', 0))
        self.is_viewed = bool(db_result.get('is_viewed', 0))
        self.has_tags = bool(db_result.get('has_tags', 0))
        self.notes_file_path = db_result.get('notes_file_path')
        self.has_note = bool(self.notes_file_path)
    
    def get_short_id(self) -> str:
        """Get the short arXiv ID."""
        return self.id
    
    def construct_filepath(self, dirpath: str = ".") -> str:
        """Construct filepath for PDF file."""
        filename = f"{self.id}.{self.title[:50].replace('/', '_').replace(':', '_')}.pdf"
        # Remove any problematic characters
        filename = "".join(c for c in filename if c.isalnum() or c in '.-_')
        filepath = os.path.join(dirpath, filename)
        return filepath
    
    def is_downloaded(self, dirpath: str = ".") -> bool:
        """Check if PDF file exists."""
        filepath = self.construct_filepath(dirpath)
        return os.path.exists(filepath)
    
    def download_pdf(self, dirpath: str = ".") -> str:
        """Download PDF file to specified directory."""
        import requests
        
        filepath = self.construct_filepath(dirpath)
        
        # Download the PDF
        if not self.is_downloaded(dirpath):
            response = requests.get(self.pdf_url, stream=True)
            response.raise_for_status()
        
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        return filepath


def convert_db_results_to_articles(db_results: List[Dict[str, Any]]) -> List[MockArticle]:
    """Convert database results to MockArticle objects."""
    return [MockArticle(result) for result in db_results]


def debug_log(msg: str) -> None:
    """Write debug message to stderr and a debug file."""
    import sys
    print(f"DEBUG: {msg}", file=sys.stderr, flush=True)
    with open("debug.log", "a") as f:
        f.write(f"DEBUG: {msg}\n")
        f.flush()
