"""
Disease News API
- GET  /api/disease-news          : list berita dengan filter dan paginasi
- GET  /api/disease-news/trending : 2 berita Home, 1 Indonesia + 1 internasional
- POST /api/disease-news/refresh  : trigger manual refresh

Fetcher gratis/API:
- NewsAPI jika NEWS_API_KEY tersedia di .env
- Google News RSS Indonesia/global
- Google Trends RSS Indonesia/US
- Kemenkes RSS
- CDC RSS, WHO API fallback
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import struct_time
from urllib.parse import quote_plus, urljoin, urlparse

import feedparser
import requests
from flask import Response, current_app, request
from flask_restful import Resource
from sqlalchemy import case, inspect, text

try:
    from scrapling.parser import Adaptor
except ImportError:
    Adaptor = None

from app.models import DiseaseNews, db

logger = logging.getLogger(__name__)

WHO_OUTBREAK_NEWS_URL = "https://www.who.int/api/news/diseaseoutbreaknews"
WHO_OUTBREAKS_URL = "https://www.who.int/api/news/outbreaks"
CDC_RSS_URL = "https://tools.cdc.gov/api/v2/resources/media/316422.rss"
KEMENKES_RSS_URL = "https://kemkes.go.id/id/rss/article/rilis-berita"
NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
NEWSAPI_TOP_HEADLINES_URL = "https://newsapi.org/v2/top-headlines"
GOOGLE_TRENDS_RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"

REQUEST_TIMEOUT = 15
ACTIVE_NEWS_TOTAL_LIMIT = 10
ACTIVE_NEWS_PER_REGION_LIMIT = 5
SOURCE_KIND_PER_REGION_LIMIT = 2
SOURCE_NAME_PER_REGION_LIMIT = 2

INDONESIA_NEWS_QUERY = (
    "(penyakit OR virus OR wabah OR kesehatan OR infeksi OR vaksin OR "
    "imunisasi OR \"kesehatan masyarakat\") Indonesia when:2d"
)
GLOBAL_NEWS_QUERY = (
    "(disease OR virus OR outbreak OR health OR infection OR vaccine OR "
    "\"public health\") when:2d"
)
NEWSAPI_INDONESIA_QUERY = (
    "penyakit OR virus OR wabah OR kesehatan OR infeksi OR vaksin OR "
    "imunisasi OR demam"
)
NEWSAPI_GLOBAL_QUERY = (
    "disease OR virus OR outbreak OR health OR infection OR vaccine OR "
    "\"public health\""
)

HIGH_ALERT_KEYWORDS = [
    "pandemic", "epidemic", "outbreak", "wabah", "pandemi", "ebola",
    "cholera", "plague", "mpox", "monkeypox", "avian influenza",
    "bird flu", "flu burung", "marburg", "lassa", "hanta",
    "hantavirus", "rabies", "anthrax",
]
MEDIUM_ALERT_KEYWORDS = [
    "dengue", "dbd", "malaria", "typhoid", "tifoid", "tuberculosis",
    "tbc", "hepatitis", "measles", "campak", "pertussis",
    "whooping cough", "leptospirosis", "meningitis", "salmonella",
    "covid", "influenza", "pneumonia", "gastroenteritis",
]
HEALTH_KEYWORDS = sorted(
    set(HIGH_ALERT_KEYWORDS + MEDIUM_ALERT_KEYWORDS + [
        "penyakit", "virus", "kesehatan", "gejala", "infeksi", "vaksin",
        "imunisasi", "demam", "batuk", "diare", "penularan", "kasus",
        "patient", "patients", "infection", "infectious", "vaccine",
        "hospital", "medicine", "public health", "health",
    ]),
    key=len,
    reverse=True,
)
DISEASE_SIGNAL_KEYWORDS = sorted(
    set(HIGH_ALERT_KEYWORDS + MEDIUM_ALERT_KEYWORDS + [
        "penyakit", "virus", "wabah", "infeksi", "vaksin", "imunisasi",
        "gejala", "penularan", "kasus", "disease", "outbreak",
        "infection", "infectious", "vaccine", "case", "cases",
    ]),
    key=len,
    reverse=True,
)
BLOCKED_NEWS_KEYWORDS = [
    "malware", "trojan", "ransomware", "computer virus", "win32",
    "movie", "film", "cannes", "premiere", "album", "song", "game",
    "sinopsis", "tayang", "malam ini", "trans tv", "bioskop", "trailer",
    "serial", "drama", "aktor", "aktris", "actor", "actress",
    "dominic cooper", "stratton", "trump", "white house", "football",
    "crypto",
]
BLOCKED_SOURCE_NAMES = {
    "Globalresearch.ca",
    "Vidio",
}

SOURCE_BASE_SCORE = {
    "newsapi_top": 52,
    "newsapi": 44,
    "google_trends": 40,
    "google_news": 35,
    "cdc": 32,
    "who": 30,
    "kemenkes": 25,
}


def _strip_html(html: str) -> str:
    if not html:
        return ""
    if Adaptor and "<" in html:
        try:
            page = Adaptor(html)
            clean = page.get_all_text(ignore_tags=["script", "style"], separator=" ").strip()
            return clean[:500]
        except Exception:
            pass
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:500]


def _extract_image_from_html(html: str) -> str:
    if not html:
        return ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip()


def _entry_image_url(entry, base_url: str = "") -> str:
    candidates = []
    for media in entry.get("media_content", []) or []:
        candidates.append(media.get("url"))
    for media in entry.get("media_thumbnail", []) or []:
        candidates.append(media.get("url"))
    for link in entry.get("links", []) or []:
        rel = (link.get("rel") or "").lower()
        media_type = (link.get("type") or "").lower()
        if rel == "enclosure" and media_type.startswith("image/"):
            candidates.append(link.get("href"))
    candidates.append(_extract_image_from_html(entry.get("summary") or ""))
    candidates.append(_extract_image_from_html(entry.get("description") or ""))

    for candidate in candidates:
        if not candidate:
            continue
        url = str(candidate).strip()
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if base_url:
            return urljoin(base_url, url)
    return ""


def _absolute_url(url: str, base_url: str = "") -> str:
    if not url:
        return ""
    raw = str(url).strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return urljoin(base_url, raw) if base_url else raw


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, struct_time):
        dt = datetime(*value[:6])
    elif isinstance(value, str):
        raw = value.strip()
        dt = None
        try:
            dt = parsedate_to_datetime(raw)
        except Exception:
            pass
        if dt is None:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
                try:
                    dt = datetime.strptime(raw[:19], fmt)
                    break
                except (ValueError, TypeError):
                    continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                return None
    else:
        return None

    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_feed(url: str):
    headers = {
        "User-Agent": "SmartFarmasi-App/1.0 (Educational)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = resp.content.decode(resp.encoding or "utf-8", errors="ignore")
    text = "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32)
    return feedparser.parse(text)


def _classify_alert(title: str, summary: str) -> tuple[str, str]:
    text = f"{title} {summary or ''}".lower()
    if any(keyword in text for keyword in HIGH_ALERT_KEYWORDS):
        return "high", "Wabah Global"
    if any(keyword in text for keyword in MEDIUM_ALERT_KEYWORDS):
        return "medium", "Perlu Diwaspadai"
    return "low", "Update Terbaru"


def _health_hits(title: str, summary: str) -> list[str]:
    text = f"{title} {summary or ''}".lower()
    return [keyword for keyword in HEALTH_KEYWORDS if keyword in text]


def _disease_signal_hits(title: str, summary: str) -> list[str]:
    text = f"{title} {summary or ''}".lower()
    return [keyword for keyword in DISEASE_SIGNAL_KEYWORDS if keyword in text]


def _is_blocked_news_topic(title: str, summary: str) -> bool:
    text = f"{title} {summary or ''}".lower()
    return any(keyword in text for keyword in BLOCKED_NEWS_KEYWORDS)


def _parse_traffic(value: str | None) -> int:
    if not value:
        return 0
    raw = value.lower().replace("+", "").replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*([km]?)", raw)
    if not match:
        return 0
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix == "m":
        number *= 1_000_000
    elif suffix == "k":
        number *= 1_000
    return int(number)


def _recency_score(published_at: datetime | None, now: datetime) -> int:
    if not published_at:
        return 5
    age = now - published_at
    if age.total_seconds() < 0:
        return 50
    if age <= timedelta(hours=24):
        return 50
    if age <= timedelta(days=2):
        return 42
    if age <= timedelta(days=7):
        return 28
    if age <= timedelta(days=30):
        return 12
    return 0


def _traffic_score(traffic: int) -> int:
    if traffic >= 1_000_000:
        return 20
    if traffic >= 200_000:
        return 16
    if traffic >= 50_000:
        return 12
    if traffic >= 10_000:
        return 8
    return 0


def _split_google_news_title(title: str) -> tuple[str, str]:
    if " - " not in title:
        return title.strip(), "Google News"
    article_title, source = title.rsplit(" - ", 1)
    return article_title.strip(), source.strip() or "Google News"


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return _parse_datetime(value)
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            return _parse_datetime(value)
    return None


def _trend_news_fields(entry) -> tuple[str, str, str]:
    title = entry.get("ht_news_item_title") or entry.get("news_item_title") or ""
    url = entry.get("ht_news_item_url") or entry.get("news_item_url") or entry.get("link") or ""
    source = entry.get("ht_news_item_source") or entry.get("news_item_source") or "Google Trends"

    if isinstance(title, list):
        title = title[0] if title else ""
    if isinstance(url, list):
        url = url[0] if url else ""
    if isinstance(source, list):
        source = source[0] if source else "Google Trends"

    return str(title), str(url), str(source)


def _build_news_item(
    *,
    title: str,
    summary: str = "",
    source_name: str,
    source_url: str = "",
    source_kind: str,
    region_scope: str,
    country: str = "",
    disease_name: str = "",
    published_at: datetime | None = None,
    trend_keyword: str = "",
    traffic: int = 0,
    image_url: str = "",
) -> dict | None:
    title = (title or "").strip()
    summary = _strip_html(summary or "")
    if not title:
        return None
    if _is_blocked_news_topic(title, summary):
        return None

    alert_level, badge = _classify_alert(title, summary)
    hits = _health_hits(title, summary)
    disease_hits = _disease_signal_hits(title, summary)

    if source_kind in {"google_news", "google_trends", "newsapi", "newsapi_top"} and not hits:
        return None
    if source_kind == "newsapi" and not disease_hits:
        return None

    now = datetime.utcnow()
    score = SOURCE_BASE_SCORE.get(source_kind, 25)
    score += _recency_score(published_at, now)
    score += min(len(hits) * 3, 15)
    score += _traffic_score(traffic)
    if image_url:
        score += 4
    if alert_level == "high":
        score += 12
    elif alert_level == "medium":
        score += 8

    score = min(score, 150)
    if score >= 75 and badge == "Update Terbaru":
        badge = "Trending"

    return {
        "title": title,
        "disease_name": disease_name or (disease_hits[0].title() if disease_hits else hits[0].title() if hits else ""),
        "summary": summary,
        "country": country,
        "source_name": source_name,
        "source_kind": source_kind,
        "source_url": source_url,
        "image_url": image_url,
        "alert_level": alert_level,
        "badge": badge,
        "published_at": published_at,
        "region_scope": region_scope,
        "trend_score": score,
        "trend_keyword": trend_keyword or (hits[0] if hits else ""),
        "is_trending": score >= 70 or (published_at and published_at >= now - timedelta(days=2)),
    }


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _dedupe_items(items: list[dict]) -> list[dict]:
    best_by_key: dict[str, dict] = {}
    for item in items:
        key = item.get("source_url") or _normalize_title(item["title"])[:120]
        current = best_by_key.get(key)
        if not current or item.get("trend_score", 0) > current.get("trend_score", 0):
            best_by_key[key] = item
    return list(best_by_key.values())


def _sort_key(item: dict) -> tuple:
    published_at = item.get("published_at") or datetime.min
    has_image = 1 if item.get("image_url") else 0
    return (
        item.get("trend_score", 0),
        has_image,
        published_at,
    )


def _pick_region_items(items: list[dict], region_scope: str, limit: int) -> list[dict]:
    """Pick a small, source-diverse set for one region."""
    candidates = sorted(
        [item for item in items if item.get("region_scope") == region_scope],
        key=_sort_key,
        reverse=True,
    )
    selected: list[dict] = []
    kind_count: Counter[str] = Counter()
    source_count: Counter[str] = Counter()

    for item in candidates:
        source_kind = item.get("source_kind") or item.get("source_name") or "unknown"
        source_name = item.get("source_name") or source_kind
        if kind_count[source_kind] >= SOURCE_KIND_PER_REGION_LIMIT:
            continue
        if source_count[source_name] >= SOURCE_NAME_PER_REGION_LIMIT:
            continue

        selected.append(item)
        kind_count[source_kind] += 1
        source_count[source_name] += 1
        if len(selected) == limit:
            return selected

    selected_ids = {id(item) for item in selected}
    for item in candidates:
        if id(item) in selected_ids:
            continue
        selected.append(item)
        if len(selected) == limit:
            break

    return selected


def _select_active_news_items(items: list[dict]) -> list[dict]:
    """Keep the app lightweight: 5 Indonesia + 5 international when available."""
    selected = (
        _pick_region_items(items, "indonesia", ACTIVE_NEWS_PER_REGION_LIMIT)
        + _pick_region_items(items, "international", ACTIVE_NEWS_PER_REGION_LIMIT)
    )
    selected_ids = {id(item) for item in selected}

    if len(selected) < ACTIVE_NEWS_TOTAL_LIMIT:
        remaining = sorted(
            [item for item in items if id(item) not in selected_ids],
            key=_sort_key,
            reverse=True,
        )
        for item in remaining:
            selected.append(item)
            if len(selected) == ACTIVE_NEWS_TOTAL_LIMIT:
                break

    return selected[:ACTIVE_NEWS_TOTAL_LIMIT]


def _find_existing_news(item: dict) -> DiseaseNews | None:
    source_url = item.get("source_url")
    if source_url:
        existing = DiseaseNews.query.filter_by(source_url=source_url).first()
        if existing:
            return existing

    return DiseaseNews.query.filter(
        DiseaseNews.title.ilike(f"%{item['title'][:80]}%")
    ).first()


def _prune_disease_news_cache(max_rows: int = ACTIVE_NEWS_TOTAL_LIMIT) -> int:
    """Delete everything outside the active cache so the table stays tiny."""
    has_image = case(
        (db.and_(DiseaseNews.image_url.isnot(None), DiseaseNews.image_url != ""), 1),
        else_=0,
    )

    def top_region_rows(region_scope: str, limit: int) -> list[DiseaseNews]:
        return (
            DiseaseNews.query
            .filter_by(is_active=True, region_scope=region_scope)
            .order_by(
                DiseaseNews.trend_score.desc(),
                has_image.desc(),
                DiseaseNews.published_at.desc(),
                DiseaseNews.fetched_at.desc(),
            )
            .limit(limit)
            .all()
        )

    keep_rows = (
        top_region_rows("indonesia", ACTIVE_NEWS_PER_REGION_LIMIT)
        + top_region_rows("international", ACTIVE_NEWS_PER_REGION_LIMIT)
    )
    keep_ids = [row.id for row in keep_rows]

    if len(keep_ids) < max_rows:
        remaining_query = DiseaseNews.query.filter_by(is_active=True)
        if keep_ids:
            remaining_query = remaining_query.filter(DiseaseNews.id.notin_(keep_ids))

        remaining = (
            remaining_query
            .order_by(
                DiseaseNews.trend_score.desc(),
                has_image.desc(),
                DiseaseNews.published_at.desc(),
                DiseaseNews.fetched_at.desc(),
            )
            .limit(max_rows - len(keep_ids))
            .all()
        )
        keep_ids.extend(row.id for row in remaining)

    keep_ids = keep_ids[:max_rows]
    if not keep_ids:
        return DiseaseNews.query.delete(synchronize_session=False)

    return (
        DiseaseNews.query
        .filter(DiseaseNews.id.notin_(keep_ids))
        .delete(synchronize_session=False)
    )


def _ensure_disease_news_schema() -> None:
    """Additive schema guard for local dev DBs created with db.create_all()."""
    inspector = inspect(db.engine)
    if "disease_news" not in inspector.get_table_names():
        db.create_all()
        return

    columns = {column["name"] for column in inspector.get_columns("disease_news")}
    statements = []
    if "region_scope" not in columns:
        statements.append(
            "ALTER TABLE disease_news "
            "ADD COLUMN region_scope VARCHAR(30) NOT NULL DEFAULT 'international'"
        )
    if "trend_score" not in columns:
        statements.append(
            "ALTER TABLE disease_news "
            "ADD COLUMN trend_score INTEGER DEFAULT 0"
        )
    if "trend_keyword" not in columns:
        statements.append(
            "ALTER TABLE disease_news "
            "ADD COLUMN trend_keyword VARCHAR(200)"
        )
    if "image_url" not in columns:
        statements.append(
            "ALTER TABLE disease_news "
            "ADD COLUMN image_url VARCHAR(1000)"
        )

    if not statements:
        return

    with db.engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _fetch_newsapi(region_scope: str) -> list[dict]:
    api_key = current_app.config.get("NEWS_API_KEY") or ""
    if not api_key:
        logger.info("NewsAPI skipped: NEWS_API_KEY is not configured.")
        return []

    if region_scope == "indonesia":
        query = "Indonesia"
        title_query = NEWSAPI_INDONESIA_QUERY
        country = "Indonesia"
        language = None
    else:
        query = None
        title_query = NEWSAPI_GLOBAL_QUERY
        country = "Global"
        language = "en"

    try:
        params = {
            "apiKey": api_key,
            "qInTitle": title_query,
            "from": (datetime.utcnow() - timedelta(days=2)).date().isoformat(),
            "sortBy": "publishedAt",
            "pageSize": 25,
        }
        if query:
            params["q"] = query
        if language:
            params["language"] = language

        resp = requests.get(
            NEWSAPI_EVERYTHING_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "ok":
            logger.warning("NewsAPI %s returned: %s", region_scope, data)
            return []

        results = []
        for article in data.get("articles", [])[:25]:
            source = article.get("source") or {}
            source_name = source.get("name") or "NewsAPI"
            if source_name in BLOCKED_SOURCE_NAMES:
                continue
            item = _build_news_item(
                title=article.get("title") or "",
                summary=article.get("description") or article.get("content") or "",
                source_name=source_name,
                source_url=article.get("url") or "",
                image_url=article.get("urlToImage") or "",
                source_kind="newsapi",
                region_scope=region_scope,
                country=country,
                published_at=_parse_datetime(article.get("publishedAt")),
            )
            if item:
                results.append(item)

        logger.info("NewsAPI %s: fetched %d health items", region_scope, len(results))
        return results
    except Exception as exc:
        logger.warning("NewsAPI %s fetch failed: %s", region_scope, exc)
        return []


def _fetch_newsapi_top_headlines(region_scope: str) -> list[dict]:
    api_key = current_app.config.get("NEWS_API_KEY") or ""
    if not api_key:
        logger.info("NewsAPI top-headlines skipped: NEWS_API_KEY is not configured.")
        return []

    country_code = "id" if region_scope == "indonesia" else "us"
    country = "Indonesia" if region_scope == "indonesia" else "Global"

    try:
        resp = requests.get(
            NEWSAPI_TOP_HEADLINES_URL,
            params={
                "apiKey": api_key,
                "country": country_code,
                "category": "health",
                "pageSize": 20,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "ok":
            logger.warning("NewsAPI top-headlines %s returned: %s", region_scope, data)
            return []

        results = []
        for article in data.get("articles", [])[:20]:
            source = article.get("source") or {}
            source_name = source.get("name") or "NewsAPI"
            if source_name in BLOCKED_SOURCE_NAMES:
                continue
            item = _build_news_item(
                title=article.get("title") or "",
                summary=article.get("description") or article.get("content") or "",
                source_name=source_name,
                source_url=article.get("url") or "",
                image_url=article.get("urlToImage") or "",
                source_kind="newsapi_top",
                region_scope=region_scope,
                country=country,
                published_at=_parse_datetime(article.get("publishedAt")),
            )
            if item:
                results.append(item)

        logger.info("NewsAPI top-headlines %s: fetched %d health items", region_scope, len(results))
        return results
    except Exception as exc:
        logger.warning("NewsAPI top-headlines %s fetch failed: %s", region_scope, exc)
        return []


def _fetch_google_news(region_scope: str) -> list[dict]:
    if region_scope == "indonesia":
        query = INDONESIA_NEWS_QUERY
        url = GOOGLE_NEWS_RSS_URL.format(
            query=quote_plus(query), hl="id", gl="ID", ceid="ID:id"
        )
        country = "Indonesia"
    else:
        query = GLOBAL_NEWS_QUERY
        url = GOOGLE_NEWS_RSS_URL.format(
            query=quote_plus(query), hl="en-US", gl="US", ceid="US:en"
        )
        country = "Global"

    try:
        feed = _parse_feed(url)
        results = []
        for entry in feed.entries[:25]:
            raw_title = entry.get("title", "")
            title, source = _split_google_news_title(raw_title)
            summary = entry.get("summary") or entry.get("description") or ""
            item = _build_news_item(
                title=title,
                summary=summary,
                source_name=source,
                source_url=entry.get("link", ""),
                image_url=_entry_image_url(entry),
                source_kind="google_news",
                region_scope=region_scope,
                country=country,
                published_at=_entry_date(entry),
            )
            if item:
                results.append(item)
        logger.info("Google News %s: fetched %d health items", region_scope, len(results))
        return results
    except Exception as exc:
        logger.warning("Google News %s fetch failed: %s", region_scope, exc)
        return []


def _fetch_google_trends(region_scope: str) -> list[dict]:
    geo = "ID" if region_scope == "indonesia" else "US"
    country = "Indonesia" if region_scope == "indonesia" else "Global"
    try:
        feed = _parse_feed(GOOGLE_TRENDS_RSS_URL.format(geo=geo))
        results = []
        for entry in feed.entries[:30]:
            trend_title = (entry.get("title") or "").strip()
            news_title, news_url, news_source = _trend_news_fields(entry)
            summary = entry.get("summary") or entry.get("description") or news_title
            traffic = _parse_traffic(
                entry.get("ht_approx_traffic") or entry.get("approx_traffic")
            )
            title = news_title if news_title else trend_title
            item = _build_news_item(
                title=title,
                summary=f"{trend_title}. {summary}",
                source_name=news_source,
                source_url=news_url or entry.get("link", ""),
                image_url=_entry_image_url(entry),
                source_kind="google_trends",
                region_scope=region_scope,
                country=country,
                published_at=_entry_date(entry),
                trend_keyword=trend_title,
                traffic=traffic,
            )
            if item:
                results.append(item)
        logger.info("Google Trends %s: fetched %d health items", region_scope, len(results))
        return results
    except Exception as exc:
        logger.warning("Google Trends %s fetch failed: %s", region_scope, exc)
        return []


def _fetch_kemenkes_rss() -> list[dict]:
    try:
        feed = _parse_feed(KEMENKES_RSS_URL)
        results = []
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            item = _build_news_item(
                title=title,
                summary=entry.get("summary") or entry.get("description") or "",
                source_name="Kemenkes",
                source_url=entry.get("link", ""),
                image_url=_entry_image_url(entry, KEMENKES_RSS_URL),
                source_kind="kemenkes",
                region_scope="indonesia",
                country="Indonesia",
                published_at=_entry_date(entry),
            )
            if item:
                results.append(item)
        logger.info("Kemenkes RSS: fetched %d items", len(results))
        return results
    except Exception as exc:
        logger.warning("Kemenkes RSS fetch failed: %s", exc)
        return []


def _fetch_who_disease_outbreak_news() -> list[dict]:
    try:
        headers = {
            "User-Agent": "SmartFarmasi-App/1.0 (Educational)",
            "Accept": "application/json",
        }
        resp = requests.get(
            WHO_OUTBREAK_NEWS_URL,
            headers=headers,
            params={"sf_culture": "en"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("value", []) or data.get("data", []) or (data if isinstance(data, list) else [])
        items = sorted(items, key=lambda x: x.get("PublicationDateAndTime", ""), reverse=True)

        results = []
        for item in items[:20]:
            title = item.get("Title") or item.get("title") or ""
            raw_summary = (
                item.get("Summary") or item.get("Overview") or item.get("Assessment")
                or item.get("synopsis") or item.get("body") or ""
            )
            url = item.get("ItemDefaultUrl") or item.get("Url") or item.get("url") or item.get("link") or ""
            image_url = (
                item.get("ThumbnailUrl") or item.get("ImageUrl") or item.get("Image")
                or item.get("thumbnail") or ""
            )
            news_item = _build_news_item(
                title=title,
                summary=raw_summary,
                source_name="WHO",
                source_url=url if url.startswith("http") else f"https://www.who.int{url}",
                image_url=_absolute_url(str(image_url), "https://www.who.int"),
                source_kind="who",
                region_scope="international",
                country=item.get("CountryName") or item.get("country") or "Global",
                disease_name=item.get("DiseaseName") or item.get("disease") or "",
                published_at=_parse_datetime(
                    item.get("PublicationDateAndTime") or item.get("publication_date")
                ),
            )
            if news_item:
                results.append(news_item)
        logger.info("WHO DON: fetched %d items", len(results))
        return results
    except Exception as exc:
        logger.warning("WHO DON fetch failed: %s", exc)
        return []


def _fetch_who_outbreaks() -> list[dict]:
    try:
        headers = {"User-Agent": "SmartFarmasi-App/1.0", "Accept": "application/json"}
        resp = requests.get(
            WHO_OUTBREAKS_URL,
            headers=headers,
            params={"sf_culture": "en"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("value", []) or (data if isinstance(data, list) else [])
        items = sorted(items, key=lambda x: x.get("PublicationDateAndTime", ""), reverse=True)

        results = []
        for item in items[:15]:
            title = item.get("Title") or item.get("title") or ""
            url = item.get("ItemDefaultUrl") or item.get("Url") or item.get("url") or ""
            image_url = (
                item.get("ThumbnailUrl") or item.get("ImageUrl") or item.get("Image")
                or item.get("thumbnail") or ""
            )
            news_item = _build_news_item(
                title=title,
                summary=item.get("Summary") or item.get("body") or "",
                source_name="WHO",
                source_url=url if url.startswith("http") else f"https://www.who.int{url}",
                image_url=_absolute_url(str(image_url), "https://www.who.int"),
                source_kind="who",
                region_scope="international",
                country=item.get("CountryName") or "Global",
                published_at=_parse_datetime(item.get("PublicationDateAndTime")),
            )
            if news_item:
                results.append(news_item)
        logger.info("WHO Outbreaks: fetched %d items", len(results))
        return results
    except Exception as exc:
        logger.warning("WHO Outbreaks fetch failed: %s", exc)
        return []


def _fetch_cdc_rss() -> list[dict]:
    try:
        feed = _parse_feed(CDC_RSS_URL)
        results = []
        for entry in feed.entries[:20]:
            item = _build_news_item(
                title=entry.get("title", ""),
                summary=entry.get("summary") or entry.get("description") or "",
                source_name="CDC",
                source_url=entry.get("link", ""),
                image_url=_entry_image_url(entry),
                source_kind="cdc",
                region_scope="international",
                country="Global",
                published_at=_entry_date(entry),
            )
            if item:
                results.append(item)
        logger.info("CDC RSS: fetched %d items", len(results))
        return results
    except Exception as exc:
        logger.warning("CDC RSS fetch failed: %s", exc)
        return []


def fetch_and_store_disease_news(app=None):
    """Fetch, score, dedupe, and store active health news."""
    ctx = app.app_context() if app else current_app.app_context()
    with ctx:
        _ensure_disease_news_schema()
        logger.info("=== Disease News Refresh Started ===")
        all_items: list[dict] = []

        fetchers = [
            lambda: _fetch_newsapi_top_headlines("indonesia"),
            lambda: _fetch_newsapi("indonesia"),
            lambda: _fetch_google_news("indonesia"),
            lambda: _fetch_google_trends("indonesia"),
            _fetch_kemenkes_rss,
            lambda: _fetch_newsapi_top_headlines("international"),
            lambda: _fetch_newsapi("international"),
            lambda: _fetch_google_news("international"),
            lambda: _fetch_google_trends("international"),
            _fetch_cdc_rss,
            _fetch_who_disease_outbreak_news,
            _fetch_who_outbreaks,
        ]

        for fetcher in fetchers:
            try:
                all_items.extend(fetcher())
            except Exception as exc:
                logger.warning("Fetcher skipped after error: %s", exc)

        all_items = _dedupe_items(all_items)
        if not all_items:
            logger.warning("No news fetched from any source!")
            return 0

        active_items = _select_active_news_items(all_items)
        DiseaseNews.query.update({"is_active": False})

        saved = 0
        now = datetime.utcnow()
        for item in active_items:
            existing = _find_existing_news(item)

            if existing:
                existing.disease_name = item.get("disease_name", existing.disease_name)
                existing.summary = item.get("summary", existing.summary)
                existing.country = item.get("country", existing.country)
                existing.source_name = item.get("source_name", existing.source_name)
                existing.source_url = item.get("source_url", existing.source_url)
                existing.image_url = item.get("image_url", existing.image_url)
                existing.alert_level = item.get("alert_level", existing.alert_level)
                existing.badge = item.get("badge", existing.badge)
                existing.region_scope = item.get("region_scope", existing.region_scope or "international")
                existing.trend_score = item.get("trend_score", existing.trend_score or 0)
                existing.trend_keyword = item.get("trend_keyword", existing.trend_keyword)
                existing.is_trending = bool(item.get("is_trending"))
                existing.published_at = item.get("published_at") or existing.published_at
                existing.fetched_at = now
                existing.is_active = True
                continue

            db.session.add(DiseaseNews(
                title=item["title"],
                disease_name=item.get("disease_name", ""),
                summary=item.get("summary", ""),
                country=item.get("country", ""),
                source_name=item["source_name"],
                source_url=item.get("source_url", ""),
                image_url=item.get("image_url", ""),
                alert_level=item["alert_level"],
                badge=item["badge"],
                region_scope=item.get("region_scope", "international"),
                trend_score=item.get("trend_score", 0),
                trend_keyword=item.get("trend_keyword", ""),
                is_trending=bool(item.get("is_trending")),
                published_at=item.get("published_at"),
                fetched_at=now,
                is_active=True,
            ))
            saved += 1

        db.session.commit()
        deleted = _prune_disease_news_cache()
        db.session.commit()
        logger.info(
            "=== Disease News Refresh Done: %d new, %d active, %d pruned (from %d candidates) ===",
            saved,
            len(active_items),
            deleted,
            len(all_items),
        )
        return saved


def cleanup_inactive_disease_news(
    app=None,
    retention_days: int = 2,
    max_rows: int = ACTIVE_NEWS_TOTAL_LIMIT,
):
    """Keep only the compact active news cache used by Home and Lihat Semua."""
    ctx = app.app_context() if app else current_app.app_context()
    with ctx:
        _ensure_disease_news_schema()
        deleted = _prune_disease_news_cache(max_rows=max_rows)
        db.session.commit()
        logger.info(
            "Disease News cleanup done: %d rows deleted (max_rows=%d, retention=%d days).",
            deleted,
            max_rows,
            retention_days,
        )
        return deleted


def _top_news_for_region(region_scope: str):
    has_image = case(
        (db.and_(DiseaseNews.image_url.isnot(None), DiseaseNews.image_url != ""), 1),
        else_=0,
    )
    return (
        DiseaseNews.query.filter_by(is_active=True, region_scope=region_scope)
        .order_by(
            DiseaseNews.trend_score.desc(),
            has_image.desc(),
            DiseaseNews.published_at.desc(),
            DiseaseNews.fetched_at.desc(),
        )
        .first()
    )


class DiseaseNewsTrendingAPI(Resource):
    """GET /api/disease-news/trending - exactly 2 Home items."""

    def get(self):
        try:
            _ensure_disease_news_schema()
            news = [
                item for item in (
                    _top_news_for_region("indonesia"),
                    _top_news_for_region("international"),
                )
                if item is not None
            ]

            if len(news) < 2:
                try:
                    fetch_and_store_disease_news()
                    news = [
                        item for item in (
                            _top_news_for_region("indonesia"),
                            _top_news_for_region("international"),
                        )
                        if item is not None
                    ]
                except Exception as exc:
                    logger.error("Auto-fetch failed: %s", exc)

            if len(news) < 2:
                seen_ids = {item.id for item in news}
                fallback = (
                    DiseaseNews.query.filter_by(is_active=True)
                    .order_by(
                        DiseaseNews.trend_score.desc(),
                        DiseaseNews.published_at.desc(),
                        DiseaseNews.fetched_at.desc(),
                    )
                    .limit(5)
                    .all()
                )
                for item in fallback:
                    if item.id not in seen_ids:
                        news.append(item)
                        seen_ids.add(item.id)
                    if len(news) == 2:
                        break

            news = news[:2]
            last_updated = max((n.fetched_at for n in news if n.fetched_at), default=None)

            return {
                "success": True,
                "data": [n.to_dict() for n in news],
                "total": len(news),
                "last_updated": last_updated.isoformat() if last_updated else None,
            }, 200
        except Exception as exc:
            logger.error("DiseaseNewsTrendingAPI error: %s", exc)
            return {"success": False, "message": str(exc)}, 500


class DiseaseNewsListAPI(Resource):
    """GET /api/disease-news with filters, pagination, and optional region."""

    def get(self):
        try:
            _ensure_disease_news_schema()
            page = int(request.args.get("page", 1))
            per_page = min(int(request.args.get("per_page", 10)), 50)
            source = request.args.get("source")
            level = request.args.get("alert_level")
            country = request.args.get("country")
            region = request.args.get("region")
            search = request.args.get("search")
            sort = request.args.get("sort", "latest")

            query = DiseaseNews.query.filter_by(is_active=True)

            if source:
                query = query.filter(DiseaseNews.source_name.ilike(f"%{source}%"))
            if level:
                query = query.filter_by(alert_level=level)
            if country:
                query = query.filter(DiseaseNews.country.ilike(f"%{country}%"))
            if region:
                query = query.filter_by(region_scope=region)
            if search:
                like = f"%{search}%"
                query = query.filter(
                    db.or_(
                        DiseaseNews.title.ilike(like),
                        DiseaseNews.summary.ilike(like),
                        DiseaseNews.disease_name.ilike(like),
                        DiseaseNews.trend_keyword.ilike(like),
                    )
                )

            if sort == "trending":
                query = query.order_by(
                    DiseaseNews.trend_score.desc(),
                    DiseaseNews.published_at.desc(),
                    DiseaseNews.fetched_at.desc(),
                )
            else:
                query = query.order_by(
                    DiseaseNews.published_at.desc(),
                    DiseaseNews.trend_score.desc(),
                    DiseaseNews.fetched_at.desc(),
                )

            paginated = query.paginate(page=page, per_page=per_page, error_out=False)

            return {
                "success": True,
                "data": [n.to_dict() for n in paginated.items],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": paginated.total,
                    "pages": paginated.pages,
                    "has_next": paginated.has_next,
                    "has_prev": paginated.has_prev,
                },
            }, 200
        except Exception as exc:
            logger.error("DiseaseNewsListAPI error: %s", exc)
            return {"success": False, "message": str(exc)}, 500


class DiseaseNewsRefreshAPI(Resource):
    """POST /api/disease-news/refresh - manual trigger for demo/testing."""

    def post(self):
        try:
            saved = fetch_and_store_disease_news()
            active_total = DiseaseNews.query.filter_by(is_active=True).count()
            return {
                "success": True,
                "message": (
                    f"Refresh selesai: {active_total} berita aktif tersimpan "
                    f"(limit {ACTIVE_NEWS_TOTAL_LIMIT})."
                ),
                "saved": saved,
                "active_total": active_total,
                "cache_limit": ACTIVE_NEWS_TOTAL_LIMIT,
            }, 200
        except Exception as exc:
            logger.error("DiseaseNewsRefreshAPI error: %s", exc)
            return {"success": False, "message": str(exc)}, 500


class DiseaseNewsImageProxyAPI(Resource):
    """GET /api/disease-news/image?url=... - proxy stored article images."""

    def get(self):
        try:
            _ensure_disease_news_schema()
            image_url = (request.args.get("url") or "").strip()
            parsed = urlparse(image_url)
            if parsed.scheme not in {"http", "https"}:
                return {"success": False, "message": "Invalid image URL."}, 400

            exists = (
                DiseaseNews.query
                .filter(DiseaseNews.image_url == image_url)
                .first()
            )
            if not exists:
                return {"success": False, "message": "Image is not registered."}, 404

            resp = requests.get(
                image_url,
                headers={
                    "User-Agent": "Mozilla/5.0 SmartFarmasi/1.0",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": f"{parsed.scheme}://{parsed.netloc}/",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "image/jpeg")
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"

            return Response(
                resp.content,
                mimetype=content_type,
                headers={"Cache-Control": "public, max-age=3600"},
            )
        except Exception as exc:
            logger.warning("DiseaseNewsImageProxyAPI error: %s", exc)
            return {"success": False, "message": "Image could not be loaded."}, 502


class DiseaseNewsViewAPI(Resource):
    """POST /api/disease-news/<int:news_id>/view
    Increments view_count when a mobile user opens a news article.
    No auth required — public endpoint, fire-and-forget from Flutter.
    """

    def post(self, news_id: int):
        try:
            news = DiseaseNews.query.get(news_id)
            if not news:
                return {"success": False, "message": "News not found"}, 404
            # Atomic increment
            news.view_count = (news.view_count or 0) + 1
            db.session.commit()
            return {"success": True, "view_count": news.view_count}, 200
        except Exception as exc:
            db.session.rollback()
            logger.warning("DiseaseNewsViewAPI error: %s", exc)
            return {"success": False, "message": str(exc)}, 500
