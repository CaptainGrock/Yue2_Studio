"""Library metadata tests: no workers, models, or GPU calls."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from test_studio import payload
from yue2_studio.jobs import JobManager
from yue2_studio.server import StudioServer


class LibraryTests(unittest.TestCase):
    def test_persistence_and_running_job_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(tmp, start=False)
            job = manager.generate(payload())
            key = job['id']
            self.assertFalse(job['starred'])
            directory = manager.directory(key)
            before = (directory/'input.json').read_bytes()
            manager.jobs[key]['status'] = 'running'
            queue_size = manager.queue.qsize()
            updated = manager.set_starred(key, True)
            self.assertTrue(updated['starred'])
            self.assertEqual(updated['status'], 'running')
            self.assertEqual((directory/'input.json').read_bytes(), before)
            self.assertEqual(manager.queue.qsize(), queue_size)
            self.assertIsNone(manager.process)
            saved = json.loads((directory/'job.json').read_text())
            self.assertTrue(saved['starred'])
            self.assertTrue(JobManager(tmp, start=False).jobs[key]['starred'])
            manager.set_starred(key, False)
            self.assertFalse(JobManager(tmp, start=False).jobs[key]['starred'])
            saved.pop('starred')
            saved['status'] = 'complete'
            (directory/'job.json').write_text(json.dumps(saved))
            self.assertFalse(JobManager(tmp, start=False).jobs[key]['starred'])

    def test_invalid_values_and_failed_save_do_not_change_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(tmp, start=False)
            key = manager.generate(payload())['id']
            for value in (1, 0, 'true', None, [], {}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    manager.set_starred(key, value)
            with self.assertRaises(ValueError):
                manager.set_starred('0'*32, True)
            with patch.object(manager, '_persist', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    manager.set_starred(key, True)
            self.assertFalse(manager.jobs[key]['starred'])

    def test_rename_is_durable_and_does_not_touch_render_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(tmp, start=False)
            key = manager.generate(payload())['id']
            directory = manager.directory(key)
            before = (directory/'input.json').read_bytes()
            manager.jobs[key]['status'] = 'running'
            manager.set_starred(key, True)
            renamed = manager.rename(key, '  New song 🎵  ')
            self.assertEqual(renamed['title'], 'New song 🎵')
            self.assertEqual(renamed['status'], 'running')
            self.assertTrue(renamed['starred'])
            self.assertEqual((directory/'input.json').read_bytes(), before)
            self.assertEqual(JobManager(tmp, start=False).jobs[key]['title'], 'New song 🎵')
            for title in ('', '   ', 'x'*181, None, 123, True, []):
                with self.subTest(title=title), self.assertRaises(ValueError):
                    manager.rename(key, title)
            with patch.object(manager, '_persist', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    manager.rename(key, 'Not saved')
            self.assertEqual(manager.jobs[key]['title'], 'New song 🎵')
            with self.assertRaises(ValueError):
                manager.rename('0'*32, 'Unknown')

    def test_http_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(tmp, start=False)
            key = manager.generate(payload())['id']
            server = StudioServer(('127.0.0.1', 0), manager=manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def post(data, token=True, job_id=key, action='star'):
                    headers = {'Content-Type': 'application/json'}
                    if token:
                        headers['X-Studio-Token'] = server.token
                    request = Request(f'http://127.0.0.1:{server.server_port}/api/jobs/{job_id}/{action}',
                                      data=json.dumps(data).encode(), headers=headers)
                    try:
                        response = urlopen(request)
                    except HTTPError as error:
                        response = error
                    with response:
                        return response.status, json.load(response)
                status, result = post({'starred': True})
                self.assertEqual(status, 200)
                self.assertTrue(result['starred'])
                self.assertFalse(post({'starred': False})[1]['starred'])
                self.assertEqual(post({'starred': True}, token=False)[0], 403)
                for data in ({}, {'starred': 1}, {'starred': True, 'title': 'Unwanted edit'}):
                    self.assertEqual(post(data)[0], 400)
                self.assertEqual(post({'starred': True}, job_id='0'*32)[0], 400)
                status, result = post({'title': 'New title'}, action='rename')
                self.assertEqual(status, 200)
                self.assertEqual(result['title'], 'New title')
                self.assertEqual(post({'title': 'Name'}, token=False, action='rename')[0], 403)
                for data in ({}, {'title': ''}, {'title': 1}, {'title': 'x'*181}, {'title': 'Name', 'starred': True}):
                    self.assertEqual(post(data, action='rename')[0], 400)
                self.assertEqual(post({'title': 'Name'}, job_id='0'*32, action='rename')[0], 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
