import unittest
from yue2_studio.lifetime import BrowserLifetime

class LifetimeTests(unittest.TestCase):
    def test_last_tab_grace_reload_and_active_work(self):
        now=[0];life=BrowserLifetime(clock=lambda:now[0])
        self.assertFalse(life.should_stop(False))
        life.opened('a');life.opened('b');life.closed('a');now[0]=30
        self.assertFalse(life.should_stop(False))
        life.closed('b');now[0]=40
        self.assertFalse(life.should_stop(False))
        life.opened('reload');now[0]=60
        self.assertFalse(life.should_stop(False))
        life.closed('reload');now[0]=76
        self.assertFalse(life.should_stop(True))
        self.assertTrue(life.should_stop(False))
