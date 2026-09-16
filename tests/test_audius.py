"""Audius integration contract tests; no network or credentials required."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from yue2_studio.server import audius_config


class AudiusConfigTests(unittest.TestCase):
    def test_disabled_without_public_client_id(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(audius_config(),{'enabled':False,'client_id':''})

    def test_public_client_id_is_trimmed(self):
        with patch.dict(os.environ,{'YUE2_AUDIUS_API_KEY':'  public-app-id  '},clear=True):
            self.assertEqual(audius_config(),{'enabled':True,'client_id':'public-app-id'})

    def test_browser_code_rejects_non_audius_public_links(self):
        source=(ROOT/'src/yue2_studio/static/audius.js').read_text(encoding='utf-8')
        self.assertIn("url.hostname==='audius.co'",source)
        self.assertNotIn('AUDIUS_BEARER',source)
        self.assertNotIn('mainnet-1.',source)


if __name__=='__main__':
    unittest.main()
