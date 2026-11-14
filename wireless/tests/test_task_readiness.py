import threading
import time
import unittest
from unittest.mock import patch
from wireless.console.server import Console

class Device:
    live=False
    def snapshot(self): return {'live':self.live}
    def recover_receiver(self): return False
    def fresh_frame(self): raise RuntimeError('no frame')

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        config=patch("wireless.console.server.planner_settings",return_value={})
        config.start();self.addCleanup(config.stop)

    def test_direct_dispatch(self):
        device=Device();device.live=True
        with patch("wireless.console.server.run_task", return_value=("finish","ok")) as direct:
            console=Console(device,"codex");console.submit("测试任务",defer=.01)
            self.wait_for(lambda:console.state()["jobs"][0]["state"]=="finish")
            direct.assert_called_once()
    def wait_for(self, predicate):
        deadline=time.monotonic()+2
        while not predicate():
            if time.monotonic()>deadline: self.fail('worker timed out')
            time.sleep(.01)
    def test_resumes_only_after_frame(self):
        device=Device(); ran=threading.Event()
        with patch('wireless.console.server.run_task',side_effect=lambda *a:(ran.set() or 'finish','ok')):
            console=Console(device,'codex')
            console.submit('test')
            self.wait_for(lambda:any(e['title']=='等待手机画面' for e in console.state()['events']))
            self.assertFalse(ran.is_set())
            device.live=True
            self.wait_for(lambda:console.state()['jobs'][0]['state']=='finish')
            self.assertTrue(ran.is_set())
    def test_stop_while_waiting(self):
        device=Device()
        with patch('wireless.console.server.run_task') as run:
            console=Console(device,'codex'); console.submit('test')
            self.wait_for(lambda:any(e['title']=='等待手机画面' for e in console.state()['events']))
            console.stop()
            self.wait_for(lambda:console.state()['jobs'][0]['state']=='cancelled')
            run.assert_not_called()

if __name__=='__main__': unittest.main()
