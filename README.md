# Salesforce Knowledge Article Uploader

A Python CLI tool that automates the migration of MindTouch-exported Knowledge Articles into Salesforce Knowledge, including inline images and file attachments.

## Overview

This tool reads a MindTouch site export, cleans up the HTML for Salesforce compatibility, uploads images and attachments to Salesforce Files, and creates Knowledge Articles as drafts — all in one pass.

### What it does for each article

1. **Parses** the MindTouch `page.html` and strips DekiScript, custom attributes, and MindTouch-specific markup
2. **Uploads images** (PNG, JPG, etc.) to Salesforce Files and replaces local `<img src>` references with Salesforce content URLs
3. **Uploads attachments** (.oft, .pdf, .doc, etc.) to Salesforce Files and updates download links
4. **Creates a Knowledge Article** (`Knowledge__kav`) as a Draft with the cleaned HTML body
5. **Links** uploaded files to the article via `ContentDocumentLink`
6. **Generates a JSON report** of all processed articles with success/failure status

## Prerequisites

- **Python 3.9+**
- **Salesforce CLI** (`sf`) — installed and authenticated to your target org
- **Salesforce Knowledge** enabled in your org with a custom article type

Authenticate your org before running:

```bash
sf org login web --alias my-org
```

## Installation

```bash
# Clone or copy this folder
cd sf_knowledge_uploader

# Install Python dependencies
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `simple-salesforce` | Salesforce REST API client |
| `beautifulsoup4` | HTML parsing and transformation |
| `requests` | HTTP client (used by simple-salesforce) |

## Quick Start

```bash
# 1. Configure your org and article path (edit config.py, or use CLI flags)

# 2. Preview what will happen (no API calls)
python main.py --dry-run --root /path/to/articles

# 3. Run for real
python main.py --root /path/to/articles
```

## Usage

```bash
# Process all article folders under a root directory
python main.py --root /path/to/articles

# Process a single article folder
python main.py --folder /path/to/articles/My_Article_Folder

# Dry run — preview without making any Salesforce API calls
python main.py --dry-run --root /path/to/articles

# Target a specific Salesforce org
python main.py --root /path/to/articles --org my-sandbox

# Publish articles immediately (skip draft stage)
python main.py --root /path/to/articles --publish

# Verbose logging (includes HTTP debug output)
python main.py --root /path/to/articles --verbose

