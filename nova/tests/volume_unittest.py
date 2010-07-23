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

import logging

from nova import exception
from nova import flags
from nova import test
from nova.compute import computeservice
from nova.volume import volumeservice


FLAGS = flags.FLAGS


class VolumeTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(VolumeTestCase, self).setUp()
        self.compute = computeservice.ComputeService()
        self.volume = None
        self.flags(fake_libvirt=True,
                   fake_storage=True)
        self.volume = volumeservice.VolumeService()

    def test_run_create_volume(self):
        vol_size = '0'
        user_id = 'fake'
        project_id = 'fake'
        volume_id = self.volume.create_volume(vol_size, user_id, project_id)
        # TODO(termie): get_volume returns differently than create_volume
        self.assertEqual(volume_id,
                         volumeservice.get_volume(volume_id)['volume_id'])

        rv = self.volume.delete_volume(volume_id)
        self.assertRaises(exception.Error,
                          volumeservice.get_volume,
                          volume_id)

    def test_too_big_volume(self):
        vol_size = '1001'
        user_id = 'fake'
        project_id = 'fake'
        self.assertRaises(TypeError,
                          self.volume.create_volume,
                          vol_size, user_id, project_id)

    def test_too_many_volumes(self):
        vol_size = '1'
        user_id = 'fake'
        project_id = 'fake'
        num_shelves = FLAGS.last_shelf_id - FLAGS.first_shelf_id + 1
        total_slots = FLAGS.slots_per_shelf * num_shelves
        vols = []
        for i in xrange(total_slots):
            vid = self.volume.create_volume(vol_size, user_id, project_id)
            vols.append(vid)
        self.assertRaises(volumeservice.NoMoreVolumes,
                          self.volume.create_volume,
                          vol_size, user_id, project_id)
        for id in vols:
            self.volume.delete_volume(id)

    def test_run_attach_detach_volume(self):
        # Create one volume and one compute to test with
        instance_id = "storage-test"
        vol_size = "5"
        user_id = "fake"
        project_id = 'fake'
        mountpoint = "/dev/sdf"
        volume_id = self.volume.create_volume(vol_size, user_id, project_id)

        volume_obj = volumeservice.get_volume(volume_id)
        volume_obj.start_attach(instance_id, mountpoint)
        rv = yield self.compute.attach_volume(volume_id,
                                          instance_id,
                                          mountpoint)
        self.assertEqual(volume_obj['status'], "in-use")
        self.assertEqual(volume_obj['attachStatus'], "attached")
        self.assertEqual(volume_obj['instance_id'], instance_id)
        self.assertEqual(volume_obj['mountpoint'], mountpoint)

        self.assertRaises(exception.Error,
                          self.volume.delete_volume,
                          volume_id)

        rv = yield self.volume.detach_volume(volume_id)
        volume_obj = volumeservice.get_volume(volume_id)
        self.assertEqual(volume_obj['status'], "available")

        rv = self.volume.delete_volume(volume_id)
        self.assertRaises(exception.Error,
                          volumeservice.get_volume,
                          volume_id)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass
