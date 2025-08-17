"""
ArTui - A Terminal User Interface for browsing arXiv papers.

A modern TUI application for researchers to stay up-to-date with recent publications
in their field, featuring persistent local database, tag management, notes, and more.
"""

__version__ = "1.0.0"
__author__ = "Florian Jonas"
__email__ = "florian.jonas@cern.ch"
__description__ = "A Terminal User Interface for browsing arXiv papers"

from .app import ArxivReaderApp
from .database import ArticleDatabase
from .config import ConfigManager

__all__ = ["ArxivReaderApp", "ArticleDatabase", "ConfigManager"]
