"""Studio contract tests run without model loads, API credentials, or extra packages."""
from copy import deepcopy
from dataclasses import fields
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from yue2.protocol import GenerationConfig,Sampling
from yue2_studio.settings import defaults,validate_settings
from yue2_studio.jobs import JobManager,generation_spec,is_cuda_oom,oom_retry_spec,score_check
from yue2_studio.server import StudioServer
from yue2_studio import llm

ABC='X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=120\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nV: Ins clef=treble name="Ins Melody" snm="Inst."\nK:C\n% verse\nV: Vocal\n"C"C8D8E8G8|\nV: Ins\nZ|\n'


def payload():
    return {'title':'Test song','request':{'style':'English, piano pop','lyrics':'[Verse]\nA small original test','seed':831001},'settings':defaults()}


class CompatibilityTests(unittest.TestCase):
    def test_fallback_preserves_every_other_setting(self):
        from yue2_studio.compatibility import compatible_runtime
        runtime=defaults()['runtime'];runtime.update(backend='torch',device='cuda:0',memory_budget_gib=30)
        original=deepcopy(runtime)
        effective,note=compatible_runtime(runtime,False)
        self.assertEqual(effective,original)
        self.assertEqual(runtime,original)
        self.assertEqual(note['requested_backend'],'torch')
        for backend,device,flash in [('torch','cuda',True),('torch','cpu',False),('torch-eager','cuda',False)]:
            runtime.update(backend=backend,device=device)
            self.assertEqual(compatible_runtime(runtime,flash),(runtime,None))

    def test_worker_applies_fallback_and_records_it(self):
        from yue2_studio.worker import run
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            spec=generation_spec(payload());spec['settings']['runtime']['backend']='torch'
            path=Path(tmp)/'input.json';path.write_text(json.dumps(spec))
            pipeline=MagicMock()
            with patch('yue2.YuE2Pipeline.from_pretrained',pipeline), patch('yue2_studio.worker.capabilities',return_value={'flash_attention':False}):
                run(path)
            args=pipeline.call_args.kwargs
            self.assertEqual(args['backend'],'torch')
            self.assertEqual(args['generation_config'].to_dict(),GenerationConfig.from_dict({k:spec['settings'][k] for k in ('abc','semantic')}|{'ode_steps':spec['settings']['generation']['ode_steps']}).to_dict())
            self.assertTrue((Path(tmp)/'runtime_adjustments.json').is_file())
            self.assertEqual(json.loads(path.read_text())['settings']['runtime']['backend'],'torch')

    def test_old_failed_log_has_useful_error_and_path(self):
        from yue2_studio.jobs import failure_summary
        self.assertEqual(failure_summary('Traceback\nValueError: bad score',1),'ValueError: bad score')
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);job=manager.generate(payload())
            manager.jobs[job['id']]['status']='failed'
            log=manager.directory(job['id'])/'run.log'
            log.write_text('RuntimeError: USE_FLASH_ATTENTION was not enabled for build.')
            detail=manager.detail(job['id'])
            self.assertIn('CUDA graphs',detail['error'])
            self.assertEqual(detail['log_path'],str(log))


