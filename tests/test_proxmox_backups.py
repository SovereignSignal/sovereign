import contextlib
import io
import json
import subprocess
import time
import unittest
from unittest.mock import patch

from proxmox_backups import PROBE, parse_probe, vm_status


class BackupInventory(unittest.TestCase):
    def setUp(self):
        self.inventory = {'version': 2, 'node': 'node-a', 'jobs': [
            {'id': 'nightly', 'vmids': ['102'], 'storage': 'nas', 'schedule': '01:00'}],
            'storages': [{'storage': 'local', 'backups': []}, {'storage': 'nas', 'backups': [
                {'vmid': 102, 'ctime': 9000, 'size': 1024, 'volid': 'nas:backup/new'},
                {'vmid': 102, 'ctime': 7000, 'size': 1024, 'volid': 'nas:backup/old'}]}]}

    def result(self, vmid='102'):
        inventory = parse_probe(json.dumps(self.inventory))
        return vm_status({'inventory': inventory, 'reachable': True, '_at': 10000}, vmid, 10000)

    def test_nas_inventory_and_exact_job_membership(self):
        result = self.result()
        self.assertTrue(result['scheduled'])
        self.assertEqual(result['last_backup']['storage'], 'nas')
        self.assertEqual(result['last_backup']['volid'], 'nas:backup/new')
        self.assertTrue(result['inventory_complete'])
        other = self.result('101')
        self.assertFalse(other['scheduled'])
        self.assertEqual(other['jobs'], 0)
        self.assertIsNone(other['last_dump_age_h'])

    def test_unavailable_store_preserves_found_backup_but_marks_partial(self):
        self.inventory['storages'][0] = {'storage': 'offline', 'error': 'Storage is unavailable'}
        result = self.result()
        self.assertIsNotNone(result['last_backup'])
        self.assertFalse(result['inventory_complete'])
        self.assertTrue(result['backup_errors'])

    def test_failed_inventory_is_unknown_even_when_job_exists(self):
        self.inventory['storages'] = []
        self.inventory['storage_error'] = 'TimeoutExpired'
        result = self.result()
        self.assertTrue(result['scheduled'])
        self.assertFalse(result['inventory_complete'])
        self.assertIsNone(result['last_dump_age_h'])

    def test_job_selection_failure_does_not_assert_no_schedule(self):
        self.inventory['jobs'].append({'id': 'pool-job', 'error': 'Permission denied'})
        result = self.result()
        self.assertIsNone(result['scheduled'])
        self.assertIsNone(result['jobs'])
        self.assertEqual(len(result['backup_jobs']), 1)

    def test_failed_job_list_does_not_assert_no_schedule(self):
        self.inventory['jobs'] = []
        self.inventory['jobs_error'] = 'TimeoutExpired'
        self.assertIsNone(self.result()['scheduled'])

    def test_invalid_future_metadata_never_produces_green_evidence(self):
        self.inventory['storages'][1]['backups'][0]['ctime'] = 20000
        result = self.result()
        self.assertFalse(result['inventory_complete'])
        self.assertEqual(result['last_backup']['ctime'], 7000)

    def test_incomplete_backups_are_not_counted(self):
        for item in self.inventory['storages'][1]['backups']:
            item['incomplete'] = True
        self.assertIsNone(self.result()['last_backup'])

    def test_valid_empty_inventory_is_distinct_from_unreadable(self):
        self.inventory['storages'] = []
        result = self.result()
        self.assertTrue(result['inventory_complete'])
        self.assertIsNone(result['last_backup'])

    def test_malformed_protocol_and_job_selection_fail_closed(self):
        for value in ('1\n1700 dump', 'null', '{}', '{"version":1}'):
            with self.assertRaises(ValueError):
                parse_probe(value)
        self.inventory['jobs'][0]['vmids'] = '102'
        with self.assertRaises(ValueError):
            parse_probe(json.dumps(self.inventory))


class RemoteCollector(unittest.TestCase):
    def collect(self, fake):
        output = io.StringIO()
        with patch('subprocess.run', side_effect=fake), patch('socket.gethostname', return_value='node-a'), contextlib.redirect_stdout(output):
            exec(PROBE, {})
        return parse_probe(output.getvalue())

    def test_only_enabled_jobs_and_actual_selected_guests_are_counted(self):
        calls = []

        def fake(argv, **kwargs):
            calls.append(argv)
            route = argv[2]
            if route == '/cluster/backup':
                value = [{'id': 'pool-job', 'enabled': 1, 'pool': 'pool-a'},
                         {'id': 'disabled', 'enabled': 0}, {'id': 'other-node', 'node': 'node-b'}]
            elif route.endswith('/included_volumes'):
                value = {'children': [{'id': 102, 'children': []}]}
            elif route.endswith('/storage'):
                value = [{'storage': 'nas', 'active': 1}]
            else:
                value = [{'vmid': 102, 'ctime': 9000, 'size': 100, 'volid': 'nas:backup/x'}]
            return subprocess.CompletedProcess(argv, 0, json.dumps(value), '')

        result = self.collect(fake)
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['jobs'][0]['vmids'], ['102'])
        self.assertTrue(all(c[:2] == ['pvesh', 'get'] for c in calls))
        self.assertEqual(result['storages'][0]['backups'][0]['vmid'], 102)

    def test_slow_storage_and_queued_reads_return_partial_before_ssh_deadline(self):
        def fake(argv, **kwargs):
            route = argv[2]
            if route == '/cluster/backup':
                value = [{'id': 'nightly', 'enabled': 1}]
            elif route.endswith('/included_volumes'):
                value = {'children': [{'id': 102}]}
            elif route.endswith('/storage'):
                time.sleep(2.5)
                value = [{'storage': 'nas-' + str(n), 'active': 1} for n in range(7)]
            else:
                time.sleep(kwargs['timeout'])
                raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
            return subprocess.CompletedProcess(argv, 0, json.dumps(value), '')

        start = time.monotonic()
        result = self.collect(fake)
        self.assertLess(time.monotonic() - start, 5.5)
        self.assertEqual(result['jobs'][0]['vmids'], ['102'])
        self.assertEqual(len(result['storages']), 7)
        self.assertTrue(all(row.get('error') for row in result['storages']))


if __name__ == '__main__':
    unittest.main()
