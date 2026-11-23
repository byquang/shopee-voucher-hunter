import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

SOURCE_URL = "https://magiamgia.com/shopee/"
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
DAY_HEADING = re.compile(r"\bMã Shopee\b.{0,80}?\bNgày\s+(\d{1,2})[/.](\d{1,2})(?:[/.](\d{4}))?\b", re.I)
DISCOUNT = re.compile(r"(?:giảm\s+\d|freeship|miễn phí vận chuyển|hoàn\s+\d.*xu)", re.I)
CODE = re.compile(r"[A-Z0-9][A-Z0-9_-]{3,31}", re.I)
SHOPEE_HOSTS = {"shopee.vn", "www.shopee.vn", "s.shopee.vn", "shp.ee"}


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class Voucher:
    category: str
    terms: str
    code: str = ""
    url: str = ""


def shopee_url(value: str) -> str:
    if len(value) > 600 or any(c.isspace() or ord(c) < 32 for c in value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.netloc not in SHOPEE_HOSTS or not parts.path.strip("/"):
            return ""
        if parts.path == "/an_redir":
            origins = parse_qs(parts.query).get("origin_link", [])
            if len(origins) != 1 or urlsplit(origins[0]).netloc not in {"shopee.vn", "www.shopee.vn"}:
                return ""
            if urlsplit(origins[0]).path == "/an_redir":
                return ""
            return shopee_url(origins[0])
    except ValueError:
        return ""
    return value


def parse_vouchers(page: bytes, today: date) -> list[Voucher]:
    soup = BeautifulSoup(page, "html.parser", from_encoding="utf-8")
    stamp = soup.find("meta", property="article:modified_time")
    try:
        modified = datetime.fromisoformat(stamp["content"].replace("Z", "+00:00"))
        if modified.utcoffset() is None:
            raise ValueError
        modified_day = modified.astimezone(VIETNAM).date()
    except (TypeError, ValueError, KeyError):
        raise SourceError("Missing or invalid source update date.") from None

    dated_panels = []
    for title in soup.select(".elementor-tab-title[aria-controls]"):
        match = DAY_HEADING.search(title.get_text(" ", strip=True))
        if match:
            day, month, year = match.groups()
            dated_panels.append((int(day), int(month), int(year) if year else None, title["aria-controls"]))
    if not dated_panels:
        raise SourceError("The source no longer has dated voucher sections.")
    if not today - timedelta(days=1) <= modified_day <= today:
        return []

    vouchers = []
    for day, month, year, panel_id in dated_panels:
        if (day, month, year or today.year) != (today.day, today.month, today.year):
            continue
        panel = soup.find(id=panel_id, class_="elementor-tab-content")
        if panel is None:
            raise SourceError("The source's current voucher section is missing.")
        category, claim = "", ""
        for row in panel.find_all(["p", "li"]):
            copy = row.find(attrs={"data-clipboard-text": True})
            code = copy["data-clipboard-text"].strip().upper() if copy else ""
            code = code if CODE.fullmatch(code) else ""
            links = [link for a in row.find_all("a", href=True) if (link := shopee_url(a["href"]))]
            for a in row.find_all("a", href=True):
                if a.get_text(strip=True).startswith(("http://", "https://")):
                    a.decompose()
            raw = " ".join(row.get_text(" ", strip=True).split())
            if raw.startswith("🔴"):
                category = raw.removeprefix("🔴").strip(" :")[:65]
                claim = links[0] if links else ""
                continue
            if raw.startswith(("📌", "🎁", "📝", "**")) or not DISCOUNT.search(raw):
                continue
            if any(marker in raw.casefold() for marker in ("đã hết hạn", "đã hết lượt")):
                continue
            url = links[0] if links else claim
            if code or url:
                terms = raw.strip("►• :>-")
                vouchers.append(Voucher(category, terms[:220], code, url))
    return vouchers