class SettingsTests(unittest.TestCase):
    def test_sampling_schema_has_every_native_field_and_default(self):
        config=GenerationConfig().to_dict()
        for stage in ('abc','semantic'):
            self.assertEqual(defaults()[stage],config[stage])
            self.assertEqual(set(defaults()[stage]),{f.name for f in fields(Sampling)})

    def test_invalid_ranges_types_unknown_fields(self):
        for group,key,value in [('abc','min_tokens',5000),('semantic','temperature',float('nan')),('runtime','offload_ar','false'),('generation','ode_steps',True),('transcription','threads',0),('runtime','mystery',1)]:
            with self.subTest(key=key),self.assertRaises((ValueError,TypeError)):
                validate_settings({group:{key:value}})

    def test_cover_rejects_missing_score_and_chorded_melody(self):
        p=payload();p['mode']='cover'
        with self.assertRaisesRegex(ValueError,'reviewed ABC'):
            generation_spec(p)
        p['request'].update(abc=ABC,cot='melody')
        with self.assertRaisesRegex(ValueError,'contains chords'):
            generation_spec(p)
        p['request']['abc']=score_check(ABC,True)['abc']
        self.assertEqual(generation_spec(p)['request']['cot'],'melody')

    def test_score_strip_preserves_both_voices_and_header(self):
        source=ABC.replace('Z|','E32|')
        prepared=score_check(source,True)
        self.assertIn('name="Vocal Melody"',prepared['abc'])
        self.assertEqual(prepared['report']['voices']['Ins']['sounding_notes'],1)
        self.assertEqual(prepared['report']['voices']['Vocal']['sounding_notes'],4)
        self.assertEqual(prepared['report']['voices']['Vocal']['chords'],[])

    def test_direct_audio_rejects_score_or_plan(self):
        p=payload();p['request']['cot']='off';p['stage']='plan'
        with self.assertRaises(ValueError):generation_spec(p)
        p['stage']='audio';p['request']['abc']=ABC
        with self.assertRaises(ValueError):generation_spec(p)

    def test_no_secrets_or_shell_fields_in_run_inputs(self):
        for key in ('connection','api_key','command'):
            p=payload();p[key]='SECRET'
            with self.assertRaises(ValueError):generation_spec(p)

    def test_full_seed_range_without_browser_rounding(self):
        p=payload();p['request']['seed']='9223372036854775807'
        self.assertEqual(generation_spec(p)['request']['seed'],2**63-1)
        p['request']['seed']='9223372036854775808'
        with self.assertRaises(ValueError):generation_spec(p)

    def test_transcription_overlap_constraints(self):
        with self.assertRaisesRegex(ValueError,'lookahead'):
            validate_settings({'transcription':{'overlap_seconds':50}})
        with self.assertRaisesRegex(ValueError,'paper'):
            validate_settings({'transcription':{'preset':'paper','overlap_seconds':200}})


class FakeLLM(BaseHTTPRequestHandler):
    requests=[]
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"local-song-model"}]}')
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append((self.path,body))
        draft=json.dumps({'title':'Test draft','lyrics':'[Verse]\nA new line','style':'English, piano','notes':'Reviewed phrasing.'})
        self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'choices':[{'message':{'content':draft},'finish_reason':'stop'}]}).encode())


