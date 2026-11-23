import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import hunter
from sources import SourceError, Voucher, parse_vouchers, shopee_url

TODAY = date(2026, 11, 23)
STAMP = "2026-11-22T17:10:00+00:00"


def section(title, id_, rows):
    return f"""
        <div class="elementor-tab-title" aria-controls="{id_}">
          <a class="elementor-toggle-title">{title}</a>
        </div>
        <div id="{id_}" class="elementor-tab-content elementor-clearfix">{rows}</div>
    """


CURRENT = section("79+ Mã Shopee Ngày 23/11", "current", """
    <p>🔴 SHOPEE VIP:
      <a href="https://s.shopee.vn/an_redir?origin_link=https%3A%2F%2Fshopee.vn%2Fm%2Fvip%23123">https://shp.ee/abc</a>
    </p>
    <p>► 9H-12H: Lưu banner mã giảm 25% tối đa 200K</p>
    <p>📌 List áp dụng mã giảm 30% <a href="https://shp.ee/list">Áp dụng</a></p>
    <p>🔴 MÃ MALL:</p>
    <p>► <span data-clipboard-text="MALL50K">MALL50K</span> giảm 50K đơn từ 199K</p>
    <p>► <span data-clipboard-text=EXPIRED50>EXPIRED50</span> giảm 50K (đã hết lượt)</p>
    <p>► Mã giảm 99% <a href="https://shopee.vn.evil.example/m/x">Link</a></p>
    <p>► Mở hộp quà để nhận xu <a href="https://shp.ee/game">Link</a></p>
""")
OLD = section("Mã Shopee Từ 9H-21H Ngày 22.11", "old",
              "<p><span data-clipboard-text=YESTERDAY>YESTERDAY</span> giảm 90%</p>")
PAGE = (
    f'<meta property="article:modified_time" content="{STAMP}">'
    f'<div class="elementor-widget-toggle" data-id="7a6eca0">{CURRENT}</div>'
    f'<div class="elementor-widget-toggle" data-id="archived">{OLD}</div>'
).encode()
EXPECTED = [
    Voucher("SHOPEE VIP", "9H-12H: Lưu banner mã giảm 25% tối đa 200K", url="https://shopee.vn/m/vip#123"),
    Voucher("MÃ MALL", "MALL50K giảm 50K đơn từ 199K", code="MALL50K"),
]


class SourceTests(unittest.TestCase):
    def test_only_current_codes_and_claim_links(self):
        self.assertEqual(parse_vouchers(PAGE, TODAY), EXPECTED)

    def test_stale_page_or_prior_year_produces_no_alerts(self):
        self.assertEqual(parse_vouchers(PAGE, date(2027, 11, 23)), [])
        self.assertEqual(parse_vouchers(PAGE.replace(b"23/11", b"23/11/2025"), TODAY), [])

    def test_same_day_and_month_in_archive_never_contributes(self):
        self.assertEqual(parse_vouchers(PAGE.replace(b"22.11", b"23.11"), TODAY), EXPECTED)
        only_archive_matches = PAGE.replace(b"23/11", b"22/11").replace(b"22.11", b"23.11")
        self.assertEqual(parse_vouchers(only_archive_matches, TODAY), [])

    def test_source_layout_error_is_not_reported_as_an_empty_listing(self):
        with self.assertRaises(SourceError):
            parse_vouchers(b"<title>Access denied</title>", TODAY)
        with self.assertRaises(SourceError):
            parse_vouchers(PAGE.replace(b'id="current"', b'id="wrong"'), TODAY)

    def test_disallow_untrusted_or_malformed_claim_urls(self):
        for url in (
            "http://shopee.vn/m/offer",
            "https://shopee.vn@evil.example/m/offer",
            "https://s.shopee.vn/an_redir?origin_link=https://evil.example/m/offer",
            "https://s.shopee.vn/an_redir?origin_link=https://shopee.vn/an_redir",
            "https://shopee.vn/m/bad\nurl",
        ):
            with self.subTest(url=url):
                self.assertEqual(shopee_url(url), "")


