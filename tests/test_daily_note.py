"""Unit tests for daily note creation and Templater resolution (T9)."""
import tempfile
from pathlib import Path

from daily_note import (
    _resolve_template,
    _parse_date,
    ensure_daily_note,
    append_to_section,
)


class TestTemplaterResolution:
    def test_date_format_yyyy_mm_dd(self):
        dt = _parse_date("2026-08-10")
        result = _resolve_template("{{date:YYYY-MM-DD}}", dt, "14:30")
        assert result == "2026-08-10"

    def test_date_format_weekday_portuguese(self):
        dt = _parse_date("2026-08-10")  # Monday
        result = _resolve_template("{{date:dddd}}", dt, "14:30")
        assert result == "segunda-feira"

    def test_date_format_with_bracket_escaping(self):
        dt = _parse_date("2026-08-10")
        result = _resolve_template(
            "{{date:D [de] MMMM [de] YYYY}}", dt, "14:30",
        )
        assert result == "10 de agosto de 2026"

    def test_tp_date_now_offset_minus_one(self):
        dt = _parse_date("2026-08-10")
        result = _resolve_template(
            '<% tp.date.now("YYYY-MM-DD", -1, tp.file.title) %>', dt, "14:30",
        )
        assert result == "2026-08-09"

    def test_tp_date_now_offset_plus_eight(self):
        dt = _parse_date("2026-08-10")
        result = _resolve_template(
            '<% tp.date.now("YYYY-MM-DD", 8, tp.file.title) %>', dt, "14:30",
        )
        assert result == "2026-08-18"

    def test_tp_file_title(self):
        dt = _parse_date("2026-08-10")
        result = _resolve_template("<% tp.file.title %>", dt, "14:30")
        assert result == "2026-08-10"


class TestDailyNote:
    def test_create_daily_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            templates = vault / "_templates"
            templates.mkdir()
            (templates / "generic_daily_note.md").write_text(
                "---\ndate_created: {{date:YYYY-MM-DD}}T{{time:HH:mm}}\n---\n"
                "# Nota Diária: {{date:dddd}}\n"
                "### ✅ Tarefas Registradas\n- [ ]\n\n### 📓 Anotações\n-\n"
            )

            path, created = ensure_daily_note(vault, "2026-08-10", "14:30")
            assert created
            content = path.read_text()
            assert "2026-08-10" in content
            assert "segunda-feira" in content
            assert "### ✅ Tarefas Registradas" in content

            # Second call should not recreate
            path2, created2 = ensure_daily_note(vault, "2026-08-10", "14:30")
            assert not created2
            assert path2 == path

    def test_append_to_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            templates = vault / "_templates"
            templates.mkdir()
            daily = vault / "10 Daily"
            daily.mkdir(parents=True)
            (daily / "2026-08-10.md").write_text(
                "### ✅ Tarefas Registradas\n- [ ]\n\n### 📓 Anotações\n-\n"
            )

            append_to_section(
                vault / "10 Daily" / "2026-08-10.md",
                "### 📓 Anotações",
                ["- Teste de bullet"],
            )

            content = (vault / "10 Daily" / "2026-08-10.md").read_text()
            assert "Teste de bullet" in content

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            import pytest
            with pytest.raises(ValueError, match="YYYY-MM-DD"):
                ensure_daily_note(Path(tmp), "../../../etc/passwd", "14:30")
