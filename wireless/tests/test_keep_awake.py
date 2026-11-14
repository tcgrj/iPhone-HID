from collections import deque
from threading import Condition
from unittest import TestCase
from unittest.mock import Mock
from wireless.console.server import Console
class KeepAwakeTests(TestCase):
 def setup_console(self):
  c=Console.__new__(Console);c.changed=Condition();c.pending=deque();c.active=None;c.refresh_during_plan=False
  c.device=Mock();c.device.snapshot.return_value={'paired':True};c.keep_awake_last=None;c.keep_awake_error=''
  return c
 def test_idle_and_planning_only(self):
  c=self.setup_console();c.keep_awake_tick()
  self.assertEqual([a.args[0] for a in c.device.command.call_args_list],['move 1 0','move -1 0'])
  c.device.command.reset_mock();c.active={'id':1};c.keep_awake_tick();c.device.command.assert_not_called()
  c.refresh_during_plan=True;c.keep_awake_tick();self.assertEqual(c.device.command.call_count,2)
 def test_queued_or_unpaired_does_not_move(self):
  c=self.setup_console();c.pending.append({});c.keep_awake_tick();c.device.command.assert_not_called()
  c.pending.clear();c.device.snapshot.return_value={'paired':False};c.keep_awake_tick();c.device.command.assert_not_called()
