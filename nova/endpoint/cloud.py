# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Cloud Controller: Implementation of EC2 REST API calls, which are
dispatched to other nodes via AMQP RPC. State is via distributed
datastore.
"""

import json
import logging
import os
import time

from nova import vendor
from twisted.internet import defer

from nova import datastore
from nova import flags
from nova import rpc
from nova import utils
from nova import exception
from nova.auth import users
from nova.compute import model
from nova.compute import network
from nova.endpoint import images
from nova.volume import storage

FLAGS = flags.FLAGS

flags.DEFINE_string('cloud_topic', 'cloud', 'the topic clouds listen on')

def _gen_key(user_id, key_name):
    """ Tuck this into UserManager """
    try:
        manager = users.UserManager.instance()
        private_key, fingerprint = manager.generate_key_pair(user_id, key_name)
    except Exception as ex:
        return {'exception': ex}
    return {'private_key': private_key, 'fingerprint': fingerprint}


class CloudController(object):
    """ CloudController provides the critical dispatch between
 inbound API calls through the endpoint and messages
 sent to the other nodes.
"""
    def __init__(self):
        self._instances = datastore.Keeper(FLAGS.instances_prefix)
        self.instdir = model.InstanceDirectory()
        self.network = network.NetworkController()
        self.setup()

    @property
    def instances(self):
        """ All instances in the system, as dicts """
        for instance in self.instdir.all:
            yield {instance['instance_id']: instance}

    @property
    def volumes(self):
        """ returns a list of all volumes """
        for volume_id in datastore.Redis.instance().smembers("volumes"):
            volume = storage.Volume(volume_id=volume_id)
            yield volume

    def __str__(self):
        return 'CloudController'

    def setup(self):
        """ Ensure the keychains and folders exist. """
        # Create keys folder, if it doesn't exist
        if not os.path.exists(FLAGS.keys_path):
            os.makedirs(os.path.abspath(FLAGS.keys_path))
        # Gen root CA, if we don't have one
        root_ca_path = os.path.join(FLAGS.ca_path, FLAGS.ca_file)
        if not os.path.exists(root_ca_path):
            start = os.getcwd()
            os.chdir(FLAGS.ca_path)
            utils.runthis("Generating root CA: %s", "sh genrootca.sh")
            os.chdir(start)
            # TODO: Do this with M2Crypto instead

    def get_instance_by_ip(self, ip):
        return self.instdir.by_ip(ip)

    def get_metadata(self, ip):
        i = self.instdir.by_ip(ip)
        if i is None:
            return None
        if i['key_name']:
            keys = {
                '0': {
                    '_name': i['key_name'],
                    'openssh-key': i['key_data']
                }
            }
        else:
            keys = ''
        data = {
            'user-data': base64.b64decode(i['user_data']),
            'meta-data': {
                'ami-id': i['image_id'],
                'ami-launch-index': i['ami_launch_index'],
                'ami-manifest-path': 'FIXME', # image property
                'block-device-mapping': { # TODO: replace with real data
                    'ami': 'sda1',
                    'ephemeral0': 'sda2',
                    'root': '/dev/sda1',
                    'swap': 'sda3'
                },
                'hostname': i['private_dns_name'], # is this public sometimes?
                'instance-action': 'none',
                'instance-id': i['instance_id'],
                'instance-type': i.get('instance_type', ''),
                'local-hostname': i['private_dns_name'],
                'local-ipv4': i['private_dns_name'], # TODO: switch to IP
                'kernel-id': i.get('kernel_id', ''),
                'placement': {
                    'availaibility-zone': i.get('availability_zone', 'nova'),
                },
                'public-hostname': i.get('dns_name', ''),
                'public-ipv4': i.get('dns_name', ''), # TODO: switch to IP
                'public-keys' : keys,
                'ramdisk-id': i.get('ramdisk_id', ''),
                'reservation-id': i['reservation_id'],
                'security-groups': i.get('groups', '')
            }
        }
        if False: # TODO: store ancestor ids
            data['ancestor-ami-ids'] = []
        if i.get('product_codes', None):
            data['product-codes'] = i['product_codes']
        return data


    def describe_availability_zones(self, context, **kwargs):
        return {'availabilityZoneInfo': [{'zoneName': 'nova',
                                          'zoneState': 'available'}]}

    def describe_key_pairs(self, context, key_name=None, **kwargs):
        key_pairs = []
        key_names = key_name and key_name or []
        if len(key_names) > 0:
            for key_name in key_names:
                key_pair = context.user.get_key_pair(key_name)
                if key_pair != None:
                    key_pairs.append({
                        'keyName': key_pair.name,
                        'keyFingerprint': key_pair.fingerprint,
                    })
        else:
            for key_pair in context.user.get_key_pairs():
                key_pairs.append({
                    'keyName': key_pair.name,
                    'keyFingerprint': key_pair.fingerprint,
                })

        return { 'keypairsSet': key_pairs }

    def create_key_pair(self, context, key_name, **kwargs):
        try:
            d = defer.Deferred()
            p = context.handler.application.settings.get('pool')
            def _complete(kwargs):
                if 'exception' in kwargs:
                    d.errback(kwargs['exception'])
                    return
                d.callback({'keyName': key_name,
                    'keyFingerprint': kwargs['fingerprint'],
                    'keyMaterial': kwargs['private_key']})
            p.apply_async(_gen_key, [context.user.id, key_name],
                callback=_complete)
            return d

        except users.UserError, e:
            raise

    def delete_key_pair(self, context, key_name, **kwargs):
        context.user.delete_key_pair(key_name)
        # aws returns true even if the key doens't exist
        return True

    def describe_security_groups(self, context, group_names, **kwargs):
        groups = { 'securityGroupSet': [] }

        # Stubbed for now to unblock other things.
        return groups

    def create_security_group(self, context, group_name, **kwargs):
        return True

    def delete_security_group(self, context, group_name, **kwargs):
        return True

    def get_console_output(self, context, instance_id, **kwargs):
        # instance_id is passed in as a list of instances
        instance = self.instdir.get(instance_id[0])
        if instance['state'] == 'pending':
            raise exception.ApiError('Cannot get output for pending instance')
        if not context.user.is_authorized(instance.get('owner_id', None)):
            raise exception.ApiError('Not authorized to view output')
        return rpc.call('%s.%s' % (FLAGS.compute_topic, instance['node_name']),
            {"method": "get_console_output",
             "args" : {"instance_id": instance_id[0]}})

    def _get_user_id(self, context):
        if context and context.user:
            return context.user.id
        else:
            return None

    def describe_volumes(self, context, **kwargs):
        volumes = []
        for volume in self.volumes:
            if context.user.is_authorized(volume.get('user_id', None)):
                v = self.format_volume(context, volume)
                volumes.append(v)
        return defer.succeed({'volumeSet': volumes})

    def format_volume(self, context, volume):
        v = {}
        v['volumeId'] = volume['volume_id']
        v['status'] = volume['status']
        v['size'] = volume['size']
        v['availabilityZone'] = volume['availability_zone']
        v['createTime'] = volume['create_time']
        if context.user.is_admin():
            v['status'] = '%s (%s, %s, %s, %s)' % (
                volume.get('status', None),
                volume.get('user_id', None),
                volume.get('node_name', None),
                volume.get('instance_id', ''),
                volume.get('mountpoint', ''))
        return v

    def create_volume(self, context, size, **kwargs):
        # TODO(vish): refactor this to create the volume object here and tell storage to create it
        res = rpc.call(FLAGS.storage_topic, {"method": "create_volume",
                                 "args" : {"size": size,
                                           "user_id": context.user.id}})
        def _format_result(result):
            volume = self._get_volume(result['result'])
            return {'volumeSet': [self.format_volume(context, volume)]}
        res.addCallback(_format_result)
        return res

    def _get_by_id(self, nodes, id):
        if nodes == {}:
            raise exception.NotFound("%s not found" % id)
        for node_name, node in nodes.iteritems():
            if node.has_key(id):
                return node_name, node[id]
        raise exception.NotFound("%s not found" % id)

    def _get_volume(self, volume_id):
        for volume in self.volumes:
            if volume['volume_id'] == volume_id:
                return volume

    def attach_volume(self, context, volume_id, instance_id, device, **kwargs):
        volume = self._get_volume(volume_id)
        storage_node = volume['node_name']
        # TODO: (joshua) Fix volumes to store creator id
        if not context.user.is_authorized(volume.get('user_id', None)):
            raise exception.ApiError("%s not authorized for %s" %
                                        (context.user.id, volume_id))
        instance = self.instdir.get(instance_id)
        compute_node = instance['node_name']
        if not context.user.is_authorized(instance.get('owner_id', None)):
            raise exception.ApiError(message="%s not authorized for %s" %
                                        (context.user.id, instance_id))
        aoe_device = volume['aoe_device']
        # Needs to get right node controller for attaching to
        # TODO: Maybe have another exchange that goes to everyone?
        rpc.cast('%s.%s' % (FLAGS.compute_topic, compute_node),
                                {"method": "attach_volume",
                                 "args" : {"aoe_device": aoe_device,
                                           "instance_id" : instance_id,
                                           "mountpoint" : device}})
        rpc.cast('%s.%s' % (FLAGS.storage_topic, storage_node),
                                {"method": "attach_volume",
                                 "args" : {"volume_id": volume_id,
                                           "instance_id" : instance_id,
                                           "mountpoint" : device}})
        return defer.succeed(True)

    def detach_volume(self, context, volume_id, **kwargs):
        # TODO(joshua): Make sure the updated state has been received first
        volume = self._get_volume(volume_id)
        storage_node = volume['node_name']
        if not context.user.is_authorized(volume.get('user_id', None)):
            raise exception.ApiError("%s not authorized for %s" %
                                        (context.user.id, volume_id))
        if 'instance_id' in volume.keys():
            instance_id = volume['instance_id']
            try:
                instance = self.instdir.get(instance_id)
                compute_node = instance['node_name']
                mountpoint = volume['mountpoint']
                if not context.user.is_authorized(
                        instance.get('owner_id', None)):
                    raise exception.ApiError(
                            "%s not authorized for %s" %
                            (context.user.id, instance_id))
                rpc.cast('%s.%s' % (FLAGS.compute_topic, compute_node),
                                {"method": "detach_volume",
                                 "args" : {"instance_id": instance_id,
                                           "mountpoint": mountpoint}})
            except exception.NotFound:
                pass
        rpc.cast('%s.%s' % (FLAGS.storage_topic, storage_node),
                                {"method": "detach_volume",
                                 "args" : {"volume_id": volume_id}})
        return defer.succeed(True)

    def _convert_to_set(self, lst, str):
        if lst == None or lst == []:
            return None
        return [{str: x} for x in lst]

    def describe_instances(self, context, **kwargs):
        return defer.succeed(self.format_instances(context.user))

    def format_instances(self, user, reservation_id = None):
        if self.instances == {}:
            return {'reservationSet': []}
        reservations = {}
        for inst in self.instances:
            instance = inst.values()[0]
            res_id = instance.get('reservation_id', 'Unknown')
            if (user.is_authorized(instance.get('owner_id', None))
                and (reservation_id == None or reservation_id == res_id)):
                i = {}
                i['instance_id'] = instance.get('instance_id', None)
                i['image_id'] = instance.get('image_id', None)
                i['instance_state'] = {
                    'code': 42,
                    'name': instance.get('state', 'pending')
                }
                i['public_dns_name'] = self.network.get_public_ip_for_instance(
                                                            i['instance_id'])
                i['private_dns_name'] = instance.get('private_dns_name', None)
                if not i['public_dns_name']:
                    i['public_dns_name'] = i['private_dns_name']
                i['dns_name'] = instance.get('dns_name', None)
                i['key_name'] = instance.get('key_name', None)
                if user.is_admin():
                    i['key_name'] = '%s (%s, %s)' % (i['key_name'],
                        instance.get('owner_id', None), instance.get('node_name',''))
                i['product_codes_set'] = self._convert_to_set(
                    instance.get('product_codes', None), 'product_code')
                i['instance_type'] = instance.get('instance_type', None)
                i['launch_time'] = instance.get('launch_time', None)
                i['ami_launch_index'] = instance.get('ami_launch_index',
                                                     None)
                if not reservations.has_key(res_id):
                    r = {}
                    r['reservation_id'] = res_id
                    r['owner_id'] = instance.get('owner_id', None)
                    r['group_set'] = self._convert_to_set(
                        instance.get('groups', None), 'group_id')
                    r['instances_set'] = []
                    reservations[res_id] = r
                reservations[res_id]['instances_set'].append(i)

        instance_response = {'reservationSet' : list(reservations.values()) }
        return instance_response

    def describe_addresses(self, context, **kwargs):
        return self.format_addresses(context.user)

    def format_addresses(self, user):
        addresses = []
        # TODO(vish): move authorization checking into network.py
        for address_record in self.network.describe_addresses(
                                    type=network.PublicNetwork):
            #logging.debug(address_record)
            if user.is_authorized(address_record[u'user_id']):
                address = {
                    'public_ip': address_record[u'address'],
                    'instance_id' : address_record.get(u'instance_id', 'free')
                }
                # FIXME: add another field for user id
                if user.is_admin():
                    address['instance_id'] = "%s (%s)" % (
                        address['instance_id'],
                        address_record[u'user_id'],
                    )
                addresses.append(address)
        # logging.debug(addresses)
        return {'addressesSet': addresses}

    def allocate_address(self, context, **kwargs):
        # TODO: Verify user is valid?
        kwargs['owner_id'] = context.user.id
        (address,network_name) = self.network.allocate_address(
                                context.user.id, type=network.PublicNetwork)
        return defer.succeed({'addressSet': [{'publicIp' : address}]})

    def release_address(self, context, **kwargs):
        self.network.deallocate_address(kwargs.get('public_ip', None))
        return defer.succeed({'releaseResponse': ["Address released."]})

    def associate_address(self, context, instance_id, **kwargs):
        instance = self.instdir.get(instance_id)
        rv = self.network.associate_address(
                            kwargs['public_ip'],
                            instance['private_dns_name'],
                            instance_id)
        return defer.succeed({'associateResponse': ["Address associated."]})

    def disassociate_address(self, context, **kwargs):
        rv = self.network.disassociate_address(kwargs['public_ip'])
        # TODO - Strip the IP from the instance
        return rv

    def run_instances(self, context, **kwargs):
        logging.debug("Going to run instances...")
        reservation_id = utils.generate_uid('r')
        launch_time = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        key_data = None
        if kwargs.has_key('key_name'):
            key_pair = context.user.get_key_pair(kwargs['key_name'])
            if not key_pair:
                raise exception.ApiError('Key Pair %s not found' %
                                         kwargs['key_name'])
            key_data = key_pair.public_key

        for num in range(int(kwargs['max_count'])):
            inst = self.instdir.new()
            # TODO(ja): add ari, aki
            inst['image_id'] = kwargs['image_id']
            inst['user_data'] = kwargs.get('user_data', '')
            inst['instance_type'] = kwargs.get('instance_type', '')
            inst['reservation_id'] = reservation_id
            inst['launch_time'] = launch_time
            inst['key_data'] = key_data or ''
            inst['key_name'] = kwargs.get('key_name', '')
            inst['owner_id'] = context.user.id
            inst['mac_address'] = utils.generate_mac()
            inst['ami_launch_index'] = num
            address, _netname = self.network.allocate_address(
                inst['owner_id'], mac=inst['mac_address'])
            network = self.network.get_users_network(str(context.user.id))
            inst['network_str'] = json.dumps(network.to_dict())
            inst['bridge_name'] = network.bridge_name
            inst['private_dns_name'] = str(address)
            # TODO: allocate expresses on the router node
            inst.save()
            rpc.cast(FLAGS.compute_topic,
                 {"method": "run_instance",
                  "args": {"instance_id" : inst.instance_id}})
            logging.debug("Casting to node for %s's instance with IP of %s" %
                      (context.user.name, inst['private_dns_name']))
        # TODO: Make the NetworkComputeNode figure out the network name from ip.
        return defer.succeed(self.format_instances(
                                context.user, reservation_id))

    def terminate_instances(self, context, instance_id, **kwargs):
        logging.debug("Going to start terminating instances")
        # TODO: return error if not authorized
        for i in instance_id:
            logging.debug("Going to try and terminate %s" % i)
            instance = self.instdir.get(i)
            #if instance['state'] == 'pending':
            #    raise exception.ApiError('Cannot terminate pending instance')
            if context.user.is_authorized(instance.get('owner_id', None)):
                try:
                    self.network.disassociate_address(
                        instance.get('public_dns_name', 'bork'))
                except:
                    pass
                if instance.get('private_dns_name', None):
                    logging.debug("Deallocating address %s" % instance.get('private_dns_name', None))
                    try:
                        self.network.deallocate_address(instance.get('private_dns_name', None))
                    except Exception, _err:
                        pass
                if instance.get('node_name', 'unassigned') != 'unassigned':  #It's also internal default
                    rpc.cast('%s.%s' % (FLAGS.compute_topic, instance['node_name']),
                             {"method": "terminate_instance",
                              "args" : {"instance_id": i}})
                else:
                    instance.destroy()
        return defer.succeed(True)

    def reboot_instances(self, context, instance_id, **kwargs):
        # TODO: return error if not authorized
        for i in instance_id:
            instance = self.instdir.get(i)
            if instance['state'] == 'pending':
                raise exception.ApiError('Cannot reboot pending instance')
            if context.user.is_authorized(instance.get('owner_id', None)):
                rpc.cast('%s.%s' % (FLAGS.node_topic, instance['node_name']),
                             {"method": "reboot_instance",
                              "args" : {"instance_id": i}})
        return defer.succeed(True)

    def delete_volume(self, context, volume_id, **kwargs):
        # TODO: return error if not authorized
        volume = self._get_volume(volume_id)
        storage_node = volume['node_name']
        if context.user.is_authorized(volume.get('user_id', None)):
            rpc.cast('%s.%s' % (FLAGS.storage_topic, storage_node),
                                {"method": "delete_volume",
                                 "args" : {"volume_id": volume_id}})
        return defer.succeed(True)

    def describe_images(self, context, image_id=None, **kwargs):
        imageSet = images.list(context.user)
        if not image_id is None:
            imageSet = [i for i in imageSet if i['imageId'] in image_id]

        return defer.succeed({'imagesSet': imageSet})

    def deregister_image(self, context, image_id, **kwargs):
        images.deregister(context.user, image_id)

        return defer.succeed({'imageId': image_id})

    def register_image(self, context, image_location=None, **kwargs):
        if image_location is None and kwargs.has_key('name'):
            image_location = kwargs['name']

        image_id = images.register(context.user, image_location)
        logging.debug("Registered %s as %s" % (image_location, image_id))

        return defer.succeed({'imageId': image_id})

    def modify_image_attribute(self, context, image_id,
                                attribute, operation_type, **kwargs):
        if attribute != 'launchPermission':
            raise exception.ApiError('only launchPermission is supported')
        if len(kwargs['user_group']) != 1 and kwargs['user_group'][0] != 'all':
            raise exception.ApiError('only group "all" is supported')
        if not operation_type in ['add', 'delete']:
            raise exception.ApiError('operation_type must be add or delete')
        result = images.modify(context.user, image_id, operation_type)
        return defer.succeed(result)

    def update_state(self, topic, value):
        """ accepts status reports from the queue and consolidates them """
        # TODO(jmc): if an instance has disappeared from
        # the node, call instance_death
        if topic == "instances":
            return defer.succeed(True)
        aggregate_state = getattr(self, topic)
        node_name = value.keys()[0]
        items = value[node_name]

        logging.debug("Updating %s state for %s" % (topic, node_name))

        for item_id in items.keys():
            if (aggregate_state.has_key('pending') and
                aggregate_state['pending'].has_key(item_id)):
                del aggregate_state['pending'][item_id]
        aggregate_state[node_name] = items

        return defer.succeed(True)
