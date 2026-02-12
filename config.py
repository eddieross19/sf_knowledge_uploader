"""
Configuration for Salesforce Knowledge Article Uploader.
Update these values to match your Salesforce org and local file structure.
"""

# =============================================================================
# SALESFORCE ORG SETTINGS
# =============================================================================

# The alias or username you authenticated with `sf org login`
SF_CLI_TARGET_ORG = ""  # e.g., "my-sandbox" — leave blank to use default org

# Knowledge Article object and field API names
ARTICLE_API_NAME = "Knowledge__kav"
BODY_FIELD_API_NAME = "FAQ_Answer__c"
TITLE_FIELD_API_NAME = "Title"
URL_NAME_FIELD_API_NAME = "UrlName"

# Optional: Set a default Data Category Group and Category
# Leave as None to skip data category assignment
DATA_CATEGORY_GROUP = None  # e.g., "Knowledge_Topics"
DATA_CATEGORY = None        # e.g., "Claims_Process"

# =============================================================================
# LOCAL FILE STRUCTURE
# =============================================================================

# Root folder containing all article subfolders
ARTICLES_ROOT_DIR = ""  # e.g., "/Users/you/Desktop/KnowledgeArticles"

# The HTML filename to look for in each subfolder
HTML_FILENAME = "page.html"

# File extensions to upload as Salesforce Files (attachments)
# Matching is case-insensitive (e.g. .PDF and .pdf both match)
ATTACHMENT_EXTENSIONS = {
    ".oft", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pptx", ".ppt", ".msg", ".vsd", ".vsdx", ".xlsm",
    ".csv", ".txt", ".mp4", ".docm", ".mpp",
}

# Image file extensions to process for inline embedding
# Matching is case-insensitive (e.g. .PNG and .png both match)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg"}

# =============================================================================
# UPLOAD BEHAVIOR
# =============================================================================

# Whether to publish articles immediately after creation
# False = create as Draft (recommended for review)
PUBLISH_ON_CREATE = False

# Article language (used in KnowledgeArticleVersion)
ARTICLE_LANGUAGE = "en_US"

# Logging verbosity: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL = "INFO"

# Dry run mode — set to True to preview actions without making API calls
DRY_RUN = False

# Whether to skip MindTouch category/guide landing pages
# (pages tagged as article:topic-category or article:topic-guide that contain
#  only DekiScript templates and no real article content)
SKIP_CATEGORY_PAGES = True
