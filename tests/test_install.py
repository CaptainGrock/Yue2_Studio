import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('installer',Path(__file__).resolve().parents[1]/'install_studio.py')
installer=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(installer)

class InstallTests(unittest.TestCase):
 def kit(self,root):
  (root/'src/yue2').mkdir(parents=True)
  (root/'src/yue2/pipeline.py').write_text((installer.REPO/'src/yue2/pipeline.py').read_text(encoding='utf-8'),encoding='utf-8')
  (root/'pyproject.toml').write_text('[project]\nname = "yue2-infer"\nversion = "0.1.6"')
 def test_install_backup_idempotence_and_check(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.kit(root)
   old=root/'src/yue2/cuda_graph.py';old.write_text('# original')
   self.assertGreater(installer.install(root,True),0)
   self.assertEqual(old.read_text(),'# original')
   with patch.object(installer.socket,'create_connection',side_effect=OSError):
    self.assertGreater(installer.install(root),0)
    self.assertEqual(installer.install(root),0)
   backups=list((root/'.studio-backups').rglob('cuda_graph.py'))
   self.assertEqual(len(backups),1)
   self.assertEqual(backups[0].read_text(),'# original')
   self.assertTrue((root/'src/yue2_studio/static/app.js').is_file())
   self.assertFalse((root/'models').exists())
   self.assertTrue((root/'src/yue2/lora.py').is_file())
   self.assertTrue((root/'src/yue2_studio/training_worker.py').is_file())
   self.assertTrue((root/'src/yue2_studio/static/trainer.js').is_file())
   self.assertTrue((root/'src/yue2/artist_lora.py').is_file())
   self.assertTrue((root/'src/yue2_studio/static/artist.js').is_file())
   self.assertTrue((root/'docs/artist-trainer.md').is_file())

 def test_custom_artist_adapter_is_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.kit(root)
   adapter=root/'src/yue2/artist_lora.py';adapter.write_text('# custom Artist implementation')
   with self.assertRaisesRegex(ValueError,'artist_lora.py'):installer.install(root)
   self.assertEqual(adapter.read_text(),'# custom Artist implementation')

 def test_custom_engine_is_never_overwritten(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.kit(root)
   pipeline=root/'src/yue2/pipeline.py';pipeline.write_text('# custom engine')
   with self.assertRaisesRegex(ValueError,'differs'):installer.install(root)
   self.assertEqual(pipeline.read_text(),'# custom engine')
   self.assertFalse((root/'src/yue2_studio').exists())
 def test_invalid_layout_and_version(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   with self.assertRaises(ValueError):installer.install(root)
   self.kit(root);(root/'pyproject.toml').write_text('name="yue2-infer"\nversion="0.0.1"')
   with self.assertRaises(ValueError):installer.install(root)

 def test_active_server_prevents_changes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.kit(root)
   from unittest.mock import MagicMock
   with patch.object(installer.socket,'create_connection',return_value=MagicMock()):
    with self.assertRaisesRegex(ValueError,'Port 7862'):installer.install(root)
   self.assertFalse((root/'launch_studio.py').exists())
