"""Controlled local subprocess fixtures; these tests never contact a model."""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from home.adapters import (
    AdapterCancelled,
    AdapterError,
    AdapterTimeout,
    ClaudeAdapter,
    CodexAdapter,
    OutputLimitExceeded,
    ProtocolError,
    UnexpectedAction,
)
from home.models import Cancelled, ProviderError

SESSION = "12345678-1234-4234-9234-123456789abc"
OTHER = "87654321-4321-4321-9321-cba987654321"


class NativeAdapterTests(unittest.TestCase):
    def test_errors_follow_the_shared_provider_contract(self):
        self.assertTrue(issubclass(AdapterError, ProviderError))
        self.assertTrue(issubclass(AdapterCancelled, Cancelled))
        self.assertTrue(issubclass(AdapterCancelled, AdapterError))
        self.assertEqual(AdapterCancelled.status, 409)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.directory.name)
        self.fixture = self.workspace / "cli_fixture.py"
        self.commands = []
        self.original_popen = subprocess.Popen

    def tearDown(self):
        self.directory.cleanup()

    def run_fixture(self, adapter, source, prompt="Hello", session=None, cancel=None):
        self.fixture.write_text(source, encoding="utf-8")

        def launch(command, **kwargs):
            self.commands.append(command)
            self.assertFalse(kwargs["shell"])
            return self.original_popen([sys.executable, "-u", str(self.fixture)], **kwargs)

        with patch("home.adapters.process.subprocess.Popen", side_effect=launch):
            return adapter.generate(prompt, session, cancel or threading.Event())

    def adapter(self, cls, **limits):
        return cls(executable=sys.executable, workspace=self.workspace, **limits)

    def events(self, *events):
        return "import sys\nsys.stdin.read()\n" + "\n".join(
            "print(" + repr(json.dumps(event)) + ", flush=True)" for event in events)

    def claude_events(self, text="A real fixture reply", session=SESSION, model="fixture-model"):
        return self.events(
            {"type": "system", "subtype": "init", "session_id": session, "model": model},
            {"type": "result", "subtype": "success", "is_error": False,
             "result": text, "session_id": session})

    def codex_events(self, text="A real fixture reply", session=SESSION, **metadata):
        return self.events(
            {"type": "thread.started", "thread_id": session, **metadata},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
            {"type": "turn.completed", "usage": {"input_tokens": 10}})

    def test_claude_reply_and_reported_identity(self):
        reply = self.run_fixture(self.adapter(ClaudeAdapter), self.claude_events())
        self.assertEqual((reply.text, reply.provider, reply.session_id, reply.model),
                         ("A real fixture reply", "claude", SESSION, "fixture-model"))
        args = self.commands[0]
        self.assertNotIn("--model", args)
        self.assertNotIn("--permission-mode", args)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", args)
        self.assertNotIn("--dangerously-skip-permissions", args)

    def test_claude_exact_resume(self):
        reply = self.run_fixture(self.adapter(ClaudeAdapter), self.claude_events(), session=SESSION)
        self.assertEqual(reply.session_id, SESSION)
        args = self.commands[0]
        self.assertEqual(args[args.index("--resume") + 1], SESSION)
        self.assertNotIn("--fork-session", args)

    def test_codex_final_reply_not_reasoning_or_earlier_text(self):
        source = self.events(
            {"type": "thread.started", "thread_id": SESSION},
            {"type": "item.completed", "item": {"type": "reasoning", "text": "private thinking"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "earlier"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "final"}},
            {"type": "turn.completed"})
        reply = self.run_fixture(self.adapter(CodexAdapter), source)
        self.assertEqual(reply.text, "final")
        self.assertIsNone(reply.model)
        args = self.commands[0]
        self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
        self.assertIn('approval_policy="never"', args)

    def test_codex_exact_resume_has_read_only_config_and_preserves_model(self):
        reply = self.run_fixture(self.adapter(CodexAdapter), self.codex_events(model="reported"),
                                 session=SESSION)
        self.assertEqual(reply.model, "reported")
        args = self.commands[0]
        self.assertEqual(args[1:4], ["exec", "resume", SESSION])
        self.assertIn('sandbox_mode="read-only"', args)
        self.assertNotIn("--sandbox", args)
        self.assertNotIn("--model", args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)

    def test_prompt_is_stdin_not_command(self):
        prompt = 'Hello; $(secret) " --model invented\nsecond line'
        source = ("import sys,json\nprompt=sys.stdin.read()\n" +
                  f"print(json.dumps({{'type':'thread.started','thread_id':'{SESSION}'}}))\n" +
                  "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':prompt}}))\n" +
                  "print(json.dumps({'type':'turn.completed'}))\n")
        reply = self.run_fixture(self.adapter(CodexAdapter), source, prompt=prompt)
        self.assertEqual(reply.text, prompt)
        self.assertNotIn(prompt, self.commands[0])

    def test_exact_session_aliases_share_identity_fresh_adapters_do_not(self):
        first, second = self.adapter(CodexAdapter), self.adapter(CodexAdapter)
        self.assertEqual(first.identity_key(SESSION), second.identity_key(SESSION.upper()))
        self.assertNotEqual(first.identity_key(None), second.identity_key(None))
        self.assertNotEqual(first.identity_key(SESSION), self.adapter(ClaudeAdapter).identity_key(SESSION))

    def test_invalid_or_cli_option_session_is_rejected_before_launch(self):
        with self.assertRaises(ProtocolError):
            self.run_fixture(self.adapter(ClaudeAdapter), self.claude_events(), session="--last")
        self.assertEqual(self.commands, [])

    def test_mismatched_exact_resume_is_not_silently_accepted(self):
        for cls, source in ((ClaudeAdapter, self.claude_events(session=OTHER)),
                            (CodexAdapter, self.codex_events(session=OTHER))):
            with self.subTest(provider=cls.provider), self.assertRaises(ProtocolError):
                self.run_fixture(self.adapter(cls), source, session=SESSION)

    def test_nonzero_exit_is_sanitized_even_with_success_text(self):
        source = self.claude_events() + "\nprint('sk-secret /private/location', file=sys.stderr)\nsys.exit(7)"
        with self.assertRaises(AdapterError) as caught:
            self.run_fixture(self.adapter(ClaudeAdapter), source)
        self.assertNotIn("sk-secret", str(caught.exception))
        self.assertNotIn("/private/location", str(caught.exception))

    def test_claude_error_result_does_not_expose_raw_error(self):
        source = self.events({"type": "result", "subtype": "error_during_execution",
                              "is_error": True, "result": "private error sk-secret"})
        with self.assertRaises(AdapterError) as caught:
            self.run_fixture(self.adapter(ClaudeAdapter), source)
        self.assertNotIn("sk-secret", str(caught.exception))

    def test_missing_completed_turn_or_session_is_not_success(self):
        for source in (
            self.events({"type": "thread.started", "thread_id": SESSION},
                        {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}),
            self.events({"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}},
                        {"type": "turn.completed"})):
            with self.assertRaises(ProtocolError):
                self.run_fixture(self.adapter(CodexAdapter), source)

    def test_malformed_output_fails_safely(self):
        with self.assertRaises(ProtocolError) as caught:
            self.run_fixture(self.adapter(ClaudeAdapter), "print('sk-secret invalid-json')")
        self.assertNotIn("sk-secret", str(caught.exception))

    def test_tool_event_stops_owned_process_before_timeout(self):
        for cls, event in (
            (CodexAdapter, {"type": "item.started", "item": {"type": "command_execution"}}),
            (ClaudeAdapter, {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash"}]}})):
            source = "import time\nprint(" + repr(json.dumps(event)) + ", flush=True)\ntime.sleep(8)"
            started = time.monotonic()
            with self.subTest(provider=cls.provider), self.assertRaises(UnexpectedAction):
                self.run_fixture(self.adapter(cls, timeout=5), source)
            self.assertLess(time.monotonic() - started, 3)

    def test_timeout_stops_nonreading_process(self):
        started = time.monotonic()
        with self.assertRaises(AdapterTimeout):
            self.run_fixture(self.adapter(CodexAdapter, timeout=0.15), "import time\ntime.sleep(8)",
                             prompt="x" * (100 * 1024))
        self.assertLess(time.monotonic() - started, 3)

    def test_pre_cancel_prevents_launch(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(AdapterCancelled):
            self.run_fixture(self.adapter(ClaudeAdapter), self.claude_events(), cancel=cancel)
        self.assertEqual(self.commands, [])

    def test_live_cancel_stops_owned_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        try:
            with self.assertRaises(AdapterCancelled):
                self.run_fixture(self.adapter(ClaudeAdapter), "import time\ntime.sleep(8)", cancel=cancel)
        finally:
            timer.join()

    def test_abort_stops_owned_descendant_and_preserves_unrelated_process(self):
        ready = self.workspace / "descendant_ready"
        escaped = self.workspace / "descendant_escaped"
        child = self.workspace / "child_fixture.py"
        child.write_text(
            "import pathlib,time\n" +
            f"pathlib.Path({str(ready)!r}).write_text('ready')\n" +
            "time.sleep(0.6)\n" +
            f"pathlib.Path({str(escaped)!r}).write_text('escaped')\n", encoding="utf-8")
        source = (
            "import pathlib,subprocess,sys,time,json\n" +
            f"subprocess.Popen([sys.executable,{str(child)!r}])\n" +
            f"ready=pathlib.Path({str(ready)!r})\n" +
            "while not ready.exists(): time.sleep(0.01)\n" +
            "print(json.dumps({'type':'item.started','item':{'type':'command_execution'}}),flush=True)\n" +
            "time.sleep(8)\n")
        unrelated = self.original_popen([sys.executable, "-c", "import time; time.sleep(8)"])
        try:
            with self.assertRaises(UnexpectedAction):
                self.run_fixture(self.adapter(CodexAdapter, timeout=3), source)
            self.assertTrue(ready.exists(), "The controlled descendant must have actually started.")
            time.sleep(0.7)
            self.assertFalse(escaped.exists(), "An owned descendant survived abort.")
            self.assertIsNone(unrelated.poll(), "The unrelated process was stopped.")
        finally:
            unrelated.kill()
            unrelated.wait(timeout=2)

    def test_bounded_stdout_and_stderr(self):
        for target in ("sys.stdout", "sys.stderr"):
            source = f"import sys\n{target}.write('x'*100000)\n{target}.flush()"
            with self.subTest(target=target), self.assertRaises(OutputLimitExceeded):
                self.run_fixture(self.adapter(CodexAdapter, max_output_bytes=2048), source)

    def test_bounded_reply(self):
        with self.assertRaises(ProtocolError):
            self.run_fixture(self.adapter(ClaudeAdapter, max_reply_bytes=4), self.claude_events(text="too long"))

    def test_missing_executable_has_safe_error(self):
        adapter = ClaudeAdapter(executable="nonexistent-fixture-cli-12345", workspace=self.workspace)
        with self.assertRaises(AdapterError) as caught:
            adapter.generate("hi", None, threading.Event())
        self.assertNotIn("nonexistent-fixture", str(caught.exception))

    def test_limits_are_finite_and_input_bound(self):
        for timeout in (float("inf"), float("nan"), 0):
            with self.assertRaises(ValueError):
                self.adapter(CodexAdapter, timeout=timeout)
        with self.assertRaises(ValueError):
            self.run_fixture(self.adapter(CodexAdapter), self.codex_events(), prompt="x" * (129 * 1024))
        self.assertEqual(self.commands, [])

    def test_invalid_unicode_is_rejected_safely(self):
        with self.assertRaises(ValueError):
            self.run_fixture(self.adapter(CodexAdapter), self.codex_events(), prompt="invalid\ud800")
        self.assertEqual(self.commands, [])
        with self.assertRaises(ProtocolError):
            self.run_fixture(self.adapter(ClaudeAdapter), self.claude_events(text="invalid\ud800"))


if __name__ == "__main__":
    unittest.main()
