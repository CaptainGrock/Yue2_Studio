"""Track browser connections independently of background-tab timer throttling."""
import threading
import time


class BrowserLifetime:
    def __init__(self, grace=15, clock=time.monotonic):
        self.grace, self.clock = grace, clock
        self.lock = threading.Lock()
        self.clients = set()
        self.empty_since = None
        self.armed = False

    def opened(self, client):
        with self.lock:
            self.armed = True
            self.clients.add(client)
            self.empty_since = None

    def closed(self, client):
        with self.lock:
            self.clients.discard(client)
            if not self.clients and self.empty_since is None:
                self.empty_since = self.clock()

    def should_stop(self, busy):
        with self.lock:
            return (self.armed and not self.clients and not busy and
                    self.empty_since is not None and self.clock()-self.empty_since >= self.grace)
