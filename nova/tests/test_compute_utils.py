# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

"""Tests For miscellaneous util methods used with compute."""

from nova.compute import instance_types
from nova.compute import utils as compute_utils
from nova import context
from nova import db
from nova import flags
import nova.image.fake
from nova import log as logging
from nova.notifier import test_notifier
from nova.openstack.common import importutils
from nova import test
from nova.tests import fake_network
from nova import utils


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
flags.DECLARE('stub_network', 'nova.compute.manager')


class UsageInfoTestCase(test.TestCase):

    def setUp(self):
        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1,
                                                          spectacular=True)

        super(UsageInfoTestCase, self).setUp()
        self.stubs.Set(nova.network.API, 'get_instance_nw_info',
                       fake_get_nw_info)

        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   stub_network=True,
                   notification_driver='nova.notifier.test_notifier',
                   network_manager='nova.network.manager.FlatManager')
        self.compute = importutils.import_object(FLAGS.compute_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.image.fake._FakeImageService, 'show', fake_show)

    def _create_instance(self, params={}):
        """Create a test instance"""
        inst = {}
        inst['image_ref'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst.update(params)
        return db.instance_create(self.context, inst)['id']

    def test_notify_usage_exists(self):
        """Ensure 'exists' notification generates appropriate usage data."""
        instance_id = self._create_instance()
        instance = db.instance_get(self.context, instance_id)
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        db.instance_system_metadata_update(self.context, instance['uuid'],
                sys_metadata, False)
        compute_utils.notify_usage_exists(self.context, instance)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.exists')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance.uuid)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEquals(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        image_ref_url = "%s/images/1" % utils.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_notify_usage_exists_instance_not_found(self):
        """Ensure 'exists' notification generates appropriate usage data."""
        instance_id = self._create_instance()
        instance = db.instance_get(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance['uuid'])
        compute_utils.notify_usage_exists(self.context, instance)
        msg = test_notifier.NOTIFICATIONS[-1]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.exists')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance.uuid)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEquals(payload['image_meta'], {})
        image_ref_url = "%s/images/1" % utils.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)
