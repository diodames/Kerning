import fcntl
import os
import tempfile
import threading
import time
import unittest

from kerning_fetch import fetch_lock, lock_is_stale


class FetchLockTests(unittest.TestCase):
    def test_lock_is_stale_when_mtime_is_old(self):
        fd, path = tempfile.mkstemp(prefix="kerning-lock-")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        os.utime(path, (0, time.time() - 400))
        self.assertTrue(lock_is_stale(path, ttl=280))

    def test_second_fetch_steals_stale_lock_without_hanging(self):
        fd, path = tempfile.mkstemp(prefix="kerning-lock-")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        holder = open(path, "a+")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.utime(path, (time.time() - 400, time.time() - 400))

        acquired = []

        def take():
            with fetch_lock(ttl=1, path=path, poll=0.01):
                acquired.append(True)

        t = threading.Thread(target=take)
        t.start()
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(acquired, [True])


if __name__ == "__main__":
    unittest.main()
