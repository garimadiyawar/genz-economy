"""
News Parser — Gen Z Economy Sentiment
Uses free sources: RSS feeds + NewsAPI (free tier) + GDELT

Tracks media coverage and sentiment around:
- Gen Z economy, housing, jobs, student debt
- Economic anxiety, quiet quitting, soft life, etc.

Usage: python src/news_parser/news_parser.py
"""

import os
import time
import hashlib
import requests
import feedparser
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    logger.warning("vaderSentiment not installed — run: pip install vaderSentiment")

load_dotenv()
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

NEWS_DIR = Path("data/raw/news")
NEWS_DIR.mkdir(parents=True, exist_ok=True)

analyzer = SentimentIntensityAnalyzer() if VADER_AVAILABLE else None


# ═══════════════════════════════════════════════════════════════
# SEARCH QUERIES — topics relevant to Gen Z economy
# ═══════════════════════════════════════════════════════════════

NEWSAPI_QUERIES = [
    "Gen Z economy",
    "Gen Z housing affordability",
    "Gen Z student debt",
    "Gen Z job market",
    "Gen Z financial stress",
    "Gen Z rent burden",
    "Gen Z cost of living",
    "young adults homeownership",
    "millennials gen z wealth gap",
]

# Free RSS feeds (no API key needed)
RSS_FEEDS = {
    "BLS News":       "https://www.bls.gov/rss/special.requests.rss",
    "Fed Reserve":    "https://www.federalreserve.gov/feeds/press_all.xml",
    "Census Bureau":  "https://www.census.gov/newsroom/blogs/feed.xml",
    "NPR Economy":    "https://feeds.npr.org/1017/rss.xml",
    "MarketWatch":    "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
}

# GDELT — free global news database (no API key)
GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


# ═══════════════════════════════════════════════════════════════
# SENTIMENT ANALYSIS
# ═══════════════════════════════════════════════════════════════

def get_sentiment(text: str) -> dict:
    """VADER sentiment — works well for news headlines."""
    if not analyzer or not text:
        return {"compound": 0, "pos": 0, "neg": 0, "neu": 1}
    scores = analyzer.polarity_scores(text)
    return scores


def classify_sentiment(compound: float) -> str:
    if compound >= 0.05:  return "positive"
    if compound <= -0.05: return "negative"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# SOURCE 1: NewsAPI
# ═══════════════════════════════════════════════════════════════

