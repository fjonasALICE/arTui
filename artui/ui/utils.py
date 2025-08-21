"""UI utility classes and functions."""

import os
import json
import requests
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


def get_arxiv_ids_from_inspire_ids(inspire_ids: List[int]) -> List[str]:
    """Extract arXiv IDs from INSPIRE-HEP record IDs using arxiv_eprints field.
    
    This function queries the INSPIRE-HEP API for each provided record ID and extracts
    the associated arXiv IDs from the arxiv_eprints field according to the INSPIRE
    schemas documentation at https://inspire-schemas.readthedocs.io
    
    Args:
        inspire_ids: List of INSPIRE-HEP record IDs (integers)
        
    Returns:
        List of arXiv IDs (strings) extracted from the arxiv_eprints field
        
    Example:
        >>> inspire_ids = [1234567, 2345678]
        >>> arxiv_ids = get_arxiv_ids_from_inspire_ids(inspire_ids)
        >>> print(arxiv_ids)  # ['1612.08928', '1701.12345', ...]
    """
    arxiv_ids = []
    
    for inspire_id in inspire_ids:
        try:
            # Fetch the INSPIRE-HEP record data
            url = f"https://inspirehep.net/api/literature/{inspire_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            record = response.json()
            
            # Extract arXiv IDs from arxiv_eprints field
            # Handle both metadata wrapper and direct response formats
            arxiv_eprints = None
            if 'metadata' in record and 'arxiv_eprints' in record['metadata']:
                arxiv_eprints = record['metadata']['arxiv_eprints']
            elif 'arxiv_eprints' in record:
                arxiv_eprints = record['arxiv_eprints']
            

            if arxiv_eprints:
                # only get the first arXiv ID
                for eprint in arxiv_eprints:
                    if 'value' in eprint:
                        arxiv_ids.append(eprint['value'])
                        break
                        
        except requests.exceptions.RequestException as e:
            print(f"Error fetching INSPIRE-HEP record {inspire_id}: {e}")
        except KeyError as e:
            print(f"Missing field in INSPIRE-HEP record {inspire_id}: {e}")
        except Exception as e:
            print(f"Unexpected error processing INSPIRE-HEP record {inspire_id}: {e}")
    
    return arxiv_ids


def get_citing_articles_from_inspire_id(inspire_id: int, max_results: int = 100) -> List[str]:
    """Get arXiv IDs of articles that cite the given INSPIRE-HEP record.
    
    Args:
        inspire_id: INSPIRE-HEP record ID
        max_results: Maximum number of citing articles to retrieve
        
    Returns:
        List of arXiv IDs of articles that cite the given paper
    """
    arxiv_ids = []
    
    try:
        # Search for articles that cite the given record using INSPIRE-HEP API
        base_url = "https://inspirehep.net/api/literature"
        query = f"refersto:recid:{inspire_id}"
        params = {
            "q": query,
            "size": max_results,
            "fields": "arxiv_eprints"  # Only get arXiv eprints field
        }
        
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        hits = data.get("hits", {}).get("hits", [])
        
        for hit in hits:
            metadata = hit.get("metadata", {})
            arxiv_eprints = metadata.get("arxiv_eprints", [])
            
            # Extract arXiv ID from the first eprint (most papers have only one)
            if arxiv_eprints:
                for eprint in arxiv_eprints:
                    if 'value' in eprint:
                        arxiv_ids.append(eprint['value'])
                        break  # Only take the first arXiv ID per paper
        
        print(f"Found {len(arxiv_ids)} citing articles with arXiv IDs from {len(hits)} total citing articles")
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching citing articles from INSPIRE-HEP: {e}")
    except KeyError as e:
        print(f"Missing field in INSPIRE-HEP response: {e}")
    except Exception as e:
        print(f"Unexpected error fetching citing articles: {e}")
    
    return arxiv_ids
