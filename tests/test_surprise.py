"""Auto-song batch orchestration without paid APIs or GPU loads."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from yue2_studio.jobs import JobManager
from yue2_studio.surprise import SurpriseManager


def options(**values):
    return {'count':5,'voice':'female','style':'Acoustic soul','language':'English',
            'connection':{'provider':'own_server','model':'test-model','api_key':'TEST-SECRET'},**values}


class SurpriseTests(unittest.TestCase):
    def test_five_distinct_songs_sequential_with_constraints_and_no_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=JobManager(tmp,start=False);manager=SurpriseManager(jobs,threading.Lock())
            events=[];inputs=[]
            def assist(payload):
                self.assertFalse(any(j['status']=='running' for j in jobs.list()))
                events.append('write');inputs.append(payload)
                n=len(inputs)
                return {'draft':{'title':f'Song {n}','lyrics':f'[Verse]\nOriginal words {n}','style':'warm guitar','notes':'test'},'truncated':False}
            original=jobs.generate
            def generate(payload):
                events.append('render')
                result=original(payload)
                jobs.jobs[result['id']]['status']='complete'
                return result
            with patch('yue2_studio.surprise.llm.assist',side_effect=assist),patch.object(jobs,'generate',side_effect=generate):
                record=manager.start(options());manager.threads[record['id']].join(5)
            batch=manager.list()[0]
            self.assertEqual(batch['status'],'complete');self.assertEqual(len(batch['songs']),5)
            self.assertEqual(events,['write','render']*5)
            seeds=[]
            for job in jobs.list():
                spec=json.loads((jobs.directory(job['id'])/'input.json').read_text())
                self.assertTrue(spec['request']['style'].startswith('Female lead vocal.'))
                seeds.append(spec['request']['seed'])
            self.assertEqual(len(set(seeds)),5)
            self.assertIn('Acoustic soul',inputs[0]['brief'])
            self.assertIn('Song 1',inputs[1]['brief'])
            for path in Path(tmp).rglob('*.json'):
                self.assertNotIn('TEST-SECRET',path.read_text())

    def test_stop_during_writing_discards_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=JobManager(tmp,start=False);manager=SurpriseManager(jobs,threading.Lock())
            started=threading.Event();release=threading.Event()
            def assist(_):
                started.set();release.wait(3)
                return {'draft':{'title':'Discard me','lyrics':'[Verse]\nWords','style':'pop','notes':''}}
            with patch('yue2_studio.surprise.llm.assist',side_effect=assist):
                batch=manager.start(options());self.assertTrue(started.wait(2))
                manager.cancel(batch['id']);release.set();manager.threads[batch['id']].join(3)
            self.assertEqual(manager.list()[0]['status'],'cancelled');self.assertEqual(jobs.list(),[])

    def test_required_profanity_checks_sung_words_before_render(self):
        from yue2_studio.surprise import profanity_count
        self.assertEqual(profanity_count('[fuck shit bitch]\nA dark mood, f**k, bullshitake'),0)
        self.assertEqual(profanity_count('[Verse]\nFuck this fucking bullshit'),3)
        for lyrics,accepted in [('[Verse]\nDark but clean words',False),('[Verse]\nFuck this fucking bullshit',True)]:
            with self.subTest(accepted=accepted),tempfile.TemporaryDirectory() as tmp:
                jobs=JobManager(tmp,start=False);manager=SurpriseManager(jobs,threading.Lock())
                draft={'title':'Test','lyrics':lyrics,'style':'rock','notes':''}
                def generate(payload):
                    result=original(payload)
                    jobs.jobs[result['id']]['status']='complete'
                    return result
                original=jobs.generate
                with patch('yue2_studio.surprise.llm.assist',return_value={'draft':draft}) as assist,patch.object(jobs,'generate',side_effect=generate):
                    batch=manager.start(options(count=1,profanity='required'))
                    manager.threads[batch['id']].join(3)
                self.assertEqual(bool(jobs.list()),accepted)
                self.assertIn('PROFANITY REQUIREMENT',assist.call_args.args[0]['brief'])
                self.assertEqual(manager.list()[0]['status'],'complete' if accepted else 'failed')

    def test_incomplete_draft_stops_without_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=JobManager(tmp,start=False);manager=SurpriseManager(jobs,threading.Lock())
            with patch('yue2_studio.surprise.llm.assist',return_value={'draft':None,'truncated':True}):
                batch=manager.start(options());manager.threads[batch['id']].join(3)
            self.assertEqual(manager.list()[0]['status'],'failed');self.assertEqual(jobs.list(),[])

    def test_next_song_waits_for_render_and_failure_stops_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=JobManager(tmp,start=False);manager=SurpriseManager(jobs,threading.Lock())
            submitted=threading.Event();calls=[]
            def assist(_):
                calls.append(1)
                return {'draft':{'title':'One','lyrics':'[Verse]\nOne new song','style':'pop','notes':''}}
            original=jobs.generate
            def generate(payload):
                result=original(payload);submitted.set();return result
            with patch('yue2_studio.surprise.llm.assist',side_effect=assist),patch.object(jobs,'generate',side_effect=generate):
                batch=manager.start(options());self.assertTrue(submitted.wait(2))
                self.assertEqual(len(calls),1)
                with jobs.lock:
                    next(iter(jobs.jobs.values()))['status']='failed'
                manager.threads[batch['id']].join(3)
            self.assertEqual(len(calls),1);self.assertEqual(manager.list()[0]['status'],'failed')

    def test_invalid_count_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=JobManager(tmp,start=False);manager=SurpriseManager(jobs,threading.Lock())
            for count in (0,51,True,1.5):
                with self.assertRaises(ValueError):manager.start(options(count=count))
            path=manager.root/('a'*32+'.json')
            path.write_text(json.dumps({'id':'a'*32,'status':'writing','created':'2026'}))
            restored=SurpriseManager(jobs,threading.Lock())
            self.assertEqual(restored.list()[0]['status'],'interrupted')


if __name__=='__main__':unittest.main()
