import unittest
from engine import Lab, MACS


class LabTests(unittest.TestCase):
    def setUp(self): self.lab=Lab()

    def run_commands(self,device,commands,session='test'):
        for c in commands:
            result=self.lab.execute(device,c,session)
            self.assertTrue(result['ok'],(device,c,result['output']))

    def apply_task(self,report):
        task=report['task'];self.run_commands(task['device'],task['commands'])

    def test_healthy_end_to_end_and_device_pings(self):
        self.lab.reset()
        self.assertTrue(self.lab.probe()['passed'])
        for d,target in [('PC1','192.168.30.10'),('SERVER','192.168.10.10'),('SW2','192.168.99.2'),('PC1','192.168.10.11')]:
            self.assertTrue(self.lab.ping(d,target)['passed'],(d,target))

    def test_four_scenes_need_two_repairs(self):
        for code in 'ABCD':
            with self.subTest(code=code):
                self.lab.reset(code)
                first=self.lab.assistant()
                self.assertFalse(first['passed'])
                self.apply_task(first)
                second=self.lab.assistant(first['id'])
                self.assertFalse(second['passed'])
                self.apply_task(second)
                final=self.lab.assistant(second['id'])
                self.assertTrue(final['passed'])
                self.assertTrue(final['recovered'])

    def test_a_local_recovers_before_gateway(self):
        self.run_commands('SW1',['system-view','interface GE0/0/1','undo shutdown','return'])
        results=self.lab.probe()['results']
        self.assertEqual([r['passed'] for r in results],[True,False,False])

    def test_c_return_path_remains_broken(self):
        self.lab.reset('C');self.apply_task(self.lab.assistant())
        r=self.lab.ping('PC1','192.168.30.10')
        self.assertFalse(r['passed']);self.assertEqual(r['stage'],'return')
        self.assertIn('SERVER',r['forward'])

    def test_e_config_does_not_repair_physical_signal(self):
        self.lab.reset('E');first=self.lab.assistant();self.apply_task(first)
        result=self.lab.assistant(first['id'])
        self.assertFalse(result['passed']);self.assertTrue(result['task']['handoff'])
        for d in ('SW2','SW3'):
            self.run_commands(d,['system-view','interface GE0/0/24','undo shutdown','return'])
        self.assertFalse(self.lab.probe()['passed'])
        self.assertNotIn('Static',self.lab.display('SW2','display ip routing-table',{'view':'user','iface':None}))
        self.assertIn('ip route-static',self.lab.configuration('SW3'))

    def test_wrong_device_port_and_view(self):
        revision=self.lab.revision
        self.assertFalse(self.lab.execute('SW1','undo shutdown')['ok'])
        self.assertEqual(self.lab.revision,revision)
        self.run_commands('SW1',['system-view','interface GE0/0/2','undo shutdown','return'])
        self.assertFalse(self.lab.ping('PC1','192.168.10.11')['passed'])
        self.assertFalse(self.lab.execute('PC1','system-view')['ok'])

    def test_invalid_vlan_does_not_mutate(self):
        self.lab.reset();self.run_commands('SW1',['system-view','interface GE0/0/24'])
        before=list(self.lab.switches['SW1']['ports']['24']['allowed'])
        self.assertFalse(self.lab.execute('SW1','port trunk allow-pass vlan 30 5000','test')['ok'])
        self.assertEqual(before,self.lab.switches['SW1']['ports']['24']['allowed'])

    def test_keep_other_vlan_and_static_policy(self):
        self.lab.reset()
        self.run_commands('SW1',['system-view','interface GE0/0/24','undo port trunk allow-pass vlan 20','return'])
        p=self.lab.probe();self.assertTrue(all(r['passed'] for r in p['results']));self.assertFalse(p['passed'])
        self.lab.reset();self.run_commands('SW2',['system-view','undo arp static 192.168.99.2','return'])
        self.assertTrue(self.lab.ping('PC1','192.168.30.10')['passed'])
        self.assertFalse(self.lab.probe()['passed'])

    def test_query_and_svi_shutdown(self):
        self.lab.reset()
        r=self.lab.execute('SW2','display ip routing-table 192.168.30.10')
        self.assertTrue(r['ok']);self.assertIn('192.168.99.2',r['output'])
        self.run_commands('SW2',['system-view','interface Vlanif10','shutdown','return'])
        self.assertFalse(self.lab.ping('PC1','192.168.10.1')['passed'])

    def test_sessions_and_devices_keep_separate_views(self):
        self.run_commands('SW1',['system-view','interface GE0/0/1'],'a')
        self.assertEqual(self.lab.context('a','SW1')['view'],'interface')
        self.assertEqual(self.lab.context('b','SW1')['view'],'user')
        self.assertEqual(self.lab.context('a','SW2')['view'],'user')
        self.lab.reset();self.assertEqual(self.lab.context('a','SW1')['view'],'user')

    def test_stale_reports_and_probe_revisions(self):
        report=self.lab.assistant();probe=self.lab.probe()
        self.run_commands('SW1',['system-view','interface GE0/0/1','undo shutdown','return'])
        self.assertNotEqual(self.lab.revision,probe['revision'])
        self.lab.reset();fresh=self.lab.assistant(report['id'])
        self.assertTrue(fresh['passed']);self.assertFalse(fresh['recovered'])

    def test_probe_and_assistant_do_not_depend_on_scene_id(self):
        original=self.lab.probe();task=self.lab.assistant()['task']
        self.lab.scene='D'
        self.assertEqual(original['results'],self.lab.probe()['results'])
        self.assertEqual(task,self.lab.assistant()['task'])

    def test_every_scene_exposes_manual_sources(self):
        for code in 'ABCDE':
            with self.subTest(code=code):
                self.lab.reset(code)
                snapshot=self.lab.snapshot()
                self.assertGreaterEqual(len(snapshot['sources']),1)
                for source in snapshot['sources']:
                    self.assertTrue(source['section'].startswith('§'))
                    self.assertRegex(source['pdf_pages'],r'^\d+(?:–\d+)?$')
                    self.assertTrue(source['basis'])
        self.lab.reset()
        self.assertEqual(self.lab.snapshot()['sources'],[])

    def test_other_port_down_propagates_to_link_and_ping(self):
        self.lab.reset();self.run_commands('SW2',['system-view','interface GE0/0/1','shutdown','return'])
        self.assertFalse(self.lab.iface_up('SW1','24'))
        self.assertFalse(self.lab.ping('PC1','192.168.10.1')['passed'])
        self.assertTrue(self.lab.ping('PC1','192.168.10.11')['passed'])

    def test_external_assistant_distinguishes_five_demo_scenes(self):
        expected = {'A': 'diagnosis', 'B': 'diagnosis', 'C': 'auto_repair',
                    'D': 'auto_repair', 'E': 'handoff'}
        for code, category in expected.items():
            with self.subTest(code=code):
                self.lab.reset(code)
                diagnosis = self.lab.external_diagnosis()
                self.assertEqual((diagnosis['fault_code'], diagnosis['category']), (code, category))

    def test_only_auto_repair_scenes_are_mutated_and_recovered(self):
        for code in 'ABCDE':
            with self.subTest(code=code):
                self.lab.reset(code)
                before = self.lab.revision
                result = self.lab.auto_repair()
                if code in 'CD':
                    self.assertTrue(result['eligible'])
                    self.assertTrue(result['repaired'])
                    self.assertGreater(self.lab.revision, before)
                else:
                    self.assertFalse(result['eligible'])
                    self.assertFalse(result['repaired'])
                    self.assertEqual(self.lab.revision, before)

    def test_wrong_repair_skill_does_not_mutate(self):
        self.lab.reset('C')
        before = self.lab.revision
        result = self.lab.auto_repair(expected='D')
        self.assertFalse(result['eligible'])
        self.assertEqual(self.lab.revision, before)


if __name__=='__main__':unittest.main()
