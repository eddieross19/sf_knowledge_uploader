# Salesforce Knowledge Article Uploader

A Python CLI tool that automates the migration of MindTouch-exported Knowledge Articles into Salesforce Knowledge, including inline images and file attachments.

## Overview

This tool reads a MindTouch site export, cleans up the HTML for Salesforce compatibility, uploads images and attachments to Salesforce Files, and creates Knowledge Articles as drafts — all in one pass.

It supports **full-export mode**: point it at the top-level export folder (e.g., `site_14870-export-20260205233221.155/`) and it will recursively discover all articles under `relative/`, automatically skipping category landing pages that have no real content.

### What it does for each article

1. **Parses** the MindTouch `page.html` and strips DekiScript, custom attributes, and MindTouch-specific markup
2. **Uploads images** (PNG, JPG, etc.) to Salesforce Files and replaces local `<img src>` references with Salesforce content URLs
3. **Uploads attachments** (.oft, .pdf, .doc, .pptx, .msg, etc.) to Salesforce Files and updates download links
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

### Process an entire MindTouch export (Windows)

```cmd
REM 1. Preview what will happen (no API calls)
python main.py --dry-run --root C:\Users\you\Desktop\site_14870-export-20260205233221.155

REM 2. Run for real
python main.py --root C:\Users\you\Desktop\site_14870-export-20260205233221.155

REM 3. Process only a specific section
python main.py --root C:\Users\you\Desktop\site_14870-export-20260205233221.155\relative\Clients\MRA_CSP\Profiles
```

### Process an entire MindTouch export (macOS/Linux)

```bash
# 1. Preview what will happen (no API calls)
python main.py --dry-run --root /path/to/site_14870-export-20260205233221.155

# 2. Run for real
python main.py --root /path/to/site_14870-export-20260205233221.155

# 3. Process only a specific section
python main.py --root /path/to/export/relative/Clients/MRA_CSP/Profiles
```

## Usage

```bash
# Process the entire export — auto-detects relative/ and scans recursively
python main.py --root C:\path\to\site_14870-export-20260205233221.155

# Process a subtree within the export
python main.py --root C:\path\to\export\relative\Clients\MRA_CSP\Profiles

# Process a single article folder
python main.py --folder C:\path\to\export\relative\Clients\MRA_CSP\Profiles\Some_Article

# Dry run — preview without making any Salesforce API calls
python main.py --dry-run --root C:\path\to\export

# Target a specific Salesforce org
python main.py --root C:\path\to\export --org my-sandbox

# Publish articles immediately (skip draft stage)
python main.py --root C:\path\to\export --publish

# Include category/guide landing pages (skipped by default)
python main.py --root C:\path\to\export --include-categories

# Verbose logging (includes HTTP debug output)
python main.py --root C:\path\to\export --verbose

# Specify the MindTouch export root manually (auto-detected by default)
python main.py --root C:\path\to\articles --export-root C:\path\to\export
```

### CLI Reference

| Flag | Description |
|------|-------------|
| `--root <path>` | Directory to scan for articles. Can be the export root or any subfolder. |
| `--folder <path>` | Process a single article folder instead of scanning a directory. |
| `--export-root <path>` | MindTouch export root directory. Auto-detected from `--root` if omitted. |
| `--dry-run` | Preview mode — no Salesforce API calls are made. |
| `--publish` | Publish articles immediately after creation. |
| `--org <alias>` | Target a specific Salesforce org (overrides `config.py`). |
| `--include-categories` | Include category/guide landing pages (skipped by default). |
| `--verbose` | Enable debug-level logging. |

## Expected Folder Structure

The tool expects a MindTouch site export with this structure:

