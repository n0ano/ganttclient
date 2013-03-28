import mox
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils


XENSM_TYPE = 'xensm'
ISCSI_TYPE = 'iscsi'


def get_fake_connection_data(sr_type):
    fakes = {XENSM_TYPE: {'sr_uuid': 'falseSR',
                          'name_label': 'fake_storage',
                          'name_description': 'test purposes',
                          'server': 'myserver',
                          'serverpath': '/local/scratch/myname',
                          'sr_type': 'nfs',
                          'introduce_sr_keys': ['server',
                                                'serverpath',
                                                'sr_type'],
                          'vdi_uuid': 'falseVDI'},
             ISCSI_TYPE: {'volume_id': 'fake_volume_id',
                          'target_lun': 1,
                          'target_iqn': 'fake_iqn:volume-fake_volume_id',
                          'target_portal': u'localhost:3260',
                          'target_discovered': False}, }
    return fakes[sr_type]


class GetInstanceForVdisForSrTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(GetInstanceForVdisForSrTestCase, self).setUp()
        self.flags(disable_process_locking=True,
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',)

    def test_get_instance_vdis_for_sr(self):
        vm_ref = fake.create_vm("foo", "Running")
        sr_ref = fake.create_sr()

        vdi_1 = fake.create_vdi('vdiname1', sr_ref)
        vdi_2 = fake.create_vdi('vdiname2', sr_ref)

        for vdi_ref in [vdi_1, vdi_2]:
            fake.create_vbd(vm_ref, vdi_ref)

        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = list(vm_utils.get_instance_vdis_for_sr(
            driver._session, vm_ref, sr_ref))

        self.assertEquals([vdi_1, vdi_2], result)

    def test_get_instance_vdis_for_sr_no_vbd(self):
        vm_ref = fake.create_vm("foo", "Running")
        sr_ref = fake.create_sr()

        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = list(vm_utils.get_instance_vdis_for_sr(
            driver._session, vm_ref, sr_ref))

        self.assertEquals([], result)

    def test_get_vdi_uuid_for_volume_with_sr_uuid(self):
        connection_data = get_fake_connection_data(XENSM_TYPE)
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        vdi_uuid = vm_utils.get_vdi_uuid_for_volume(
                driver._session, connection_data)
        self.assertEquals(vdi_uuid, 'falseVDI')

    def test_get_vdi_uuid_for_volume_failure(self):
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        def bad_introduce_sr(session, sr_uuid, label, sr_params):
            return None

        self.stubs.Set(volume_utils, 'introduce_sr', bad_introduce_sr)
        connection_data = get_fake_connection_data(XENSM_TYPE)
        self.assertRaises(exception.NovaException,
                          vm_utils.get_vdi_uuid_for_volume,
                          driver._session, connection_data)

    def test_get_vdi_uuid_for_volume_from_iscsi_vol_missing_sr_uuid(self):
        connection_data = get_fake_connection_data(ISCSI_TYPE)
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        vdi_uuid = vm_utils.get_vdi_uuid_for_volume(
                driver._session, connection_data)
        self.assertNotEquals(vdi_uuid, None)


class VMRefOrRaiseVMFoundTestCase(test.TestCase):

    def test_lookup_call(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn('ignored')

        mock.ReplayAll()
        vm_utils.vm_ref_or_raise('session', 'somename')
        mock.VerifyAll()

    def test_return_value(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn('vmref')

        mock.ReplayAll()
        self.assertEquals(
            'vmref', vm_utils.vm_ref_or_raise('session', 'somename'))
        mock.VerifyAll()


class VMRefOrRaiseVMNotFoundTestCase(test.TestCase):

    def test_exception_raised(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn(None)

        mock.ReplayAll()
        self.assertRaises(
            exception.InstanceNotFound,
            lambda: vm_utils.vm_ref_or_raise('session', 'somename')
        )
        mock.VerifyAll()

    def test_exception_msg_contains_vm_name(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn(None)

        mock.ReplayAll()
        try:
            vm_utils.vm_ref_or_raise('session', 'somename')
        except exception.InstanceNotFound as e:
            self.assertTrue(
                'somename' in str(e))
        mock.VerifyAll()


class BittorrentTestCase(stubs.XenAPITestBase):
    def setUp(self):
        super(BittorrentTestCase, self).setUp()
        self.context = context.get_admin_context()

    def test_image_uses_bittorrent(self):
        sys_meta = {'image_bittorrent': True}
        instance = db.instance_create(self.context,
                                      {'system_metadata': sys_meta})
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.flags(xenapi_torrent_images='some')
        self.assertTrue(vm_utils._image_uses_bittorrent(self.context,
                                                        instance))

    def _test_create_image(self, cache_type):
        sys_meta = {'image_cache_in_nova': True}
        instance = db.instance_create(self.context,
                                      {'system_metadata': sys_meta})
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.flags(cache_images=cache_type)

        was = {'called': None}

        def fake_create_cached_image(*args):
            was['called'] = 'some'
            return {}
        self.stubs.Set(vm_utils, '_create_cached_image',
                       fake_create_cached_image)

        def fake_fetch_image(*args):
            was['called'] = 'none'
            return {}
        self.stubs.Set(vm_utils, '_fetch_image',
                       fake_fetch_image)

        vm_utils._create_image(self.context, None, instance,
                               'foo', 'bar', 'baz')

        self.assertEqual(was['called'], cache_type)

    def test_create_image_cached(self):
        self._test_create_image('some')

    def test_create_image_uncached(self):
        self._test_create_image('none')


class CreateVBDTestCase(test.TestCase):
    def setUp(self):
        super(CreateVBDTestCase, self).setUp()

        class FakeSession():
            def call_xenapi(*args):
                pass

        self.session = FakeSession()
        self.mock = mox.Mox()
        self.mock.StubOutWithMock(self.session, 'call_xenapi')
        self.vbd_rec = self._generate_vbd_rec()

    def _generate_vbd_rec(self):
        vbd_rec = {}
        vbd_rec['VM'] = 'vm_ref'
        vbd_rec['VDI'] = 'vdi_ref'
        vbd_rec['userdevice'] = '0'
        vbd_rec['bootable'] = False
        vbd_rec['mode'] = 'RW'
        vbd_rec['type'] = 'disk'
        vbd_rec['unpluggable'] = True
        vbd_rec['empty'] = False
        vbd_rec['other_config'] = {}
        vbd_rec['qos_algorithm_type'] = ''
        vbd_rec['qos_algorithm_params'] = {}
        vbd_rec['qos_supported_algorithms'] = []
        return vbd_rec

    def test_create_vbd_default_args(self):
        self.session.call_xenapi('VBD.create',
                self.vbd_rec).AndReturn("vbd_ref")
        self.mock.ReplayAll()

        result = vm_utils.create_vbd(self.session, "vm_ref", "vdi_ref", 0)
        self.assertEquals(result, "vbd_ref")
        self.mock.VerifyAll()

    def test_create_vbd_osvol(self):
        self.session.call_xenapi('VBD.create',
                self.vbd_rec).AndReturn("vbd_ref")
        self.session.call_xenapi('VBD.add_to_other_config', "vbd_ref",
                                 "osvol", "True")
        self.mock.ReplayAll()
        result = vm_utils.create_vbd(self.session, "vm_ref", "vdi_ref", 0,
                                     osvol=True)
        self.assertEquals(result, "vbd_ref")
        self.mock.VerifyAll()

    def test_create_vbd_extra_args(self):
        self.vbd_rec['VDI'] = 'OpaqueRef:NULL'
        self.vbd_rec['type'] = 'a'
        self.vbd_rec['mode'] = 'RO'
        self.vbd_rec['bootable'] = True
        self.vbd_rec['empty'] = True
        self.vbd_rec['unpluggable'] = False
        self.session.call_xenapi('VBD.create',
                self.vbd_rec).AndReturn("vbd_ref")
        self.mock.ReplayAll()

        result = vm_utils.create_vbd(self.session, "vm_ref", None, 0,
                vbd_type="a", read_only=True, bootable=True,
                empty=True, unpluggable=False)
        self.assertEquals(result, "vbd_ref")
        self.mock.VerifyAll()

    def test_attach_cd(self):
        self.mock.StubOutWithMock(vm_utils, 'create_vbd')

        vm_utils.create_vbd(self.session, "vm_ref", None, 1,
                vbd_type='cd', read_only=True, bootable=True,
                empty=True, unpluggable=False).AndReturn("vbd_ref")
        self.session.call_xenapi('VBD.insert', "vbd_ref", "vdi_ref")
        self.mock.ReplayAll()

        result = vm_utils.attach_cd(self.session, "vm_ref", "vdi_ref", 1)
        self.assertEquals(result, "vbd_ref")
        self.mock.VerifyAll()
