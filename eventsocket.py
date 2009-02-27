# coding: utf-8
# freeswitch's event socket protocol for twisted
# Copyright (C) 2009  Alexandre Fiori & Arnaldo Pereira
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

import re, urllib
from Queue import Queue
from cStringIO import StringIO
from twisted.protocols import basic
from twisted.internet import defer, reactor, protocol

def debug(s): print s

class superdict(dict):
    """Translates dictionary keys to instance attributes"""
    def __setattr__(self, k, v):
        dict.__setitem__(self, k, v)

    def __delattr__(self, k):
	dict.__delitem__(self, k)

    def __getattribute__(self, k):
	try: return dict.__getitem__(self, k)
	except KeyError: return dict.__getattribute__(self, k)

class EventSocket(basic.LineReceiver):
    delimiter = '\n'
    debug_enabled = False

    def __init__(self):
	self.ctx = None
	self.rawlen = None
	self.io = StringIO()
	self.crlf = re.compile(r'[\r\n]+')
	self.rawresponse = [
	    'api/response',
	    'text/disconnect-notice',
	]

    def send(self, cmd):
	try:
	    if type(cmd) is unicode: cmd = cmd.encode('utf-8')
	    self.transport.write(cmd)
	    self.transport.write('\n\n')
	except Exception, e:
	    if self.debug_enabled: debug('[eventsocket] send: %s' % e)

    def sendmsg(self, name, arg=None, uuid='', lock=False):
	if type(name) is unicode: name = name.encode('utf-8')
	if type(arg) is unicode: arg = arg.encode('utf-8')

	self.transport.write('sendmsg %s\ncall-command: execute\n' % uuid)
	self.transport.write('execute-app-name: %s\n' % name)
	if arg: self.transport.write('execute-app-arg: %s\n' % arg)
	if lock: self.transport.write('event-lock: true\n')
	self.transport.write('\n\n')

    def processLine(self, cur, line):
	try:
	    k, v = self.crlf.sub('', line).split(':', 1)
	    k = k.replace('-', '_').strip()
	    v = urllib.url2pathname(v.strip())
	    cur[k] = v
	    #cur[k] = v.isdigit() and int(v) or v
	except: pass

    def parseEvent(self, isctx=False):
	ev = superdict()
	self.io.reset()

	for line in self.io:
	    if line == '\n': break
	    self.processLine(ev, line)

	if not isctx:
	    rawlength = ev.get('Content_Length')
	    if rawlength: ev.rawresponse = self.io.read(int(rawlength))

	self.io.reset()
	self.io.truncate()
	return ev

    def readRawResponse(self):
	self.io.reset()
	chunk = self.io.read(int(self.ctx.Content_Length))
	self.io.reset()
	self.io.truncate()
	return superdict(rawresponse=chunk)

    def dispatchEvent(self, ctx, event):
	ctx.data = superdict(event.copy())
	reactor.callLater(0, self.eventHandler, superdict(ctx.copy()))
	self.ctx = self.rawlen = None

    def eventHandler(self, ctx):
	pass

    def lineReceived(self, line):
	if line: self.io.write(line+'\n')
	else:
	    ctx = self.parseEvent(True)
	    rawlength = ctx.get('Content_Length')
	    if rawlength:
		self.ctx = ctx
		self.rawlen = int(rawlength)
		self.setRawMode()
	    else:
		self.dispatchEvent(ctx, {})

    def rawDataReceived(self, data):
	if self.rawlen is not None:
	    data, rest = data[:self.rawlen], data[self.rawlen:]
	    self.rawlen -= len(data)
	else: rest = ''
	
	self.io.write(data)
	if self.rawlen == 0:
	    if self.ctx.get('Content_Type') in self.rawresponse:
		self.dispatchEvent(self.ctx, self.readRawResponse())
	    else:
		self.dispatchEvent(self.ctx, self.parseEvent())
	    self.setLineMode(rest)
		
