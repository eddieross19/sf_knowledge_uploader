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
from html_transformer import transform_article, replace_placeholders
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

def discover_articles(root_dir: str) -> list:
    """
    Scan the root directory for article subfolders.
    Each subfolder should contain a page.html file.

    Returns:
        List of folder paths that contain a valid article.
    """
    articles = []
    for entry in sorted(os.listdir(root_dir)):
        folder_path = os.path.join(root_dir, entry)
        if not os.path.isdir(folder_path):
            continue

        html_path = os.path.join(folder_path, config.HTML_FILENAME)
        if os.path.exists(html_path):
            articles.append(folder_path)
        else:
            logging.warning(f"Skipping folder (no {config.HTML_FILENAME}): {folder_path}")

    return articles


def detect_export_root(articles_root: str) -> str:
    """
    Auto-detect the MindTouch export root by walking up from the articles root
    directory until we find a directory that contains a 'relative/' subdirectory.

    Returns:
        The export root path, or None if not found.
    """
    current = os.path.abspath(articles_root)
    while current != os.path.dirname(current):  # stop at filesystem root
        if os.path.isdir(os.path.join(current, "relative")):
            return current
        # Check if we ARE inside 'relative/'
        parent, name = os.path.split(current)
        if name == "relative":
            return parent
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
        "attachments_uploaded": 0,
        "errors": [],
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
                error_msg = f"Image not found: {img['local_path']}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
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
                logger.warning(f"Attachment not found (skipping): {att['local_path']}")
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
    errors = sum(1 for r in results if r["status"] == "error")

    logger.info("")
    logger.info(f"{'='*60}")
    logger.info(f"UPLOAD SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total articles processed: {total}")
    logger.info(f"  Successful: {success}")
    logger.info(f"  Failed:     {errors}")
    logger.info(f"{'='*60}")

    for r in results:
        status_icon = "✓" if r["status"] == "success" else "✗"
        logger.info(
            f"  {status_icon} {r['title'] or r['folder']}"
            f"  (ID: {r['article_id'] or 'N/A'})"
            f"  [{r['images_uploaded']} imgs, {r['attachments_uploaded']} attachments]"
        )
        if r["errors"]:
            for err in r["errors"]:
                logger.info(f"      ERROR: {err}")

    # Save results to JSON for reference
    report_path = os.path.join(
        config.ARTICLES_ROOT_DIR or ".",
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
        help="Process a single article folder instead of the full root directory.",
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
        help="Override the ARTICLES_ROOT_DIR from config.",
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
        "--export-root",
        help="Root of the MindTouch export (directory containing 'relative/'). "
             "Auto-detected from --root if not specified.",
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

    setup_logging("DEBUG" if args.verbose else None)
    logger = logging.getLogger("main")

    if config.DRY_RUN:
        logger.info("*** DRY RUN MODE — No Salesforce API calls will be made ***")

    # Determine which folders to process
    if args.folder:
        folders = [args.folder]
    else:
        if not config.ARTICLES_ROOT_DIR:
            logger.error(
                "No ARTICLES_ROOT_DIR configured and no --folder specified.\n"
                "Set ARTICLES_ROOT_DIR in config.py or use --root <path>."
            )
            sys.exit(1)
        folders = discover_articles(config.ARTICLES_ROOT_DIR)

    if not folders:
        logger.warning("No article folders found to process.")
        sys.exit(0)

    # Detect or use the export root for resolving cross-folder file references
    export_root = args.export_root
    if not export_root:
        export_root = detect_export_root(config.ARTICLES_ROOT_DIR)
        if export_root:
            logger.info(f"Auto-detected export root: {export_root}")
        else:
            logger.warning(
                "Could not auto-detect MindTouch export root. "
                "Cross-folder image/attachment references may not resolve. "
                "Use --export-root to specify manually."
            )

    logger.info(f"Found {len(folders)} article(s) to process.")

    # Process each article
    results = []
    for folder in folders:
        result = process_article(folder, publish=config.PUBLISH_ON_CREATE, export_root=export_root)
        results.append(result)

    # Print summary
    print_summary(results)

    # Exit with error code if any failures
    if any(r["status"] == "error" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
