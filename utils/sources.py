"""Source links and lightweight public-page helpers for the dashboard."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import requests

BOC_VALET_CSV_URL = "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/csv"
BOC_REFERENCE_URL = "https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds/"
QC_PROJECTIONS_URL = "https://338canada.com/quebec/"
QC_SOVEREIGNTY_POLLS_URL = "https://338canada.com/quebec/polls-indy.htm"
QC_RATINGS_URL = "https://www.quebec.ca/en/gouvernement/finances-publiques/portrait-economique-du-quebec/quebecs-credit-ratings"
RBC_BOND_RATES_URL = "https://www.rbcdirectinvesting.com/pricing/gic-bond-rates.html"
EDWARD_JONES_PROVINCIAL_BONDS_URL = "https://www.edwardjones.ca/ca-en/investment-services/investment-products/fixed-income-investments/provincial-bonds"


@dataclass(frozen=True)
class SourceLink:
    """A display-ready source link."""

    label: str
    url: str
    note: str


SOURCE_LINKS: tuple[SourceLink, ...] = (
    SourceLink("Bank of Canada Valet API", BOC_VALET_CSV_URL, "Official automated Government of Canada benchmark-yield feed."),
    SourceLink("Bank of Canada selected bond yields", BOC_REFERENCE_URL, "Reference page for selected Canadian bond yields."),
    SourceLink("338Canada Québec projections", QC_PROJECTIONS_URL, "External political projection reference; not scraped for rendered charts."),
    SourceLink("338Canada Québec sovereignty polling", QC_SOVEREIGNTY_POLLS_URL, "External sovereignty-polling reference; not scraped for rendered charts."),
    SourceLink("Québec official credit ratings", QC_RATINGS_URL, "Official Government of Québec ratings page."),
    SourceLink("RBC Direct Investing bond rates", RBC_BOND_RATES_URL, "Optional public dealer snapshot; indicative, partial, and non-authoritative."),
    SourceLink("Edward Jones provincial bonds", EDWARD_JONES_PROVINCIAL_BONDS_URL, "Optional public dealer snapshot; indicative, partial, and non-authoritative."),
)

DEALER_SNAPSHOT_LINKS: tuple[SourceLink, ...] = (
    SOURCE_LINKS[-2],
    SOURCE_LINKS[-1],
)


def fetch_page_text_metadata(url: str, timeout: int = 8) -> dict[str, str]:
    """Fetch simple visible text metadata without relying on rendered charts.

    The helper is intentionally conservative: it only extracts the HTML title and
    meta description, and returns an error field instead of raising when the page
    is unavailable.
    """

    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "qc-risk-dashboard/1.0"})
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"status": "unavailable", "error": str(exc)}

    html = response.text
    title = _first_match(r"<title[^>]*>(.*?)</title>", html)
    description = _first_match(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html)
    return {
        "status": "available",
        "title": _clean_html_text(title),
        "description": _clean_html_text(description),
    }


def fetch_dealer_snapshot(url: str, timeout: int = 8) -> dict[str, object]:
    """Fetch optional dealer-snapshot metadata and best-effort HTML tables.

    Dealer pages are treated only as unstable, partial, non-authoritative spot
    checks. The dashboard must not depend on the shape or availability of these
    pages, so this helper always returns a status dictionary instead of raising.
    """

    metadata = fetch_page_text_metadata(url, timeout=timeout)
    if metadata.get("status") != "available":
        return {"metadata": metadata, "tables": [], "note": "Dealer snapshot unavailable; use manual marks or CSV upload."}

    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "qc-risk-dashboard/1.0"})
        response.raise_for_status()
        tables = pd.read_html(response.text)
    except Exception:
        tables = []

    cleaned = []
    for table in tables[:3]:
        table = table.dropna(how="all").dropna(axis=1, how="all")
        if not table.empty:
            cleaned.append(table.head(20))

    return {
        "metadata": metadata,
        "tables": cleaned,
        "note": "Indicative public snapshot only; not a benchmark history and not used automatically in spread calculations.",
    }


def fetch_quebec_ratings_tables(timeout: int = 10) -> list[pd.DataFrame]:
    """Return simple tables from Québec's official ratings page when parseable.

    If pandas cannot parse a table or the page cannot be reached, an empty list is
    returned so the Streamlit app can fall back to a manual override table.
    """

    try:
        response = requests.get(QC_RATINGS_URL, timeout=timeout, headers={"User-Agent": "qc-risk-dashboard/1.0"})
        response.raise_for_status()
        tables = pd.read_html(response.text)
    except Exception:
        return []

    cleaned: list[pd.DataFrame] = []
    for table in tables:
        if table.empty:
            continue
        table = table.dropna(how="all").dropna(axis=1, how="all")
        if not table.empty:
            cleaned.append(table)
    return cleaned


def source_links_as_markdown(links: Iterable[SourceLink] = SOURCE_LINKS) -> str:
    """Format source links as Markdown bullets."""

    return "\n".join(f"- [{link.label}]({link.url}) — {link.note}" for link in links)


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _clean_html_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()