```
site_14870-export-20260205233221.155/       <-- use as --root (full export)
├── relative/
│   ├── Archived_(admin_member_only)/
│   │   └── ...
│   ├── Business_Support/
│   │   └── ...
│   ├── Clients/
│   │   ├── page.html                       (category page — skipped by default)
│   │   ├── EBPL/
│   │   │   └── Profiles/
│   │   │       ├── Article_One/
│   │   │       │   ├── page.html           <-- article HTML (required)
│   │   │       │   ├── security.dat        (ignored — MindTouch metadata)
│   │   │       │   ├── clipboard_abc.png   <-- inline image
│   │   │       │   └── Template%2BFile.oft <-- attachment (URL-encoded)
│   │   │       └── Article_Two/
│   │   │           ├── page.html
│   │   │           └── screenshot.png
│   │   ├── MRA_CSP/
│   │   │   ├── Profiles/                   <-- or use as --root (section only)
│   │   │   ├── Procedures/
│   │   │   └── Hot_Topics/
│   │   └── MRA_PAS/
│   ├── Procedures_and_Reference_Materials/
│   │   └── ...
│   └── WebFiles/                            <-- shared files (resolved via src.path)
│       ├── EB-PL/
│       ├── MRA/
│       └── ...
├── absolute/                                (templates, media — not scanned)
├── _assets/
│   └── content.css
├── hierarchy.dat                            (used to detect export root)
├── media-hierarchy.dat
└── package.xml
```

The tool **recursively** walks the directory tree and processes every folder containing a `page.html` file. Category/guide landing pages (which contain only DekiScript templates and no real content) are automatically skipped unless `--include-categories` is used.

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
| `ATTACHMENT_EXTENSIONS` | `.oft, .pdf, .doc, .docx, .xls, .xlsx, .pptx, .ppt, .msg, .vsd, .vsdx, .xlsm, .csv, .txt, .mp4, .docm, .mpp` | File types uploaded as attachments (case-insensitive) |
| `IMAGE_EXTENSIONS` | `.png, .jpg, .jpeg, .gif, .svg` | File types processed as inline images (case-insensitive) |

### Upload Behavior

| Setting | Default | Description |
|---------|---------|-------------|
| `PUBLISH_ON_CREATE` | `False` | `True` = publish immediately; `False` = create as Draft |
| `ARTICLE_LANGUAGE` | `en_US` | Language for the KnowledgeArticleVersion record |
| `LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DRY_RUN` | `False` | `True` = preview mode (no API calls). Override: `--dry-run` |
| `SKIP_CATEGORY_PAGES` | `True` | Skip MindTouch category/guide landing pages. Override: `--include-categories` |

## Architecture

```
sf_knowledge_uploader/
├── main.py                 <- CLI entry point, orchestrator, and reporting
├── config.py               <- All configurable settings
├── html_transformer.py     <- MindTouch HTML -> Salesforce HTML cleanup
├── sf_client.py            <- Salesforce REST API client (auth, upload, create)
├── requirements.txt        <- Python dependencies
└── README.md               <- This file
```

### Component Details

#### `main.py` — Orchestrator

The main entry point and CLI interface. Handles:

- **Argument parsing**: All `--flags` for overriding config
- **Recursive article discovery**: Walks the entire directory tree under the root, finding every folder with a `page.html` file
- **Category page filtering**: Automatically skips MindTouch category/guide landing pages that contain only DekiScript templates and no real article content
- **Export root detection**: Automatically detects the MindTouch export root (the directory containing `relative/` and `hierarchy.dat`) by walking up from the scan directory. If `--root` points to the export root itself, scanning starts in `relative/`.
- **Processing pipeline**: For each article folder, coordinates the transform -> upload -> create -> link workflow
- **Summary reporting**: Prints a console summary and saves a detailed JSON report (`upload_report_YYYYMMDD_HHMMSS.json`)

#### `html_transformer.py` — HTML Cleanup

Transforms MindTouch-exported HTML into clean, Salesforce-compatible HTML. Handles:

