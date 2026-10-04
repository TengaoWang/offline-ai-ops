import http.client
import json
import threading
import unittest

import server as app


class AssistantApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.httpd.daemon_threads=True
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown();cls.httpd.server_close();cls.thread.join(2)

    def setUp(self):
        with app.LOCK:app.LAB.reset('A')

    def request(self,method,path,value=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.httpd.server_port,timeout=3)
        body=None if value is None else json.dumps(value)
        headers={'Content-Type':'application/json'} if body is not None else {}
        conn.request(method,path,body,headers);response=conn.getresponse()
        result=response.status,json.loads(response.read());conn.close();return result

    def test_health_and_observation_hide_scenario_answer(self):
        status,health=self.request('GET','/api/v1/health')
        self.assertEqual(status,200);self.assertEqual(health['status'],'ready')
        status,observation=self.request('GET','/api/v1/observation')
        self.assertEqual(status,200);self.assertIn('symptom',observation)
        self.assertNotIn('scene',observation);self.assertNotIn('sources',observation)
        self.assertNotIn('办公区全面断网',json.dumps(observation,ensure_ascii=False))

    def test_independent_device_contexts_and_command(self):
        epoch=self.request('GET','/api/v1/observation')[1]['epoch']
        payload={'session':'external-test','device':'SW1','epoch':epoch,
                 'command':'system-view\ninterface GE0/0/1\nundo shutdown\nreturn'}
        status,result=self.request('POST','/api/v1/command',payload)
        self.assertEqual(status,200);self.assertTrue(all(r['ok'] for r in result['records']))
        sw1=self.request('POST','/api/v1/context',{'session':'external-test','device':'SW1'})[1]
        sw2=self.request('POST','/api/v1/context',{'session':'external-test','device':'SW2'})[1]
        self.assertEqual(sw1['prompt'],'<SW1> ');self.assertEqual(sw2['prompt'],'<SW2> ')
        self.assertNotIn('scene',result['observation'])

    def test_stale_epoch_is_rejected(self):
        old=self.request('GET','/api/v1/observation')[1]['epoch']
        with app.LOCK:app.LAB.reset('B')
        status,_=self.request('POST','/api/v1/command',
                              {'session':'external-test','device':'SW1','epoch':old,'command':'display interface brief'})
        self.assertEqual(status,409)

    def test_v1_diagnose_and_controlled_repair(self):
        with app.LOCK:app.LAB.reset('C')
        epoch=self.request('GET','/api/v1/observation')[1]['epoch']
        status,result=self.request('POST','/api/v1/diagnose',{'epoch':epoch})
        self.assertEqual(status,200);self.assertEqual(result['diagnosis']['fault_code'],'C')
        status,result=self.request('POST','/api/v1/repair',{'epoch':epoch,'session':'external-test'})
        self.assertEqual(status,200);self.assertTrue(result['repair']['repaired'])


if __name__=='__main__':unittest.main()
