# -*- coding: utf-8 -*-

# Copyright (c) 2015 Ericsson AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import uuid
import logging

from calvin.common import calvinlogger

_log = calvinlogger.get_logger(__name__)

def get_debug_info(start=-2, limit=10):
    if _log.getEffectiveLevel() == logging.INFO:
        import traceback
        return traceback.format_stack(limit=10)[:start]
    return None

def dump_debug_info(debug_info):
    if debug_info:
        _log.info("Calvin callback created here: \n" + ''.join(debug_info))


class CalvinCB(object):
    """ This is calvins generic function caller used in callbacks etc.
        func: the function that will be called
        args: any positional arguments specific for this callback
        kwargs: any key-value arguments specific for this callback

        For example see example code at end of file.
    """
    def __init__(self, func, *args, **kwargs):
        super(CalvinCB, self).__init__()
        self._debug_info = get_debug_info()
        self._id = str(uuid.uuid4())
        self.func = func
        self.args = list(args)
        self.kwargs = kwargs
        # Ref a functions name if we wrap several CalvinCB and need to take __str__
        try:
            self.name = self.func.__name__
        except:
            self.name = self.func.name if hasattr(self.func, 'name') else "unknown"


    def __call__(self, *args, **kwargs):
        """ Call function
            args: any positional arguments for this call of the callback
            kwargs: any key-value arguments for this call of the callback

            returns the callbacks return value when no exception
        """
        try:
            return self.func(*(self.args + list(args)), **dict(self.kwargs, **kwargs))
        except AssertionError as error:
            raise error
        except (TypeError, Exception):
            name = "unknown"
            if hasattr(self.func, 'name'):
                name = self.func.name
            elif hasattr(self.func, "__name__"):
                name = self.func.__name__

            _log.exception("When callback %s %s(%s, %s) is called caught the exception" % (
                self.func, name, (self.args + list(args)), dict(self.kwargs, **kwargs)))
            dump_debug_info(self._debug_info)

    def __str__(self):
        return "CalvinCB - " + self.name + "(%s, %s)" % (self.args, self.kwargs)


class CalvinCBClass(object):
    """ Callback class that handles named sets of callbacks
        that outside users can register callbacks for. The class
        is inherited by another class to add callback support.

        callbacks: a dictionary of names with list of callbacks
                   {'n1': [cb1, cb2], ...}
                   cb1, cb2 is CalvinCB type

        callback_valid_names: None or a list of strings setting the
                   valid names of callbacks, when None all names allowed
                   when list all non-matching names will be dropped during
                   registering.

        For example see example code at end of file.
    """
    def __init__(self, callbacks=None, callback_valid_names=None):
        self.__callbacks = {}
        self.__callback_valid_names = callback_valid_names
        if not callbacks:
            return
        for name, cbs in callbacks.items():
            if self.__callback_valid_names is None or name in self.__callback_valid_names:
                self.__callbacks[name] = dict()
                for cb in cbs:
                    if not isinstance(cb, CalvinCB):
                        raise Exception("One callback of name %s is not a CalvinCB object %s, %s", name, type(cb), repr(cb))
                    self.__callbacks[name][cb._id] = cb
    
    # Unused
    def get_callbacks_by_name(self, name):
        if name not in self.__callbacks:
            _log.info("Did not find callbacks for %s" % name)
            return None
        return self.__callbacks[name]

    def callback_valid_names(self):
        """ Returns list of valid or current names that callbacks can be registered on."""
        return self.__callback_valid_names if self.__callback_valid_names else list(self.__callbacks.keys())

    def callback_register(self, name, cb):
        """ Registers a callback on a name.
            name: a name string
            cb: a callback of CalvinCB type
        """
        if self.__callback_valid_names is None or name in self.__callback_valid_names:
            if name not in self.__callbacks:
                self.__callbacks[name] = {}
            self.__callbacks[name][cb._id] = cb

    # Unused
    def callback_unregister(self, _id):
        """ Unregisters a callback
            _id: the id of the callback to unregister (CalvinCB have an attribute id)
        """
        for k, v in self.__callbacks.items():
            if _id in v:
                self.__callbacks[k].pop(_id)
                if not self.__callbacks[k]:
                    del self.__callbacks[k]
                break

    def _callback_execute(self, name, *args, **kwargs):
        """ Will execute the callbacks registered for the name
            name: a name string
            args: any positional arguments for this call of the callbacks
            kwargs: any key-value arguments for this call of the callbacks

            returns a dictionary of the individual callbacks return value, with callback id as key.
        """
        reply = {}

        if name not in self.__callbacks:
            _log.debug("No callback registered for '%s'" % name)
            # tb_str = ''
            # for a in traceback.format_stack(limit=10)[:-1]:
            #     tb_str += a
            # _log.debug('\n' + tb_str)
            return reply

        # So we can change __callbacks from callbacks
        local_copy = self.__callbacks[name].copy()
        for cb in local_copy.values():
            try:
                reply[cb._id] = cb(*args, **kwargs)
            except:
                _log.exception("Callback '%s' failed on %s(%s, %s)" % (name, cb, args, kwargs))
        return reply
