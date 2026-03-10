from __future__ import annotations

from html import unescape
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET

from ..models import Job


def _strip_html(text: str) -> str:
    """Remove basic HTML tags from RSS descriptions."""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _child_text(element: ET.Element, tag_name: str, default: str = "") -> str:
    """Safely get child text from an XML element."""
    child = element.find(tag_name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _infer_company_from_title(title: str) -> tuple[str, str]:
    """
    Try to split common title formats such as:

    - 'Python Developer at ExampleCo'
    - 'ExampleCo: Python Developer'

    Returns:
        (company, role_title)

    If no pattern is found, return ('unknown', original_title).
    """
    title = unescape(title).strip()

    # Format: "Role at Company"
    match = re.match(r"^(.*?)\s+at\s+(.*?)$", title, flags=re.IGNORECASE)
    if match:
        role = match.group(1).strip()
        company = match.group(2).strip()
        return company, role

    # Format: "Company: Role"
    if ":" in title:
        left, right = title.split(":", 1)
        company = left.strip()
        role = right.strip()
        if company and role:
            return company, role

    return "unknown", title


def _infer_company_from_remoteok_url(url: str) -> str:
    """
    Try to infer a company name from a RemoteOK-style URL slug.

    Example:
      https://remoteok.com/remote-jobs/remote-senior-enterprise-middleware-engineer-spry-methods-1130072
      -> 'Spry Methods'
    """
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").split("/")[-1]

    if not slug:
        return "unknown"

    # remove trailing numeric id
    slug = re.sub(r"-\d+$", "", slug)

    # remove common RemoteOK prefix
    slug = re.sub(r"^remote-", "", slug)

    parts = slug.split("-")
    if len(parts) < 2:
        return "unknown"

    # Heuristic: take the last 1-3 tokens as company name candidates
    # because the beginning is usually the role title.
    candidates = parts[-3:]

    # Trim common role-ish words from the front of candidate tail
    stopwords = {
        "engineer", "developer", "senior", "junior", "lead", "staff",
        "principal", "backend", "frontend", "full", "stack", "software",
        "devops", "site", "reliability", "data", "qa", "architect",
        "manager", "level", "mid", "midsenior", "job"
    }

    while candidates and candidates[0].lower() in stopwords:
        candidates.pop(0)

    if not candidates:
        return "unknown"

    company = " ".join(word.capitalize() for word in candidates)
    return company or "unknown"


def _infer_company_and_title(raw_title: str, link: str) -> tuple[str, str]:
    """
    Use title first, then fall back to URL-based heuristics for certain sources.
    """
    company, title = _infer_company_from_title(raw_title)

    if company == "unknown" and "remoteok" in link.lower():
        company = _infer_company_from_remoteok_url(link)

    return company, title


def load_jobs_from_rss(url: str) -> Iterable[Job]:
    """
    Load jobs from an RSS feed URL and yield normalized Job objects.
    """
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            )
        },
    )

    with urlopen(request, timeout=20) as response:
        xml_bytes = response.read()

    root = ET.fromstring(xml_bytes)

    channel = root.find("channel")
    if channel is None:
        raise ValueError("Invalid RSS feed: missing channel element")

    for item in channel.findall("item"):
        raw_title = _child_text(item, "title", default="Untitled job")
        link = _child_text(item, "link", default="")
        description = _child_text(item, "description", default="")
        pub_date = _child_text(item, "pubDate", default="")

        company, title = _infer_company_and_title(raw_title, link)
        clean_description = _strip_html(description)

        yield Job(
            source="rss",
            url=link,
            company=company,
            title=title,
            location="unknown",
            posted_date=pub_date or None,
            description=clean_description,
        )