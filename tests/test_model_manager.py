import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yue2_studio import model_manager as mm


class Downloads(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  with patch.object(mm.subprocess,'run',side_effect=OSError):self.manager=mm.ModelManager(self.tmp.name)
  self.data=b'model fixture';self.name='model.gguf'
  self.catalog={'repo':'audio-cpp/Yue2-3B-GGUF','revision':'pinned','files':{self.name:{'size':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest(),'git_oid':None}}}
  self.p=patch.object(mm,'CATALOG',self.catalog);self.p.start();self.addCleanup(self.p.stop)
 def run_download(self,data=None):
  self.manager.transfer.update(status='downloading')
  with patch.object(mm.urllib.request,'urlopen',return_value=io.BytesIO(self.data if data is None else data)) as request:
   self.manager._download([self.name])
  return request
 def test_verified_download_and_reuse(self):
  request=self.run_download();self.assertEqual(self.manager.transfer['status'],'complete')
  self.assertIn('/resolve/pinned/',request.call_args.args[0])
  self.assertEqual((Path(self.tmp.name)/self.name).read_bytes(),self.data)
  self.run_download().assert_not_called()
 def test_corrupt_and_incomplete_never_replace_existing_file(self):
  target=Path(self.tmp.name)/self.name;target.write_bytes(b'old')
  for body in (b'x'*len(self.data),b'partial'):
   self.run_download(body);self.assertEqual(self.manager.transfer['status'],'failed')
   self.assertEqual(target.read_bytes(),b'old');self.assertFalse(target.with_name(self.name+'.studio-part').exists())
 def test_cancellation_keeps_completed_files(self):
  target=Path(self.tmp.name)/self.name;target.write_bytes(self.data)
  self.manager.cancel_event.set();self.run_download()
  self.assertEqual(self.manager.transfer['status'],'cancelled');self.assertEqual(target.read_bytes(),self.data)
 def test_unlisted_selection_and_path_escape_rejected(self):
  with self.assertRaises(ValueError):self.manager.start('../other')
  with self.assertRaises(ValueError):self.manager.target('../outside')
