import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from wireless.console import local_planner

class ReleaseSettingsTests(TestCase):
    def test_clean_checkout_uses_account_default_and_no_keep_awake(self):
        with TemporaryDirectory() as folder, patch.object(local_planner, 'CONFIG', Path(folder)/'missing.json'), patch.dict(os.environ, {}, clear=True):
            cfg=local_planner.settings()
            self.assertEqual(cfg['transport'], 'app_server')
            self.assertIsNone(cfg['model'])
            self.assertFalse(cfg['keep_awake'])
    def test_environment_model_is_explicit(self):
        with TemporaryDirectory() as folder, patch.object(local_planner, 'CONFIG', Path(folder)/'missing.json'), patch.dict(os.environ, {'IPHONE_MODEL':'my-model'}):
            self.assertEqual(local_planner.settings()['model'], 'my-model')
    def test_old_experimental_config_is_rejected(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'planner.json';p.write_text(json.dumps({'provider':'venus'}))
            with patch.object(local_planner, 'CONFIG', p):
                with self.assertRaises(ValueError): local_planner.settings()
