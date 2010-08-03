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
#
# PORTIONS OF THIS FILE ARE FROM:
# http://code.google.com/p/boto
# Copyright (c) 2006-2009 Mitch Garnaat http://garnaat.org/
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

"""
Utility class for parsing signed AMI manifests.
"""

import base64
import hashlib
import hmac
import logging
import urllib
import boto

from nova.exception import Error

class Signer(object):
    """ hacked up code from boto/connection.py """

    def __init__(self, secret_key):
        self.hmac = hmac.new(secret_key, digestmod=hashlib.sha1)
        if hashlib.sha256:
            self.hmac_256 = hmac.new(secret_key, digestmod=hashlib.sha256)

    def s3_authorization(self, headers, verb, path):
        c_string = boto.utils.canonical_string(verb, path, headers)
        hmac = self.hmac.copy()
        hmac.update(c_string)
        b64_hmac = base64.encodestring(hmac.digest()).strip()
        return b64_hmac

    def generate(self, params, verb, server_string, path):
        if params['SignatureVersion'] == '0':
            return self._calc_signature_0(params)
        if params['SignatureVersion'] == '1':
            return self._calc_signature_1(params)
        if params['SignatureVersion'] == '2':
            return self._calc_signature_2(params, verb, server_string, path)
        raise Error('Unknown Signature Version: %s' % self.SignatureVersion)


    def _get_utf8_value(self, value):
        if not isinstance(value, str) and not isinstance(value, unicode):
            value = str(value)
        if isinstance(value, unicode):
            return value.encode('utf-8')
        else:
            return value

    def _calc_signature_0(self, params):
        s = params['Action'] + params['Timestamp']
        self.hmac.update(s)
        keys = params.keys()
        keys.sort(cmp = lambda x, y: cmp(x.lower(), y.lower()))
        pairs = []
        for key in keys:
            val = self._get_utf8_value(params[key])
            pairs.append(key + '=' + urllib.quote(val))
        return base64.b64encode(self.hmac.digest())

    def _calc_signature_1(self, params):
        keys = params.keys()
        keys.sort(cmp = lambda x, y: cmp(x.lower(), y.lower()))
        pairs = []
        for key in keys:
            self.hmac.update(key)
            val = self._get_utf8_value(params[key])
            self.hmac.update(val)
            pairs.append(key + '=' + urllib.quote(val))
        return base64.b64encode(self.hmac.digest())

    def _calc_signature_2(self, params, verb, server_string, path):
        logging.debug('using _calc_signature_2')
        string_to_sign = '%s\n%s\n%s\n' % (verb, server_string, path)
        if self.hmac_256:
            hmac = self.hmac_256
            params['SignatureMethod'] = 'HmacSHA256'
        else:
            hmac = self.hmac
            params['SignatureMethod'] = 'HmacSHA1'
        keys = params.keys()
        keys.sort()
        pairs = []
        for key in keys:
            val = self._get_utf8_value(params[key])
            pairs.append(urllib.quote(key, safe='') + '=' + urllib.quote(val, safe='-_~'))
        qs = '&'.join(pairs)
        logging.debug('query string: %s' % qs)
        string_to_sign += qs
        logging.debug('string_to_sign: %s' % string_to_sign)
        hmac.update(string_to_sign)
        b64 = base64.b64encode(hmac.digest())
        logging.debug('len(b64)=%d' % len(b64))
        logging.debug('base64 encoded digest: %s' % b64)
        return b64

if __name__ == '__main__':
    print Signer('foo').generate({"SignatureMethod": 'HmacSHA256', 'SignatureVersion': '2'}, "get", "server", "/foo")
