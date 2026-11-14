import json
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from wireless.console.siri import start_gateway

class FakeConsole:
    def __init__(self): self.jobs=[]; self.stopped=False
    def submit(self, task, defer=0): self.jobs.append((task,defer)); return len(self.jobs)
    def stop(self): self.stopped=True

class SiriTests(unittest.TestCase):
    def setUp(self):
        self.console=FakeConsole(); self.server=start_gateway(self.console,'127.0.0.1',0)
    def tearDown(self): self.server.shutdown(); self.server.server_close()
    def post(self, task, authorized=True, origin=None, path='/task'):
        headers={'Content-Type':'application/json'}
        if authorized: headers['Authorization']='Bearer '+self.server.token
        if origin: headers['Origin']=origin
        request=Request('http://127.0.0.1:%s%s'%(self.server.server_port,path),data=json.dumps({'task':task}).encode(),headers=headers)
        try: response=urlopen(request)
        except HTTPError as e: response=e
        return response.status,json.load(response)
    def test_auth_and_scope(self):
        self.assertEqual(self.post('打开多邻国',False)[0],403)
        self.assertEqual(self.post('打开多邻国',origin='https://example.com')[0],403)
        self.assertEqual(self.post('打开多邻国',path='/api/frame')[0],404)
        self.assertEqual(self.console.jobs,[])
    def test_queue_stop_and_test(self):
        self.assertEqual(self.post('连接测试')[0],200)
        self.assertEqual(self.console.jobs,[])
        self.assertEqual(self.post('打开多邻国')[0],202)
        self.assertEqual(self.console.jobs,[('打开多邻国',4)])
        self.assertEqual(self.post('打开多邻国')[0],429)
        self.assertEqual(self.post('停止任务')[0],200)
        self.assertTrue(self.console.stopped)
    def test_bad_input(self):
        for task in ('', 'x'*501, 123, None): self.assertEqual(self.post(task)[0],400)

if __name__=='__main__': unittest.main()
