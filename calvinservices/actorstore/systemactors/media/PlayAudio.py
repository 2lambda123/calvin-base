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

from calvin.actor.actor import Actor, manage, condition, stateguard, calvinsys


class PlayAudio(Actor):

    """
    documentation:
    - Play audio file <audiofile>.
    ports:
    - direction: in
      help: starts playing file when true
      name: play
    requires:
    - media.audio
    """

    @manage(['player'])
    def init(self, audiofile):
        self.player = calvinsys.open(self, "media.audio", audiofile=audiofile)

    @stateguard(lambda actor: calvinsys.can_write(actor.player))
    @condition(['play'], [])
    def play(self, play):
        if bool(play):
            calvinsys.write(self.player, None)

    action_priority = (play, )
    