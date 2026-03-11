"""Tests for response parsing and agent action logic."""

from swarm_agent.agent import extract_summary, parse_file_blocks


class TestParseFileBlocks:
    def test_single_file(self):
        response = (
            "Here are the changes:\n\n"
            "```file:src/main.py\n"
            "print('hello')\n"
            "```\n"
        )
        blocks = parse_file_blocks(response)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/main.py"
        assert "print('hello')" in blocks[0][1]

    def test_multiple_files(self):
        response = (
            "```file:src/a.py\n"
            "# file a\n"
            "```\n\n"
            "```file:src/b.py\n"
            "# file b\n"
            "```\n"
        )
        blocks = parse_file_blocks(response)
        assert len(blocks) == 2
        assert blocks[0][0] == "src/a.py"
        assert blocks[1][0] == "src/b.py"

    def test_no_file_blocks(self):
        response = "This looks good, no changes needed.\n\n```python\nx = 1\n```"
        blocks = parse_file_blocks(response)
        assert len(blocks) == 0

    def test_file_with_nested_code_block(self):
        response = (
            "```file:README.md\n"
            "# Hello\n"
            "Some text here\n"
            "```\n"
        )
        blocks = parse_file_blocks(response)
        assert len(blocks) == 1
        assert "# Hello" in blocks[0][1]

    def test_whitespace_in_path(self):
        response = "```file:  src/utils.py  \ncontent\n```"
        blocks = parse_file_blocks(response)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/utils.py"


class TestExtractSummary:
    def test_with_summary_section(self):
        response = (
            "Some analysis.\n\n"
            "## SUMMARY\n"
            "Fix authentication bug in login handler\n"
            "More details here.\n"
        )
        result = extract_summary(response)
        assert result == "Fix authentication bug in login handler"

    def test_with_summary_colon(self):
        response = "# SUMMARY:\nAdd input validation\n"
        result = extract_summary(response)
        assert result == "Add input validation"

    def test_fallback_to_first_line(self):
        response = "The code looks good overall.\n\nNo issues found."
        result = extract_summary(response)
        assert result == "The code looks good overall."

    def test_skips_code_fence_lines(self):
        response = "```python\nx = 1\n```\nActual summary here."
        result = extract_summary(response)
        assert result == "Actual summary here."

    def test_empty_response(self):
        result = extract_summary("")
        assert result == "Agent changes"

    def test_truncates_long_lines(self):
        response = "A" * 200
        result = extract_summary(response)
        assert len(result) <= 120
