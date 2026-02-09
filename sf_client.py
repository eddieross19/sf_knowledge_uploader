"""
sf_client.py

Salesforce API client using the Salesforce CLI for authentication
and the REST API (via simple-salesforce) for all CRUD operations.

Handles:
  - Authentication via `sf org display`
  - Uploading files as ContentVersion records
  - Creating Knowledge Article records
  - Linking files to articles via ContentDocumentLink
"""

import json
import subprocess
import base64
import logging
import os
from simple_salesforce import Salesforce

import config

logger = logging.getLogger(__name__)

# Cache the SF connection
_sf_connection = None


def get_connection() -> Salesforce:
    """
    Authenticate to Salesforce using the CLI's existing session.
    Returns a simple_salesforce.Salesforce instance.
    """
    global _sf_connection
    if _sf_connection:
        return _sf_connection

    logger.info("Authenticating to Salesforce via CLI...")

    # Build the sf org display command
    cmd = ["sf", "org", "display", "--json"]
    if config.SF_CLI_TARGET_ORG:
        cmd.extend(["--target-org", config.SF_CLI_TARGET_ORG])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to get org info from SF CLI:\n{result.stderr}\n"
            "Make sure you are authenticated: sf org login web"
        )

    org_info = json.loads(result.stdout)["result"]
    instance_url = org_info["instanceUrl"]
    access_token = org_info["accessToken"]

    _sf_connection = Salesforce(
        instance_url=instance_url,
        session_id=access_token,
        version="60.0",
    )

    logger.info(f"Connected to: {instance_url}")
    return _sf_connection


def upload_file(file_path: str, title: str = None) -> dict:
    """
    Upload a file to Salesforce as a ContentVersion.

    Args:
        file_path: Local path to the file.
        title: Optional title for the file. Defaults to filename.

    Returns:
        dict with:
            - content_version_id: The ContentVersion record ID
            - content_document_id: The ContentDocument record ID
            - download_url: The relative download URL for use in HTML
    """
    sf = get_connection()
    filename = os.path.basename(file_path)

    if title is None:
        title = os.path.splitext(filename)[0]

    logger.info(f"Uploading file: {filename}")

    # Read and base64-encode the file
    with open(file_path, "rb") as f:
        file_data = base64.b64encode(f.read()).decode("utf-8")

    # Create the ContentVersion record
    cv_result = sf.ContentVersion.create({
        "Title": title,
        "PathOnClient": filename,
        "VersionData": file_data,
    })

    content_version_id = cv_result["id"]

    # Query back to get the ContentDocumentId
    cv_record = sf.query(
        f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
    )
    content_document_id = cv_record["records"][0]["ContentDocumentId"]

    # Build the download URL that works in Salesforce rich text fields
    # This format renders images inline and provides download links for attachments
    download_url = f"/sfc/servlet.shepherd/document/download/{content_document_id}"
    rendition_url = (
        f"/sfc/servlet.shepherd/version/renditionDownload"
        f"?rendition=ORIGINAL_Png&versionId={content_version_id}"
    )

    logger.info(f"  -> ContentVersionId: {content_version_id}")
    logger.info(f"  -> ContentDocumentId: {content_document_id}")

    return {
        "content_version_id": content_version_id,
        "content_document_id": content_document_id,
        "download_url": download_url,
        "rendition_url": rendition_url,
        "filename": filename,
    }


def create_article(title: str, body: str, url_name: str = None) -> dict:
    """
    Create a Knowledge Article as a Draft.

    Args:
        title: Article title.
        body: Cleaned HTML body content.
        url_name: URL-friendly name. Auto-generated from title if not provided.

    Returns:
        dict with:
            - article_id: The Knowledge__kav record ID
            - title: The article title
    """
    sf = get_connection()

    if url_name is None:
        url_name = _slugify(title)

    logger.info(f"Creating Knowledge Article: '{title}'")

    # Build the article record
    article_data = {
        config.TITLE_FIELD_API_NAME: title,
        config.URL_NAME_FIELD_API_NAME: url_name,
        config.BODY_FIELD_API_NAME: body,
        "Language": config.ARTICLE_LANGUAGE,
    }

    if config.DRY_RUN:
        logger.info("[DRY RUN] Would create article with data:")
        logger.info(f"  Title: {title}")
        logger.info(f"  UrlName: {url_name}")
        logger.info(f"  Body length: {len(body)} chars")
        return {"article_id": "DRY_RUN_ID", "title": title}

    result = sf.Knowledge__kav.create(article_data)
    article_id = result["id"]

    logger.info(f"  -> Article ID: {article_id}")

    return {
        "article_id": article_id,
        "title": title,
    }


def link_file_to_article(content_document_id: str, article_id: str):
    """
    Link an uploaded file (ContentDocument) to a Knowledge Article
    via ContentDocumentLink.

    Args:
        content_document_id: The ContentDocument ID of the uploaded file.
        article_id: The Knowledge__kav record ID.
    """
    sf = get_connection()

    logger.info(f"Linking ContentDocument {content_document_id} to Article {article_id}")

    if config.DRY_RUN:
        logger.info("[DRY RUN] Would create ContentDocumentLink")
        return

    sf.ContentDocumentLink.create({
        "ContentDocumentId": content_document_id,
        "LinkedEntityId": article_id,
        "ShareType": "V",  # Viewer permission
        "Visibility": "AllUsers",
    })


def publish_article(article_id: str):
    """
    Publish a Knowledge Article (move from Draft to Published).
    Uses the KbManagement Apex REST endpoint.

    This requires a custom Apex REST class deployed to the org.
    See README for the Apex class code.
    """
    sf = get_connection()

    logger.info(f"Publishing article: {article_id}")

    if config.DRY_RUN:
        logger.info("[DRY RUN] Would publish article")
        return

    # Use the Salesforce REST API to call the publishing endpoint
    # This uses the composite API to invoke KbManagement.PublishingService
    try:
        sf.restful(
            f"knowledgeManagement/articleVersions/masterVersions/{article_id}",
            method="PATCH",
            data=json.dumps({"publishStatus": "Online"}),
        )
        logger.info(f"  -> Article published successfully")
    except Exception as e:
        logger.warning(
            f"  -> Could not auto-publish article {article_id}. "
            f"You may need to publish manually or deploy the Apex helper. Error: {e}"
        )


def _slugify(text: str) -> str:
    """Convert a title to a URL-safe slug for the UrlName field."""
    import re
    # Remove special characters, replace spaces with hyphens
    slug = re.sub(r"[^\w\s-]", "", text)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-").lower()
    # Salesforce UrlName max length is 255
    return slug[:255]
