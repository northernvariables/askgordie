"""Tests for the markdown-to-voice response shaper."""

from gordie_voice.canadagpt.shaper import ResponseShaper
from gordie_voice.config import ShaperConfig


def make_shaper(**kwargs) -> ResponseShaper:
    return ResponseShaper(ShaperConfig(**kwargs))


class TestStripMarkdown:
    def test_headers(self):
        shaper = make_shaper()
        assert "Prime Minister" in shaper.shape("## Prime Minister")[0]
        assert "#" not in shaper.shape("### Section")[0]

    def test_bold_italic(self):
        shaper = make_shaper()
        result = shaper.shape("The **Prime Minister** is *very* important.")
        assert "**" not in result[0]
        assert "*" not in result[0]
        assert "Prime Minister" in result[0]

    def test_inline_code(self):
        shaper = make_shaper()
        result = shaper.shape("Use the `query` parameter.")
        assert "`" not in result[0]
        assert "query" in result[0]

    def test_links(self):
        shaper = make_shaper()
        result = shaper.shape("See [Parliament](https://parl.ca) for details.")
        assert "Parliament" in result[0]
        assert "https" not in result[0]

    def test_code_blocks_removed(self):
        shaper = make_shaper()
        text = "Before.\n```python\nprint('hi')\n```\nAfter."
        result = " ".join(shaper.shape(text))
        assert "print" not in result
        assert "Before" in result
        assert "After" in result


class TestCitations:
    def test_strip_citations(self):
        shaper = make_shaper(strip_citations=True)
        result = shaper.shape("The bill passed [1] in 2023 [^hansard].")
        joined = " ".join(result)
        assert "[1]" not in joined
        assert "[^hansard]" not in joined

    def test_spoken_citations(self):
        shaper = make_shaper(strip_citations=False)
        result = " ".join(shaper.shape("The bill passed [1] in 2023."))
        assert "source 1" in result


class TestUrls:
    def test_strip_urls(self):
        shaper = make_shaper(strip_urls=True)
        result = " ".join(shaper.shape("Visit https://canadagpt.ca/foo for more."))
        assert "https" not in result
        assert "h-t-t-p" not in result

    def test_keep_urls_as_domains(self):
        shaper = make_shaper(strip_urls=False)
        result = " ".join(shaper.shape("Visit https://canadagpt.ca/foo for more."))
        assert "canadagpt.ca" in result


class TestLists:
    def test_bullet_list(self):
        shaper = make_shaper()
        text = "Key points:\n- First item\n- Second item\n- Third item"
        result = " ".join(shaper.shape(text))
        assert "first" in result.lower()
        assert "second" in result.lower()

    def test_numbered_list(self):
        shaper = make_shaper()
        text = "Steps:\n1. Do this\n2. Then that"
        result = " ".join(shaper.shape(text))
        assert "first" in result.lower()


class TestTruncation:
    def test_long_response_truncated(self):
        shaper = make_shaper(max_response_words=10)
        long_text = " ".join(["word"] * 50)
        result = " ".join(shaper.shape(long_text))
        assert "full details" in result

    def test_short_response_not_truncated(self):
        shaper = make_shaper(max_response_words=400)
        result = " ".join(shaper.shape("Short answer."))
        assert "full details" not in result


class TestSentenceChunking:
    def test_splits_on_periods(self):
        shaper = make_shaper()
        result = shaper.shape("First sentence. Second sentence. Third sentence.")
        assert len(result) == 3

    def test_splits_on_questions(self):
        shaper = make_shaper()
        result = shaper.shape("Is this right? Yes it is.")
        assert len(result) == 2

    def test_empty_input(self):
        shaper = make_shaper()
        result = shaper.shape("")
        assert result == []
