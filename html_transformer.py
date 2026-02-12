"""
html_transformer.py

Transforms MindTouch-exported HTML into Salesforce Knowledge-compatible HTML.
Handles:
  - Stripping DekiScript blocks
  - Cleaning MindTouch-specific attributes and classes
  - Extracting title
  - Mapping image/attachment references to placeholders for later URL replacement
"""

import re
import os
import logging
from urllib.parse import quote, unquote
from html.parser import HTMLParser
from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)


def transform_article(html_path: str, export_root: str = None) -> dict:
    """
    Parse and clean a MindTouch-exported HTML file.

    Args:
        html_path: Path to the page.html file.
        export_root: Root of the MindTouch export (the directory containing 'relative/').
                     Used to resolve images/attachments referenced from other folders.

    Returns:
        dict with keys:
            - title (str): Extracted article title
            - body (str): Cleaned HTML body content
            - images (list[dict]): List of {filename, placeholder_id} for inline images
            - attachments (list[dict]): List of {filename, placeholder_id} for linked files
    """
    with open(html_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, "html.parser")

    # --- Extract title ---
    title = _extract_title(soup)

    # --- Remove DekiScript blocks ---
    _remove_script_blocks(soup)

    # --- Remove MindTouch comment paragraphs ---
    _remove_comment_paragraphs(soup)

    # --- Remove the export title h1 (it's redundant with the Title field) ---
    title_h1 = soup.find("h1", class_="mt-export-title")
    if title_h1:
        title_h1.decompose()

    # --- Remove the page tags section at the bottom ---
    _remove_page_tags(soup)

    # --- Remove <hr class="mt-export-separator"> ---
    for hr in soup.find_all("hr", class_="mt-export-separator"):
        hr.decompose()

    # --- Process images: normalize src attributes, build image manifest ---
    images = _process_images(soup, os.path.dirname(html_path), export_root)

    # --- Process attachment links: normalize href attributes ---
    attachments = _process_attachments(soup, os.path.dirname(html_path), export_root)

    # --- Clean MindTouch-specific attributes ---
    _clean_attributes(soup)

    # --- Extract just the <body> content ---
    body = soup.find("body")
    if body:
        body_html = body.decode_contents().strip()
    else:
        body_html = str(soup).strip()

    # --- Final whitespace cleanup ---
    body_html = _clean_whitespace(body_html)

    logger.info(f"Transformed article: '{title}' | {len(images)} images | {len(attachments)} attachments")

    return {
        "title": title,
        "body": body_html,
        "images": images,
        "attachments": attachments,
    }


def is_category_page(html_path: str) -> bool:
    """
    Quick check whether a page.html is a MindTouch category/guide landing page
    rather than a real article.

    Category pages are tagged with 'article:topic-category' or 'article:topic-guide'
    in the <p class="template:tag-insert"> section and contain only DekiScript
    template calls with no real content.

    Args:
        html_path: Path to the page.html file.

    Returns:
        True if the page is a category/guide page that should be skipped.
    """
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            raw_html = f.read()
    except (OSError, UnicodeDecodeError):
        return False

    soup = BeautifulSoup(raw_html, "html.parser")

    # Check for category tags in the page tags section
    tag_section = soup.find("p", class_="template:tag-insert")
    if tag_section:
        tag_links = tag_section.find_all("a")
        tag_texts = [a.get_text(strip=True) for a in tag_links]
        category_tags = {"article:topic-category", "article:topic-guide"}
        if any(t in category_tags for t in tag_texts):
            return True

    # Also detect pages that are purely DekiScript templates with no real content.
    # After stripping scripts and MindTouch boilerplate, if the body is effectively
    # empty (just whitespace, tags section, and export summary), it's a category page.
    body = soup.find("body")
    if not body:
        return False

    # Remove known boilerplate elements to see if anything meaningful remains
    test_soup = BeautifulSoup(str(body), "html.parser")
    for el in test_soup.find_all("pre", class_=re.compile(r"^script")):
        el.decompose()
    for el in test_soup.find_all("p", class_="mt-script-comment"):
        el.decompose()
    for el in test_soup.find_all("p", class_="template:tag-insert"):
        el.decompose()
    for el in test_soup.find_all("h1", class_="mt-export-title"):
        el.decompose()
    for el in test_soup.find_all("hr", class_="mt-export-separator"):
        el.decompose()

    remaining_text = test_soup.get_text(strip=True)
    # If the only remaining text is a short summary blurb or empty, it's a category page
    if len(remaining_text) < 50:
        return True

    return False


