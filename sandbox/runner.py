from collections import deque
import json
import queue
import subprocess
import sys
import threading

from .limits import RESOURCE_LIMITS_AVAILABLE

DEFAULT_TIMEOUT_SEC = 0.2
DEFAULT_STARTUP_TIMEOUT_SEC = 2.0
DEFAULT_CPU_LIMIT_SEC = 2
DEFAULT_MEM_LIMIT_BYTES = 200 * 1024 * 1024
DEFAULT_CONSECUTIVE_FAILURE_LIMIT = 3

class SubmissionLoadError(ValueError):
    pass

def _popen_kwargs():
    return {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "bufsize": 1,
    }

def _worker_command(mode, module, cls_name, bot_id, cpu_limit, mem_limit):
    worker_args = [mode, module, cls_name, bot_id]
    if RESOURCE_LIMITS_AVAILABLE:
        return [
            sys.executable, "-B", "-m", "sandbox.launch_worker",
            str(cpu_limit), str(mem_limit), *worker_args,
        ]
    return [sys.executable, "-B", "-m", "sandbox.bot_worker", *worker_args]

def inspect_submission(module, cls_name, timeout=DEFAULT_TIMEOUT_SEC,
                       cpu_limit=DEFAULT_CPU_LIMIT_SEC,
                       mem_limit=DEFAULT_MEM_LIMIT_BYTES):
    timeout = max(timeout, DEFAULT_STARTUP_TIMEOUT_SEC)
    proc = subprocess.Popen(
        _worker_command(
            "--describe", module, cls_name, "CONFORMANCE", cpu_limit, mem_limit,
        ),
        **_popen_kwargs(),
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise SubmissionLoadError(f"inspection timed out after {timeout}s")
    if proc.returncode != 0:
        raise SubmissionLoadError(f"submission failed to load: {err.strip()[-300:]}")
    try:
        response = json.loads(out.strip())
    except json.JSONDecodeError as exc:
        raise SubmissionLoadError("inspection returned malformed protocol output") from exc
    if response.get("status") != "READY" or not isinstance(response.get("metadata"), dict):
        raise SubmissionLoadError(f"invalid inspection response: {response!r}")
    return response["metadata"]

class SandboxedBot:

    def __init__(self, module, cls_name, bot_id, timeout=DEFAULT_TIMEOUT_SEC,
                 cpu_limit=DEFAULT_CPU_LIMIT_SEC,
                 mem_limit=DEFAULT_MEM_LIMIT_BYTES, metadata=None,
                 startup_timeout=None,
                 consecutive_failure_limit=DEFAULT_CONSECUTIVE_FAILURE_LIMIT):
        self.module = module
        self.cls_name = cls_name
        self.id = bot_id
        self.timeout = timeout
        self.startup_timeout = startup_timeout or max(
            DEFAULT_STARTUP_TIMEOUT_SEC, timeout * 4,
        )
        self.cpu_limit = cpu_limit
        self.mem_limit = mem_limit
        self.consecutive_failure_limit = consecutive_failure_limit
        self.consecutive_failures = 0
        self.circuit_open = False
        self.metadata = metadata or inspect_submission(
            module, cls_name, timeout, cpu_limit, mem_limit,
        )
        self.ABILITY = self.metadata.get("ability")
        self.ROLE = self.metadata.get("role")
        self.last_status = "OK"
        self.last_diagnostic = None
        self._proc = None
        self._responses = queue.Queue()
        self._stderr = deque(maxlen=30)

    def _set_failure(self, kind, detail):
        self.last_status = f"{kind}: {detail}" if detail else kind
        self.last_diagnostic = {"kind": kind, "detail": detail}
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.consecutive_failure_limit:
            self.circuit_open = True
            self.close()

    def _read_stdout(self):
        for line in self._proc.stdout:
            self._responses.put(line)
        self._responses.put(None)

    def _read_stderr(self):
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())

    def _await_response(self, timeout=None, phase="decision"):
        timeout = self.timeout if timeout is None else timeout
        try:
            line = self._responses.get(timeout=timeout)
        except queue.Empty:
            kind = "TIMEOUT" if phase == "decision" else "STARTUP_TIMEOUT"
            self._set_failure(kind, f"{phase} exceeded {timeout}s")
            self.close()
            return None
        if line is None:
            detail = "\n".join(self._stderr)[-300:] or "worker exited without a response"
            self._set_failure("CRASH", detail)
            self.close()
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            self._set_failure("INVALID_OUTPUT", "malformed JSON transport output")
            self.close()
            return None

    def _start(self):
        self._responses = queue.Queue()
        self._stderr.clear()
        self._proc = subprocess.Popen(
            _worker_command(
                "--serve", self.module, self.cls_name, self.id,
                self.cpu_limit, self.mem_limit,
            ),
            **_popen_kwargs(),
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        response = self._await_response(self.startup_timeout, "worker startup")
        if response is None:
            return False
        if response.get("status") != "READY":
            self._set_failure("CRASH", f"invalid worker handshake: {response!r}")
            self.close()
            return False
        return True

    def buy(self, shop):
        self.last_diagnostic = None
        if self.circuit_open:
            return None
        if self._proc is None and not self._start():
            return None
        try:
            self._proc.stdin.write(json.dumps({"__buy__": shop}, separators=(",", ":")) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._set_failure("CRASH", str(exc))
            self.close()
            return None
        response = self._await_response()
        if response is None:
            return None
        if response.get("status") != "OK":
            self.last_diagnostic = {"kind": "BUY_FAILED", "detail": str(response.get("detail", ""))}
            return None
        return response.get("buy")

    def decide(self, view):
        from engine.actions import Action

        self.last_status = "OK"
        self.last_diagnostic = None
        if self.circuit_open:
            self.last_status = "CIRCUIT_OPEN: too many consecutive failures"
            self.last_diagnostic = {
                "kind": "CIRCUIT_OPEN",
                "detail": (
                    f"worker disabled after {self.consecutive_failure_limit} "
                    "consecutive failures"
                ),
            }
            return None
        if self._proc is None and not self._start():
            return None
        try:
            self._proc.stdin.write(json.dumps(view, separators=(",", ":")) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._set_failure("CRASH", str(exc))
            self.close()
            return None

        response = self._await_response()
        if response is None:
            return None
        status = response.get("status")
        if status == "NO_ACTION":
            self._set_failure("NO_ACTION", "decide(view) returned None")
            return None
        if status != "OK":
            self._set_failure(status or "INVALID_OUTPUT", str(response.get("detail", "")))
            if status == "CRASH":
                self.close()
            return None
        data = response.get("action")
        if not isinstance(data, dict) or "type" not in data:
            self._set_failure("INVALID_OUTPUT", f"invalid action payload: {data!r}")
            return None
        self.consecutive_failures = 0
        return Action(
            type=data.get("type"),
            direction=data.get("direction"),
            target=data.get("target"),
            x=data.get("x"),
            y=data.get("y"),
            say=data.get("say"),
        )

    def close(self):
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()
        try:
            proc.communicate(timeout=1)
        except (subprocess.TimeoutExpired, ValueError):
            pass
