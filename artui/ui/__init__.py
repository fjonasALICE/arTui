"""UI components for ArTui."""

from .screens import (
    SelectionPopupScreen,
    BibtexPopupScreen, 
    TagPopupScreen,
    NotesPopupScreen,
    AdvancedSearchPopupScreen
)
from .widgets import ArticleTableWidget
from .utils import MockArticle

__all__ = [
    "SelectionPopupScreen",
    "BibtexPopupScreen", 
    "TagPopupScreen",
    "NotesPopupScreen",
    "AdvancedSearchPopupScreen",
    "ArticleTableWidget",
    "MockArticle"
]
