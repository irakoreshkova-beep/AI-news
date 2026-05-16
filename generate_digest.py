#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

FEEDS = [
    {"name": "OpenAI", "kind": "rss", "url": "https://openai.com/news/rss.xml"},
    {"name": "Anthropic", "kind": "anthropic_newsroom", "url": "https://www.anthropic.com/news"},
    {"name": "Google DeepMind", "kind": "rss", "url": "https://blog.google/technology/ai/rss/"},
    {"name": "TechCrunch AI", "kind": "rss", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "Hugging Face", "kind": "rss", "url": "https://huggingface.co/blog/feed.xml"},
]

OPENAI_API_URL = "https://api.openai.com/v1/responses"
ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_DIR = ROOT / "site" / "data"
ARCHIVE_DIR = SITE_DATA_DIR / "archive"
ARCHIVE_INDEX_FILE = ARCHIVE_DIR / "index.json"


@dataclass
class Config:
    timezone_name: str
    language: str
    max_items: int
    lookback_hours: int
    archive_depth_days: int
    openai_api_key: str
    openai_model: str


@dataclass
class NewsItem:
    source: str
    title: str
    link: str
    published_at: datetime
    snippet: str
    summary: str = ""

    @property
    def fingerprint(self) -> str:
        raw = f"{self.source}|{self.link}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def load_config() -> Config:
    return Config(
        timezone_name=os.getenv("AI_DIGEST_TIMEZONE", "Asia/Tbilisi"),
        language=os.getenv("AI_DIGEST_LANGUAGE", "ru"),
        max_items=env_int("AI_DIGEST_MAX_ITEMS", 12),
        lookback_hours=env_int("AI_DIGEST_LOOKBACK_HOURS", 30),
        archive_depth_days=env_int("AI_DIGEST_ARCHIVE_DEPTH_DAYS", 30),
        openai_api_key=os.getenv("AI_DIGEST_OPENAI_API_KEY", ""),
        openai_model=os.getenv("AI_DIGEST_OPENAI_MODEL", "gpt-4.1-mini"),
    )


def fetch_url(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, method: str = "GET") -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": "ai-brief-pwa/1.0 (+https://openai.com)",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonicalize_link(url: str) -> str:
    if not url.strip():
        return ""
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url.strip()

    filtered_query = urllib.parse.urlencode(
        [
            (key, value)
            for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
        ]
    )
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc.lower(), parts.path.rstrip("/") or "/", filtered_query, "")
    )


