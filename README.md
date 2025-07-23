# ArTui

A Terminal User Interface (TUI) application for browsing, searching, and managing arXiv research papers. Built with Python and Textual, featuring a persistent SQLite database. This tool was built with the help of AI to test AI capabilities and to build something useful for myself. The code is not pretty and I simply wanted to create a usable tool for myself.

**The main goal of the tool is to stay up to date with recent publications in your field**

# Disclaimer
This tool is not associated with arXiv and we thank arXiv for use of its open access interoperability. We also thank INSPIRE for provisding their API free of charge for educational and informational use. The tool has been developed with the help of a mix of Claude Sonnet 4 and Gemini 2.5 Pro.
## Features

- **🗃️ Persistent Database**: All articles stored locally in SQLite for fast offline access
- **🚀 Smart Fetching**: Automatic background fetching of recent articles (last 7 days)
- **🔍 Advanced Filtering**: Configure custom filters with category and text-based criteria
- **📁 Category Management**: Organize articles by arXiv categories (cs.AI, hep-th, etc.)
- **🏷️ Tag Management**: Add custom tags to articles and filter by tags
- **📝 Notes Management**: Create and edit markdown notes for articles
- **📚 BibTeX Citations**: Fetch and view BibTeX citations from Inspire-HEP
- **💾 Save System**: Save and organize your favorite articles
- **📖 Reading Status**: Track viewed articles automatically
- **📱 Modern TUI**: Beautiful, responsive terminal interface with mouse support
- **📄 PDF Integration**: Download and open PDFs directly from the application
- **🔎 Full-Text Search**: Search across titles, authors, and abstracts

- **⚡ Fast Performance**: Local database ensures instant search and browsing

## Screenshots

![ArXiv Reader Screenshot](mainscreen.jpg)

*The ArXiv Reader interface showing the category sidebar, article list, and abstract panel*

![Notes Screenshot](notes.jpg)

*The Notes interface showing the markdown editor for taking notes on articles*

![Inspire information](inspire.jpg)

*The INSPIRE citation interface showing BibTeX citation information*



## Installation

### Requirements
- Python 3.8+
- Internet connection for fetching articles

### Setup

1. **Clone the repository**:
```bash
git clone <repository-url>
```

2. **Create a virtual environment** (recommended):
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```
4. After first open
Press the 'r' button to refresh the database
## Configuration

Create or edit `arxiv_config.yaml` to configure categories and filters:

```yaml
categories:
  # Display Name: arXiv category code
  "Machine Learning": "cs.LG"
  "Artificial Intelligence": "cs.AI"
  "HEP Theory": "hep-th"
  "HEP Experiments": "hep-ex"
  "Quantum Physics": "quant-ph"

filters:
  # Custom filters with advanced criteria
  "ALICE Experiment":
    categories:
      - hep-ex
      - hep-ph
    query: "ALICE"
  
  "Deep Learning":
    categories:
      - cs.LG
      - cs.CV
    query: "deep learning OR neural network"
  
  "COVID Research":
    query: "COVID-19 OR coronavirus OR SARS-CoV-2"
```

## Usage

### Running the Application

```bash
python main.py
```

The application will:
1. Create the database file if it doesn't exist
2. Start the TUI interface
3. Automatically refresh articles (same as pressing 'r') - fetching recent articles (last 7 days)
4. Load the first configured category/filter automatically

### Key Bindings

| Key | Action |
|-----|--------|
| `s` | Save/Unsave the selected article |
| `u` | Mark article as unread |
| `o` | Download and open PDF |
| `i` | Show BibTeX citation from Inspire-HEP |
| `t` | Manage tags for the selected article |
| `n` | Create/edit notes for the selected article |
| `f` | Focus search box |
| `g` | Enable web search and focus search box |
| `c` | Show category/filter selection popup |
| `r` | Refresh and fetch new articles |
| `q` | Quit application |
| `Ctrl+d` | Toggle dark/light mode |
| `↑/↓` | Navigate article list |
| `Enter` | Select article (shows abstract) |
| `Mouse` | Click to navigate and select |

### Status Indicators

In the article list, the first column shows status:
- `●` - New/unread article
- ` ` (space) - Article has been viewed
- `s` - Article is saved/bookmarked
- `t` - Article has tags
- `n` - Article has note

### Database Management

```bash
# Reset database (delete arxiv_articles.db)
rm arxiv_articles.db

# Backup database
cp arxiv_articles.db backup_$(date +%Y%m%d).db
```

## Support

For issues and feature requests, please use the GitHub issue tracker. 