class TelegramTests(unittest.TestCase):
    def test_send_uses_json_and_validates_the_response(self):
        with patch("hunter.open_http", return_value=io.BytesIO(b'{"ok":true}')) as open_http:
            hunter.send_telegram("123:fake", "-10042", "<b>Test</b>")
        request = open_http.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.telegram.org/bot123:fake/sendMessage")
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data)["chat_id"], "-10042")
        with patch("hunter.open_http", return_value=io.BytesIO(b'{"ok":false}')):
            with self.assertRaises(hunter.HuntError):
                hunter.send_telegram("123:fake", "-10042", "Test")

    def test_failed_request_does_not_log_secret(self):
        error = HTTPError("https://api.telegram.org/bot123:fake/sendMessage", 403, "Forbidden", {}, None)
        with patch("hunter.open_http", side_effect=error):
            with self.assertRaises(hunter.HuntError) as result:
                hunter.send_telegram("123:fake", "-10042", "Test")
        self.assertNotIn("123:fake", str(result.exception))

    def test_alert_escapes_source_html(self):
        message = hunter.render_alert(TODAY, [Voucher("<VIP>", "A & B", "CODE42", "https://shopee.vn/m/v?a=1&b=2")])
        self.assertIn("&lt;VIP&gt;", message)
        self.assertIn("<code>CODE42</code>", message)
        self.assertIn("A &amp; B", message)
        self.assertIn("?a=1&amp;b=2", message)

    def test_alert_separates_savings_code_hours_and_claim_link(self):
        voucher = Voucher("Mall", "9H-12H: mall50k giảm 50K đơn từ 199K", "MALL50K", "https://shp.ee/mall")
        message = hunter.render_alert(TODAY, [voucher, EXPECTED[0]])
        self.assertIn("23/11/2026 · 2 ưu đãi mới", message)
        self.assertIn(
            '01 · <b>Mall</b>\ngiảm <b>50K</b> đơn từ 199K\nMã: <code>MALL50K</code>\n'
            '<i>Khung giờ: 9H-12H</i> · <a href="https://shp.ee/mall">Mở trên Shopee ↗</a>',
            message,
        )
        self.assertIn("02 · <b>SHOPEE VIP</b>", message)
        self.assertIn("giảm <b>25%</b>", message)
        self.assertNotIn("Mã: <code></code>", message)

    def test_telegram_preview_is_clearly_marked_as_a_sample(self):
        message = hunter.render_alert(TODAY, EXPECTED, preview=True)
        self.assertIn("Tin nhắn thử · Mã minh họa không dùng được", message)
        self.assertIn("Kết nối Telegram thành công.", message)
        self.assertNotIn("ưu đãi mới", message)
        self.assertNotIn("Nguồn:", message)


@patch("hunter.fetch_source", return_value=PAGE)
@patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123:fake", "TELEGRAM_CHAT_ID": "-10042"})
class HuntTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        directory = stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "seen.json"
        now = stack.enter_context(patch("hunter.datetime"))
        now.now.return_value.date.return_value = TODAY
        self.sender = stack.enter_context(patch("hunter.send_telegram"))
        stack.enter_context(redirect_stdout(io.StringIO()))

    def test_send_persists_and_next_run_suppresses_same_day_duplicates(self, _fetch):
        hunter.hunt(self.path, dry_run=False)
        hunter.hunt(self.path, dry_run=False)
        self.sender.assert_called_once()
        self.assertEqual(hunter.read_seen(self.path, TODAY), {hunter.offer_key(v) for v in EXPECTED})
        self.assertEqual(hunter.read_seen(self.path, date(2026, 11, 24)), set())

    def test_dry_run_never_sends_or_writes(self, _fetch):
        hunter.hunt(self.path, dry_run=True)
        self.sender.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_failed_delivery_is_not_marked_seen(self, _fetch):
        self.sender.side_effect = hunter.HuntError("delivery failed")
        with self.assertRaises(hunter.HuntError):
            hunter.hunt(self.path, dry_run=False)
        self.assertFalse(self.path.exists())

    def test_remaining_offers_are_sent_next_run(self, _fetch):
        with patch("hunter.MAX_PER_ALERT", 1):
            hunter.hunt(self.path, dry_run=False)
            hunter.hunt(self.path, dry_run=False)
            hunter.hunt(self.path, dry_run=False)
        self.assertEqual(self.sender.call_count, 2)

    def test_invalid_history_fails_closed(self, _fetch):
        self.path.write_text('{"date":"2026-11-23","offers":"not a list"}')
        with self.assertRaises(hunter.HuntError):
            hunter.hunt(self.path, dry_run=False)
        self.sender.assert_not_called()
