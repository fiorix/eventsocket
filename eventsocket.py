# coding: utf-8
# Twisted protocol for the FreeSWITCH's Event Socket
# Copyright (C) 2010 Alexandre Fiori & Arnaldo Pereira
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import types
import string
import re, urllib
from cStringIO import StringIO
from twisted.python import log
from twisted.protocols import basic
from twisted.internet import defer, reactor, protocol

"Twisted protocol for the FreeSWITCH's Event Socket"

class EventError(Exception):
    pass

class AuthError(Exception):
    pass

class _O(dict):
    """Translates dictionary keys to instance attributes"""
    def __setattr__(self, k, v):
        dict.__setitem__(self, k, v)

    def __delattr__(self, k):
        dict.__delitem__(self, k)

    def __getattribute__(self, k):
        try:
            return dict.__getitem__(self, k)
        except KeyError:
            return dict.__getattribute__(self, k)

class EventSocket(basic.LineReceiver):
    delimiter = "\n"

    def __init__(self):
        self.__ctx = None
        self.__rawlen = None
        self.__io = StringIO()
        self.__crlf = re.compile(r"[\r\n]+")
        self.__rawresponse = [
            "api/response",
            "text/disconnect-notice",
        ]

    def send(self, cmd):
        if isinstance(cmd, types.UnicodeType):
            cmd = cmd.encode("utf-8")
        self.transport.write(cmd+"\n\n")

    def sendmsg(self, name, arg=None, uuid="", lock=False):
        if isinstance(name, types.UnicodeType):
            name = name.encode("utf-8")
        if isinstance(arg, types.UnicodeType):
            arg = arg.encode("utf-8")

        self.transport.write("sendmsg %s\ncall-command: execute\n" % uuid)
        self.transport.write("execute-app-name: %s\n" % name)
        if arg:
            self.transport.write("execute-app-arg: %s\n" % arg)
        if lock is True:
            self.transport.write("event-lock: true\n")

	    self.transport.write("\n\n")

    def processLine(self, ev, line):
        try:
            k, v = self.__crlf.sub("", line).split(":", 1)
            k = k.replace("-", "_").strip()
            v = urllib.unquote(v.strip())
            ev[k] = v
        except:
            pass

    def parseEvent(self, isctx=False):
        ev = _O()
        self.__io.reset()

        for line in self.__io:
            if line == "\n":
                break
            self.processLine(ev, line)

        if not isctx:
            rawlength = ev.get("Content_Length")
            if rawlength:
                ev.rawresponse = self.__io.read(int(rawlength))

        self.__io.reset()
        self.__io.truncate()
        return ev

    def readRawResponse(self):
        self.__io.reset()
        chunk = self.__io.read(int(self.__ctx.Content_Length))
        self.__io.reset()
        self.__io.truncate()
        return _O(rawresponse=chunk)

    def dispatchEvent(self, ctx, event):
        ctx.data = _O(event.copy())
        reactor.callLater(0, self.eventReceived, _O(ctx.copy()))
        self.__ctx = self.__rawlen = None

    def eventReceived(self, ctx):
        pass

    def lineReceived(self, line):
        if line:
            self.__io.write(line+"\n")
        else:
            ctx = self.parseEvent(True)
            rawlength = ctx.get("Content_Length")
            if rawlength:
                self.__ctx = ctx
                self.__rawlen = int(rawlength)
                self.setRawMode()
            else:
                self.dispatchEvent(ctx, _O())

    def rawDataReceived(self, data):
        if self.__rawlen is None:
            rest = ""
        else:
            data, rest = data[:self.__rawlen], data[self.__rawlen:]
            self.__rawlen -= len(data)
	
        self.__io.write(data)
        if self.__rawlen == 0:
            if self.__ctx.get("Content_Type") in self.__rawresponse:
                self.dispatchEvent(self.__ctx, self.readRawResponse())
            else:
                self.dispatchEvent(self.__ctx, self.parseEvent())
                self.setLineMode(rest)
		
