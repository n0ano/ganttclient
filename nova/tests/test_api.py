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

"""Unit tests for the API endpoint"""

import boto
from boto.ec2 import regioninfo
import httplib
import random
import StringIO
import webob

from nova import context
from nova import test
from nova.api import ec2
from nova.api.ec2 import cloud
from nova.api.ec2 import apirequest
from nova.auth import manager


class FakeHttplibSocket(object):
    """a fake socket implementation for httplib.HTTPResponse, trivial"""
    def __init__(self, response_string):
        self._buffer = StringIO.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer"""
        return self._buffer


class FakeHttplibConnection(object):
    """A fake httplib.HTTPConnection for boto to use

    requests made via this connection actually get translated and routed into
    our WSGI app, we then wait for the response and turn it back into
    the httplib.HTTPResponse that boto expects.
    """
    def __init__(self, app, host, is_secure=False):
        self.app = app
        self.host = host

    def request(self, method, path, data, headers):
        req = webob.Request.blank(path)
        req.method = method
        req.body = data
        req.headers = headers
        req.headers['Accept'] = 'text/html'
        req.host = self.host
        # Call the WSGI app, get the HTTP response
        resp = str(req.get_response(self.app))
        # For some reason, the response doesn't have "HTTP/1.0 " prepended; I
        # guess that's a function the web server usually provides.
        resp = "HTTP/1.0 %s" % resp
        sock = FakeHttplibSocket(resp)
        self.http_response = httplib.HTTPResponse(sock)
        self.http_response.begin()

    def getresponse(self):
        return self.http_response

    def close(self):
        """Required for compatibility with boto/tornado"""
        pass


class XmlConversionTestCase(test.TestCase):
    """Unit test api xml conversion"""
    def test_number_conversion(self):
        conv = apirequest._try_convert
        self.assertEqual(conv('None'), None)
        self.assertEqual(conv('True'), True)
        self.assertEqual(conv('False'), False)
        self.assertEqual(conv('0'), 0)
        self.assertEqual(conv('42'), 42)
        self.assertEqual(conv('3.14'), 3.14)
        self.assertEqual(conv('-57.12'), -57.12)
        self.assertEqual(conv('0x57'), 0x57)
        self.assertEqual(conv('-0x57'), -0x57)
        self.assertEqual(conv('-'), '-')
        self.assertEqual(conv('-0'), 0)


class ApiEc2TestCase(test.TestCase):
    """Unit test for the cloud controller on an EC2 API"""
    def setUp(self):
        super(ApiEc2TestCase, self).setUp()
        self.manager = manager.AuthManager()
        self.host = '127.0.0.1'
        self.app = ec2.Authenticate(ec2.Requestify(ec2.Executor(),
                       'nova.api.ec2.cloud.CloudController'))

    def expect_http(self, host=None, is_secure=False):
        """Returns a new EC2 connection"""
        self.ec2 = boto.connect_ec2(
                aws_access_key_id='fake',
                aws_secret_access_key='fake',
                is_secure=False,
                region=regioninfo.RegionInfo(None, 'test', self.host),
                port=8773,
                path='/services/Cloud')

        self.mox.StubOutWithMock(self.ec2, 'new_http_connection')
        http = FakeHttplibConnection(
                self.app, '%s:8773' % (self.host), False)
        # pylint: disable-msg=E1103
        self.ec2.new_http_connection(host, is_secure).AndReturn(http)
        return http

    def test_describe_instances(self):
        """Test that, after creating a user and a project, the describe
        instances call to the API works properly"""
        self.expect_http()
        self.mox.ReplayAll()
        user = self.manager.create_user('fake', 'fake', 'fake')
        project = self.manager.create_project('fake', 'fake', 'fake')
        self.assertEqual(self.ec2.get_all_instances(), [])
        self.manager.delete_project(project)
        self.manager.delete_user(user)

    def test_get_all_key_pairs(self):
        """Test that, after creating a user and project and generating
         a key pair, that the API call to list key pairs works properly"""
        self.expect_http()
        self.mox.ReplayAll()
        keyname = "".join(random.choice("sdiuisudfsdcnpaqwertasd") \
                          for x in range(random.randint(4, 8)))
        user = self.manager.create_user('fake', 'fake', 'fake')
        project = self.manager.create_project('fake', 'fake', 'fake')
        # NOTE(vish): create depends on pool, so call helper directly
        cloud._gen_key(context.get_admin_context(), user.id, keyname)

        rv = self.ec2.get_all_key_pairs()
        results = [k for k in rv if k.name == keyname]
        self.assertEquals(len(results), 1)
        self.manager.delete_project(project)
        self.manager.delete_user(user)

    def test_get_all_security_groups(self):
        """Test that we can retrieve security groups"""
        self.expect_http()
        self.mox.ReplayAll()
        user = self.manager.create_user('fake', 'fake', 'fake', admin=True)
        project = self.manager.create_project('fake', 'fake', 'fake')

        rv = self.ec2.get_all_security_groups()

        self.assertEquals(len(rv), 1)
        self.assertEquals(rv[0].name, 'default')

        self.manager.delete_project(project)
        self.manager.delete_user(user)

    def test_create_delete_security_group(self):
        """Test that we can create a security group"""
        self.expect_http()
        self.mox.ReplayAll()
        user = self.manager.create_user('fake', 'fake', 'fake', admin=True)
        project = self.manager.create_project('fake', 'fake', 'fake')

        # At the moment, you need both of these to actually be netadmin
        self.manager.add_role('fake', 'netadmin')
        project.add_role('fake', 'netadmin')

        security_group_name = "".join(random.choice("sdiuisudfsdcnpaqwertasd")
                                      for x in range(random.randint(4, 8)))

        self.ec2.create_security_group(security_group_name, 'test group')

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()
        self.assertEquals(len(rv), 2)
        self.assertTrue(security_group_name in [group.name for group in rv])

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

        self.manager.delete_project(project)
        self.manager.delete_user(user)

    def test_authorize_revoke_security_group_cidr(self):
        """
        Test that we can add and remove CIDR based rules
        to a security group
        """
        self.expect_http()
        self.mox.ReplayAll()
        user = self.manager.create_user('fake', 'fake', 'fake')
        project = self.manager.create_project('fake', 'fake', 'fake')

        # At the moment, you need both of these to actually be netadmin
        self.manager.add_role('fake', 'netadmin')
        project.add_role('fake', 'netadmin')

        security_group_name = "".join(random.choice("sdiuisudfsdcnpaqwertasd")
                                      for x in range(random.randint(4, 8)))

        group = self.ec2.create_security_group(security_group_name,
                                               'test group')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.authorize('tcp', 80, 81, '0.0.0.0/0')

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()
        # I don't bother checkng that we actually find it here,
        # because the create/delete unit test further up should
        # be good enough for that.
        for group in rv:
            if group.name == security_group_name:
                self.assertEquals(len(group.rules), 1)
                self.assertEquals(int(group.rules[0].from_port), 80)
                self.assertEquals(int(group.rules[0].to_port), 81)
                self.assertEquals(len(group.rules[0].grants), 1)
                self.assertEquals(str(group.rules[0].grants[0]), '0.0.0.0/0')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.revoke('tcp', 80, 81, '0.0.0.0/0')

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        rv = self.ec2.get_all_security_groups()

        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0].name, 'default')

        self.manager.delete_project(project)
        self.manager.delete_user(user)

        return

    def test_authorize_revoke_security_group_cidr_v6(self):
        """
        Test that we can add and remove CIDR based rules
        to a security group for IPv6
        """
        self.expect_http()
        self.mox.ReplayAll()
        user = self.manager.create_user('fake', 'fake', 'fake')
        project = self.manager.create_project('fake', 'fake', 'fake')

        # At the moment, you need both of these to actually be netadmin
        self.manager.add_role('fake', 'netadmin')
        project.add_role('fake', 'netadmin')

        security_group_name = "".join(random.choice("sdiuisudfsdcnpaqwertasd")
                                      for x in range(random.randint(4, 8)))

        group = self.ec2.create_security_group(security_group_name,
                                               'test group')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.authorize('tcp', 80, 81, '::/0')

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()
        # I don't bother checkng that we actually find it here,
        # because the create/delete unit test further up should
        # be good enough for that.
        for group in rv:
            if group.name == security_group_name:
                self.assertEquals(len(group.rules), 1)
                self.assertEquals(int(group.rules[0].from_port), 80)
                self.assertEquals(int(group.rules[0].to_port), 81)
                self.assertEquals(len(group.rules[0].grants), 1)
                self.assertEquals(str(group.rules[0].grants[0]), '::/0')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.revoke('tcp', 80, 81, '::/0')

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        rv = self.ec2.get_all_security_groups()

        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0].name, 'default')

        self.manager.delete_project(project)
        self.manager.delete_user(user)

        return

    def test_authorize_revoke_security_group_foreign_group(self):
        """
        Test that we can grant and revoke another security group access
        to a security group
        """
        self.expect_http()
        self.mox.ReplayAll()
        user = self.manager.create_user('fake', 'fake', 'fake', admin=True)
        project = self.manager.create_project('fake', 'fake', 'fake')

        # At the moment, you need both of these to actually be netadmin
        self.manager.add_role('fake', 'netadmin')
        project.add_role('fake', 'netadmin')

        rand_string = 'sdiuisudfsdcnpaqwertasd'
        security_group_name = "".join(random.choice(rand_string)
                                      for x in range(random.randint(4, 8)))
        other_security_group_name = "".join(random.choice(rand_string)
                                      for x in range(random.randint(4, 8)))

        group = self.ec2.create_security_group(security_group_name,
                                               'test group')

        self.expect_http()
        self.mox.ReplayAll()

        other_group = self.ec2.create_security_group(other_security_group_name,
                                                     'some other group')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.authorize(src_group=other_group)

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()

        # I don't bother checkng that we actually find it here,
        # because the create/delete unit test further up should
        # be good enough for that.
        for group in rv:
            if group.name == security_group_name:
                self.assertEquals(len(group.rules), 1)
                self.assertEquals(len(group.rules[0].grants), 1)
                self.assertEquals(str(group.rules[0].grants[0]), '%s-%s' %
                                  (other_security_group_name, 'fake'))

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()

        for group in rv:
            if group.name == security_group_name:
                self.expect_http()
                self.mox.ReplayAll()
                group.connection = self.ec2
                group.revoke(src_group=other_group)

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

        self.manager.delete_project(project)
        self.manager.delete_user(user)

        return