class LLMTests(unittest.TestCase):
    def test_url_normalization(self):
        for value in ('http://localhost:8000','http://localhost:8000/v1/','http://localhost:8000/v1/chat/completions'):
            self.assertEqual(llm.api_root(value),'http://localhost:8000/v1')
        for value in ('file:///x','https://user:key@host','https://host?key=secret'):
            with self.assertRaises(ValueError):llm.api_root(value)

    def test_live_custom_model_discovery_and_structured_draft(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),FakeLLM)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            connection={'provider':'own_server','base_url':f'http://127.0.0.1:{server.server_port}','model':'local-song-model'}
            self.assertEqual(llm.models(connection)['models'],['local-song-model'])
            result=llm.assist({'connection':connection,'brief':'An original song about home'})
            self.assertEqual(result['draft']['title'],'Test draft')
            path,body=FakeLLM.requests[-1]
            self.assertEqual(path,'/v1/chat/completions')
            self.assertIn('YUE2 NATIVE FORMAT',body['messages'][0]['content'])
            self.assertEqual(body['max_tokens'],4096)
        finally:server.shutdown();server.server_close();thread.join()

    def test_provider_payloads_and_output_parsers(self):
        cases=[('openai',{'output':[{'type':'message','content':[{'type':'output_text','text':'OK'}]}],'status':'completed'},'max_output_tokens'),
               ('anthropic',{'content':[{'type':'text','text':'OK'}],'stop_reason':'end_turn'},'max_tokens'),
               ('google',{'candidates':[{'content':{'parts':[{'text':'hidden','thought':True},{'text':'OK'}]},'finishReason':'STOP'}]},None),
               ('ollama',{'message':{'content':'OK'},'done_reason':'stop'},None),
               ('lm_studio',{'output':[{'type':'message','content':'OK'}]},'max_output_tokens')]
        for provider,response,token_field in cases:
            with self.subTest(provider=provider),patch.object(llm,'request_json',return_value=response) as call:
                result=llm.complete({'provider':provider,'api_key':'SECRET','model':'test-model','max_tokens':8192},'system','user')
                self.assertEqual(result['text'],'OK')
                body=call.call_args.args[2]
                if token_field:self.assertEqual(body[token_field],8192)
                if provider=='google':self.assertEqual(body['generationConfig']['maxOutputTokens'],8192)
                if provider=='ollama':self.assertEqual(body['options']['num_predict'],8192);self.assertEqual(body['keep_alive'],0)
                self.assertNotIn('temperature',body)

    def test_malformed_response_preserved_without_applying(self):
        with patch.object(llm,'complete',return_value={'text':'incomplete output','truncated':True}):
            result=llm.assist({'brief':'write something'})
            self.assertIsNone(result['draft']);self.assertIn('warning',result)

    def test_key_not_reflected_in_provider_error(self):
        from io import BytesIO
        error=urllib.error.HTTPError('http://example.invalid',401,'bad',{},BytesIO(b'{"error":{"message":"Invalid key SECRET"}}'))
        with patch('urllib.request.OpenerDirector.open',side_effect=error):
            with self.assertRaises(ValueError) as ctx:
                llm.models({'provider':'openai','api_key':'SECRET'})
            self.assertNotIn('SECRET',str(ctx.exception))


