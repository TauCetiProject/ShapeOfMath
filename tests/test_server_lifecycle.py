"""Exercise server management with real processes and isolated checkouts."""
from contextlib import closing
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen

import mathdb_server as server


@unittest.skipUnless(Path('/proc/self/cmdline').exists(), 'management requires Linux')
class ServerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.checkout = self.copy_checkout('project')
        self.processes = []
        self.log = tempfile.TemporaryFile(mode='w+')

    def copy_checkout(self, name):
        target = self.root / name
        target.mkdir()
        for name in ('mathdb_server.py', 'mathdb.py', 'schema.sql'):
            shutil.copyfile(Path(server.__file__).parent / name, target / name)
        (target / 'web').mkdir()
        (target / 'web/index.html').write_text('test server')
        return target

    def tearDown(self):
        # Stop supervisors before cleaning up any remaining workers.
        for process, cwd, port in self.processes:
            subprocess.run([sys.executable, 'mathdb_server.py', 'stop', '--port', str(port)],
                           cwd=cwd, stdout=self.log, stderr=self.log, timeout=15)
        for process, _, _ in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
        self.log.close()
        self.temp.cleanup()

    def port(self):
        with closing(socket.socket()) as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def launch(self, port, *args, cwd=None):
        cwd = cwd or self.checkout
        process = subprocess.Popen([sys.executable, 'mathdb_server.py', *args, '--port', str(port)],
                                   cwd=cwd, stdout=self.log, stderr=self.log)
        self.processes.append((process, cwd, port))
        return process

    def command(self, port, action, cwd=None):
        return subprocess.run([sys.executable, 'mathdb_server.py', action, '--port', str(port)],
                              cwd=cwd or self.checkout, capture_output=True, text=True, timeout=15)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.log.seek(0)
        self.fail('Timed out waiting for server:\n' + self.log.read())

    def responds(self, port, version=None):
        try:
            with urlopen(f'http://127.0.0.1:{port}/', timeout=0.5) as response:
                return response.status == 200 and (version is None or
                       response.headers['Server'].startswith(f'ShapeOfMath/{version} '))
        except (URLError, TimeoutError, ConnectionError):
            return False

    def test_restart_adopts_existing_server_and_preserves_other_port(self):
        port, other_port = self.port(), self.port()
        old = self.launch(port)
        other = self.launch(other_port)
        self.wait_for(lambda: self.responds(port) and self.responds(other_port))
        self.assertIn('running', self.command(port, 'status').stdout)
        replacement = self.launch(port, 'restart', '--reload')
        self.wait_for(lambda: old.poll() is not None and self.responds(port))
        self.assertIsNone(replacement.poll())
        self.assertIsNone(other.poll())
        self.assertEqual(self.command(port, 'stop').returncode, 0)
        replacement.wait(timeout=10)
        self.assertFalse(self.responds(port))
        self.assertTrue(self.responds(other_port))
        self.assertIn('stopped', self.command(port, 'status').stdout)

    def test_restart_refuses_server_in_another_checkout(self):
        port = self.port()
        other = self.launch(port, cwd=self.copy_checkout('other-project'))
        self.wait_for(lambda: self.responds(port))
        result = self.command(port, 'restart')
        self.assertEqual(result.returncode, 1)
        self.assertIn('already in use', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIsNone(other.poll())
        self.assertTrue(self.responds(port))

    def test_reload_reads_fresh_source_and_recovers_from_syntax_error(self):
        port = self.port()
        watcher = self.launch(port, '--reload')
        self.wait_for(lambda: self.responds(port, '1.0'))
        path = self.checkout / 'mathdb_server.py'
        original = path.read_text()
        stat = path.stat()
        path.write_text(original.replace("server_version='ShapeOfMath/1.0'",
                                         "server_version='ShapeOfMath/2.0'"))
        # Same size, same timestamp second: normal .pyc validation can miss this.
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        self.wait_for(lambda: self.responds(port, '2.0'))
        path.write_text('def broken(:\n')
        self.wait_for(lambda: not self.responds(port))
        self.assertIsNone(watcher.poll())
        path.write_text(original.replace("server_version='ShapeOfMath/1.0'",
                                         "server_version='ShapeOfMath/3.0'"))
        self.wait_for(lambda: self.responds(port, '3.0'))
        watcher.send_signal(signal.SIGINT)
        self.assertEqual(watcher.wait(timeout=10), 0)
        self.assertFalse(self.responds(port))
        self.assertIn('stopped', self.command(port, 'status').stdout)

    def test_status_and_stop_do_not_create_database(self):
        port = self.port()
        self.assertIn('stopped', self.command(port, 'status').stdout)
        self.assertEqual(self.command(port, 'stop').returncode, 0)
        self.assertFalse((self.checkout / 'data').exists())
