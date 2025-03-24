AUTHOR = 'Isaac Park'
SITENAME = "Isaac's Tech Blog"
SITEURL = ""

PATH = "content"
OUTPUT_PATH = "docs"

TIMEZONE = 'Asia/Seoul'

DEFAULT_LANG = 'ko'

# Feed generation is usually not desired when developing
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

# Blogroll
LINKS = (
    ("Pelican", "https://getpelican.com/"),
    ("Python.org", "https://www.python.org/"),
    ("Jinja2", "https://palletsprojects.com/p/jinja/"),
    ("You can modify those links in your config file", "#"),
)

# Social widget
SOCIAL = (
    ("email", "is9117@me.com"),
    ("twitter", "https://x.com/i544c_park"),
    ("trophy", "https://solved.ac/profile/is9117")
)

PROFILE_IMAGE = "profile.jpeg"

DEFAULT_PAGINATION = 10

# Uncomment following line if you want document-relative URLs when developing
# RELATIVE_URLS = True

TEMPLATE_PAGES = {'robots.txt': 'robots.txt'}

SITEMAP = {
    "format": "xml",
    "priorities": {
        "articles": 0.6,
        "indexes": 0.5,
        "pages": 0.4,
    },
    "changefreqs": {
        "articles": "daily",
        "indexes": "daily",
        "pages": "daily",
    },
}
