"""Bounded native process ownership; no shell or stored-PID cancellation."""
from __future__ import annotations

import ctypes
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from io import BufferedReader
from pathlib import Path
from typing import BinaryIO

from home.models import Cancelled, ProviderError

log = logging.getLogger(__name__)


class AdapterError(ProviderError):
    """A safe summary for the local UI; never includes provider output or paths."""

    code = "provider_failed"


class AdapterCancelled(Cancelled, AdapterError):
    code = "cancelled"


class AdapterTimeout(AdapterError):
    code = "timeout"


class OutputLimitExceeded(AdapterError):
    code = "output_limit"


class ProtocolError(AdapterError):
    code = "invalid_response"


class UnexpectedAction(AdapterError):
    code = "unexpected_action"


class _WindowsJob:
    """An owned Job Object stops descendants without enumerating external PIDs."""

    api: ctypes.CDLL
    handle: int | None

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO)] + [
                (name, ctypes.c_size_t) for name in (
                    "ProcessMemoryLimit", "JobMemoryLimit", "PeakProcessMemoryUsed",
                    "PeakJobMemoryUsed")]

        if sys.platform == "win32":
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        else:
            raise AdapterError("Windows process ownership is unavailable on this platform.")
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                     ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.handle or not self.api.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise AdapterError("Native process ownership could not be established.")
        process_handle = getattr(process, "_handle", None)
        if not isinstance(process_handle, int) or not self.api.AssignProcessToJobObject(
                self.handle, process_handle):
            self.close()
            raise AdapterError("Native process ownership could not be established.")

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.api.CloseHandle(self.handle)
            self.handle = None


def run_owned(command: list[str], workspace: Path, prompt: bytes,
              cancel: threading.Event, timeout: float, max_output_bytes: int,
              on_line: Callable[[bytes], None]) -> None:
    """Stream bounded JSON lines to a parser and own only the launched process tree.

    A parser can reject tool events while output arrives. Detection cannot undo an
    action the CLI already started; this is a conversation boundary, not a sandbox.
    """
    if cancel.is_set():
        raise AdapterCancelled("The reply was cancelled.")
    executable = shutil.which(command[0])
    if not executable or Path(executable).suffix.lower() in {".cmd", ".bat"}:
        raise AdapterError("Native executable unavailable. Configure a directly executable CLI.")
    command = [executable, *command[1:]]
    process: subprocess.Popen[bytes] | None = None
    job: _WindowsJob | None = None
    failures: list[AdapterError] = []
    guard = threading.Lock()
    output_count = 0
    stop = threading.Event()
    readers: list[threading.Thread] = []
    writer: threading.Thread | None = None

    def fail(error: AdapterError) -> None:
        with guard:
            if not failures:
                failures.append(error)
        stop.set()

    def consume(pipe: BufferedReader, parse: bool) -> None:
        nonlocal output_count
        pending = bytearray()
        try:
            while chunk := pipe.read1(4096):
                with guard:
                    output_count += len(chunk)
                    too_large = output_count > max_output_bytes
                if too_large:
                    fail(OutputLimitExceeded("Native output exceeded the configured limit."))
                    return
                if parse:
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending = bytearray(rest)
                        if line.strip():
                            on_line(bytes(line))
            if parse and pending.strip():
                on_line(bytes(pending))
        except AdapterError as error:
            fail(error)
        except (OSError, ValueError):
            # Closing owned pipes during cancellation is expected.
            if not stop.is_set():
                fail(AdapterError("Native response could not be read."))
        except Exception:
            log.exception("Native response parser failed")
            fail(ProtocolError("Native response could not be interpreted."))

    def write_input(pipe: BinaryIO) -> None:
        try:
            pipe.write(prompt)
            pipe.close()
        except (OSError, ValueError):
            pass  # Exit status and response parsing establish success.

    def stop_owned() -> None:
        if job:
            job.close()
        elif sys.platform != "win32" and process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process is not None and process.poll() is None:
            process.kill()

    try:
        try:
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                command, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, shell=False, start_new_session=os.name != "nt",
                creationflags=creation_flags)
            if os.name == "nt":
                job = _WindowsJob(process)
        except (OSError, ValueError):
            raise AdapterError("Native CLI could not start. Check its installation and workspace.") from None
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise AdapterError("Native process pipes could not be established.")
        for pipe, parse in ((process.stdout, True), (process.stderr, False)):
            worker = threading.Thread(target=consume, args=(pipe, parse), daemon=True)
            readers.append(worker)
            worker.start()
        writer = threading.Thread(target=write_input, args=(process.stdin,), daemon=True)
        writer.start()
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel.is_set():
                raise AdapterCancelled("The reply was cancelled.")
            if stop.is_set():
                raise failures[0]
            if time.monotonic() >= deadline:
                raise AdapterTimeout("The native reply timed out.")
            stop.wait(0.03)
        # Stop descendant processes holding pipes after the directly owned CLI exits.
        stop_owned()
        for reader in readers:
            reader.join(timeout=1.0)
        writer.join(timeout=0.2)
        if cancel.is_set():
            raise AdapterCancelled("The reply was cancelled.")
        if failures:
            raise failures[0]
        if any(reader.is_alive() for reader in readers):
            raise AdapterError("Native output did not close after the CLI exited.")
        if process.returncode != 0:
            raise AdapterError("Native CLI exited unsuccessfully. Check its sign-in and configuration.")
    finally:
        stop.set()
        if process is not None:
            stop_owned()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            for reader in readers:
                reader.join(timeout=1.0)
            if writer:
                writer.join(timeout=0.2)
            # Do not acquire a BufferedReader lock still held by a blocked daemon.
            if not any(reader.is_alive() for reader in readers):
                for output_pipe in (process.stdout, process.stderr):
                    if output_pipe:
                        output_pipe.close()
            if (not writer or not writer.is_alive()) and process.stdin:
                process.stdin.close()