class EventProtocol(EventSocket):
    def __init__(self):
        EventSocket.__init__(self)

        # our internal event queue
        self.__EventQueue = []

        # callbacks by event's content-type
        self.__EventCallbacks = {
            "auth/request": self.authRequest,
            "api/response": self._apiResponse,
            "command/reply": self._commandReply,
            "text/event-plain": self._plainEvent,
            "text/disconnect-notice": self.onDisconnect,
        }

    def __protocolSend(self, name, args=""):
        deferred = defer.Deferred()
        self.__EventQueue.append((name, deferred))
        self.send("%s %s" % (name, args))
        return deferred

    def __protocolSendmsg(self, name, args=None, uuid="", lock=False):
        deferred = defer.Deferred()
        self.__EventQueue.append((name, deferred))
        self.sendmsg(name, args, uuid, lock)
        return deferred

    def eventReceived(self, ctx):
        #log.msg("GOT EVENT: %s\n" % repr(ctx), logLevel=logging.DEBUG)
        content_type = ctx.get("Content_Type", None)
        if content_type:
            method = self.__EventCallbacks.get(content_type, None)
            if method:
                return method(ctx)
            else:
                return self.unknownContentType(content_type, ctx)
    
    def authRequest(self, ctx):
        pass

    def onDisconnect(self, ctx):
        pass

    def _apiResponse(self, ctx):
        cmd, deferred = self.__EventQueue.pop(0)
        if cmd == "api":
            deferred.callback(ctx)
        else:
            deferred.errback(EventError("apiResponse on '%s': out of sync?" % cmd))

    def _commandReply(self, ctx):
        cmd, deferred = self.__EventQueue.pop(0)
        if ctx.Reply_Text.startswith("+OK"):
            deferred.callback(ctx)
        elif cmd == "auth":
            deferred.errback(AuthError("invalid password"))
        else:
            deferred.errback(EventError(ctx))

    def _plainEvent(self, ctx):
        name = ctx.data.get("Event_Name")
        if name:
            evname = "on" + string.capwords(name, "_").replace("_", "")

        method = getattr(self, evname, None)
        if method:
            return method(ctx.data)
        else:
            return self.unboundEvent(ctx.data, evname)

    def unknownContentType(self, content_type, ctx):
        log.err("[eventsocket] unknown Content-Type: %s" % content_type,
            logLevel=log.logging.DEBUG)

    def unboundEvent(self, ctx, evname):
        log.err("[eventsocket] unbound Event: %s" % evname,
            logLevel=log.logging.DEBUG)

    # EVENT SOCKET COMMANDS
    def api(self, args):
        "Please refer to http://wiki.freeswitch.org/wiki/Event_Socket#api"
        return self.__protocolSend("api", args)

    def bgapi(self, args):
        "Please refer to http://wiki.freeswitch.org/wiki/Event_Socket#bgapi"
        return self.__protocolSend("bgapi", args)

    def exit(self):
        "Please refer to http://wiki.freeswitch.org/wiki/Event_Socket#exit"
        return self.__protocolSend("exit")

    def eventplain(self, args):
        "http://wiki.freeswitch.org/wiki/Event_Socket#event"
        return self.__protocolSend("eventplain", args)

    def auth(self, args):
        """Please refer to http://wiki.freeswitch.org/wiki/Event_Socket#auth
        This method is only allowed for Inbound connections"""
        return self.__protocolSend("auth", args)

    def connect(self):
        # from now on, everything (below) is outbound only
        "Please refer to http://wiki.freeswitch.org/wiki/Event_Socket_Outbound#Using_Netcat"
        return self.__protocolSend("connect")

    def myevents(self):
        "Please refer to http://wiki.freeswitch.org/wiki/Event_Socket#event"
        return self.__protocolSend("myevents")

    def answer(self):
        "Please refer to http://wiki.freeswitch.org/wiki/Event_Socket_Outbound#Using_Netcat"
        return self.__protocolSendmsg("answer", lock=True)

    def bridge(self, args):
        """Please refer to http://wiki.freeswitch.org/wiki/Event_Socket_Outbound
        example: bridge("{ignore_early_media=true}sofia/gateway/myGW/177808")"""
        return self.__protocolSendmsg("bridge", args, lock=True)

    def hangup(self, reason=""):
        """Hangup may be used by both Inbound and Outbound connections.
        When used by Inbound connections, you may add the extra `reason`
        argument. Please refer to http://wiki.freeswitch.org/wiki/Event_Socket#hangup
        for details.
        When used by Outbound connections, the `reason` argument must be ignored.
        Please refer to http://wiki.freeswitch.org/wiki/Event_Socket_Outbound for
        details."""
        return self.__protocolSendmsg("hangup", reason, lock=True)

    def sched_api(self, args):
        "Please refer to http://wiki.freeswitch.org/wiki/Mod_commands#sched_api"
        return self.__protocolSendmsg("sched_api", args, lock=True)

    def ring_ready(self):
        "Please refer to http://wiki.freeswitch.org/wiki/Misc._Dialplan_Tools_ring_ready"
        return self.__protocolSendmsg("ring_ready")

    def record_session(self, filename):
        """Please refer to http://wiki.freeswitch.org/wiki/Misc._Dialplan_Tools_record_session
        example: record_session("/tmp/dump.gsm")"""
        return self.__protocolSendmsg("record_session", filename, lock=True)

    def bind_meta_app(self, args):
        """Please refer to http://wiki.freeswitch.org/wiki/Misc._Dialplan_Tools_bind_meta_app
        example: bind_meta_app("2 ab s record_session::/tmp/dump.gsm")"""
        return self.__protocolSendmsg("bind_meta_app", args, lock=True)

    def wait_for_silence(self, args):
        """Please refer to http://wiki.freeswitch.org/wiki/Misc._Dialplan_Tools_wait_for_silence
        example: wait_for_silence("200 15 10 5000")"""
        return self.__protocolSendmsg("wait_for_silence", args, lock=True)

    def sleep(self, milliseconds):
        """Please refer to http://wiki.freeswitch.org/wiki/Misc._Dialplan_Tools_sleep
        example: sleep(5000) / sleep("5000")"""
        return self.__protocolSendmsg("sleep", milliseconds, lock=True)

    def vmd(self, args):
        """Please refer to http://wiki.freeswitch.org/wiki/Mod_vmd
        example: vmd("start") / vmd("stop")"""
        return self.__protocolSendmsg("vmd", args, lock=True)

    def set(self, args):
        """Please refer to http://wiki.freeswitch.org/wiki/Channel_Variables
        example: set("ringback=${us-ring}")"""
        return self.__protocolSendmsg("set", args, lock=True)

    def start_dtmf(self):
        "Please refer to http://wiki.freeswitch.org/wiki/Misc._Dialplan_Tools_start_dtmf"
        return self.__protocolSendmsg("start_dtmf", lock=True)

    def start_dtmf_generate(self):
        "Please refer to http://wiki.freeswitch.org/wiki/Misc._Dialplan_Tools_start_dtmf_generate"
        return self.__protocolSendmsg("start_dtmf_generate", "true", lock=True)

    def play_fsv(self, filename):
        """Please refer to http://wiki.freeswitch.org/wiki/Mod_fsv
        example: play_fsv("/tmp/video.fsv")"""
        return self.__protocolSendmsg("play_fsv", filename, lock=True)

    def record_fsv(self, filename):
        """Please refer to http://wiki.freeswitch.org/wiki/Mod_fsv
        example: record_fsv("/tmp/video.fsv")"""
        return self.__protocolSendmsg("record_fsv", filename, lock=True)

    def playback(self, filename, terminators=None):
        """Please refer to http://wiki.freeswitch.org/wiki/Mod_playback
        The optional argument `terminators` may contain a string with
        the characters that will terminate the playback.
        example: playback("/tmp/dump.gsm", terminators="#8")
        In this case, the audio playback is automatically terminated 
        by pressing either '#' or '8'"""
        self.set("playback_terminators=%s" % terminators or "none")
        return self.__protocolSendmsg("playback", filename, lock=True)
