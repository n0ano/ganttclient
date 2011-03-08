# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Unit Tests for network code
"""
import IPy
import os

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import utils
from nova.auth import manager
from nova.tests.network import base
from nova.tests.network import binpath,\
    lease_ip, release_ip

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


class VlanNetworkTestCase(base.NetworkTestCase):
    """Test cases for network code"""
    def test_public_network_association(self):
        """Makes sure that we can allocaate a public ip"""
        # TODO(vish): better way of adding floating ips
        self.context._project = self.projects[0]
        self.context.project_id = self.projects[0].id
        pubnet = IPy.IP(flags.FLAGS.floating_range)
        address = str(pubnet[0])
        try:
            db.floating_ip_get_by_address(context.get_admin_context(), address)
        except exception.NotFound:
            db.floating_ip_create(context.get_admin_context(),
                                  {'address': address,
                                   'host': FLAGS.host})
        float_addr = self.network.allocate_floating_ip(self.context,
                                                       self.projects[0].id)
        fix_addr = self._create_address(0)
        lease_ip(fix_addr)
        self.assertEqual(float_addr, str(pubnet[0]))
        self.network.associate_floating_ip(self.context, float_addr, fix_addr)
        address = db.instance_get_floating_address(context.get_admin_context(),
                                                   self.instance_id)
        self.assertEqual(address, float_addr)
        self.network.disassociate_floating_ip(self.context, float_addr)
        address = db.instance_get_floating_address(context.get_admin_context(),
                                                   self.instance_id)
        self.assertEqual(address, None)
        self.network.deallocate_floating_ip(self.context, float_addr)
        self.network.deallocate_fixed_ip(self.context, fix_addr)
        release_ip(fix_addr)
        db.floating_ip_destroy(context.get_admin_context(), float_addr)

    def test_allocate_deallocate_fixed_ip(self):
        """Makes sure that we can allocate and deallocate a fixed ip"""
        address = self._create_address(0)
        self.assertTrue(self._is_allocated_in_project(address,
                                                      self.projects[0].id))
        lease_ip(address)
        self._deallocate_address(0, address)

        # Doesn't go away until it's dhcp released
        self.assertTrue(self._is_allocated_in_project(address,
                                                      self.projects[0].id))

        release_ip(address)
        self.assertFalse(self._is_allocated_in_project(address,
                                                       self.projects[0].id))

    def test_side_effects(self):
        """Ensures allocating and releasing has no side effects"""
        address = self._create_address(0)
        address2 = self._create_address(1, self.instance2_id)

        self.assertTrue(self._is_allocated_in_project(address,
                                                      self.projects[0].id))
        self.assertTrue(self._is_allocated_in_project(address2,
                                                      self.projects[1].id))
        self.assertFalse(self._is_allocated_in_project(address,
                                                       self.projects[1].id))

        # Addresses are allocated before they're issued
        lease_ip(address)
        lease_ip(address2)

        self._deallocate_address(0, address)
        release_ip(address)
        self.assertFalse(self._is_allocated_in_project(address,
                                                       self.projects[0].id))

        # First address release shouldn't affect the second
        self.assertTrue(self._is_allocated_in_project(address2,
                                                      self.projects[1].id))

        self._deallocate_address(1, address2)
        release_ip(address2)
        self.assertFalse(self._is_allocated_in_project(address2,
                                                 self.projects[1].id))

    def test_subnet_edge(self):
        """Makes sure that private ips don't overlap"""
        first = self._create_address(0)
        lease_ip(first)
        instance_ids = []
        for i in range(1, FLAGS.num_networks):
            instance_ref = self._create_instance(i, mac=utils.generate_mac())
            instance_ids.append(instance_ref['id'])
            address = self._create_address(i, instance_ref['id'])
            instance_ref = self._create_instance(i, mac=utils.generate_mac())
            instance_ids.append(instance_ref['id'])
            address2 = self._create_address(i, instance_ref['id'])
            instance_ref = self._create_instance(i, mac=utils.generate_mac())
            instance_ids.append(instance_ref['id'])
            address3 = self._create_address(i, instance_ref['id'])
            lease_ip(address)
            lease_ip(address2)
            lease_ip(address3)
            self.context._project = self.projects[i]
            self.context.project_id = self.projects[i].id
            self.assertFalse(self._is_allocated_in_project(address,
                                                     self.projects[0].id))
            self.assertFalse(self._is_allocated_in_project(address2,
                                                     self.projects[0].id))
            self.assertFalse(self._is_allocated_in_project(address3,
                                                     self.projects[0].id))
            self.network.deallocate_fixed_ip(self.context, address)
            self.network.deallocate_fixed_ip(self.context, address2)
            self.network.deallocate_fixed_ip(self.context, address3)
            release_ip(address)
            release_ip(address2)
            release_ip(address3)
        for instance_id in instance_ids:
            db.instance_destroy(context.get_admin_context(), instance_id)
        self.context._project = self.projects[0]
        self.context.project_id = self.projects[0].id
        self.network.deallocate_fixed_ip(self.context, first)
        self._deallocate_address(0, first)
        release_ip(first)

    def test_vpn_ip_and_port_looks_valid(self):
        """Ensure the vpn ip and port are reasonable"""
        self.assert_(self.projects[0].vpn_ip)
        self.assert_(self.projects[0].vpn_port >= FLAGS.vpn_start)
        self.assert_(self.projects[0].vpn_port <= FLAGS.vpn_start +
                                                  FLAGS.num_networks)

    def test_too_many_networks(self):
        """Ensure error is raised if we run out of networks"""
        projects = []
        networks_left = (FLAGS.num_networks -
                         db.network_count(context.get_admin_context()))
        for i in range(networks_left):
            project = self.manager.create_project('many%s' % i, self.user)
            projects.append(project)
            db.project_get_network(context.get_admin_context(), project.id)
        project = self.manager.create_project('last', self.user)
        projects.append(project)
        self.assertRaises(db.NoMoreNetworks,
                          db.project_get_network,
                          context.get_admin_context(),
                          project.id)
        for project in projects:
            self.manager.delete_project(project)

    def test_ips_are_reused(self):
        """Makes sure that ip addresses that are deallocated get reused"""
        address = self._create_address(0)
        lease_ip(address)
        self.network.deallocate_fixed_ip(self.context, address)
        release_ip(address)

        address2 = self._create_address(0)
        self.assertEqual(address, address2)
        lease_ip(address)
        self.network.deallocate_fixed_ip(self.context, address2)
        release_ip(address)

    def test_too_many_addresses(self):
        """Test for a NoMoreAddresses exception when all fixed ips are used.
        """
        admin_context = context.get_admin_context()
        network = db.project_get_network(admin_context, self.projects[0].id)
        num_available_ips = db.network_count_available_ips(admin_context,
                                                           network['id'])
        addresses = []
        instance_ids = []
        for i in range(num_available_ips):
            instance_ref = self._create_instance(0)
            instance_ids.append(instance_ref['id'])
            address = self._create_address(0, instance_ref['id'])
            addresses.append(address)
            lease_ip(address)

        ip_count = db.network_count_available_ips(context.get_admin_context(),
                                                  network['id'])
        self.assertEqual(ip_count, 0)
        self.assertRaises(db.NoMoreAddresses,
                          self.network.allocate_fixed_ip,
                          self.context,
                          'foo')

        for i in range(num_available_ips):
            self.network.deallocate_fixed_ip(self.context, addresses[i])
            release_ip(addresses[i])
            db.instance_destroy(context.get_admin_context(), instance_ids[i])
        ip_count = db.network_count_available_ips(context.get_admin_context(),
                                                  network['id'])
        self.assertEqual(ip_count, num_available_ips)

    def _is_allocated_in_project(self, address, project_id):
        """Returns true if address is in specified project"""
        project_net = db.project_get_network(context.get_admin_context(),
                                             project_id)
        network = db.fixed_ip_get_network(context.get_admin_context(),
                                          address)
        instance = db.fixed_ip_get_instance(context.get_admin_context(),
                                            address)
        # instance exists until release
        return instance is not None and network['id'] == project_net['id']

    def run(self, result=None):
        if(FLAGS.network_manager == 'nova.network.manager.VlanManager'):
            super(VlanNetworkTestCase, self).run(result)
