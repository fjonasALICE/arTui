"""Modal screens for ArTui."""

import os
import re
from typing import Optional, List, Dict, Any

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Static, Input, Select, Checkbox, TextArea, ListView, ListItem
)
from textual.screen import ModalScreen
from textual import events

from .utils import get_arxiv_ids_from_inspire_ids


class SelectionPopupScreen(ModalScreen):
    """Screen with a dropdown to select a view."""

    def __init__(self, options: List[tuple], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = options

    def compose(self):
        yield Vertical(
            Static("Select a View", id="selection_popup_title"),
            Select(self.options, prompt="Select...", id="selection_popup_select"),
            id="selection_popup_dialog",
        )

    def on_mount(self) -> None:
        self.query_one(Select).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        self.dismiss(event.value)


class BibtexPopupScreen(ModalScreen):
    """Screen to display bibtex citation information."""

    def __init__(self, bibtex_content: str, n_citations: int, inspire_link: str, article_title: str, references: List[str], inspire_id: int = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bibtex_content = bibtex_content
        self.n_citations = n_citations
        self.inspire_link = inspire_link
        self.article_title = article_title
        self.references = references
        self.inspire_id = inspire_id


    def compose(self):
        # Create clickable citations text
        if self.n_citations > 0 and self.inspire_id:
            citations_text = f"[bold]Citations:[/] {self.n_citations} [dim](click to view citing articles)[/]"
        else:
            citations_text = f"[bold]Citations:[/] {self.n_citations}"
        
        # Create clickable references text
        if len(self.references) > 0:
            ref_count = len(self.references)
            ref_text = "reference" if ref_count == 1 else "references"
            references_text = f"[bold]References:[/] {ref_count} {ref_text} [dim](click to view references)[/]"
        else:
            references_text = f"[bold]References:[/] 0 references"
        
        yield Vertical(
            Static("[bold $primary]Inspire-HEP Information[/]", id="bibtex_popup_title"),
            Static(f"[bold]Article:[/] {self.article_title[:60]}{'...' if len(self.article_title) > 60 else ''}", id="bibtex_article_title"),
            Static(citations_text, id="citation_count"),
            Static(references_text, id="references"),
            Static(f"[bold]Inspire Link:[/] [@click=\"app.open_link('{self.inspire_link}')\"]{self.inspire_link}[/]", id="inspire_link"),
            Static("[bold $primary]BibTeX[/]", id="bibtex_label"),
            VerticalScroll(
                Static(self.bibtex_content, id="bibtex_content"),
                id="bibtex_scroll"
            ),
            Horizontal(
                Button("Copy BibTeX", variant="primary", id="bibtex_copy_button"),
                Button("Close", variant="primary", id="bibtex_close_button"),
                id="bibtex_buttons"
            ),
            id="bibtex_popup_dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#bibtex_close_button", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bibtex_close_button":
            self.dismiss()
        elif event.button.id == "bibtex_copy_button":
            import pyperclip
            pyperclip.copy(self.bibtex_content)
            self.notify("BibTeX copied to clipboard", timeout=2)
    
    def on_click(self, event: events.Click) -> None:
        """Handle clicks on the popup."""
        # Check if click was on citations or references static widget
        if hasattr(event.widget, 'id'):
            if event.widget.id == "citation_count" and self.n_citations > 0 and self.inspire_id:
                self._search_citations()
            elif event.widget.id == "references" and len(self.references) > 0:
                self._search_references()
    
    def action_search_references(self) -> None:
        """Handle clicking on references link."""
        self._search_references()
    
    def action_search_citations(self) -> None:
        """Handle clicking on citations link."""
        self._search_citations()

    def _search_references(self) -> None:
        """Prepare reference IDs for fetching articles."""
        if not self.references:
            self.notify("No references to search", severity="warning")
            return
        
        # Convert reference IDs to integers
        try:
            # The references should be INSPIRE-HEP record IDs (integers)
            inspire_ids = []
            for ref in self.references:
                try:
                    # Try to convert to int, skip if not a valid ID
                    inspire_ids.append(int(ref))
                except (ValueError, TypeError):
                    continue
            
            if not inspire_ids:
                self.notify("No valid INSPIRE-HEP IDs found in references", severity="warning")
                return
            
            self.notify(f"Fetching {len(inspire_ids)} reference articles...", timeout=3)
            
            # Dismiss the popup with the inspire_ids to trigger reference fetch
            self.dismiss(("search_references", inspire_ids))
            
        except Exception as e:
            self.notify(f"Error processing references: {str(e)}", severity="error")

    def _search_citations(self) -> None:
        """Prepare to fetch articles that cite this paper."""
        if not self.inspire_id:
            self.notify("No INSPIRE ID available for citations", severity="warning")
            return
        
        if self.n_citations == 0:
            self.notify("This article has no citations", severity="warning")
            return
            
        self.notify(f"Fetching {self.n_citations} citing articles...", timeout=3)
        
        # Dismiss the popup with the inspire_id to trigger citation fetch
        self.dismiss(("search_citations", self.inspire_id))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()


class TagPopupScreen(ModalScreen):
    """Screen to manage tags for an article."""

    def __init__(self, article_id: str, article_title: str, existing_tags: List[str], all_tags: List[Dict[str, Any]], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.article_id = article_id
        self.article_title = article_title
        self.existing_tags = set(existing_tags) if existing_tags else set()
        self.all_tags = all_tags if all_tags else []
        self.checkboxes = {}

    def compose(self):
        with Vertical(id="tag_popup_dialog"):
            yield Static(f"Manage Tags", id="tag_popup_title")
            yield Static(f"Article: {self.article_title[:60]}{'...' if len(self.article_title) > 60 else ''}", 
                        id="tag_popup_article")
            
            # New tag input
            with Horizontal(id="new_tag_container"):
                yield Input(placeholder="Enter new tag name...", id="new_tag_input")
                yield Button("Add", variant="primary", id="add_tag_button")
            
            # Existing tags
            with VerticalScroll(id="tags_scroll"):
                if self.all_tags:
                    for tag_data in self.all_tags:
                        tag_name = tag_data['name']
                        sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag_name)
                        is_checked = tag_name in self.existing_tags
                        checkbox = Checkbox(f"{tag_name} ({tag_data['article_count']})", 
                                          value=is_checked, 
                                          id=f"tag_checkbox_{sanitized_tag_name}")
                        self.checkboxes[tag_name] = checkbox
                        yield checkbox
                else:
                    yield Static("No tags exist yet. Create one above.", id="no_tags_message")
            
            with Horizontal(id="tag_buttons"):
                yield Button("Save", variant="primary", id="save_tags_button")
                yield Button("Cancel", id="cancel_tags_button")

    def on_mount(self) -> None:
        self.query_one("#new_tag_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel_tags_button":
            self.dismiss()
        elif event.button.id == "save_tags_button":
            self._save_tags()
        elif event.button.id == "add_tag_button":
            self._add_new_tag()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "new_tag_input":
            self._add_new_tag()

    def _add_new_tag(self) -> None:
        """Add a new tag and refresh the tag list."""
        new_tag_input = self.query_one("#new_tag_input", Input)
        tag_name = new_tag_input.value.strip()
        
        if not tag_name:
            return
            
        # Check if tag already exists
        if any(tag['name'].lower() == tag_name.lower() for tag in self.all_tags):
            self.notify(f"Tag '{tag_name}' already exists", severity="warning")
            new_tag_input.value = ""
            return
        
        # Add to all_tags list and create checkbox
        new_tag_data = {'name': tag_name, 'article_count': 0}
        self.all_tags.append(new_tag_data)
        
        # Create and add checkbox
        sanitized_tag_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tag_name)
        checkbox = Checkbox(f"{tag_name} (0)", value=True, id=f"tag_checkbox_{sanitized_tag_name}")
        self.checkboxes[tag_name] = checkbox
        
        # Remove no tags message if it exists
        try:
            no_tags = self.query_one("#no_tags_message")
            no_tags.remove()
        except:
            pass
            
        # Add checkbox to scroll area
        scroll_area = self.query_one("#tags_scroll", VerticalScroll)
        scroll_area.mount(checkbox)
        
        new_tag_input.value = ""
        self.notify(f"Added tag '{tag_name}'")

    def _save_tags(self) -> None:
        """Save the current tag selections."""
        selected_tags = set()
        
        # Check which tags are selected
        for tag_name, checkbox in self.checkboxes.items():
            if checkbox.value:
                selected_tags.add(tag_name)
        
        # Return the changes
        tags_to_add = selected_tags - self.existing_tags
        tags_to_remove = self.existing_tags - selected_tags
        
        self.dismiss((tags_to_add, tags_to_remove))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()


class NotesPopupScreen(ModalScreen):
    """Screen to display and edit notes for an article."""

    def __init__(self, notes_path: str, article_title: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notes_path = notes_path
        self.article_title = article_title
        self.original_content = ""

    def compose(self):
        # Read initial content
        if os.path.exists(self.notes_path):
            with open(self.notes_path, "r") as f:
                self.original_content = f.read()

        yield Vertical(
            Static(f"Notes for: {self.article_title[:60]}{'...' if len(self.article_title) > 60 else ''}", id="notes_popup_title"),
            TextArea(self.original_content, id="notes_text_area", language="markdown", theme="monokai"),
            Horizontal(
                Button("Save", variant="primary", id="notes_save_button"),
                Button("Close", id="notes_close_button"),
                id="notes_buttons"
            ),
            id="notes_popup_dialog",
        )

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "notes_close_button":
            self.dismiss(None)
        elif event.button.id == "notes_save_button":
            new_content = self.query_one(TextArea).text
            with open(self.notes_path, "w") as f:
                f.write(new_content)
            self.dismiss(new_content)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
