#!/usr/bin/env python3
"""Common operation context — sourced by Python operation scripts."""

import logging
import os
import signal
import sys
from datetime import datetime


class OperationContext:
    def __init__(self, script_file):
        self.script_name = os.path.splitext(os.path.basename(script_file))[0]
        self.script_dir = os.path.dirname(os.path.abspath(script_file))
        self.project_dir = os.path.dirname(self.script_dir)

        os.chdir(self.project_dir)

        self.project_name = self._get_metadata('name') or os.path.basename(self.project_dir)
        self.port = self._get_metadata('port')
        self.display_name = self._get_metadata('display_name') or self.project_name

        # Load global secrets then project-specific overrides
        projects_dir = os.path.dirname(self.project_dir)
        self._load_env(os.path.join(projects_dir, '.secrets'))
        self._load_env(os.path.join(self.project_dir, '.env'))

        # Set up logging to file + stdout
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_dir = os.path.join(self.project_dir, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f'{self.project_name}_{self.script_name}_{ts}.log')

        self.logger = logging.getLogger(self.script_name)
        self.logger.setLevel(logging.DEBUG)

        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.logger.addHandler(fh)

        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(sh)

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _get_metadata(self, key):
        md_file = os.path.join(self.project_dir, 'METADATA.md')
        try:
            with open(md_file) as f:
                for line in f:
                    if line.startswith(f'{key}:'):
                        return line[len(key) + 1:].strip()
        except OSError:
            pass
        return None

    def _load_env(self, path):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        k, _, v = line.partition('=')
                        os.environ.setdefault(k.strip(), v.strip())
        except OSError:
            pass

    def _game_port(self):
        port = os.environ.get('GAME_PORT')
        if port:
            return port
        try:
            with open(os.path.expanduser('~/.game_port')) as f:
                return f.read().strip()
        except OSError:
            return '5000'

    def _signal_handler(self, signum, frame):
        self.exit_ok()
        sys.exit(0)

    def started(self):
        self.logger.info(f'[{self.project_name}] Starting: {self.script_name}')

    def exit_ok(self):
        self.logger.info(f'[{self.project_name}] EXIT - OK')

    def exit_error(self, msg=''):
        self.logger.error(f'[{self.project_name}] EXIT - ERROR{": " + msg if msg else ""}')

    def run(self, fn):
        """Lifecycle wrapper: started → fn(ctx) → EXIT - OK or EXIT - ERROR."""
        self.started()
        try:
            fn(self)
            self.exit_ok()
        except (KeyboardInterrupt, SystemExit):
            self.exit_ok()
        except Exception as e:
            self.exit_error(str(e))
            sys.exit(1)

    def heartbeat(self, state, message='', subsystem=None):
        """POST heartbeat to GAME. state: OK WARNING ERROR CRITICAL. Silent on failure."""
        import urllib.request, json
        payload = {'program': self.script_name, 'system': self.project_name,
                   'state': state, 'message': message}
        if subsystem:
            payload['subsystem'] = subsystem
        try:
            req = urllib.request.Request(
                f'http://localhost:{self._game_port()}/api/heartbeat',
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    def log_event(self, severity, message, subsystem=None):
        """POST event to GAME. severity: INFORMATION WARNING ERROR CRITICAL. Silent on failure."""
        import urllib.request, json
        payload = {'program': self.script_name, 'system': self.project_name,
                   'severity': severity, 'message': message}
        if subsystem:
            payload['subsystem'] = subsystem
        try:
            req = urllib.request.Request(
                f'http://localhost:{self._game_port()}/api/events',
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass


def op(script_file):
    """Factory — shorthand for OperationContext(script_file)."""
    return OperationContext(script_file)
