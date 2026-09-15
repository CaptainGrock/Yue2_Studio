"""Catch a test environment accidentally importing a different/live engine."""
from pathlib import Path
import yue2.pipeline


def test_installed_pipeline_matches_shipped_overlay():
    shipped=Path(__file__).resolve().parents[1]/'src/yue2/pipeline.py'
    installed=Path(yue2.pipeline.__file__)
    assert installed.read_text(encoding='utf-8')==shipped.read_text(encoding='utf-8'), (
        'Run install_studio.py into an isolated supported YuE2 checkout first, '
        'then put that checkout/src on PYTHONPATH before running these tests.')
