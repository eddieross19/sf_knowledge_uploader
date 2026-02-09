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
ATTACHMENT_EXTENSIONS = {".oft", ".pdf", ".doc", ".docx", ".xls", ".xlsx"}

# Image file extensions to process for inline embedding
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