- **Title extraction**: Reads the article title from `<h1 class="mt-export-title">` or `<title>`
- **DekiScript removal**: Strips `<pre class="script">`, `<pre class="script-jem">`, `<pre class="script-css">` blocks and `<p class="mt-script-comment">` elements
- **Category page detection**: Identifies category/guide pages by checking for `article:topic-category` / `article:topic-guide` tags and empty content after boilerplate removal
- **Markup cleanup**: Removes MindTouch-specific attributes (`mt-*`, `src.path`, `href.path`, etc.), export separators, page tags, and MindTouch CSS links
- **Image processing**: Extracts `<img>` references using `src.filename` or `src` attributes, resolves local file paths (including URL-encoded variants), and replaces `src` with placeholders for later URL substitution
- **Attachment processing**: Extracts `<a>` links to local files using `href.filename` or `href`, resolves file paths, and replaces `href` with placeholders. Supports all file types in `ATTACHMENT_EXTENSIONS` with case-insensitive matching.
- **Cross-folder resolution**: Uses MindTouch `src.path` / `href.path` attributes to find images and attachments stored in other folders within the export tree (e.g., `//WebFiles/EB-PL`)
- **URL-encoding resolution**: Handles MindTouch's double-URL-encoding scheme where filenames on disk have spaces encoded as `%2B` and special characters encoded as `%25XX`

#### `sf_client.py` — Salesforce API Client

Manages all Salesforce API interactions via `simple-salesforce`. Handles:

- **Authentication**: Uses the Salesforce CLI (`sf org display`) to get an access token. No credentials are stored. Windows-compatible (uses `shell=True` on Windows for `.cmd` scripts).
- **File upload**: Uploads files as `ContentVersion` records with base64-encoded data, then queries back to get the `ContentDocumentId`
- **Image URLs**: Generates `/sfc/servlet.shepherd/version/renditionDownload` URLs for inline image rendering in rich text fields
- **Attachment URLs**: Generates `/sfc/servlet.shepherd/document/download/` URLs for file download links
- **Article creation**: Creates records using the configured `ARTICLE_API_NAME` with title, URL name (auto-slugified), cleaned HTML body, and language
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

## Windows Usage

The tool is fully compatible with Windows. Key notes:

1. **Salesforce CLI**: On Windows, `sf` is installed as a `.cmd` script. The tool handles this automatically (uses `shell=True` for subprocess calls on Windows).

2. **Python**: Use Python 3.9+. If you have multiple Python versions, use `py -3` instead of `python`:
   ```cmd
   py -3 main.py --dry-run --root C:\Users\you\Desktop\site_14870-export-20260205233221.155
   ```

3. **Paths**: Use Windows-style backslash paths. The tool normalizes all paths internally:
   ```cmd
   python main.py --root C:\Users\you\Desktop\site_14870-export-20260205233221.155
   python main.py --folder C:\Users\you\Desktop\export\relative\Clients\MRA_CSP\Profiles\My_Article
   ```

4. **Long paths**: MindTouch exports can have deeply nested folder structures with long encoded filenames. If you encounter path length errors, enable long paths in Windows:
   - Run `reg add HKLM\SYSTEM\CurrentControlSet\Control\FileSystem /v LongPathsEnabled /t REG_DWORD /d 1` in an admin Command Prompt
   - Or move the export folder closer to the drive root (e.g., `C:\export\`)

5. **Virtual environment** (recommended):
   ```cmd
   cd sf_knowledge_uploader
   py -3 -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Troubleshooting

### "Failed to get org info from SF CLI"

Your Salesforce CLI session has expired or you haven't authenticated yet. Run:

```bash
sf org login web --alias my-org
```

### "Could not auto-detect MindTouch export root"

The tool couldn't find the export root (directory with `relative/` and `hierarchy.dat`). This happens when `--root` points to a folder outside the export tree. Use `--export-root` to specify it explicitly:

```cmd
python main.py --root C:\some\articles --export-root C:\path\to\site_14870-export-20260205233221.155
```

### Images not rendering in the article

Salesforce rich text fields require specific URL formats for inline images. The tool uses the `/sfc/servlet.shepherd/version/renditionDownload` format. If images still don't render, check that the image file was successfully uploaded (look for the `ContentVersionId` in the log output).

### "Image not found" warnings referencing `//WebFiles/...`

These images are stored in a shared MindTouch media library. If the WebFiles directory is included in the export (check `relative/WebFiles/`), the tool will resolve them automatically. If not:

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

### Windows path too long errors

MindTouch exports have deeply nested paths with URL-encoded folder names. If you get "path too long" errors:

1. Move the export folder to a short path like `C:\export\`
2. Enable Windows long path support (see Windows Usage section above)