def parse_datetime(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def parse_rss_items(source: str, root: ET.Element) -> list[NewsItem]:
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[NewsItem] = []
    for item in channel.findall("item"):
        title = clean_html(item.findtext("title", ""))
        link = canonicalize_link(item.findtext("link", ""))
        snippet = clean_html(item.findtext("description", ""))
        published = parse_datetime(item.findtext("pubDate", ""))
        if title and link:
            items.append(NewsItem(source, title, link, published, snippet))
    return items


def parse_atom_items(source: str, root: ET.Element) -> list[NewsItem]:
    namespace = root.tag.split("}", 1)[0] + "}" if root.tag.startswith("{") else ""
    items: list[NewsItem] = []
    for entry in root.findall(f"{namespace}entry"):
        title = clean_html(entry.findtext(f"{namespace}title", ""))
        snippet = clean_html(entry.findtext(f"{namespace}summary", "") or entry.findtext(f"{namespace}content", ""))
        published = parse_datetime(entry.findtext(f"{namespace}updated", "") or entry.findtext(f"{namespace}published", ""))
        link = ""
        for link_node in entry.findall(f"{namespace}link"):
            href = link_node.attrib.get("href", "")
            rel = link_node.attrib.get("rel", "alternate")
            if href and rel == "alternate":
                link = canonicalize_link(href)
                break
        if title and link:
            items.append(NewsItem(source, title, link, published, snippet))
    return items


def fetch_feed_items(source: str, url: str) -> list[NewsItem]:
    try:
        payload = fetch_url(
            url,
            headers={
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8"
            },
        )
        root = ET.fromstring(payload)
    except (urllib.error.URLError, ET.ParseError) as exc:
        print(f"[warn] Failed to fetch {source}: {exc}", file=sys.stderr)
        return []

    tag = root.tag.lower()
    return parse_rss_items(source, root) if tag.endswith("rss") or tag.endswith("rdf") else parse_atom_items(source, root)


def parse_anthropic_article(article_url: str) -> NewsItem | None:
    try:
        payload = fetch_url(article_url).decode("utf-8", "ignore")
    except urllib.error.URLError as exc:
        print(f"[warn] Failed to fetch Anthropic article {article_url}: {exc}", file=sys.stderr)
        return None

    title_match = re.search(r"<title>(.*?)</title>", payload, re.IGNORECASE | re.DOTALL)
    description_match = re.search(
        r'<meta name="description" content="([^"]+)"', payload, re.IGNORECASE | re.DOTALL
    )
    date_match = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", payload)
    if not title_match or not date_match:
        return None

    title = clean_html(title_match.group(1)).removesuffix(" \\ Anthropic")
    snippet = clean_html(description_match.group(1)) if description_match else ""
    published = datetime.strptime(date_match.group(1), "%b %d, %Y").replace(tzinfo=timezone.utc)
    return NewsItem("Anthropic", title, canonicalize_link(article_url), published, snippet)


def fetch_anthropic_newsroom(url: str) -> list[NewsItem]:
    try:
        payload = fetch_url(url).decode("utf-8", "ignore")
    except urllib.error.URLError as exc:
        print(f"[warn] Failed to fetch Anthropic newsroom: {exc}", file=sys.stderr)
        return []

    seen_links: set[str] = set()
    article_urls: list[str] = []
    for match in re.finditer(r'href="(/news/[^"]+)"', payload):
        link = canonicalize_link(f"https://www.anthropic.com{match.group(1)}")
        if link in seen_links:
            continue
        seen_links.add(link)
        article_urls.append(link)
        if len(article_urls) >= 10:
            break

    items: list[NewsItem] = []
    for article_url in article_urls:
        item = parse_anthropic_article(article_url)
        if item is not None:
            items.append(item)
    return items


def dedupe_items(items: Iterable[NewsItem]) -> list[NewsItem]:
    deduped: dict[str, NewsItem] = {}
    for item in items:
        current = deduped.get(item.link)
        if current is None or item.published_at > current.published_at:
            deduped[item.link] = item
    return sorted(deduped.values(), key=lambda item: item.published_at, reverse=True)


def fallback_summary(item: NewsItem) -> str:
    body = re.sub(r"\s+", " ", item.snippet or item.title).strip()
    if len(body) > 240:
        body = body[:237].rstrip() + "..."
    return body or "Описание в RSS отсутствует."


def extract_response_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def summarize_with_openai(items: list[NewsItem], config: Config) -> bool:
    if not config.openai_api_key or not items:
        return False

    prompt_items = [
        {
            "id": item.fingerprint[:8],
            "source": item.source,
            "title": item.title,
            "snippet": item.snippet[:700],
        }
        for item in items
    ]

    body = json.dumps(
        {
            "model": config.openai_model,
            "instructions": (
                "Ты готовишь очень короткий ежедневный AI-дайджест на русском языке. "
                "Верни строго JSON с массивом summaries. "
                "Для каждой новости переведи или адаптируй заголовок на естественный русский язык, "
                "сохрани смысл без кликбейта. "
                "Также дай одну краткую русскоязычную выжимку, максимум 220 символов."
            ),
            "input": json.dumps(prompt_items, ensure_ascii=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "digest_summaries",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summaries": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "title": {"type": "string"},
                                        "summary": {"type": "string"},
                                    },
                                    "required": ["id", "title", "summary"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["summaries"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                }
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        response_payload = json.loads(
            fetch_url(
                OPENAI_API_URL,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {config.openai_api_key}",
                    "Content-Type": "application/json",
                },
            ).decode("utf-8")
        )
        parsed = json.loads(extract_response_text(response_payload))
        summary_map = {
            entry["id"]: {
                "title": re.sub(r"\s+", " ", entry["title"]).strip(),
                "summary": re.sub(r"\s+", " ", entry["summary"]).strip(),
            }
            for entry in parsed["summaries"]
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] OpenAI summarization failed: {exc}", file=sys.stderr)
        return False

    for item in items:
        localized = summary_map.get(item.fingerprint[:8])
        if not localized:
            continue
        item.title = localized["title"] or item.title
        item.summary = localized["summary"] or ""
    return True


def summarize_items(items: list[NewsItem], config: Config) -> None:
    used_openai = summarize_with_openai(items, config)
    for item in items:
        if not item.summary:
            item.summary = fallback_summary(item)
    print(
        "[info] Summaries generated with OpenAI." if used_openai else "[info] Summaries generated from RSS snippets.",
        file=sys.stderr,
    )


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def load_recent_fingerprints(today_key: str, depth_days: int) -> set[str]:
    index_payload = load_json(ARCHIVE_INDEX_FILE, {"entries": []})
    entries = index_payload.get("entries", [])[:depth_days]
    fingerprints: set[str] = set()

    for entry in entries:
        if entry.get("date") == today_key:
            continue
        archive_payload = load_json(SITE_DATA_DIR / entry["file"], {"items": []})
        for item in archive_payload.get("items", []):
            if item.get("fingerprint"):
                fingerprints.add(item["fingerprint"])
    return fingerprints


def serialize_digest(date_key: str, generated_at: datetime, items: list[NewsItem]) -> dict:
    unique_sources = sorted({item.source for item in items})
    return {
        "date": date_key,
        "generatedAt": generated_at.isoformat(),
        "sources": unique_sources,
        "items": [
            {
                "fingerprint": item.fingerprint,
                "source": item.source,
                "title": item.title,
                "link": item.link,
                "publishedAt": item.published_at.isoformat(),
                "summary": item.summary,
            }
            for item in items
        ],
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_archive_index(date_key: str, count: int) -> None:
    payload = load_json(ARCHIVE_INDEX_FILE, {"entries": []})
    file_path = f"data/archive/{date_key}.json"
    entries = [entry for entry in payload.get("entries", []) if entry.get("date") != date_key]
    entries.insert(0, {"date": date_key, "file": file_path, "count": count})
    write_json(ARCHIVE_INDEX_FILE, {"entries": entries[:90]})


def collect_items(config: Config, now_utc: datetime, today_key: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for feed in FEEDS:
        if feed["kind"] == "rss":
            items.extend(fetch_feed_items(feed["name"], feed["url"]))
            continue
        if feed["kind"] == "anthropic_newsroom":
            items.extend(fetch_anthropic_newsroom(feed["url"]))

    cutoff = now_utc - timedelta(hours=config.lookback_hours)
    seen_recently = load_recent_fingerprints(today_key, config.archive_depth_days)
    deduped = dedupe_items(items)
    fresh = [
        item
        for item in deduped
        if item.published_at >= cutoff and item.fingerprint not in seen_recently
    ]
    return fresh[: config.max_items]


def main() -> None:
    config = load_config()
    now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(ZoneInfo(config.timezone_name))
    today_key = local_now.strftime("%Y-%m-%d")

    items = collect_items(config, now_utc, today_key)
    summarize_items(items, config)

    payload = serialize_digest(today_key, now_utc, items)
    latest_path = SITE_DATA_DIR / "latest.json"
    archive_path = ARCHIVE_DIR / f"{today_key}.json"
    write_json(latest_path, payload)
    write_json(archive_path, payload)
    update_archive_index(today_key, len(items))
    print(f"[info] Wrote {len(items)} items for {today_key}.", file=sys.stderr)


if __name__ == "__main__":
    main()