def _extract_title(soup: BeautifulSoup) -> str:
    """Extract article title from <h1 class='mt-export-title'> or <title>."""
    h1 = soup.find("h1", class_="mt-export-title")
    if h1:
        return h1.get_text(strip=True)

    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)

    return "Untitled Article"


def _remove_script_blocks(soup: BeautifulSoup):
    """Remove DekiScript blocks: <pre class='script'>, 'script-css', 'script-jem', etc."""
    for pre in soup.find_all("pre", class_=re.compile(r"^script")):
        pre.decompose()


def _remove_comment_paragraphs(soup: BeautifulSoup):
    """Remove <p class='mt-script-comment'> elements (DekiScript comments)."""
    for p in soup.find_all("p", class_="mt-script-comment"):
        p.decompose()


def _remove_page_tags(soup: BeautifulSoup):
    """Remove the MindTouch page tags paragraph at the bottom."""
    for p in soup.find_all("p", class_="template:tag-insert"):
        p.decompose()


def _resolve_local_path(filename: str, article_dir: str, export_root: str, mt_path: str = None) -> str:
    """
    Resolve a filename to a local file path, handling MindTouch URL-encoding.

    MindTouch exports store filenames on disk with URL-encoding:
      spaces become '+', then the whole name is percent-encoded.
      e.g. "My File (1).oft" -> "My%2BFile%2B(1).oft" on disk.

    Also handles files referenced via src.path / href.path that live in
    a different folder within the export (e.g., //WebFiles/EB-PL).

    Args:
        filename: The human-readable filename from the HTML.
        article_dir: The article's own folder path.
        export_root: Root of the MindTouch export (parent of 'relative/').
        mt_path: The MindTouch src.path or href.path attribute, if present.

    Returns:
        The resolved local file path (may or may not exist on disk).
    """
    # Build the URL-encoded variant of the filename:
    # MindTouch exports double-encode filenames on disk:
    #   1. First encode: spaces -> '+', non-ASCII chars -> %XX
    #   2. Second encode: '%' -> '%25', '+' -> '%2B'
    # e.g. "My File.oft" -> "My+File.oft" -> "My%2BFile.oft"
    # e.g. "A\u00a0B.oft" -> "A%C2%A0B.oft" -> "A%25C2%25A0B.oft"
    first_pass = quote(filename.replace(" ", "+"), safe="().-_+")
    encoded_filename = quote(first_pass, safe="().-_")

    # Determine which directories to search
    search_dirs = [os.path.normpath(article_dir)]

    # If mt_path points to a different location, also search there
    if mt_path and export_root:
        # mt_path looks like "//Clients/EBPL/Procedures/Some_Article" or "//WebFiles/EB-PL"
        # Strip leading slashes and resolve relative to the export's 'relative/' dir
        # Replace forward slashes with os.sep for Windows compatibility
        rel_path = mt_path.lstrip("/").replace("/", os.sep)
        alt_dir = os.path.normpath(os.path.join(export_root, "relative", rel_path))
        if alt_dir != search_dirs[0]:
            search_dirs.append(alt_dir)

    # Try each directory with both the original and encoded filename
    for search_dir in search_dirs:
        for candidate in [filename, encoded_filename]:
            candidate_path = os.path.join(search_dir, candidate)
            if os.path.exists(candidate_path):
                return candidate_path

    # Nothing found — return the best-guess path for error reporting
    return os.path.join(article_dir, filename)


