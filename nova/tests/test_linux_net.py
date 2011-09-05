# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 NTT
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova import context
from nova import db
from nova import exception
from nova import log as logging
from nova import test
from nova import utils
from nova import flags
from nova.network import manager as network_manager

import mox

FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.tests.network')


HOST = "testhost"

instances = [{'id': 0,
              'host': 'fake_instance00',
              'hostname': 'fake_instance00'},
             {'id': 1,
              'host': 'fake_instance01',
              'hostname': 'fake_instance01'}]


addresses = [{"address" : "10.0.0.1" },
             {"address" : "10.0.0.2" },
             {"address" : "10.0.0.3" },
             {"address" : "10.0.0.4" }]


networks = [{'id': 0,
             'uuid': "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
             'label': 'test0',
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.0.0/24',
             'cidr_v6': '2001:db8::/64',
             'gateway_v6': '2001:db8::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa0',
             'bridge_interface': 'fake_fa0',
             'gateway': '192.168.0.1',
             'broadcast': '192.168.0.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'dhcp_server' : '0.0.0.0',
             'dhcp_start' : '192.168.100.1',             
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.0.2'},
            {'id': 1,
             'uuid': "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
             'label': 'test1',
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.1.0/24',
             'cidr_v6': '2001:db9::/64',
             'gateway_v6': '2001:db9::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa1',
             'bridge_interface': 'fake_fa1',
             'gateway': '192.168.1.1',
             'broadcast': '192.168.1.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'dhcp_server' : '0.0.0.0',
             'dhcp_start' : '192.168.100.1',             
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.1.2'}]


fixed_ips = [{'id': 0,
              'network_id': 0,
              'address': '192.168.0.100',
              'instance_id': 0,
              'allocated': True,
              'virtual_interface_id': 0,
              'virtual_interface' : addresses[0],
              'instance': instances[0],
              'floating_ips': []},
             {'id': 1,
              'network_id': 1,
              'address': '192.168.1.100',
              'instance_id': 0,
              'allocated': True,
              'virtual_interface_id': 1,
              'virtual_interface' : addresses[1],
              'instance': instances[0],
              'floating_ips': []},
             {'id': 2,
              'network_id': 0,
              'address': '192.168.0.101',
              'instance_id': 1,
              'allocated': True,
              'virtual_interface_id': 2,
              'virtual_interface' : addresses[2],
              'instance': instances[1],
              'floating_ips': []},
             {'id': 3,
              'network_id': 1,
              'address': '192.168.1.101',
              'instance_id': 1,
              'allocated': True,
              'virtual_interface_id': 3,
              'virtual_interface' : addresses[3],
              'instance': instances[1],
              'floating_ips': []}]




vifs = [{'id': 0,
         'address': 'DE:AD:BE:EF:00:00',
         'uuid': '00000000-0000-0000-0000-0000000000000000',
         'network_id': 0,
         'network': networks[0],
         'instance_id': 0},
        {'id': 1,
         'address': 'DE:AD:BE:EF:00:01',
         'uuid': '00000000-0000-0000-0000-0000000000000001',
         'network_id': 1,
         'network': networks[1],
         'instance_id': 0},
        {'id': 2,
         'address': 'DE:AD:BE:EF:00:02',
         'uuid': '00000000-0000-0000-0000-0000000000000002',
         'network_id': 1,
         'network': networks[1],
         'instance_id': 1},
        {'id': 3,
         'address': 'DE:AD:BE:EF:00:03',
         'uuid': '00000000-0000-0000-0000-0000000000000003',
         'network_id': 0,
         'network': networks[0],
         'instance_id': 1}]


class LinuxNetworkTestCase(test.TestCase):

    def setUp(self):
        super(LinuxNetworkTestCase, self).setUp()
        network_driver = FLAGS.network_driver
        self.driver = utils.import_object(network_driver)
        self.driver.db = db

    def test_update_dhcp(self):
        self.mox.StubOutWithMock(db, 'network_get_associated_fixed_ips')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_network')
        self.mox.StubOutWithMock(db, 'virtual_interface_get_by_instance')

        fixed_ips[1]['instance'] = instances[0] 
        db.network_get_associated_fixed_ips(mox.IgnoreArg(),
                                            mox.IgnoreArg()).AndReturn(fixed_ips)

        db.instance_get_all_by_network(mox.IgnoreArg(),
                                       mox.IgnoreArg()).AndReturn(instances)
        db.network_get_associated_fixed_ips(mox.IgnoreArg(),
                                            mox.IgnoreArg()).AndReturn(fixed_ips)
        db.virtual_interface_get_by_instance(mox.IgnoreArg(),
                                             mox.IgnoreArg()).AndReturn([vifs[0],vifs[1]])
        db.virtual_interface_get_by_instance(mox.IgnoreArg(),
                                             mox.IgnoreArg()).AndReturn([vifs[2],vifs[3]])

        self.mox.ReplayAll()
        self.driver.update_dhcp(None, "eth0", networks[0])


    def test_get_dhcp_hosts(self):
        self.mox.StubOutWithMock(db, 'network_get_associated_fixed_ips')

        fixed_ips[1]['instance'] = instances[0] 
        db.network_get_associated_fixed_ips(mox.IgnoreArg(),
                                            mox.IgnoreArg()).AndReturn(fixed_ips)

        self.mox.ReplayAll()

        hosts = self.driver.get_dhcp_hosts(None, networks[0])
        
        self.assertEquals(hosts,
                          "10.0.0.1,fake_instance00.novalocal,192.168.0.100,net:NW-i00000000-0\n" \
                          "10.0.0.2,fake_instance00.novalocal,192.168.1.100,net:NW-i00000000-1\n" \
                          "10.0.0.3,fake_instance01.novalocal,192.168.0.101,net:NW-i00000001-0\n" \
                          "10.0.0.4,fake_instance01.novalocal,192.168.1.101,net:NW-i00000001-1")

        
    def test_get_dhcp_opts(self):
        self.mox.StubOutWithMock(db, 'network_get_associated_fixed_ips')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_network')
        self.mox.StubOutWithMock(db, 'virtual_interface_get_by_instance')

        fixed_ips[1]['instance'] = instances[0] 

        db.instance_get_all_by_network(mox.IgnoreArg(),
                                       mox.IgnoreArg()).AndReturn(instances)
        db.network_get_associated_fixed_ips(mox.IgnoreArg(),
                                            mox.IgnoreArg()).AndReturn(fixed_ips)
        db.virtual_interface_get_by_instance(mox.IgnoreArg(),
                                             mox.IgnoreArg()).AndReturn([vifs[0],vifs[1]])
        db.virtual_interface_get_by_instance(mox.IgnoreArg(),
                                             mox.IgnoreArg()).AndReturn([vifs[2],vifs[3]])

        self.mox.ReplayAll()

        opts = self.driver.get_dhcp_opts(None, networks[0])
        self.assertEquals(opts, '\nNW-i00000000-1,3\nNW-i00000001-0,3\n')

        

