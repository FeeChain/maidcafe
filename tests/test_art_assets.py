"""Packaged illustration integrity, requiring no image library at runtime."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ArtAssets(unittest.TestCase):
    def test_complete_cast_and_portable_asset_budget(self):
        assets = json.loads((ROOT / 'static/cafe/artwork-prompts.json').read_text())['assets']
        self.assertEqual(len(assets), 23)
        self.assertLess(sum(a['bytes'] for a in assets), 8 * 1024 * 1024)
        for name in ('haruka', 'momo', 'shizuku', 'suzu', 'aoi'):
            self.assertIn('static/cafe/cast/' + name + '-full-v3.webp', [a['file'] for a in assets])
            self.assertIn('static/cafe/avatars/' + name + '-avatar-v3.webp', [a['file'] for a in assets])
            self.assertIn('static/cafe/hidden/' + name + '-hidden-v3.webp', [a['file'] for a in assets])
        for asset in assets:
            with self.subTest(asset=asset['id']):
                data = (ROOT / asset['file']).read_bytes()
                self.assertEqual(data[:4], b'RIFF')
                self.assertEqual(data[8:12], b'WEBP')
                self.assertEqual(len(data), asset['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), asset['sha256'])
                self.assertTrue(asset['prompt'])


if __name__ == '__main__':
    unittest.main()