class QueueTests(unittest.TestCase):
    def test_oom_retry_memory_policy_preserves_song(self):
        spec=generation_spec(payload());original=deepcopy(spec)
        retry,info=oom_retry_spec(spec)
        self.assertEqual(retry['request'],original['request'])
        self.assertEqual(spec,original)
        self.assertTrue(retry['settings']['runtime']['offload_ar'])
        self.assertTrue(info['offload_ar'])
        artist=deepcopy(spec);artist['lora']={'kind':'artist'}
        artist_retry,artist_info=oom_retry_spec(artist)
        self.assertFalse(artist_retry['settings']['runtime']['offload_ar'])
        self.assertTrue(artist_info['artist_lora'])
        self.assertTrue(is_cuda_oom('torch.OutOfMemoryError: CUDA out of memory'))
        self.assertFalse(is_cuda_oom('ValueError: bad score'))

    def test_generation_oom_retries_once_in_fresh_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);job=manager.generate(payload());calls=[]
            original=(manager.directory(job['id'])/'input.json').read_bytes()
            class Process:
                def __init__(self,command,**kwargs):
                    self.number=len(calls)+1;calls.append((command,kwargs['env']))
                    kwargs['stdout'].write('torch.OutOfMemoryError: CUDA out of memory\n' if self.number==1 else 'Studio: artifacts saved.\n')
                    kwargs['stdout'].flush()
                    if self.number==1:
                        result=Path(command[-1]).parent/'result';result.mkdir();(result/'partial.tmp').write_text('incomplete')
                def wait(self):return 1 if self.number==1 else 0
                def poll(self):return 1 if self.number==1 else 0
            with patch('yue2_studio.jobs.subprocess.Popen',Process):
                manager.thread.start();manager.queue.join();manager.close()
            saved=manager.jobs[job['id']]
            retry=json.loads((manager.directory(job['id'])/'retry-input.json').read_text())
            self.assertEqual(len(calls),2)
            self.assertEqual(saved['status'],'complete')
            self.assertTrue(saved['auto_retry']['succeeded'])
            self.assertTrue(retry['settings']['runtime']['offload_ar'])
            self.assertEqual(retry['request'],json.loads(original)['request'])
            self.assertEqual((manager.directory(job['id'])/'input.json').read_bytes(),original)
            self.assertTrue((manager.directory(job['id'])/'run.attempt-1.log').is_file())
            self.assertEqual(calls[1][1]['PYTORCH_CUDA_ALLOC_CONF'],'expandable_segments:True')

    def test_second_generation_oom_is_classified_for_popup(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);job=manager.generate(payload());calls=[]
            class Process:
                def __init__(self,command,**kwargs):
                    calls.append(command);kwargs['stdout'].write('torch.OutOfMemoryError: CUDA out of memory\n');kwargs['stdout'].flush()
                def wait(self):return 1
                def poll(self):return 1
            with patch('yue2_studio.jobs.subprocess.Popen',Process):
                manager.thread.start();manager.queue.join();manager.close()
            saved=manager.jobs[job['id']]
            self.assertEqual(len(calls),2)
            self.assertEqual(saved['status'],'failed')
            self.assertEqual(saved['failure_kind'],'cuda_oom')
            self.assertTrue(saved['auto_retry']['exhausted'])
            self.assertIn('automatically retried',saved['error'])
            self.assertIn('automatically retried',manager.detail(job['id'])['error'])

    def test_oom_popup_contract_is_present(self):
        index=(ROOT/'src/yue2_studio/static/index.html').read_text()
        script=(ROOT/'src/yue2_studio/static/app.js').read_text()
        self.assertIn('id="oomDialog"',index)
        self.assertIn("job.failure_kind==='cuda_oom'",script)
        self.assertIn('Artist LoRA must keep AR offloading disabled',script)

    def test_serial_execution_and_cancelled_queue_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False)
            events=[]
            class Process:
                def __init__(self,*args,**kwargs):events.append('start')
                def wait(self):time.sleep(.02);events.append('end');return 0
                def poll(self):return 0
            first=manager.generate(payload());second=manager.generate(payload());third=manager.generate(payload())
            manager.cancel(second['id'])
            with patch('yue2_studio.jobs.subprocess.Popen',Process):
                manager.thread.start();manager.queue.join();manager.close()
            self.assertEqual(events,['start','end','start','end'])
            self.assertEqual(manager.jobs[second['id']]['status'],'cancelled')
            self.assertEqual(manager.jobs[first['id']]['status'],'complete')
            self.assertNotEqual(first['id'],third['id'])

    def test_running_worker_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);started=threading.Event();stopped=threading.Event()
            class Process:
                def __init__(self,*args,**kwargs):started.set()
                def wait(self):stopped.wait(3);return -15
                def poll(self):return None if not stopped.is_set() else -15
                def terminate(self):stopped.set()
            with patch('yue2_studio.jobs.subprocess.Popen',Process):
                job=manager.generate(payload());manager.thread.start();self.assertTrue(started.wait(2));manager.cancel(job['id']);manager.queue.join();manager.close()
            self.assertEqual(manager.jobs[job['id']]['status'],'cancelled')

    def test_restart_does_not_silently_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);job=manager.generate(payload())
            reopened=JobManager(tmp,start=False)
            self.assertEqual(reopened.jobs[job['id']]['status'],'interrupted')

    def test_library_backend_metadata_and_safe_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);job=manager.generate(payload());job_id=job['id']
            self.assertEqual(job['backend'],'torch')
            manager.jobs[job_id]['status']='cancelled';manager._persist(manager.jobs[job_id])
            with patch('yue2_studio.jobs.shutil.rmtree',side_effect=OSError('busy')):
                with self.assertRaises(OSError):manager.delete(job_id)
            self.assertIn(job_id,manager.jobs)
            result=manager.delete(job_id)
            self.assertEqual(result['deleted'],job_id)
            self.assertNotIn(job_id,manager.jobs)
            self.assertFalse((Path(tmp)/job_id).exists())

    def test_old_generation_loads_backend_from_saved_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);job=manager.generate(payload());job_id=job['id']
            job_path=manager.directory(job_id)/'job.json'
            saved=json.loads(job_path.read_text());saved.pop('backend');job_path.write_text(json.dumps(saved))
            input_path=manager.directory(job_id)/'input.json'
            saved_input=json.loads(input_path.read_text());saved_input['settings']['runtime']['backend']='audio.cpp';input_path.write_text(json.dumps(saved_input))
            reopened=JobManager(tmp,start=False)
            self.assertEqual(reopened.jobs[job_id]['backend'],'audio.cpp')

    def test_worker_command_uses_argument_array_and_separate_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False)
            p=payload();p['settings']['runtime']['model']='folder with spaces & symbols'
            job=manager.generate(p)
            command=manager._command(job['id'],generation_spec(p))
            self.assertEqual(command[:4],[sys.executable,'-u','-m','yue2_studio.worker'])
            self.assertEqual(json.loads((manager.directory(job['id'])/'input.json').read_text())['settings']['runtime']['model'],'folder with spaces & symbols')

    def test_browser_run_details_preserve_large_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(tmp,start=False);p=payload();p['request']['seed']=str(2**63-1)
            job=manager.generate(p)
            self.assertEqual(manager.detail(job['id'])['input']['request']['seed'],'9223372036854775807')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.manager=JobManager(self.tmp.name,start=False)
        self.server=StudioServer(('127.0.0.1',0),self.manager)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,data=None,headers=None):
        hdr={'Content-Type':'application/json','X-Studio-Token':self.server.token};hdr.update(headers or {})
        return urllib.request.urlopen(urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers=hdr))
    def test_bootstrap_and_fractional_score_report(self):
        with self.request('/api/bootstrap') as response:self.assertIn('groups',json.load(response))
        with self.request('/api/score',{'abc':ABC,'strip':True}) as response:
            data=json.load(response);self.assertEqual(data['report']['bpm'],120)
    def test_csrf_and_cross_origin_rejected(self):
        for headers in ({'X-Studio-Token':''},{'Origin':'https://evil.invalid'},{'Host':'evil.invalid'}):
            with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/api/generate',payload(),headers)
            self.assertEqual(ctx.exception.code,403)
    def test_job_errors_dont_enter_queue(self):
        p=payload();p['mode']='cover'
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/generate',p)
        self.assertEqual(self.manager.list(),[])
    def test_retry_preserves_saved_song_without_llm(self):
        original=self.manager.generate(payload());job_id=original['id']
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/jobs/'+job_id+'/retry',{})
        self.manager.jobs[job_id]['status']='failed'
        before=(self.manager.directory(job_id)/'input.json').read_bytes()
        with patch('yue2_studio.llm.assist',side_effect=AssertionError('Retry must not call LLM')):
            with self.request('/api/jobs/'+job_id+'/retry',{}) as response:
                self.assertEqual(response.status,202);new=json.load(response)
        spec=self.manager.detail(new['id'])['input']
        self.assertEqual(spec['request'],self.manager.detail(job_id)['input']['request'])
        self.assertEqual(spec['settings'],self.manager.detail(job_id)['input']['settings'])
        self.assertEqual(spec['source_job'],job_id)
        self.assertEqual((self.manager.directory(job_id)/'input.json').read_bytes(),before)

    def test_artifact_range_and_traversal(self):
        job=self.manager.generate(payload());directory=self.manager.directory(job['id']);(directory/'test.wav').write_bytes(b'0123456789')
        with self.request('/artifacts/'+job['id']+'/test.wav',headers={'Range':'bytes=2-5'}) as response:
            self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345')
        with self.assertRaises(urllib.error.HTTPError):self.request('/artifacts/'+job['id']+'/%2e%2e/%2e%2e/private.txt')


if __name__=='__main__':unittest.main()
