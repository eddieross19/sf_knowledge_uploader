#!/usr/bin/env python3
"""
main.py — Salesforce Knowledge Article Uploader

Orchestrates the end-to-end process:
  1. Scans the articles root directory for subfolders
  2. Transforms MindTouch HTML into Salesforce-compatible HTML
  3. Uploads images and attachments to Salesforce Files
  4. Creates Knowledge Articles as drafts
  5. Links uploaded files to articles
  6. Optionally publishes articles

Usage:
    # Process all articles in the configured root directory
    python main.py

    # Process a single article folder
    python main.py --folder /path/to/article_folder

    # Dry run (preview without making API calls)
    python main.py --dry-run

    # Process all + publish immediately
    python main.py --publish
"""

import argparse
import logging
import os
import sys
import json
from datetime import datetime

import config
from html_transformer import transform_article, replace_placeholders, is_category_page
import sf_client

# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(log_level: str = None):
    level = getattr(logging, log_level or config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# =============================================================================
# Core Processing Logic
# =============================================================================

def discover_articles(root_dir: str, skip_categories: bool = True) -> list:
    """
    Recursively scan for article folders containing page.html.

    Walks the entire directory tree under root_dir. For each folder that
    contains a page.html file, checks whether it's a MindTouch category
    landing page or a real article.

    Args:
        root_dir: Root directory to scan (e.g., the 'relative/' folder
                  inside a MindTouch export, or any subfolder within it).
        skip_categories: If True, skip MindTouch category/guide pages that
                         contain only DekiScript templates and no real content.

    Returns:
        Sorted list of folder paths that contain a valid article.
    """
    logger = logging.getLogger("discover")
    articles = []
    skipped_categories = 0

    root_dir = os.path.normpath(root_dir)

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip hidden directories and MindTouch system directories
        dirnames[:] = [
            d for d in sorted(dirnames)
            if not d.startswith(".") and d != "_assets"
        ]

        if config.HTML_FILENAME not in filenames:
            continue

        html_path = os.path.join(dirpath, config.HTML_FILENAME)

        # Optionally skip category/guide landing pages
        if skip_categories and is_category_page(html_path):
            logger.debug(f"Skipping category page: {dirpath}")
            skipped_categories += 1
            continue

        articles.append(dirpath)

    if skipped_categories > 0:
        logger.info(f"Skipped {skipped_categories} category/guide landing pages.")

    articles.sort()
    return articles


def detect_export_root(path: str) -> str:
    """
    Auto-detect the MindTouch export root directory.

    Walks up from the given path looking for a directory that contains
    'relative/' and 'hierarchy.dat' — the signature of a MindTouch export.

    If the given path itself is the export root, returns it directly.

    Args:
        path: A path inside (or to) the export directory.

    Returns:
        The export root path, or None if not found.
    """
    path = os.path.normpath(os.path.abspath(path))

    # Check the path itself and walk up
    current = path
    for _ in range(20):  # Safety limit on depth
        if (os.path.isdir(os.path.join(current, "relative"))
                and os.path.exists(os.path.join(current, "hierarchy.dat"))):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return None


def process_article(folder_path: str, publish: bool = False, export_root: str = None) -> dict:
    """
    Process a single article folder:
      1. Transform HTML
      2. Upload images → get Salesforce URLs
      3. Upload attachments → get Salesforce URLs
      4. Replace placeholders in HTML body
      5. Create Knowledge Article
      6. Link files to article

    Args:
        folder_path: Path to the article folder.
        publish: Whether to publish the article after creation.
        export_root: Root of the MindTouch export (for cross-folder file resolution).

    Returns:
        dict with processing results.
    """
    logger = logging.getLogger("process_article")
    folder_name = os.path.basename(folder_path)
    html_path = os.path.join(folder_path, config.HTML_FILENAME)

    logger.info(f"{'='*60}")
    logger.info(f"Processing: {folder_name}")
    logger.info(f"{'='*60}")

    result = {
        "folder": folder_name,
        "status": "pending",
        "article_id": None,
        "title": None,
        "images_uploaded": 0,
        "images_missing": 0,
        "attachments_uploaded": 0,
        "attachments_missing": 0,
        "errors": [],
        "warnings": [],
    }

    try:
        # ----- Step 1: Transform HTML -----
        logger.info("Step 1: Transforming HTML...")
        article_data = transform_article(html_path, export_root=export_root)
        result["title"] = article_data["title"]

        # ----- Step 2: Upload images -----
        logger.info(f"Step 2: Uploading {len(article_data['images'])} images...")
        url_replacements = {}

        for img in article_data["images"]:
            if not os.path.exists(img["local_path"]):
                warn_msg = f"Image not found (skipping): {img['local_path']}"
                logger.warning(warn_msg)
                result["warnings"].append(warn_msg)
                result["images_missing"] += 1
                # Use empty string so the <img> tag renders as broken image
                # rather than causing the entire article to fail
                url_replacements[img["placeholder"]] = ""
                continue

            if config.DRY_RUN:
                logger.info(f"  [DRY RUN] Would upload image: {img['filename']}")
                url_replacements[img["placeholder"]] = f"[IMAGE: {img['filename']}]"
            else:
                upload_result = sf_client.upload_file(
                    file_path=img["local_path"],
                    title=img["filename"],
                )
                # For images, use the rendition URL so they display inline
                url_replacements[img["placeholder"]] = upload_result["rendition_url"]
                result["images_uploaded"] += 1

        # ----- Step 3: Upload attachments -----
        logger.info(f"Step 3: Uploading {len(article_data['attachments'])} attachments...")
        attachment_docs = []  # Track for linking later

        for att in article_data["attachments"]:
            if not os.path.exists(att["local_path"]):
                # Attachments may not always be in the same folder — warn but continue
                warn_msg = f"Attachment not found (skipping): {att['local_path']}"
                logger.warning(warn_msg)
                result["warnings"].append(warn_msg)
                result["attachments_missing"] += 1
                url_replacements[att["placeholder"]] = "#"
                continue

            if config.DRY_RUN:
                logger.info(f"  [DRY RUN] Would upload attachment: {att['filename']}")
                url_replacements[att["placeholder"]] = f"[ATTACHMENT: {att['filename']}]"
            else:
                upload_result = sf_client.upload_file(
                    file_path=att["local_path"],
                    title=att["filename"],
                )
                url_replacements[att["placeholder"]] = upload_result["download_url"]
                attachment_docs.append(upload_result)
                result["attachments_uploaded"] += 1

        # ----- Step 4: Replace placeholders in body -----
        logger.info("Step 4: Replacing placeholders with Salesforce URLs...")
        final_body = replace_placeholders(article_data["body"], url_replacements)

        # Validate body length (Salesforce rich text limit is ~131,072 chars)
        if len(final_body) > 131072:
            logger.warning(
                f"Article body is {len(final_body)} chars — exceeds 131,072 char limit. "
                "Consider splitting the article or reducing image size."
            )

        # ----- Step 5: Create Knowledge Article -----
        logger.info("Step 5: Creating Knowledge Article...")
        article_result = sf_client.create_article(
            title=article_data["title"],
            body=final_body,
        )
        result["article_id"] = article_result["article_id"]

        # ----- Step 6: Link attachments to article -----
        if attachment_docs and not config.DRY_RUN:
            logger.info(f"Step 6: Linking {len(attachment_docs)} attachments to article...")
            for doc in attachment_docs:
                try:
                    sf_client.link_file_to_article(
                        content_document_id=doc["content_document_id"],
                        article_id=result["article_id"],
                    )
                except Exception as e:
                    logger.warning(f"Could not link {doc['filename']}: {e}")

        # ----- Step 7 (Optional): Publish -----
        if publish and not config.DRY_RUN:
            logger.info("Step 7: Publishing article...")
            sf_client.publish_article(result["article_id"])

        result["status"] = "success"
        if result["warnings"]:
            result["status"] = "success_with_warnings"
            logger.info(f"⚠ Article created with warnings: {result['title']} ({len(result['warnings'])} missing files)")
        else:
            logger.info(f"✓ Article created successfully: {result['title']}")

    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))
        logger.error(f"✗ Failed to process {folder_name}: {e}", exc_info=True)

    return result


