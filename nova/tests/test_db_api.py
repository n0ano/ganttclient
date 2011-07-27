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

"""Unit tests for the DB API"""

from nova import test
from nova import context
from nova import db
from nova import flags
from nova.auth import manager

FLAGS = flags.FLAGS


def _setup_networking(instance_id, ip='1.2.3.4', flo_addr='1.2.1.2'):
    ctxt = context.get_admin_context()
    network_ref = db.project_get_networks(ctxt,
                                           'fake',
                                           associate=True)[0]
    vif = {'address': '56:12:12:12:12:12',
           'network_id': network_ref['id'],
           'instance_id': instance_id}
    vif_ref = db.virtual_interface_create(ctxt, vif)

    fixed_ip = {'address': ip,
                'network_id': network_ref['id'],
                'virtual_interface_id': vif_ref['id'],
                'allocated': True,
                'instance_id': instance_id}
    db.fixed_ip_create(ctxt, fixed_ip)
    fix_ref = db.fixed_ip_get_by_address(ctxt, ip)
    db.floating_ip_create(ctxt, {'address': flo_addr,
                                        'fixed_ip_id': fix_ref.id})


class DbApiTestCase(test.TestCase):
    def setUp(self):
        super(DbApiTestCase, self).setUp()
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('admin', 'admin', 'admin', True)
        self.project = self.manager.create_project('proj', 'admin', 'proj')
        self.context = context.RequestContext(user=self.user,
                                              project=self.project)

    def tearDown(self):
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        super(DbApiTestCase, self).tearDown()

    def test_instance_get_project_vpn(self):
        result = db.fixed_ip_get_all(self.context)
        values = {'instance_type_id': FLAGS.default_instance_type,
                  'image_ref': FLAGS.vpn_image_id,
                  'project_id': self.project.id}
        instance = db.instance_create(self.context, values)
        result = db.instance_get_project_vpn(self.context, self.project.id)
        self.assertEqual(instance.id, result.id)

    def test_instance_get_project_vpn_joins(self):
        result = db.fixed_ip_get_all(self.context)
        values = {'instance_type_id': FLAGS.default_instance_type,
                  'image_ref': FLAGS.vpn_image_id,
                  'project_id': self.project.id}
        instance = db.instance_create(self.context, values)
        _setup_networking(instance.id)
        result = db.instance_get_project_vpn(self.context, self.project.id)
        self.assertEqual(instance.id, result.id)
        self.assertEqual(result['fixed_ips'][0]['floating_ips'][0].address,
                         '1.2.1.2')
