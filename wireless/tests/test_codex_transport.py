import base64
import io
import json
from pathlib import Path
import queue
import tempfile
from threading import Event, Timer
import time
from unittest import TestCase
from unittest.mock import patch

from wireless.console.codex_transport import ScreenPlanner, TransportCancelled


class FakeProcess:
    def __init__(self):
        self.stdin, self.stdout = io.StringIO(), io.StringIO()
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, 0

    def wait(self, timeout=None):
        return self.returncode


class ScriptedPlanner(ScreenPlanner):
    """Exercise the real event loop without a subprocess, network or credentials."""
    def __init__(self, script):
        super().__init__('unused-codex')
        self.process = FakeProcess()
        self.fake_process = self.process
        self.events = queue.Queue()
        self.folder = tempfile.TemporaryDirectory(prefix='transport-test-')
        self.script = script
        self.requests = []
        self.turns = []
        self.disabled_mcp = {'test-mcp': {'enabled': False}}

    def _start(self, stopped):
        pass

    def _request(self, method, params, stopped, timeout=15):
        self.requests.append((method, params))
        if method == 'thread/start':
            return {'thread': {'id': 'screen-' + str(len(self.turns))}}
        if method == 'thread/unsubscribe':
            return {'status': 'unsubscribed'}
        raise AssertionError(method)

    def _send(self, method, params=None, notification=False):
        number = super()._send(method, params, notification)
        if method == 'turn/start':
            self.turns.append(params)
            # There must never be a screenshot file, even during the request.
            assert list(Path(self.folder.name).iterdir()) == []
            for item in self.script(number, params['threadId']):
                self.events.put(item)
        return number


def notification(method, thread, **params):
    return {'method': method, 'params': dict(params, threadId=thread)}


def success(request, thread):
    return [
        {'id': request, 'result': {'turn': {'id': 'turn-1'}}},
        notification('item/started', thread, item={'type': 'reasoning'}),
        notification('item/agentMessage/delta', thread, delta='{"action":"finish"}'),
        notification('item/completed', thread, item={
            'type': 'agentMessage', 'text': '{"action":"finish"}'}),
        notification('thread/tokenUsage/updated', thread,
                     tokenUsage={'last': {'totalTokens': 21}}),
        notification('turn/completed', thread, turn={'status': 'completed'}),
    ]


