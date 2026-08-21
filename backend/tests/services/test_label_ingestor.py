"""Reading a TBA and address off a package label (ADR-246).

The risk this guards is a confident wrong answer. A misread that still *looks*
like a TBA becomes a phantom package; a return address read as the destination
sends a walker to the wrong street. Both are worse than the walker typing it,
so the parser must decline rather than guess — every test here is really about
what it refuses.

Textract is never called: `parse_label_lines` is pure, and LabelIngestor takes
an injected client, the same contract ImageManifestIngestor uses.
"""
import pytest

from app.services.label_ingestor import LabelIngestor, parse_label_lines


def _lines(*texts, conf=99.0):
    return [(t, conf) for t in texts]


class TestTbaExtraction:
    def test_reads_a_plain_tba(self):
        r = parse_label_lines(_lines("TBA303912345447"))
        assert r.tba == "TBA303912345447"

    def test_reads_a_tba_with_ocr_spacing(self):
        """Textract commonly splits a long digit run. Stripping spaces before
        matching is the difference between a read and a manual entry."""
        r = parse_label_lines(_lines("TBA 3039 1234 5447"))
        assert r.tba == "TBA303912345447"

    def test_lowercase_is_normalised(self):
        assert parse_label_lines(_lines("tba303912345447")).tba == "TBA303912345447"

    def test_a_bare_digit_run_is_not_a_tba(self):
        """Barcodes print long digit runs under the label. Requiring the TBA
        prefix keeps those from becoming phantom tracking numbers."""
        r = parse_label_lines(_lines("303912345447", "9821 4410 0293"))
        assert r.tba is None
        assert "no_tba_found" in r.warnings

    def test_too_short_to_be_a_tba_is_rejected(self):
        assert parse_label_lines(_lines("TBA12345")).tba is None

    def test_absurdly_long_digit_run_is_rejected(self):
        """A bounded pattern, so a barcode digit run touching the TBA does not
        get swallowed into one oversized 'tracking number'."""
        assert parse_label_lines(_lines("TBA30391234544712345678")).tba is None


class TestAddressExtraction:
    def test_reads_a_street_line(self):
        r = parse_label_lines(_lines("SHIP TO:", "1 MAIN ST", "NEW YORK NY 10001"))
        assert r.address_line == "1 MAIN ST"

    def test_strips_label_furniture(self):
        r = parse_label_lines(_lines("SHIP TO: 250 W 57TH ST"))
        assert r.address_line == "250 W 57TH ST"

    def test_city_state_zip_is_not_an_address_line(self):
        """No leading house number, so it must not be mistaken for the street."""
        r = parse_label_lines(_lines("NEW YORK NY 10001"))
        assert r.address_line is None
        assert "no_address_found" in r.warnings

    def test_first_street_line_wins(self):
        """Labels put the delivery address above the return address, so
        first-wins matches the physical layout rather than guessing."""
        r = parse_label_lines(_lines("1 MAIN ST", "999 RETURN RD"))
        assert r.address_line == "1 MAIN ST"

    def test_two_candidates_raise_a_warning(self):
        """Picking silently is what sends a package to the return address."""
        r = parse_label_lines(_lines("1 MAIN ST", "999 RETURN RD"))
        assert "more_than_one_address_line" in r.warnings

    def test_the_tba_line_is_not_read_as_an_address(self):
        r = parse_label_lines(_lines("TBA303912345447"))
        assert r.address_line is None

    def test_apartment_suffix_survives(self):
        r = parse_label_lines(_lines("250 W 57TH ST APT 4B"))
        assert r.address_line == "250 W 57TH ST APT 4B"


class TestConfidenceAndFallback:
    def test_confidence_is_scaled_to_a_fraction(self):
        r = parse_label_lines(_lines("TBA303912345447", "1 MAIN ST", conf=90.0))
        assert r.confidence == pytest.approx(0.9, abs=0.01)

    def test_a_complete_read_does_not_need_manual_entry(self):
        r = parse_label_lines(_lines("TBA303912345447", "1 MAIN ST"))
        assert r.needs_manual_entry is False

    def test_a_partial_read_needs_manual_entry(self):
        """Half a label is not a suggestion — the UI must fall back to typing
        rather than pre-filling one field and implying the other was checked."""
        assert parse_label_lines(_lines("TBA303912345447")).needs_manual_entry
        assert parse_label_lines(_lines("1 MAIN ST")).needs_manual_entry

    def test_empty_input_is_handled(self):
        r = parse_label_lines([])
        assert r.needs_manual_entry
        assert r.confidence is None

    def test_all_lines_are_returned_for_manual_pick(self):
        """So the UI can offer 'none of these' without a second Textract call."""
        r = parse_label_lines(_lines("SHIP TO:", "1 MAIN ST", "TBA303912345447"))
        assert r.lines == ["SHIP TO:", "1 MAIN ST", "TBA303912345447"]


class TestTextractBoundary:
    def test_only_line_blocks_are_read(self):
        response = {"Blocks": [
            {"BlockType": "PAGE"},
            {"BlockType": "LINE", "Text": "TBA303912345447", "Confidence": 99.1},
            {"BlockType": "WORD", "Text": "TBA303912345447", "Confidence": 99.1},
            {"BlockType": "LINE", "Text": "", "Confidence": 10.0},
        ]}
        lines = LabelIngestor.extract_lines(response)
        assert lines == [("TBA303912345447", 99.1)]

    def test_read_uses_the_injected_client_and_never_calls_aws(self):
        class Stub:
            def __init__(self):
                self.called_with = None

            def detect_document_text(self, Document):
                self.called_with = Document
                return {"Blocks": [
                    {"BlockType": "LINE", "Text": "TBA303912345447", "Confidence": 98.0},
                    {"BlockType": "LINE", "Text": "1 MAIN ST", "Confidence": 96.0},
                ]}

        stub = Stub()
        result = LabelIngestor(b"fake-bytes", _textract_client=stub).read()

        assert stub.called_with == {"Bytes": b"fake-bytes"}
        assert result.tba == "TBA303912345447"
        assert result.address_line == "1 MAIN ST"
        assert result.needs_manual_entry is False

    def test_a_shaky_address_drags_the_score_down(self):
        """Confidence must average EVERY field returned, not just the TBA.

        A cleanly-read TBA beside a barely-legible street line is exactly the
        case where a single high number would talk the walker into accepting a
        wrong address.
        """
        r = parse_label_lines([("TBA303912345447", 99.0), ("1 MAIN ST", 51.0)])
        assert r.confidence == pytest.approx(0.75, abs=0.01)

    def test_confidence_reflects_the_address_when_no_tba_was_found(self):
        r = parse_label_lines([("1 MAIN ST", 40.0)])
        assert r.confidence == pytest.approx(0.4, abs=0.01)
