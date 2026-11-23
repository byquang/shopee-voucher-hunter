import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime
from html import escape
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sources import SOURCE_URL, VIETNAM, SourceError, Voucher, parse_vouchers

MAX_PER_ALERT = 10
PAGE_LIMIT = 2 * 1024 * 1024
STATE_PATH = Path("seen.json")
USER_AGENT = "ShopeeVoucherHunter/1.0 (+https://github.com/byquang/shopee-voucher-hunter)"
TIME_PREFIX = re.compile(r"^([0-2]?\dH(?:\d{2})?(?:\s*[-–,]\s*[0-2]?\dH(?:\d{2})?)*)\s*:\s*", re.I)
DISCOUNT_AMOUNT = re.compile(r"\b(?:giảm|hoàn)\s+(\d+(?:[.,]\d+)*\s*(?:%|₫|đ\b|k\b|tr\b|triệu\b))", re.I)


class HuntError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_http(request: Request):
    return build_opener(NoRedirects()).open(request, timeout=20)


def fetch_source() -> bytes:
    try:
        with open_http(Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})) as response:
            page = response.read(PAGE_LIMIT + 1)
    except HTTPError as error:
        raise HuntError(f"Mã Giảm Giá returned HTTP {error.code}.") from None
    except (OSError, HTTPException):
        raise HuntError("Could not reach Mã Giảm Giá.") from None
    if len(page) > PAGE_LIMIT:
        raise HuntError("The source page exceeded the size limit.")
    return page


def telegram_config() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        raise HuntError("Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable delivery.")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise HuntError("Invalid TELEGRAM_BOT_TOKEN format.")
    return token, chat


def send_telegram(token: str, chat: str, message: str) -> None:
    data = json.dumps({
        "chat_id": chat,
        "text": message,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }).encode()
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_http(request) as response:
            result = json.loads(response.read(65_537))
    except HTTPError as error:
        raise HuntError(f"Telegram rejected delivery (HTTP {error.code}). Check bot access and chat ID.") from None
    except (OSError, HTTPException, ValueError):
        raise HuntError("Could not confirm Telegram delivery.") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise HuntError("Telegram did not confirm delivery.")


def offer_key(voucher: Voucher) -> str:
    parts = ["code", voucher.code] if voucher.code else [
        "claim", voucher.category.casefold(), voucher.terms.casefold(), voucher.url
    ]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def read_seen(path: Path, today: date) -> set[str]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        day = date.fromisoformat(content["date"])
        keys = content["offers"]
        if not isinstance(keys, list) or any(
            not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) for key in keys
        ):
            raise ValueError
    except FileNotFoundError:
        return set()
    except (OSError, ValueError, KeyError, TypeError):
        raise HuntError("Could not read voucher alert history; no alert was sent.") from None
    return set(keys) if day == today else set()


def save_seen(path: Path, today: date, keys: set[str]) -> None:
    temporary = path.with_suffix(".json.tmp")
    try:
        data = {"date": today.isoformat(), "offers": sorted(keys)}
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        raise HuntError("Telegram accepted the alert, but history could not be saved.") from None


def format_terms(terms: str) -> str:
    discount = DISCOUNT_AMOUNT.search(terms)
    if not discount:
        return escape(terms)
    start, end = discount.span(1)
    return f"{escape(terms[:start])}<b>{escape(terms[start:end])}</b>{escape(terms[end:])}"


def render_voucher(index: int, voucher: Voucher) -> str:
    category = escape(voucher.category or "Ưu đãi Shopee")
    lines = [f"{index:02d} · <b>{category}</b>"]
    terms = voucher.terms
    schedule = TIME_PREFIX.match(terms)
    if schedule:
        terms = terms[schedule.end():]
    if voucher.code:
        prefix = rf"^{re.escape(voucher.code)}(?:$|[\s:–]+)"
        terms = re.sub(prefix, "", terms, count=1, flags=re.I)
    if terms:
        lines.append(format_terms(terms))
    if voucher.code:
        lines.append(f"Mã: <code>{escape(voucher.code)}</code>")
    links = []
    if schedule:
        links.append(f"<i>Khung giờ: {escape(schedule[1])}</i>")
    if voucher.url:
        links.append(f'<a href="{escape(voucher.url)}">Mở trên Shopee ↗</a>')
    if links:
        lines.append(" · ".join(links))
    return "\n".join(lines)


def render_alert(today: date, vouchers: list[Voucher], *, preview: bool = False) -> str:
    label = "Tin nhắn thử · Mã minh họa không dùng được" if preview else f"{len(vouchers)} ưu đãi mới"
    sections = [f"🛍️ <b>VOUCHER SHOPEE VIỆT NAM</b>\n<i>{today:%d/%m/%Y} · {label}</i>"]
    sections.extend(render_voucher(index, voucher) for index, voucher in enumerate(vouchers, start=1))
    if preview:
        sections.append("<i>Kết nối Telegram thành công.</i>")
    else:
        sections.append(
            f'Nguồn: <a href="{SOURCE_URL}">Mã Giảm Giá</a>\n'
            "<i>Kiểm tra điều kiện và lượt còn lại trên Shopee.</i>"
        )
    return "\n\n".join(sections)


def hunt(path: Path, dry_run: bool) -> None:
    credentials = () if dry_run else telegram_config()
    page = fetch_source()
    today = datetime.now(VIETNAM).date()
    seen = set() if dry_run else read_seen(path, today)
    pending = {}
    for voucher in parse_vouchers(page, today):
        key = offer_key(voucher)
        if key not in seen:
            pending.setdefault(key, voucher)
    if not pending:
        print("No new vouchers in today's source listing.")
        return
    batch = dict(list(pending.items())[:MAX_PER_ALERT])
    alert = render_alert(today, list(batch.values()))
    if dry_run:
        print(alert)
        print(f"Previewed {len(batch)} of {len(pending)} voucher(s).")
    else:
        send_telegram(*credentials, alert)
        save_seen(path, today, seen | batch.keys())
        print(f"Sent {len(batch)} voucher(s); {len(pending) - len(batch)} pending.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check today's Shopee Vietnam vouchers.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview source vouchers without sending or saving.")
    mode.add_argument("--test-telegram", action="store_true", help="Send one labeled preview without hunting.")
    parser.add_argument("--state", type=Path, default=STATE_PATH, help="Alert history path (default: seen.json).")
    args = parser.parse_args()
    try:
        if args.test_telegram:
            today = datetime.now(VIETNAM).date()
            sample = Voucher("Shopee Mall", "12H-18H: Giảm 50K cho đơn từ 199K", "MAVIDU50K", "https://shopee.vn/")
            send_telegram(*telegram_config(), render_alert(today, [sample], preview=True))
            print("Telegram accepted the test message.")
        else:
            hunt(args.state, args.dry_run)
    except (HuntError, SourceError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