class TransportTests(TestCase):
    def make(self, script=success):
        planner = ScriptedPlanner(script)
        self.addCleanup(planner.close)
        return planner

    def decide(self, planner, stopped=None):
        return planner.decide('screen instructions', 'inspect current screen', b'image bytes',
                              {'type': 'object'}, 'test-model', 'low', stopped or Event())

    def test_fresh_ephemeral_threads_reuse_process_and_release_each_image(self):
        planner = self.make()
        process = planner.process
        for _ in range(2):
            action, metrics = self.decide(planner)
            self.assertEqual(action, {'action': 'finish'})
            self.assertEqual(metrics['usage'], {'totalTokens': 21})
            self.assertIs(planner.process, process)
        starts = [p for m, p in planner.requests if m == 'thread/start']
        releases = [p for m, p in planner.requests if m == 'thread/unsubscribe']
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(releases), 2)
        self.assertNotEqual(releases[0]['threadId'], releases[1]['threadId'])
        self.assertTrue(all(p['ephemeral'] for p in starts))
        self.assertTrue(all(p['environments'] == [] for p in starts))
        self.assertFalse(starts[0]['config']['features']['shell_tool'])
        self.assertFalse(starts[0]['config']['features']['plugins'])
        self.assertTrue(starts[0]['config']['features']['skip_host_skill_discovery'])
        self.assertFalse(starts[0]['config']['tools']['update_plan']['enabled'])
        self.assertFalse(starts[0]['config']['tools']['experimental_request_user_input']['enabled'])
        self.assertEqual(starts[0]['config']['mcp_servers'], {'test-mcp': {'enabled': False}})
        self.assertEqual(list(Path(planner.folder.name).iterdir()), [])
        for turn in planner.turns:
            self.assertEqual(turn['outputSchema'], {'type': 'object'})
            image = turn['input'][1]
            self.assertEqual(image['type'], 'image')
            self.assertEqual(base64.b64decode(image['url'].split(',', 1)[1]), b'image bytes')

    def test_other_thread_notifications_never_supply_result(self):
        def script(request, thread):
            return [notification('item/completed', 'old-thread', item={
                'type': 'agentMessage', 'text': '{"action":"tap"}'})] + success(request, thread)
        action, _ = self.decide(self.make(script))
        self.assertEqual(action['action'], 'finish')

    def test_delta_only_response(self):
        def script(request, thread):
            return [notification('item/agentMessage/delta', thread, delta='{"action":'),
                    notification('item/agentMessage/delta', thread, delta='"finish"}'),
                    notification('turn/completed', thread, turn={'status': 'completed'})]
        self.assertEqual(self.decide(self.make(script))[0]['action'], 'finish')

    def test_protocol_error_aborts_without_retry(self):
        planner = self.make(lambda request, thread: [{'id': request, 'error': {'message': 'bad model'}}])
        with self.assertRaisesRegex(RuntimeError, 'bad model'):
            self.decide(planner)
        self.assertEqual(len(planner.turns), 1)
        self.assertTrue(planner.fake_process.terminated)
        self.assertIsNone(planner.folder)

    def test_server_tool_request_is_rejected_and_process_terminated(self):
        planner = self.make(lambda request, thread: [{'id': 99, 'method': 'item/tool/call', 'params': {}}])
        with self.assertRaisesRegex(RuntimeError, '不支持的工具'):
            self.decide(planner)
        self.assertTrue(planner.fake_process.terminated)
        self.assertIsNone(planner.folder)

    def test_unexpected_builtin_tool_event_fails_closed(self):
        for kind in ['commandExecution', 'fileChange', 'mcpToolCall', 'webSearch', 'imageView']:
            with self.subTest(kind=kind):
                planner = self.make(lambda request, thread: [
                    notification('item/started', thread, item={'type': kind})])
                with self.assertRaisesRegex(RuntimeError, '不支持的工具'):
                    self.decide(planner)
                self.assertTrue(planner.fake_process.terminated)

    def test_eof_aborts_without_returning_partial_action(self):
        planner = self.make(lambda request, thread: [
            notification('item/agentMessage/delta', thread, delta='{"action":"tap"}'), None])
        with self.assertRaisesRegex(RuntimeError, '连接已退出'):
            self.decide(planner)
        self.assertTrue(planner.fake_process.terminated)

    def test_failed_turn_never_returns_json_action(self):
        planner = self.make(lambda request, thread: [
            notification('item/completed', thread, item={
                'type': 'agentMessage', 'text': '{"action":"tap"}'}),
            notification('turn/completed', thread, turn={
                'status': 'failed', 'error': {'message': 'service failure'}})])
        with self.assertRaisesRegex(RuntimeError, 'service failure'):
            self.decide(planner)

    def test_invalid_json_terminates_ephemeral_session(self):
        planner = self.make(lambda request, thread: [
            notification('item/completed', thread, item={'type': 'agentMessage', 'text': 'invalid'}),
            notification('turn/completed', thread, turn={'status': 'completed'})])
        with self.assertRaises(json.JSONDecodeError):
            self.decide(planner)
        self.assertTrue(planner.fake_process.terminated)

    def test_queued_cancellation_does_not_kill_other_request(self):
        planner = self.make()
        stop = Event()
        timer = Timer(.02, stop.set)
        with planner.lock:
            timer.start()
            started = time.monotonic()
            with self.assertRaises(TransportCancelled):
                self.decide(planner, stop)
            self.assertLess(time.monotonic() - started, .3)
        timer.join()
        self.assertFalse(planner.fake_process.terminated)
        self.assertEqual(planner.turns, [])

    def test_active_cancellation_terminates_and_cleans_up(self):
        stop = Event()

        def script(request, thread):
            stop.set()
            return []

        planner = self.make(script)
        with self.assertRaises(TransportCancelled):
            self.decide(planner, stop)
        self.assertTrue(planner.fake_process.terminated)
        self.assertIsNone(planner.folder)

    def test_expired_deadline_raises_immediately(self):
        planner = self.make()
        with self.assertRaisesRegex(RuntimeError, '超时'):
            planner._next(time.monotonic() - 1, Event())

    def test_mcp_names_collected_across_pages_without_retaining_other_fields(self):
        planner = self.make()
        with patch.object(planner, '_request', side_effect=[
            {'data': [{'name': 'first', 'authStatus': 'unread', 'tools': {'unused': {}}}], 'nextCursor': 'page-2'},
            {'data': [{'name': 'second'}, {'name': 'third'}], 'nextCursor': None},
        ]) as request:
            planner._load_mcp_restrictions(Event())
        self.assertEqual(planner.disabled_mcp, {
            'first': {'enabled': False}, 'second': {'enabled': False}, 'third': {'enabled': False}})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[:2], (
            'mcpServerStatus/list', {'detail': 'toolsAndAuthOnly', 'limit': 100}))
        self.assertEqual(request.call_args_list[1].args[1]['cursor'], 'page-2')
        self.decide(planner)
        self.assertEqual(planner.requests[0][1]['config']['mcp_servers'], planner.disabled_mcp)

    def test_mcp_second_page_failure_prevents_any_model_turn(self):
        planner = self.make()
        with patch.object(planner, '_start', side_effect=lambda stopped: planner._load_mcp_restrictions(stopped)), \
                patch.object(planner, '_request', side_effect=[
                    {'data': [{'name': 'first'}], 'nextCursor': 'page-2'},
                    RuntimeError('registry unavailable'),
                ]) as request:
            with self.assertRaisesRegex(RuntimeError, 'registry unavailable'):
                self.decide(planner)
        self.assertTrue(all(call.args[0] == 'mcpServerStatus/list' for call in request.call_args_list))
        self.assertEqual(planner.turns, [])
        self.assertIsNone(planner.disabled_mcp)
        self.assertTrue(planner.fake_process.terminated)

    def test_mcp_malformed_or_looping_pagination_is_not_accepted(self):
        pages = [
            [{'data': None, 'nextCursor': None}],
            [{'data': [{'name': None}], 'nextCursor': None}],
            [{'data': [], 'nextCursor': 5}],
            [{'data': [], 'nextCursor': 'same'}, {'data': [], 'nextCursor': 'same'}],
        ]
        for result in pages:
            with self.subTest(result=result):
                planner = self.make()
                with patch.object(planner, '_request', side_effect=result):
                    with self.assertRaises(RuntimeError):
                        planner._load_mcp_restrictions(Event())
                self.assertIsNone(planner.disabled_mcp)

    def test_empty_mcp_registry_is_valid_and_missing_registry_is_not(self):
        planner = self.make()
        with patch.object(planner, '_request', return_value={'data': [], 'nextCursor': None}):
            planner._load_mcp_restrictions(Event())
        self.assertEqual(planner.disabled_mcp, {})
        self.decide(planner)
        planner.disabled_mcp = None
        with self.assertRaisesRegex(RuntimeError, '未能确认外部工具已禁用'):
            self.decide(planner)
        self.assertEqual(len(planner.turns), 1)