class EventProtocol(EventSocket):
    def __init__(self):
	EventSocket.__init__(self)
	self._queue_ = Queue()

	# content type dispatcher
	self._content_ = {
	    'auth/request': self.authRequest,
	    'api/response': self.apiResponse,
	    'command/reply': self.commandReply,
	    'text/event-plain': self.eventPlain,
	    'text/disconnect-notice': self.disconnectNotice,
	}

	# plain event name dispatcher
	self._events_ = {
            'CUSTOM': self.onCustom,
            'CHANNEL_CREATE': self.onChannelCreate,
            'CHANNEL_DESTROY': self.onChannelDestroy,
            'CHANNEL_STATE': self.onChannelState,
            'CHANNEL_ANSWER': self.onChannelAnswer,
            'CHANNEL_HANGUP': self.onChannelHangup,
            'CHANNEL_EXECUTE': self.onChannelExecute,
            'CHANNEL_EXECUTE_COMPLETE': self.onChannelExecuteComplete,
            'CHANNEL_BRIDGE': self.onChannelBridge,
            'CHANNEL_UNBRIDGE': self.onChannelUnbridge,
            'CHANNEL_PROGRESS': self.onChannelProgress,
            'CHANNEL_PROGRESS_MEDIA': self.onChannelProgressMedia,
            'CHANNEL_OUTGOING': self.onChannelOutgoing,
            'CHANNEL_PARK': self.onChannelPark,
            'CHANNEL_UNPARK': self.onChannelUnpark,
            'CHANNEL_APPLICATION': self.onChannelApplication,
            'CHANNEL_ORIGINATE': self.onChannelOriginate,
            'CHANNEL_UUID': self.onChannelUuid,
            'API': self.onApi,
            'LOG': self.onLog,
            'INBOUND_CHAN': self.onInboundChannel,
            'OUTBOUND_CHAN': self.onOutboundChannel,
            'STARTUP': self.onStartup,
            'SHUTDOWN': self.onShutdown,
            'PUBLISH': self.onPublish,
            'UNPUBLISH': self.onUnpublish,
            'TALK': self.onTalk,
            'NOTALK': self.onNotalk,
            'SESSION_CRASH': self.onSessionCrash,
            'MODULE_LOAD': self.onModuleLoad,
            'MODULE_UNLOAD': self.onModuleUnload,
            'DTMF': self.onDtmf,
            'MESSAGE': self.onMessage,
            'PRESENCE_IN': self.onPresenceIn,
            'NOTIFY_IN': self.onNotifyIn,
            'PRESENCE_OUT': self.onPresenceOut,
            'PRESENCE_PROBE': self.onPresenceProbe,
            'MESSAGE_WAITING': self.onMessageWaiting,
            'MESSAGE_QUERY': self.onMessageQuery,
            'ROSTER': self.onRoster,
            'CODEC': self.onCodec,
            'BACKGROUND_JOB': self.onBackgroundJob,
            'DETECTED_SPEECH': self.onDetectSpeech,
            'DETECTED_TONE': self.onDetectTone,
            'PRIVATE_COMMAND': self.onPrivateCommand,
            'HEARTBEAT': self.onHeartbeat,
            'TRAP': self.onTrap,
            'ADD_SCHEDULE': self.onAddSchedule,
            'DEL_SCHEDULE': self.onDelSchedule,
            'EXE_SCHEDULE': self.onExeSchedule,
            'RE_SCHEDULE': self.onReSchedule,
            'RELOADXML': self.onReloadxml,
            'NOTIFY': self.onNotify,
            'SEND_MESSAGE': self.onSendMessage,
            'RECV_MESSAGE': self.onRecvMessage,
            'REQUEST_PARAMS': self.onRequestParams,
            'CHANNEL_DATA': self.onChannelData,
            'GENERAL': self.onGeneral,
            'COMMAND': self.onCommand,
            'SESSION_HEARTBEAT': self.onSessionHeartbeat,
            'CLIENT_DISCONNECTED': self.onClientDisconnected,
            'SERVER_DISCONNECTED': self.onServerDisconnected,
            'ALL': self.onAll
	}

	# successful command reply by type
	self._commands_ = {
	    'auth': '+OK accepted',
	    'bgapi': '+OK Job-UUID',
	    'eventplain': '+OK event',
	    'exit': '+OK bye',
	    'connect': '+OK',
	    'myevents': '+OK Events Enabled',
	    'answer': '+OK',
	    'bridge': '+OK',
	    'playback': '+OK',
	    'hangup': '+OK',
	    'sched_api': '+OK',
	    'record_session': '+OK',
	    'vmd': '+OK',
	    'set': '+OK',
	}

    # callbacks by content type
    def authSuccess(self, ev): pass
    def authFailure(self, failure): pass # self.factory.reconnect = False
    def bgapiSuccess(self, ev): pass
    def bgapiFailure(self, failure): pass
    def eventplainSuccess(self, ev): pass
    def eventplainFailure(self, failure): pass
    def myeventsSuccess(self, ev): pass
    def myeventsFailure(self, failure): pass
    def exitSuccess(self, ev): pass
    def exitFailure(self, failure): pass
    def connectSuccess(self, ev): pass
    def connectFailure(self, failure): pass
    def answerSuccess(self, ev): pass
    def answerFailure(self, failure): pass
    def bridgeSuccess(self, ev): pass
    def bridgeFailure(self, failure): pass
    def playbackSuccess(self, ev): pass
    def playbackFailure(self, failure): pass
    def hangupSuccess(self, ev): pass
    def hangupFailure(self, failure): pass
    def sched_apiSuccess(self, ev): pass
    def sched_apiFailure(self, failure): pass
    def record_sessionSuccess(self, ev): pass
    def record_sessionFailure(self, failure): pass
    def vmdSuccess(self, ev): pass
    def vmdFailure(self, failure): pass
    def setSuccess(self, ev): pass
    def setFailure(self, failure): pass
    def apiSuccess(self, ev): pass
    def apiFailure(self, failure): pass

    # callbacks by event name (plain)
    def onCustom(self, data): pass
    def onChannelCreate(self, data): pass
    def onChannelDestroy(self, data): pass
    def onChannelState(self, data): pass
    def onChannelAnswer(self, data): pass
    def onChannelHangup(self, data): pass
    def onChannelExecute(self, data): pass
    def onChannelExecuteComplete(self, data): pass
    def onChannelBridge(self, data): pass
    def onChannelUnbridge(self, data): pass
    def onChannelProgress(self, data): pass
    def onChannelProgressMedia(self, data): pass
    def onChannelOutgoing(self, data): pass
    def onChannelPark(self, data): pass
    def onChannelUnpark(self, data): pass
    def onChannelApplication(self, data): pass
    def onChannelOriginate(self, data): pass
    def onChannelUuid(self, data): pass
    def onApi(self, data): pass
    def onLog(self, data): pass
    def onInboundChannel(self, data): pass
    def onOutboundChannel(self, data): pass
    def onStartup(self, data): pass
    def onShutdown(self, data): pass
    def onPublish(self, data): pass
    def onUnpublish(self, data): pass
    def onTalk(self, data): pass
    def onNotalk(self, data): pass
    def onSessionCrash(self, data): pass
    def onModuleLoad(self, data): pass
    def onModuleUnload(self, data): pass
    def onDtmf(self, data): pass
    def onMessage(self, data): pass
    def onPresenceIn(self, data): pass
    def onNotifyIn(self, data): pass
    def onPresenceOut(self, data): pass
    def onPresenceProbe(self, data): pass
    def onMessageWaiting(self, data): pass
    def onMessageQuery(self, data): pass
    def onRoster(self, data): pass
    def onCodec(self, data): pass
    def onBackgroundJob(self, data): pass
    def onDetectSpeech(self, data): pass
    def onDetectTone(self, data): pass
    def onPrivateCommand(self, data): pass
    def onHeartbeat(self, data): pass
    def onTrap(self, data): pass
    def onAddSchedule(self, data): pass
    def onDelSchedule(self, data): pass
    def onExeSchedule(self, data): pass
    def onReSchedule(self, data): pass
    def onReloadxml(self, data): pass
    def onNotify(self, data): pass
    def onSendMessage(self, data): pass
    def onRecvMessage(self, data): pass
    def onRequestParams(self, data): pass
    def onChannelData(self, data): pass
    def onGeneral(self, data): pass
    def onCommand(self, data): pass
    def onSessionHeartbeat(self, data): pass
    def onClientDisconnected(self, data): pass
    def onServerDisconnected(self, data): pass
    def onAll(self, data): pass
    def onUnknownEvent(self, data): pass

    def _defer_(self, name):
	deferred = defer.Deferred()
	deferred.addCallback(getattr(self, '%sSuccess' % name))
	deferred.addErrback(getattr(self, '%sFailure' % name))
	self._queue_.put((name, deferred))
	return deferred

    def _exec_(self, name, args=''):
	deferred = self._defer_(name)
	self.send('%s %s' % (name, args))
	return deferred

    def _execmsg_(self, name, args=None, uuid='', lock=False):
	deferred = self._defer_(name)
	self.sendmsg(name, args, uuid, lock)
	return deferred

    def api(self, text): self._exec_('api', text)
    def bgapi(self, text): self._exec_('bgapi', text)
    def exit(self): self._exec_('exit')
    def eventplain(self, text): self._exec_('eventplain', text)
    def auth(self, text): deferred = self._exec_('auth', text) # inbound only
    def connect(self): self._exec_('connect') # everything below is outbound only
    def myevents(self): self._exec_('myevents')
    def answer(self): self._execmsg_('answer', lock=True)
    def bridge(self, text): self._execmsg_('bridge', text, lock=True)
    def hangup(self): self._execmsg_('hangup', lock=True)
    def sched_api(self, text): self._execmsg_('sched_api', text, lock=True)
    def record_session(self, text): self._execmsg_('record_session', text, lock=True)
    def vmd(self, text): self._execmsg_('vmd', text, lock=True)
    def set(self, text): self._execmsg_('set', text, lock=True)
    def playback(self, text, terminators=None):
	self.set('playback_terminators=%s' % terminators or 'none')
	self._execmsg_('playback', text, lock=True)

    def eventHandler(self, ctx):
	if self.debug_enabled: debug('GOT EVENT: %s\n' % repr(ctx))
	method = self._content_.get(ctx.get('Content_Type'), self.eventUnknown)
	return method(ctx)
	#try: method(ctx)
	#except Exception, e:
	#    debug('[eventsocket] cannot dispatch (content) event: "%s"' % repr(e))
    
    def authRequest(self, ctx):
	self.auth(self.factory.password)

    def disconnectNotice(self, ctx):
	pass

    def apiResponse(self, ctx):
	cmd, deferred = self._queue_.get()
	if cmd == 'api': deferred.callback(ctx)
	elif self.debug_enabled: debug('[eventsocket] apiResponse on "%s": out of sync?' % cmd)

    def commandReply(self, ctx):
	cmd, deferred = self._queue_.get()
	if self._commands_.has_key(cmd):
	    if ctx.Reply_Text.startswith(self._commands_.get(cmd)):
		deferred.callback(ctx)
	    else:
		deferred.errback(ctx)

    def eventPlain(self, ctx):
	name = ctx.data.get('Event_Name')
	method = self._events_.has_key(name) and \
	    self._events_[name] or self.onUnknownEvent
	return method(ctx.data)
	#try: method(ctx.data)
	#except Exception, e:
	#    debug('[eventsocket] cannot dispatch (plain) event: %s, "%s"' % (name, repr(e)))

    def eventUnknown(self, ctx):
	pass
