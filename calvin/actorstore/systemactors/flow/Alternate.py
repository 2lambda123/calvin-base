# -*- coding: utf-8 -*-

# Copyright (c) 2017 Ericsson AB
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

from calvin.actor.actor import Actor, condition, manage, stateguard

class Alternate(Actor):
    """
    Fetch tokens from the fan-in port in the order given by the argument 'order'
    Inputs:
      token(routing="collect-all-tagged"): incoming tokens from connected ports in order
    Outputs:
      token : tokens collected from ports as given by order
    """

    @manage(['order', 'incoming'])
    def init(self, order):
        self.order = order
        self.incoming = []

    def will_start(self):
        self.port_order = self.inports['token'].get_ordering(self.order)

    @stateguard(lambda self: len(self.incoming) > 0)
    @condition([], ['token'])
    def dispatch(self):
        next = self.incoming.pop(0)
        return (next,)

    @condition(['token'], [], metadata=True)
    def collect(self, tok):
        data, meta = tok
        tdict = dict(zip(meta['port_tag'], data))
        self.incoming += [tdict[k] for k in self.port_order]
        return None
        
    action_priority = (dispatch, collect)