# Specify the MindTouch export root manually (auto-detected by default)
python main.py --root /path/to/articles --export-root /path/to/export
```

### CLI Reference

| Flag | Description |
|------|-------------|
| `--root <path>` | Root directory containing article subfolders (overrides `config.py`) |
| `--folder <path>` | Process a single article folder instead of an entire root |
| `--dry-run` | Preview mode — no Salesforce API calls are made |
| `--publish` | Publish articles immediately after creation |
| `--org <alias>` | Target a specific Salesforce org (overrides `config.py`) |
| `--export-root <path>` | MindTouch export root directory (auto-detected if omitted) |
| `--verbose` | Enable debug-level logging |

## Expected Folder Structure

The tool expects a MindTouch site export with this structure:

```
export_root/
├── relative/
│   ├── Clients/
│   │   └── YourTeam/
│   │       └── Procedures/            ← Use this as --root
│   │           ├── Article_One/
│   │           │   ├── page.html                  ← Article HTML (required)
│   │           │   ├── clipboard_abc123.png       ← Inline image
│   │           │   └── Template%2BFile.oft        ← Attachment (URL-encoded)
│   │           ├── Article_Two/
│   │           │   ├── page.html
│   │           │   └── screenshot.png
│   │           └── ...
│   └── WebFiles/                      ← Shared images (may or may not be in export)
├── _assets/
├── hierarchy.dat
└── package.xml
```

Each subfolder under the root = one Knowledge Article. The tool looks for `page.html` in each subfolder.

### Filename encoding

MindTouch exports double-URL-encode filenames on disk. For example:

| Name in HTML | Filename on disk |
|---|---|
| `My Template (v1).oft` | `My%2BTemplate%2B(v1).oft` |
| `Report File.pdf` | `Report%2BFile.pdf` |

The tool handles this encoding automatically — no manual renaming needed.

## Configuration

All settings are in `config.py`. They can also be overridden via CLI flags.

### Salesforce Org Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `SF_CLI_TARGET_ORG` | `""` | SF CLI org alias. Blank = default org. Override: `--org` |
| `ARTICLE_API_NAME` | `Knowledge__kav` | Knowledge article object API name |
| `BODY_FIELD_API_NAME` | `FAQ_Answer__c` | Rich text field for the article body |
| `TITLE_FIELD_API_NAME` | `Title` | Field for the article title |
| `URL_NAME_FIELD_API_NAME` | `UrlName` | Field for the URL-friendly article name |
| `DATA_CATEGORY_GROUP` | `None` | Data Category Group to assign (optional) |
| `DATA_CATEGORY` | `None` | Data Category value to assign (optional) |

### Local File Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `ARTICLES_ROOT_DIR` | `""` | Root folder containing article subfolders. Override: `--root` |
| `HTML_FILENAME` | `page.html` | HTML filename to look for in each folder |
| `ATTACHMENT_EXTENSIONS` | `.oft, .pdf, .doc, .docx, .xls, .xlsx` | File types uploaded as attachments |
| `IMAGE_EXTENSIONS` | `.png, .jpg, .jpeg, .gif, .svg` | File types processed as inline images |

### Upload Behavior

| Setting | Default | Description |
|---------|---------|-------------|
| `PUBLISH_ON_CREATE` | `False` | `True` = publish immediately; `False` = create as Draft |
| `ARTICLE_LANGUAGE` | `en_US` | Language for the KnowledgeArticleVersion record |
| `LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DRY_RUN` | `False` | `True` = preview mode (no API calls). Override: `--dry-run` |

## Architecture

```
sf_knowledge_uploader/
├── main.py                 ← CLI entry point, orchestrator, and reporting
├── config.py               ← All configurable settings
├── html_transformer.py     ← MindTouch HTML → Salesforce HTML cleanup
├── sf_client.py            ← Salesforce REST API client (auth, upload, create)
├── requirements.txt        ← Python dependencies
└── README.md               ← This file
```

### Component Details

#### `main.py` — Orchestrator

The main entry point and CLI interface. Handles:

- **Argument parsing**: All `--flags` for overriding config
- **Article discovery**: Scans the root directory for subfolders containing `page.html`
- **Export root detection**: Automatically walks up from the articles directory to find the MindTouch export root (the directory containing `relative/`). This is needed to resolve cross-folder image and attachment references.
- **Processing pipeline**: For each article folder, coordinates the transform → upload → create → link workflow
- **Summary reporting**: Prints a console summary and saves a detailed JSON report (`upload_report_YYYYMMDD_HHMMSS.json`)

#### `html_transformer.py` — HTML Cleanup

Transforms MindTouch-exported HTML into clean, Salesforce-compatible HTML. Handles:

- **Title extraction**: Reads the article title from `<h1 class="mt-export-title">` or `<title>`
- **DekiScript removal**: Strips `<pre class="script">` blocks and `<p class="mt-script-comment">` elements
- **Markup cleanup**: Removes MindTouch-specific attributes (`mt-*`, `src.path`, `href.path`, etc.), export separators, page tags, and MindTouch CSS links
- **Image processing**: Extracts `<img>` references using `src.filename` or `src` attributes, resolves local file paths (including URL-encoded variants), and replaces `src` with placeholders for later URL substitution
- **Attachment processing**: Extracts `<a>` links to local files (`.oft`, `.pdf`, etc.) using `href.filename` or `href`, resolves file paths, and replaces `href` with placeholders
- **Cross-folder resolution**: Uses MindTouch `src.path` / `href.path` attributes to find images and attachments stored in other folders within the export tree
- **URL-encoding resolution**: Handles MindTouch's double-URL-encoding scheme where filenames on disk have spaces encoded as `%2B` and special characters like `&nbsp;` encoded as `%25C2%25A0`

#### `sf_client.py` — Salesforce API Client

Manages all Salesforce API interactions via `simple-salesforce`. Handles:

- **Authentication**: Uses the Salesforce CLI (`sf org display`) to get an access token from an already-authenticated session. No credentials are stored in the tool.
- **File upload**: Uploads files as `ContentVersion` records with base64-encoded data, then queries back to get the `ContentDocumentId`
- **Image URLs**: Generates `/sfc/servlet.shepherd/version/renditionDownload` URLs for inline image rendering in rich text fields
- **Attachment URLs**: Generates `/sfc/servlet.shepherd/document/download/` URLs for file download links
- **Article creation**: Creates `Knowledge__kav` records with the article title, URL name (auto-slugified), cleaned HTML body, and language
- **File linking**: Creates `ContentDocumentLink` records to associate uploaded files with the article
- **Publishing** (optional): Calls the Knowledge Management REST API to move articles from Draft to Published

## Output

After processing, the tool generates:

- **Console summary** with success/failure counts and per-article details
- **JSON report** (`upload_report_YYYYMMDD_HHMMSS.json`) saved in the articles root directory

Example report entry:

```json
{
  "folder": "Accenture_-_PELI_Claims_Process_(PL)",
  "status": "success",
  "article_id": "ka0XXXXXXXXXXXXXXX",
  "title": "Accenture - PELI Claims Process (PL)",
  "images_uploaded": 1,
  "attachments_uploaded": 2,
  "errors": []
}
```

## Troubleshooting

### "Failed to get org info from SF CLI"

Your Salesforce CLI session has expired or you haven't authenticated yet. Run:

```bash
sf org login web --alias my-org
```

### Images not rendering in the article

Salesforce rich text fields require specific URL formats for inline images. The tool uses the `/sfc/servlet.shepherd/version/renditionDownload` format. If images still don't render, check that the image file was successfully uploaded (look for the `ContentVersionId` in the log output).

### "Image not found" warnings referencing `//WebFiles/...`

These images are stored in a shared MindTouch media library that was not included in your export. Options:

- Export the `WebFiles` section separately and re-run with `--export-root` pointing to the combined export
- Source the images manually and place them in the article folders
- Accept that these images will be missing from the migrated articles

### Body exceeds 131,072 characters

Salesforce rich text fields have a character limit. The tool warns if this happens. Options:

- Split the article into multiple articles
- Compress images or use lower resolution
- Simplify the HTML structure

### Attachment links show "#"

The attachment file wasn't found in the article folder or the export. Check that:

- The file exists on disk (filenames may be URL-encoded)
- The `href.path` in the HTML points to a folder that exists in the export
- The file extension is included in `ATTACHMENT_EXTENSIONS` in `config.py`

### Duplicate articles on re-run

The tool does not check for existing articles before creating new ones. If you re-run against the same folder, duplicate articles will be created. Delete the duplicates manually in Salesforce before re-running, or process only the folders that need re-processing using `--folder`.
