# -*- coding: utf-8 -*-

# Copyright (c) 2015-2016 Ericsson AB
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

import importlib
from jsonschema import validate

from calvin.utilities import calvinconfig
from calvin.utilities import calvinlogger

_log = calvinlogger.get_logger(__name__)
_conf = calvinconfig.get()
_calvinsys = None

def get_calvinsys():
    """ Returns the calvinsys singleton"""
    global _calvinsys
    if _calvinsys is None:
        _calvinsys = CalvinSys()
    return _calvinsys

class CalvinSys(object):

    """
    Handles calvinsys objects.
    """

    def __init__(self):
        self._node = None
        self.capabilities = {}
        self._objects = {}
        self._actors = {}

    def init(self, node):
        """
        Get and setup capabilities from config
        """
        self._node = node
        capabilities = _conf.get('calvinsys', 'capabilities') or {}
        blacklist = _conf.get(None, 'capabilities_blacklist') or []
        for capability in blacklist:
            _ = capabilities.pop(capability, None)
        for key, value in capabilities.iteritems():
            module = value['module']
            value['path'] = module
            value['module'] = None
            _log.info("Capability '%s' registered with module '%s'" % (key, module))
        self.capabilities = capabilities

    def _get_class(self, capability_name):
        """
        Open a capability and return corresponding object
        """
        capability = self.capabilities.get(capability_name, None)
        if capability is None:
            raise Exception("No such capability '%s'", capability_name)
        pymodule = capability.get('module', None)
        if pymodule is None:
            pymodule = importlib.import_module('calvin.runtime.south.calvinsys.' + capability['path'])
            if pymodule is None:
                raise Exception("Failed to import module '%s'" % capability_name)
            capability['module'] = pymodule
        class_name = capability["path"].rsplit(".", 1)
        pyclass = getattr(pymodule, class_name[1])
        if not pyclass:
            raise Exception("No entry %s in %s" % (capability_name, capability['path']))
        return capability, pyclass

    def _open(self, actor, capability_name, **kwargs):
        capability, pyclass = self._get_class(capability_name)
        obj = pyclass(calvinsys=self, name=capability_name, actor=actor)
        # Ensure platform attributes take precedence
        data = kwargs
        data.update(capability['attributes'])
        validate(data, obj.init_schema)
        obj.init(**data)
        return obj

    def scheduler_wakeup(self, actor):
        """
        Trigger scheduler
        """
        self._node.sched.trigger_loop(actor_ids=[actor.id])

    def has_capability(self, requirement):
        """
        Returns True if "requirement" is satisfied in this system,
        otherwise False.
        """
        return requirement in self.capabilities

    def list_capabilities(self):
        """
        Returns list of requirements this system satisfies
        """
        return self.capabilities.keys()

    def _get_capability_object(self, ref, required=True):
        """
            Get capability object given a reference. If required (default), then raise exception if no such reference.
        """
        cap = self._objects.get(ref, None)
        if not cap and required:
            raise Exception("Invalid reference {}. Available references: {}".format(ref, self._objects))
        return cap["obj"] if cap else None

    # Calvinsys objects api

    def can_write(self, ref):
        obj = self._get_capability_object(ref)
        data = obj.can_write()
        try:
            validate(data, obj.can_write_schema)
        except Exception as e:
            _log.exception("Failed to validate schema, exception={}".format(e))
        return data

    def write(self, ref, data):
        obj = self._get_capability_object(ref)
        try:
            validate(data, obj.write_schema)
            obj.write(data)
        except Exception as e:
            _log.exception("Failed to validate schema, exception={}".format(e))

    def can_read(self, ref):
        obj = self._get_capability_object(ref)
        data = obj.can_read()
        try:
            validate(data, obj.can_read_schema)
        except Exception as e:
            _log.exception("Failed to validate schema, exception={}".format(e))
        return data

    def read(self, ref):
        obj = self._get_capability_object(ref)
        data = obj.read()
        try:
            validate(data, obj.read_schema)
        except Exception as e:
            _log.exception("Failed to validate schema, exception={}".format(e))
        return data

    def close(self, ref):
        obj = self._get_capability_object(ref, required=False)
        if obj:
            obj.close()
            self._objects.pop(ref)
            for actor, refs in self._actors.iteritems():
                if ref in refs:
                    refs.remove(ref)


    def open(self, capability_name, actor, **kwargs):
        """
        Open a capability and return corresponding object
        """
        obj = self._open(actor, capability_name, **kwargs)

        csobjects = self._actors.setdefault(actor, [])
        if len(csobjects) == 0:
            idx = 0
        else :
            idx = int(csobjects[-1].rsplit('#', 1)[1])+1

        ref = "{}#{}".format(actor.id, idx)
        self._objects[ref] = {"name": capability_name, "obj": obj, "args": kwargs}
        self._actors.get(actor).append(ref)

        return ref

    def close_all(self, actor):
        """
            Close and free all open calvinsys objects for given actor
        """
        if actor in self._actors:
            references = self._actors.pop(actor)
            for ref in references:
                self.close(ref)

    def serialize(self, actor):
        """
            serializes calvinsys objects used by given actor
        """
        if actor in self._actors:
            references = self._actors.get(actor)
        else :
            # Nothing to do here
            return {}

        serz = {}
        for ref in references:
            csobj = self._objects.get(ref)
            state = csobj["obj"].serialize() # serialize object
            serz[ref] = {"name": csobj["name"], "obj": state, "args": csobj["args"]}
        return serz

    def deserialize(self, actor, csobjects):
        """
            deserializes a list of calvinsys objects and associates them with given actor
        """
        for ref, csobj in csobjects.items():
            capability, pyclass = self._get_class(csobj["name"])
            # Ensure platform attributes take precedence
            data = csobj["args"]
            data.update(capability['attributes'])
            csobj["obj"] = pyclass(calvinsys=self, name=csobj["name"], actor=actor).deserialize(state=csobj["obj"], **data)
            self._objects[ref] = csobj
            self._actors.setdefault(actor, []).append(ref)