def _process_images(soup: BeautifulSoup, article_dir: str, export_root: str = None) -> list:
    """
    Normalize image src attributes and build an image manifest.

    MindTouch uses custom attributes:
        src.path="//path/to/page"
        src.filename="image.png"
        src="./image.png"

    We normalize to use the local filename and insert a placeholder
    that will be replaced with the Salesforce Content URL after upload.
    """
    images = []
    for idx, img in enumerate(soup.find_all("img")):
        # Determine the actual filename
        filename = None

        # Try src.filename first (MindTouch custom attribute)
        if img.get("src.filename"):
            filename = img["src.filename"]
        elif img.get("src"):
            # Fall back to the src attribute (may be relative like ./image.png)
            src = img["src"]
            filename = os.path.basename(src)

        if not filename:
            logger.warning(f"Could not determine filename for <img> tag: {img}")
            continue

        # Resolve the file path, checking URL-encoded variants and alt directories
        mt_path = img.get("src.path")
        local_path = _resolve_local_path(filename, article_dir, export_root, mt_path)

        if not os.path.exists(local_path):
            logger.warning(f"Image file not found: {local_path}"
                           + (f" (referenced from {mt_path})" if mt_path else ""))

        # Create a placeholder ID for later URL replacement
        placeholder = f"{{{{IMG_PLACEHOLDER_{idx}}}}}"
        img["src"] = placeholder

        # Remove MindTouch-specific attributes
        for attr in ["src.path", "src.filename"]:
            if img.get(attr):
                del img[attr]

        images.append({
            "filename": filename,
            "local_path": local_path,
            "placeholder": placeholder,
            "index": idx,
        })

    return images


def _process_attachments(soup: BeautifulSoup, article_dir: str, export_root: str = None) -> list:
    """
    Normalize attachment link href attributes.

    MindTouch uses:
        href.path="//path/to/page"
        href.filename="file.oft"
        href="./file.oft"
    """
    from config import ATTACHMENT_EXTENSIONS

    attachments = []
    for idx, a in enumerate(soup.find_all("a")):
        filename = None

        # Try href.filename first
        if a.get("href.filename"):
            filename = a["href.filename"].strip()
        elif a.get("href"):
            href = a["href"]
            # Only process local file links (not mailto:, http://, etc.)
            if href.startswith("mailto:") or href.startswith("http://") or href.startswith("https://"):
                continue
            filename = os.path.basename(href)

        if not filename:
            continue

        # Check if this is an attachment type we care about (case-insensitive)
        _, ext = os.path.splitext(filename)
        if ext.lower() not in {e.lower() for e in ATTACHMENT_EXTENSIONS}:
            continue

        # Resolve the file path, checking URL-encoded variants and alt directories
        mt_path = a.get("href.path")
        local_path = _resolve_local_path(filename, article_dir, export_root, mt_path)

        placeholder = f"{{{{ATTACH_PLACEHOLDER_{idx}}}}}"

        # Update the href to use the placeholder
        a["href"] = placeholder

        # Remove MindTouch-specific attributes
        for attr in ["href.path", "href.filename"]:
            if a.get(attr):
                del a[attr]

        attachments.append({
            "filename": filename,
            "local_path": local_path,
            "placeholder": placeholder,
            "index": idx,
        })

    return attachments


def _clean_attributes(soup: BeautifulSoup):
    """Remove MindTouch-specific attributes and classes from all elements."""
    mt_attrs = [
        "mt-export-translate", "mt-revision", "mt-type", "mt-unsafe",
        "src.path", "src.filename", "href.path", "href.filename",
    ]

    for tag in soup.find_all(True):
        # Remove MindTouch-specific attributes
        for attr in mt_attrs:
            if tag.get(attr):
                del tag[attr]

        # Remove mt-* classes but keep other classes
        if tag.get("class"):
            cleaned = [c for c in tag["class"] if not c.startswith("mt-")]
            if cleaned:
                tag["class"] = cleaned
            else:
                del tag["class"]

    # Remove <meta> tags with mt-* attributes
    for meta in soup.find_all("meta"):
        if any(attr.startswith("mt-") for attr in meta.attrs):
            meta.decompose()

    # Remove the <link> to MindTouch CSS
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        if "_assets" in href:
            link.decompose()


def _clean_whitespace(html: str) -> str:
    """Clean up excessive whitespace while preserving structure."""
    # Remove multiple blank lines
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def replace_placeholders(body: str, replacements: dict) -> str:
    """
    Replace image/attachment placeholders with actual Salesforce URLs.

    Args:
        body: HTML body with placeholders like {{IMG_PLACEHOLDER_0}}
        replacements: dict mapping placeholder string -> Salesforce URL

    Returns:
        Updated HTML body.
    """
    for placeholder, url in replacements.items():
        body = body.replace(placeholder, url)
    return body
