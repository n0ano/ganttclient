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
from M2Crypto import BIO
from M2Crypto import RSA
from M2Crypto import X509
import unittest

from nova import crypto
from nova import flags
from nova import test
from nova.auth import manager
from nova.endpoint import cloud

FLAGS = flags.FLAGS


class AuthTestCase(test.TrialTestCase):
    flush_db = False
    def setUp(self):
        super(AuthTestCase, self).setUp()
        self.flags(connection_type='fake',
                   fake_storage=True)
        self.manager = manager.AuthManager()

    def test_001_can_create_users(self):
        self.manager.create_user('test1', 'access', 'secret')
        self.manager.create_user('test2')

    def test_002_can_get_user(self):
        user = self.manager.get_user('test1')

    def test_003_can_retreive_properties(self):
        user = self.manager.get_user('test1')
        self.assertEqual('test1', user.id)
        self.assertEqual('access', user.access)
        self.assertEqual('secret', user.secret)

    def test_004_signature_is_valid(self):
        #self.assertTrue(self.manager.authenticate( **boto.generate_url ... ? ? ? ))
        pass
        #raise NotImplementedError

    def test_005_can_get_credentials(self):
        return
        credentials = self.manager.get_user('test1').get_credentials()
        self.assertEqual(credentials,
        'export EC2_ACCESS_KEY="access"\n' +
        'export EC2_SECRET_KEY="secret"\n' +
        'export EC2_URL="http://127.0.0.1:8773/services/Cloud"\n' +
        'export S3_URL="http://127.0.0.1:3333/"\n' +
        'export EC2_USER_ID="test1"\n')

    def test_006_test_key_storage(self):
        user = self.manager.get_user('test1')
        user.create_key_pair('public', 'key', 'fingerprint')
        key = user.get_key_pair('public')
        self.assertEqual('key', key.public_key)
        self.assertEqual('fingerprint', key.fingerprint)

    def test_007_test_key_generation(self):
        user = self.manager.get_user('test1')
        private_key, fingerprint = user.generate_key_pair('public2')
        key = RSA.load_key_string(private_key, callback=lambda: None)
        bio = BIO.MemoryBuffer()
        public_key = user.get_key_pair('public2').public_key
        key.save_pub_key_bio(bio)
        converted = crypto.ssl_pub_to_ssh_pub(bio.read())
        # assert key fields are equal
        self.assertEqual(public_key.split(" ")[1].strip(),
                         converted.split(" ")[1].strip())

    def test_008_can_list_key_pairs(self):
        keys = self.manager.get_user('test1').get_key_pairs()
        self.assertTrue(filter(lambda k: k.name == 'public', keys))
        self.assertTrue(filter(lambda k: k.name == 'public2', keys))

    def test_009_can_delete_key_pair(self):
        self.manager.get_user('test1').delete_key_pair('public')
        keys = self.manager.get_user('test1').get_key_pairs()
        self.assertFalse(filter(lambda k: k.name == 'public', keys))

    def test_010_can_list_users(self):
        users = self.manager.get_users()
        logging.warn(users)
        self.assertTrue(filter(lambda u: u.id == 'test1', users))

    def test_101_can_add_user_role(self):
        self.assertFalse(self.manager.has_role('test1', 'itsec'))
        self.manager.add_role('test1', 'itsec')
        self.assertTrue(self.manager.has_role('test1', 'itsec'))

    def test_199_can_remove_user_role(self):
        self.assertTrue(self.manager.has_role('test1', 'itsec'))
        self.manager.remove_role('test1', 'itsec')
        self.assertFalse(self.manager.has_role('test1', 'itsec'))

    def test_201_can_create_project(self):
        project = self.manager.create_project('testproj', 'test1', 'A test project', ['test1'])
        self.assertTrue(filter(lambda p: p.name == 'testproj', self.manager.get_projects()))
        self.assertEqual(project.name, 'testproj')
        self.assertEqual(project.description, 'A test project')
        self.assertEqual(project.project_manager_id, 'test1')
        self.assertTrue(project.has_member('test1'))

    def test_202_user1_is_project_member(self):
        self.assertTrue(self.manager.get_user('test1').is_project_member('testproj'))

    def test_203_user2_is_not_project_member(self):
        self.assertFalse(self.manager.get_user('test2').is_project_member('testproj'))

    def test_204_user1_is_project_manager(self):
        self.assertTrue(self.manager.get_user('test1').is_project_manager('testproj'))

    def test_205_user2_is_not_project_manager(self):
        self.assertFalse(self.manager.get_user('test2').is_project_manager('testproj'))

    def test_206_can_add_user_to_project(self):
        self.manager.add_to_project('test2', 'testproj')
        self.assertTrue(self.manager.get_project('testproj').has_member('test2'))

    def test_207_can_remove_user_from_project(self):
        self.manager.remove_from_project('test2', 'testproj')
        self.assertFalse(self.manager.get_project('testproj').has_member('test2'))

    def test_208_can_remove_add_user_with_role(self):
        self.manager.add_to_project('test2', 'testproj')
        self.manager.add_role('test2', 'developer', 'testproj')
        self.manager.remove_from_project('test2', 'testproj')
        self.assertFalse(self.manager.has_role('test2', 'developer', 'testproj'))
        self.manager.add_to_project('test2', 'testproj')
        self.manager.remove_from_project('test2', 'testproj')

    def test_209_can_generate_x509(self):
        # MUST HAVE RUN CLOUD SETUP BY NOW
        self.cloud = cloud.CloudController()
        self.cloud.setup()
        _key, cert_str = self.manager._generate_x509_cert('test1', 'testproj')
        logging.debug(cert_str)

        # Need to verify that it's signed by the right intermediate CA
        full_chain = crypto.fetch_ca(project_id='testproj', chain=True)
        int_cert = crypto.fetch_ca(project_id='testproj', chain=False)
        cloud_cert = crypto.fetch_ca()
        logging.debug("CA chain:\n\n =====\n%s\n\n=====" % full_chain)
        signed_cert = X509.load_cert_string(cert_str)
        chain_cert = X509.load_cert_string(full_chain)
        int_cert = X509.load_cert_string(int_cert)
        cloud_cert = X509.load_cert_string(cloud_cert)
        self.assertTrue(signed_cert.verify(chain_cert.get_pubkey()))
        self.assertTrue(signed_cert.verify(int_cert.get_pubkey()))

        if not FLAGS.use_intermediate_ca:
            self.assertTrue(signed_cert.verify(cloud_cert.get_pubkey()))
        else:
            self.assertFalse(signed_cert.verify(cloud_cert.get_pubkey()))

    def test_210_can_add_project_role(self):
        project = self.manager.get_project('testproj')
        self.assertFalse(project.has_role('test1', 'sysadmin'))
        self.manager.add_role('test1', 'sysadmin')
        self.assertFalse(project.has_role('test1', 'sysadmin'))
        project.add_role('test1', 'sysadmin')
        self.assertTrue(project.has_role('test1', 'sysadmin'))

    def test_211_can_list_project_roles(self):
        project = self.manager.get_project('testproj')
        user = self.manager.get_user('test1')
        self.manager.add_role(user, 'netadmin', project)
        roles = self.manager.get_user_roles(user)
        self.assertTrue('sysadmin' in roles)
        self.assertFalse('netadmin' in roles)
        project_roles = self.manager.get_user_roles(user, project)
        self.assertTrue('sysadmin' in project_roles)
        self.assertTrue('netadmin' in project_roles)
        # has role should be false because global role is missing
        self.assertFalse(self.manager.has_role(user, 'netadmin', project))


    def test_212_can_remove_project_role(self):
        project = self.manager.get_project('testproj')
        self.assertTrue(project.has_role('test1', 'sysadmin'))
        project.remove_role('test1', 'sysadmin')
        self.assertFalse(project.has_role('test1', 'sysadmin'))
        self.manager.remove_role('test1', 'sysadmin')
        self.assertFalse(project.has_role('test1', 'sysadmin'))

    def test_214_can_retrieve_project_by_user(self):
        project = self.manager.create_project('testproj2', 'test2', 'Another test project', ['test2'])
        self.assert_(len(self.manager.get_projects()) > 1)
        self.assertEqual(len(self.manager.get_projects('test2')), 1)

    def test_299_can_delete_project(self):
        self.manager.delete_project('testproj')
        self.assertFalse(filter(lambda p: p.name == 'testproj', self.manager.get_projects()))
        self.manager.delete_project('testproj2')

    def test_999_can_delete_users(self):
        self.manager.delete_user('test1')
        users = self.manager.get_users()
        self.assertFalse(filter(lambda u: u.id == 'test1', users))
        self.manager.delete_user('test2')
        self.assertEqual(self.manager.get_user('test2'), None)


if __name__ == "__main__":
    # TODO: Implement use_fake as an option
    unittest.main()
