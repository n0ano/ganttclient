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
Twisted daemon helpers, specifically to parse out gFlags from twisted flags,
manage pid files and support syslogging.
"""

import logging
import os
import signal
import sys
import time
from twisted.scripts import twistd
from twisted.python import log
from twisted.python import reflect
from twisted.python import runtime
from twisted.python import usage

from nova import flags


if runtime.platformType == "win32":
    from twisted.scripts._twistw import ServerOptions
else:
    from twisted.scripts._twistd_unix import ServerOptions


FLAGS = flags.FLAGS


class TwistdServerOptions(ServerOptions):
    def parseArgs(self, *args):
        return


def WrapTwistedOptions(wrapped):
    class TwistedOptionsToFlags(wrapped):
        subCommands = None
        def __init__(self):
            # NOTE(termie): _data exists because Twisted stuff expects
            #               to be able to set arbitrary things that are
            #               not actual flags
            self._data = {}
            self._flagHandlers = {}
            self._paramHandlers = {}

            # Absorb the twistd flags into our FLAGS
            self._absorbFlags()
            self._absorbParameters()
            self._absorbHandlers()

            super(TwistedOptionsToFlags, self).__init__()

        def _absorbFlags(self):
            twistd_flags = []
            reflect.accumulateClassList(self.__class__, 'optFlags', twistd_flags)
            for flag in twistd_flags:
                key = flag[0].replace('-', '_')
                flags.DEFINE_boolean(key, None, str(flag[-1]))

        def _absorbParameters(self):
            twistd_params = []
            reflect.accumulateClassList(self.__class__, 'optParameters', twistd_params)
            for param in twistd_params:
                key = param[0].replace('-', '_')
                flags.DEFINE_string(key, param[2], str(param[-1]))

        def _absorbHandlers(self):
            twistd_handlers = {}
            reflect.addMethodNamesToDict(self.__class__, twistd_handlers, "opt_")

            # NOTE(termie): Much of the following is derived/copied from
            #               twisted.python.usage with the express purpose of
            #               providing compatibility
            for name in twistd_handlers.keys():
                method = getattr(self, 'opt_'+name)

                takesArg = not usage.flagFunction(method, name)
                doc = getattr(method, '__doc__', None)
                if not doc:
                    doc = 'undocumented'

                if not takesArg:
                    if name not in FLAGS:
                        flags.DEFINE_boolean(name, None, doc)
                    self._flagHandlers[name] = method
                else:
                    if name not in FLAGS:
                        flags.DEFINE_string(name, None, doc)
                    self._paramHandlers[name] = method


        def _doHandlers(self):
            for flag, handler in self._flagHandlers.iteritems():
                if self[flag]:
                    handler()
            for param, handler in self._paramHandlers.iteritems():
                if self[param] is not None:
                    handler(self[param])

        def __str__(self):
            return str(FLAGS)

        def parseOptions(self, options=None):
            if options is None:
                options = sys.argv
            else:
                options.insert(0, '')

            args = FLAGS(options)
            argv = args[1:]
            # ignore subcommands

            try:
                self.parseArgs(*argv)
            except TypeError:
                raise usage.UsageError("Wrong number of arguments.")

            self.postOptions()
            return args

        def parseArgs(self, *args):
            # TODO(termie): figure out a decent way of dealing with args
            #return
            super(TwistedOptionsToFlags, self).parseArgs(*args)

        def postOptions(self):
            self._doHandlers()

            super(TwistedOptionsToFlags, self).postOptions()

        def __getitem__(self, key):
            key = key.replace('-', '_')
            try:
                return getattr(FLAGS, key)
            except (AttributeError, KeyError):
                return self._data[key]

        def __setitem__(self, key, value):
            key = key.replace('-', '_')
            try:
                return setattr(FLAGS, key, value)
            except (AttributeError, KeyError):
                self._data[key] = value

        def get(self, key, default):
            key = key.replace('-', '_')
            try:
                return getattr(FLAGS, key)
            except (AttributeError, KeyError):
                self._data.get(key, default)

    return TwistedOptionsToFlags


def stop(pidfile):
    """
    Stop the daemon
    """
    # Get the pid from the pidfile
    try:
        pf = file(pidfile,'r')
        pid = int(pf.read().strip())
        pf.close()
    except IOError:
        pid = None

    if not pid:
        message = "pidfile %s does not exist. Daemon not running?\n"
        sys.stderr.write(message % pidfile)
        return # not an error in a restart

    # Try killing the daemon process
    try:
        while 1:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.1)
    except OSError, err:
        err = str(err)
        if err.find("No such process") > 0:
            if os.path.exists(pidfile):
                os.remove(pidfile)
        else:
            print str(err)
            sys.exit(1)


def serve(filename):
    logging.debug("Serving %s" % filename)
    name = os.path.basename(filename)
    OptionsClass = WrapTwistedOptions(TwistdServerOptions)
    options = OptionsClass()
    argv = options.parseOptions()
    logging.getLogger('amqplib').setLevel(logging.WARN)
    FLAGS.python = filename
    FLAGS.no_save = True
    if not FLAGS.pidfile:
        FLAGS.pidfile = '%s.pid' % name
    elif FLAGS.pidfile.endswith('twistd.pid'):
        FLAGS.pidfile = FLAGS.pidfile.replace('twistd.pid', '%s.pid' % name)
    # NOTE(vish): if we're running nodaemon, redirect the log to stdout
    if FLAGS.nodaemon and not FLAGS.logfile:
        FLAGS.logfile = "-"
    if not FLAGS.logfile:
        FLAGS.logfile = '%s.log' % name
    elif FLAGS.logfile.endswith('twistd.log'):
        FLAGS.logfile = FLAGS.logfile.replace('twistd.log', '%s.log' % name)
    if not FLAGS.prefix:
        FLAGS.prefix = name
    elif FLAGS.prefix.endswith('twisted'):
        FLAGS.prefix = FLAGS.prefix.replace('twisted', name)

    action = 'start'
    if len(argv) > 1:
        action = argv.pop()

    if action == 'stop':
        stop(FLAGS.pidfile)
        sys.exit()
    elif action == 'restart':
        stop(FLAGS.pidfile)
    elif action == 'start':
        pass
    else:
        print 'usage: %s [options] [start|stop|restart]' % argv[0]
        sys.exit(1)

    class NoNewlineFormatter(logging.Formatter):
        """Strips newlines from default formatter"""
        def format(self, record):
            """Grabs default formatter's output and strips newlines"""
            data = logging.Formatter.format(self, record)
            return data.replace("\n", "--")

    # NOTE(vish): syslog-ng doesn't handle newlines from trackbacks very well
    formatter = NoNewlineFormatter(
        '(%(name)s): %(levelname)s %(message)s')
    handler = logging.StreamHandler(log.StdioOnnaStick())
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)

    if FLAGS.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    logging.debug("Full set of FLAGS:")
    for flag in FLAGS:
        logging.debug("%s : %s" % (flag, FLAGS.get(flag, None)))

    twistd.runApp(options)