def fetch_newsapi(query: str, days_back: int = 30) -> list[dict]:
    """NewsAPI free tier: 100 requests/day, 1 month back."""
    if not NEWSAPI_KEY:
        logger.warning("No NEWSAPI_KEY set — skipping NewsAPI")
        return []

    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "from": from_date,
        "sortBy": "relevancy",
        "language": "en",
        "pageSize": 20,
        "apiKey": NEWSAPI_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        results = []
        for a in articles:
            text = f"{a.get('title', '')} {a.get('description', '')}"
            sentiment = get_sentiment(text)
            results.append({
                "source":          "newsapi",
                "query":           query,
                "title":           a.get("title"),
                "description":     a.get("description"),
                "url":             a.get("url"),
                "published_at":    a.get("publishedAt"),
                "outlet":          a.get("source", {}).get("name"),
                "compound_score":  sentiment["compound"],
                "sentiment":       classify_sentiment(sentiment["compound"]),
                "article_id":      hashlib.md5(a.get("url", "").encode()).hexdigest(),
            })
        return results
    except Exception as e:
        logger.error(f"NewsAPI '{query}': {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# SOURCE 2: RSS Feeds
# ═══════════════════════════════════════════════════════════════

def fetch_rss(feed_name: str, url: str) -> list[dict]:
    """Parse RSS feed and extract relevant articles."""
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:30]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            text = f"{title} {summary}"

            # Filter: only keep if relevant to economy/Gen Z topics
            keywords = ["gen z", "young adult", "student loan", "rent", "wage",
                       "housing", "employment", "inflation", "debt", "economy"]
            if not any(kw.lower() in text.lower() for kw in keywords):
                continue

            sentiment = get_sentiment(text)
            published = entry.get("published", "")

            results.append({
                "source":          "rss",
                "query":           feed_name,
                "title":           title,
                "description":     summary[:300],
                "url":             entry.get("link"),
                "published_at":    published,
                "outlet":          feed_name,
                "compound_score":  sentiment["compound"],
                "sentiment":       classify_sentiment(sentiment["compound"]),
                "article_id":      hashlib.md5(entry.get("link", title).encode()).hexdigest(),
            })
        return results
    except Exception as e:
        logger.error(f"RSS '{feed_name}': {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# SOURCE 3: GDELT (free, no key needed)
# ═══════════════════════════════════════════════════════════════

def fetch_gdelt(query: str = "gen z economy", max_records: int = 50) -> list[dict]:
    """
    GDELT free API — massive global news database.
    Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
    """
    params = {
        "query":      query,
        "mode":       "artlist",
        "maxrecords": max_records,
        "format":     "json",
        "sort":       "DateDesc",
    }
    try:
        resp = requests.get(GDELT_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])
        results = []
        for a in articles:
            title = a.get("title", "")
            sentiment = get_sentiment(title)
            results.append({
                "source":          "gdelt",
                "query":           query,
                "title":           title,
                "description":     None,
                "url":             a.get("url"),
                "published_at":    a.get("seendate"),
                "outlet":          a.get("domain"),
                "compound_score":  sentiment["compound"],
                "sentiment":       classify_sentiment(sentiment["compound"]),
                "article_id":      hashlib.md5(a.get("url", title).encode()).hexdigest(),
            })
        return results
    except Exception as e:
        logger.error(f"GDELT error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# AGGREGATE & SAVE
# ═══════════════════════════════════════════════════════════════

def compute_sentiment_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sentiment scores by topic and date for Tableau."""
    df["date"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True)
    df["date"] = df["date"].dt.tz_localize(None).dt.to_period("W").dt.to_timestamp()

    summary = df.groupby(["query", "date"]).agg(
        article_count  = ("article_id", "nunique"),
        avg_sentiment  = ("compound_score", "mean"),
        positive_count = ("sentiment", lambda x: (x == "positive").sum()),
        negative_count = ("sentiment", lambda x: (x == "negative").sum()),
        neutral_count  = ("sentiment", lambda x: (x == "neutral").sum()),
    ).reset_index()

    summary["sentiment_label"] = summary["avg_sentiment"].apply(classify_sentiment)
    return summary


def run():
    logger.info("=== News Parser ===")
    all_articles = []

    # 1. NewsAPI
    logger.info("Fetching NewsAPI...")
    for query in NEWSAPI_QUERIES[:5]:  # Respect free tier limit
        articles = fetch_newsapi(query)
        all_articles.extend(articles)
        logger.info(f"  '{query}': {len(articles)} articles")
        time.sleep(0.5)

    # 2. RSS
    logger.info("Fetching RSS feeds...")
    for name, url in RSS_FEEDS.items():
        articles = fetch_rss(name, url)
        all_articles.extend(articles)
        logger.info(f"  {name}: {len(articles)} relevant articles")

    # 3. GDELT
    logger.info("Fetching GDELT...")
    for query in ["gen z economy", "young adult housing", "student loan debt"]:
        articles = fetch_gdelt(query)
        all_articles.extend(articles)
        logger.info(f"  GDELT '{query}': {len(articles)} articles")
        time.sleep(1)

    if not all_articles:
        logger.warning("No articles collected.")
        return

    df = pd.DataFrame(all_articles).drop_duplicates(subset=["article_id"])
    df.to_parquet(NEWS_DIR / "news_articles.parquet", index=False)
    df.to_csv(NEWS_DIR / "news_articles.csv", index=False)
    logger.success(f"Saved {len(df)} articles")

    # Export summary for Tableau
    summary = compute_sentiment_summary(df)
    summary.to_csv(Path("data/exports/tableau_news_sentiment.csv"), index=False)
    logger.success(f"Sentiment summary: {len(summary)} rows → tableau_news_sentiment.csv")

    return df


if __name__ == "__main__":
    run()
