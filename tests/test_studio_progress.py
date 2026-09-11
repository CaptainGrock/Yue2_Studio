import unittest
from yue2_studio.progress import read_progress


class ProgressTests(unittest.TestCase):
    def test_known_steps_and_stage_history(self):
        data=read_progress('[YuE2] Starting Loading model: elapsed 0.0s\n[YuE2] Completed Loading model: elapsed 6.5s\n[YuE2] Running Synthesizing audio: 8/32 steps (25%) | elapsed 2.0s','running')
        self.assertEqual(len(data['stages']),2)
        self.assertEqual(data['stages'][0]['status'],'completed')
        self.assertEqual(data['current']['completed'],8)
        self.assertEqual(data['current']['total'],32)

    def test_token_budget_is_not_a_percentage(self):
        data=read_progress('[YuE2] Running Generating song: 482 tokens | 83.6 tokens/s | elapsed 5.8s','running')
        self.assertIsNone(data['current']['total'])
        self.assertEqual(data['current']['tokens_per_second'],83.6)
        self.assertEqual(data['current']['completed'],482)

    def test_failures_cancellation_and_no_output(self):
        for status in ('failed','cancelled','interrupted'):
            data=read_progress('[YuE2] Starting Loading model: elapsed 0.0s\nRuntimeError: failure',status)
            self.assertEqual(data['current']['status'],status)
        self.assertIsNone(read_progress('Waiting for the GPU queue.','queued')['current'])

    def test_limit_reached_is_not_normal_completion(self):
        data=read_progress('[YuE2] Finished (generation limit reached) Generating song: 128 tokens | 83.6 tokens/s | elapsed 1.5s','needs_review')
        self.assertEqual(data['current']['status'],'truncated')

if __name__=='__main__':unittest.main()
