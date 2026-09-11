import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from yue2_studio.settings import defaults
from yue2_studio.gguf import SIDECARS,validate,prepare,run

class GGUFTests(unittest.TestCase):
 def spec(self,root):
  executable=root/'audiocpp_cli.exe';executable.write_bytes(b'test fixture')
  models=root/'models';(models/'sidecars').mkdir(parents=True)
  settings=defaults();settings['runtime']['backend']='audio.cpp'
  settings['gguf'].update(executable=str(executable),model_dir=str(models))
  for name in [settings['gguf']['model_gguf'],settings['gguf']['vae_gguf'],*('sidecars/'+s for s in SIDECARS)]:
   (models/name).write_bytes(b'test fixture')
  return {'settings':settings,'stage':'audio','request':{'lyrics':'[Verse]\nUnicode café "quotes" & stuff\n'*3000,'style':'English, rock','seed':2**63-1,'cot':'melody','abc':'X:1\nK:C\nC4|','cfg_scale':1.2}}
 def test_full_mapping_and_long_unicode_json_seed(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);spec=self.spec(root);out=root/'out';out.mkdir()
   command,config=prepare(spec,out)
   self.assertNotIn(spec['request']['lyrics'],command)
   request=json.loads((out/'audiocpp-request.json').read_text(encoding='utf-8'))[0]
   self.assertEqual(request['text'],spec['request']['lyrics'])
   self.assertEqual(request['options']['seed'],str(2**63-1))
   self.assertEqual(request['options']['num_inference_steps'],'32')
   self.assertEqual(request['options']['cfg_scale'],'1.2')
   for stage in ('abc','semantic'):
    for key,value in spec['settings'][stage].items():self.assertEqual(request['options'][stage+'_'+key],str(value))
   self.assertEqual(Path(request['options']['abc_file']).read_text(),spec['request']['abc'])
   self.assertIn('--batch-merge-audio',command)
   self.assertIn('yue2.model_gguf=yue2-3b-q8_0.gguf',command)
   self.assertIn('offload_ar',config['not_applicable_pytorch_controls'])
 def test_preflight_rejects_missing_assets_and_plan(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);spec=self.spec(root)
   with self.assertRaisesRegex(ValueError,'Plan only'):validate(spec['settings'],'plan')
   (root/'models/sidecars/yue2-qwen.tiktoken').unlink()
   with self.assertRaisesRegex(ValueError,'Missing GGUF'):validate(spec['settings'],'audio')
 def test_worker_writes_playable_flac_and_review_receipt(self):
  import numpy as np
  import soundfile as sf
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);spec=self.spec(root);spec['settings']['runtime']['progress']=False
   path=root/'input.json';path.write_text(json.dumps(spec))
   def cli(command,**kwargs):
    self.assertTrue(kwargs['check']);self.assertNotIn('shell',kwargs)
    sf.write(command[command.index('--out')+1],np.zeros((100,2)),48000)
   with patch('yue2_studio.gguf.subprocess.run',side_effect=cli):run(path)
   info=sf.info(root/'result/audio.flac');self.assertEqual(info.frames,100);self.assertEqual(info.channels,2)
   receipt=json.loads((root/'result/studio_summary.json').read_text());self.assertTrue(receipt['warnings'])