# =============================================================================
# Summary Report
# =============================================================================

def print_summary(results: list):
    """Print a summary table of all processed articles."""
    logger = logging.getLogger("summary")

    total = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    with_warnings = sum(1 for r in results if r["status"] == "success_with_warnings")
    errors = sum(1 for r in results if r["status"] == "error")

    logger.info("")
    logger.info(f"{'='*60}")
    logger.info(f"UPLOAD SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total articles processed: {total}")
    logger.info(f"  Successful:            {success}")
    logger.info(f"  Success with warnings: {with_warnings}")
    logger.info(f"  Failed:                {errors}")
    logger.info(f"{'='*60}")

    for r in results:
        if r["status"] == "success":
            status_icon = "✓"
        elif r["status"] == "success_with_warnings":
            status_icon = "⚠"
        else:
            status_icon = "✗"

        missing_parts = []
        if r.get("images_missing", 0) > 0:
            missing_parts.append(f"{r['images_missing']} imgs missing")
        if r.get("attachments_missing", 0) > 0:
            missing_parts.append(f"{r['attachments_missing']} att missing")
        missing_str = f" | {', '.join(missing_parts)}" if missing_parts else ""

        logger.info(
            f"  {status_icon} {r['title'] or r['folder']}"
            f"  (ID: {r['article_id'] or 'N/A'})"
            f"  [{r['images_uploaded']} imgs, {r['attachments_uploaded']} attachments{missing_str}]"
        )
        if r["errors"]:
            for err in r["errors"]:
                logger.info(f"      ERROR: {err}")
        if r.get("warnings"):
            for warn in r["warnings"]:
                logger.info(f"      WARNING: {warn}")

    # Save results to JSON for reference
    report_dir = config.ARTICLES_ROOT_DIR or os.getcwd()
    report_path = os.path.join(
        report_dir,
        f"upload_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    try:
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"\nDetailed report saved to: {report_path}")
    except Exception:
        pass


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Upload MindTouch Knowledge Articles to Salesforce"
    )
    parser.add_argument(
        "--folder",
        help="Process a single article folder instead of scanning a directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without making any Salesforce API calls.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish articles immediately after creation.",
    )
    parser.add_argument(
        "--root",
        help=(
            "Root directory to scan for articles. Can be the export root "
            "(auto-detects relative/ subfolder) or any subfolder within the export."
        ),
    )
    parser.add_argument(
        "--export-root",
        help=(
            "MindTouch export root directory (the folder containing relative/, "
            "hierarchy.dat, and package.xml). Used to resolve cross-folder file "
            "references. Auto-detected from --root if omitted."
        ),
    )
    parser.add_argument(
        "--org",
        help="Override the SF_CLI_TARGET_ORG from config.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging.",
    )
    parser.add_argument(
        "--include-categories",
        action="store_true",
        help=(
            "Include MindTouch category/guide landing pages. By default these are "
            "skipped because they contain only DekiScript templates and no real content."
        ),
    )

    args = parser.parse_args()

    # Apply overrides
    if args.dry_run:
        config.DRY_RUN = True
    if args.publish:
        config.PUBLISH_ON_CREATE = True
    if args.root:
        config.ARTICLES_ROOT_DIR = args.root
    if args.org:
        config.SF_CLI_TARGET_ORG = args.org
    if args.include_categories:
        config.SKIP_CATEGORY_PAGES = False

    setup_logging("DEBUG" if args.verbose else None)
    logger = logging.getLogger("main")

    if config.DRY_RUN:
        logger.info("*** DRY RUN MODE — No Salesforce API calls will be made ***")

    # --- Resolve export root ---
    export_root = None
    if args.export_root:
        export_root = os.path.normpath(os.path.abspath(args.export_root))
        if not os.path.isdir(os.path.join(export_root, "relative")):
            logger.error(
                f"Export root does not contain a 'relative/' folder: {export_root}\n"
                "The export root should be the top-level directory of the MindTouch export "
                "(e.g., site_14870-export-20260205233221.155/)."
            )
            sys.exit(1)

    # --- Determine which folders to process ---
    if args.folder:
        # Single folder mode
        folder = os.path.normpath(os.path.abspath(args.folder))
        folders = [folder]
        # Auto-detect export root if not explicitly provided
        if not export_root:
            export_root = detect_export_root(folder)
    else:
        # Batch mode — scan a directory tree
        scan_root = config.ARTICLES_ROOT_DIR
        if not scan_root:
            logger.error(
                "No articles directory specified.\n"
                "Use --root <path> to set the directory to scan, or --folder for a single article.\n"
                "Examples:\n"
                "  python main.py --root C:\\path\\to\\site_14870-export-20260205233221.155\n"
                "  python main.py --root C:\\path\\to\\export\\relative\\Clients\\MRA_CSP\\Profiles"
            )
            sys.exit(1)

        scan_root = os.path.normpath(os.path.abspath(scan_root))

        # Auto-detect export root if not explicitly provided
        if not export_root:
            export_root = detect_export_root(scan_root)

        # If scan_root IS the export root, scan the 'relative/' subfolder
        if export_root and os.path.normpath(scan_root) == os.path.normpath(export_root):
            scan_root = os.path.join(export_root, "relative")
            logger.info(f"Export root detected — scanning: {scan_root}")

        if not os.path.isdir(scan_root):
            logger.error(f"Scan directory does not exist: {scan_root}")
            sys.exit(1)

        folders = discover_articles(
            scan_root,
            skip_categories=config.SKIP_CATEGORY_PAGES,
        )

    if not folders:
        logger.warning("No article folders found to process.")
        sys.exit(0)

    if export_root:
        logger.info(f"Export root: {export_root}")
    else:
        logger.warning(
            "Could not auto-detect MindTouch export root. Cross-folder file "
            "references (src.path, href.path) may not resolve correctly. "
            "Use --export-root to set it explicitly."
        )

    logger.info(f"Found {len(folders)} article(s) to process.")

    # Process each article
    results = []
    for folder in folders:
        result = process_article(
            folder,
            publish=config.PUBLISH_ON_CREATE,
            export_root=export_root,
        )
        results.append(result)

    # Print summary
    print_summary(results)

    # Exit with error code if any failures
    if any(r["status"] == "error" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
