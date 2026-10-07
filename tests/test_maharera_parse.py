"""Tests for the deterministic MahaRERA parsers.

The HTML below is small hand-written markup that exercises the generic extraction rules
(RERA-number anchoring, label/value pairs, pager links). It is NOT a copy of a real
MahaRERA page: no live results/detail page could be captured during development.
Add real saved pages under tests/fixtures/maharera/ once the crawler has fetched some.
"""
import unittest

from scrapers.maharera import parse

LISTING = """
<div class="views-row project-card"><h4>Sea Breeze Phase 2</h4>
  <p>P51800012345</p><p>ABC Developers LLP</p><p>Boisar, Palghar</p>
  <a href="/public/project/view/123">View Details</a></div>
<div class="views-row project-card"><h4>Green Acres</h4>
  <p>PR1170002500999</p><p>Dahanu</p><a href="https://maharerait.example/project/view/9">View</a></div>
<ul class="pager"><li class="pager__item--next"><a href="?page=1">Next</a></li></ul>
"""

DETAIL = """
<table>
  <tr><th>Project Name</th><td>Sea Breeze Phase 2</td></tr>
  <tr><th>Registration Number</th><td>P51800012345</td></tr>
  <tr><th>Promoter Name</th><td>ABC Developers LLP</td></tr>
  <tr><th>Taluka</th><td>Palghar</td><th>Village</th><td>Boisar</td></tr>
  <tr><th>Pin Code</th><td>401 501 / 401501</td></tr>
  <tr><th>Survey / CTS Number</th><td>12/3, 14</td></tr>
  <tr><th>Total Land Area (sq mtrs)</th><td>4,250.50</td></tr>
  <tr><th>Proposed Date of Completion</th><td>31/12/2025</td></tr>
  <tr><th>Revised Proposed Date of Completion</th><td>30-06-2027</td></tr>
  <tr><th>Total Number of Apartments</th><td>120</td></tr>
  <tr><th>Booked Apartments</th><td>48</td></tr>
  <tr><th>Project Status</th><td>Registered</td></tr>
</table>
<dl><dt>Date of Registration</dt><dd>15th March 2022</dd></dl>
"""


class PrimitiveTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse.parse_date("31/12/2025"), "2025-12-31")
        self.assertEqual(parse.parse_date("15th March 2022"), "2022-03-15")
        self.assertEqual(parse.parse_date("2024-06-19T10:00:00.000Z"), "2024-06-19")
        self.assertIsNone(parse.parse_date("soon"))
        self.assertIsNone(parse.parse_date("NA"))

    def test_numbers(self):
        self.assertEqual(parse.parse_float("4,250.50 sq m"), 4250.5)
        self.assertEqual(parse.parse_int("120"), 120)
        self.assertIsNone(parse.parse_int("12.5"))
        self.assertEqual(parse.parse_pincode("Palghar 401404"), "401404")

    def test_rera_numbers(self):
        self.assertEqual(parse.find_rera_no("Reg: P51800012345 dated"), "P51800012345")
        self.assertEqual(parse.find_rera_no("PR1170002500999"), "PR1170002500999")
        self.assertIsNone(parse.find_rera_no("no number here"))


class ListingTests(unittest.TestCase):
    def test_rows_anchor_on_rera_numbers(self):
        rows = parse.parse_listing(LISTING, "https://www.maharera.maharashtra.gov.in/projects-search-result")
        self.assertEqual([r["rera_no"] for r in rows], ["P51800012345", "PR1170002500999"])
        self.assertEqual(rows[0]["project_name"], "Sea Breeze Phase 2")
        self.assertEqual(rows[0]["detail_url"], "https://www.maharera.maharashtra.gov.in/public/project/view/123")
        self.assertIn("Boisar", rows[0]["extra"]["listing_text"])

    def test_next_page(self):
        url = parse.next_page_url(LISTING, "https://www.maharera.maharashtra.gov.in/projects-search-result?x=1")
        self.assertEqual(url, "https://www.maharera.maharashtra.gov.in/projects-search-result?page=1")
        self.assertIsNone(parse.next_page_url("<p>last page</p>", "https://x.example/"))


class DetailTests(unittest.TestCase):
    def test_fields_from_label_value_pairs(self):
        rec = parse.parse_detail(DETAIL, "https://example/view/123")
        self.assertEqual(set(rec), set(parse.PROJECT_KEYS))
        self.assertEqual(rec["rera_no"], "P51800012345")
        self.assertEqual(rec["project_name"], "Sea Breeze Phase 2")
        self.assertEqual(rec["promoter"], "ABC Developers LLP")
        self.assertEqual((rec["taluka"], rec["village"]), ("Palghar", "Boisar"))
        self.assertEqual(rec["pincode"], "401501")
        self.assertEqual(rec["survey_numbers"], "12/3, 14")
        self.assertEqual(rec["land_area_sqm"], 4250.5)
        self.assertEqual(rec["proposed_completion_date"], "2025-12-31")
        self.assertEqual(rec["revised_completion_date"], "2027-06-30")
        self.assertEqual((rec["total_units"], rec["booked_units"]), (120, 48))
        self.assertEqual(rec["registration_date"], "2022-03-15")
        self.assertEqual(rec["status"], "Registered")

    def test_unknown_fields_stay_empty(self):
        rec = parse.parse_detail("<p>Nothing useful</p>")
        self.assertIsNone(rec["rera_no"])
        self.assertIsNone(rec["registration_date"])


if __name__ == "__main__":
    unittest.main()
