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
	    debug('[eventsocket] send: %s' % e)

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
            'CUSTOM': self.gotCustom,
            'CHANNEL_CREATE': self.gotChannelCreate,
            'CHANNEL_DESTROY': self.gotChannelDestroy,
            'CHANNEL_STATE': self.gotChannelState,
            'CHANNEL_ANSWER': self.gotChannelAnswer,
            'CHANNEL_HANGUP': self.gotChannelHangup,
            'CHANNEL_EXECUTE': self.gotChannelExecute,
            'CHANNEL_EXECUTE_COMPLETE': self.gotChannelExecuteComplete,
            'CHANNEL_BRIDGE': self.gotChannelBridge,
            'CHANNEL_UNBRIDGE': self.gotChannelUnbridge,
            'CHANNEL_PROGRESS': self.gotChannelProgress,
            'CHANNEL_PROGRESS_MEDIA': self.gotChannelProgressMedia,
            'CHANNEL_OUTGOING': self.gotChannelOutgoing,
            'CHANNEL_PARK': self.gotChannelPark,
            'CHANNEL_UNPARK': self.gotChannelUnpark,
            'CHANNEL_APPLICATION': self.gotChannelApplication,
            'CHANNEL_ORIGINATE': self.gotChannelOriginate,
            'CHANNEL_UUID': self.gotChannelUuid,
            'API': self.gotApi,
            'LOG': self.gotLog,
            'INBOUND_CHAN': self.gotInboundChannel,
            'OUTBOUND_CHAN': self.gotOutboundChannel,
            'STARTUP': self.gotStartup,
            'SHUTDOWN': self.gotShutdown,
            'PUBLISH': self.gotPublish,
            'UNPUBLISH': self.gotUnpublish,
            'TALK': self.gotTalk,
            'NOTALK': self.gotNotalk,
            'SESSION_CRASH': self.gotSessionCrash,
            'MODULE_LOAD': self.gotModuleLoad,
            'MODULE_UNLOAD': self.gotModuleUnload,
            'DTMF': self.gotDtmf,
            'MESSAGE': self.gotMessage,
            'PRESENCE_IN': self.gotPresenceIn,
            'NOTIFY_IN': self.gotNotifyIn,
            'PRESENCE_OUT': self.gotPresenceOut,
            'PRESENCE_PROBE': self.gotPresenceProbe,
            'MESSAGE_WAITING': self.gotMessageWaiting,
            'MESSAGE_QUERY': self.gotMessageQuery,
            'ROSTER': self.gotRoster,
            'CODEC': self.gotCodec,
            'BACKGROUND_JOB': self.gotBackgroundJob,
            'DETECTED_SPEECH': self.gotDetectSpeech,
            'DETECTED_TONE': self.gotDetectTone,
            'PRIVATE_COMMAND': self.gotPrivateCommand,
            'HEARTBEAT': self.gotHeartbeat,
            'TRAP': self.gotTrap,
            'ADD_SCHEDULE': self.gotAddSchedule,
            'DEL_SCHEDULE': self.gotDelSchedule,
            'EXE_SCHEDULE': self.gotExeSchedule,
            'RE_SCHEDULE': self.gotReSchedule,
            'RELOADXML': self.gotReloadxml,
            'NOTIFY': self.gotNotify,
            'SEND_MESSAGE': self.gotSendMessage,
            'RECV_MESSAGE': self.gotRecvMessage,
            'REQUEST_PARAMS': self.gotRequestParams,
            'CHANNEL_DATA': self.gotChannelData,
            'GENERAL': self.gotGeneral,
            'COMMAND': self.gotCommand,
            'SESSION_HEARTBEAT': self.gotSessionHeartbeat,
            'CLIENT_DISCONNECTED': self.gotClientDisconnected,
            'SERVER_DISCONNECTED': self.gotServerDisconnected,
            'ALL': self.gotAll
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
    def gotCustom(self, data): pass
    def gotChannelCreate(self, data): pass
    def gotChannelDestroy(self, data): pass
    def gotChannelState(self, data): pass
    def gotChannelAnswer(self, data): pass
    def gotChannelHangup(self, data): pass
    def gotChannelExecute(self, data): pass
    def gotChannelExecuteComplete(self, data): pass
    def gotChannelBridge(self, data): pass
    def gotChannelUnbridge(self, data): pass
    def gotChannelProgress(self, data): pass
    def gotChannelProgressMedia(self, data): pass
    def gotChannelOutgoing(self, data): pass
    def gotChannelPark(self, data): pass
    def gotChannelUnpark(self, data): pass
    def gotChannelApplication(self, data): pass
    def gotChannelOriginate(self, data): pass
    def gotChannelUuid(self, data): pass
    def gotApi(self, data): pass
    def gotLog(self, data): pass
    def gotInboundChannel(self, data): pass
    def gotOutboundChannel(self, data): pass
    def gotStartup(self, data): pass
    def gotShutdown(self, data): pass
    def gotPublish(self, data): pass
    def gotUnpublish(self, data): pass
    def gotTalk(self, data): pass
    def gotNotalk(self, data): pass
    def gotSessionCrash(self, data): pass
    def gotModuleLoad(self, data): pass
    def gotModuleUnload(self, data): pass
    def gotDtmf(self, data): pass
    def gotMessage(self, data): pass
    def gotPresenceIn(self, data): pass
    def gotNotifyIn(self, data): pass
    def gotPresenceOut(self, data): pass
    def gotPresenceProbe(self, data): pass
    def gotMessageWaiting(self, data): pass
    def gotMessageQuery(self, data): pass
    def gotRoster(self, data): pass
    def gotCodec(self, data): pass
    def gotBackgroundJob(self, data): pass
    def gotDetectSpeech(self, data): pass
    def gotDetectTone(self, data): pass
    def gotPrivateCommand(self, data): pass
    def gotHeartbeat(self, data): pass
    def gotTrap(self, data): pass
    def gotAddSchedule(self, data): pass
    def gotDelSchedule(self, data): pass
    def gotExeSchedule(self, data): pass
    def gotReSchedule(self, data): pass
    def gotReloadxml(self, data): pass
    def gotNotify(self, data): pass
    def gotSendMessage(self, data): pass
    def gotRecvMessage(self, data): pass
    def gotRequestParams(self, data): pass
    def gotChannelData(self, data): pass
    def gotGeneral(self, data): pass
    def gotCommand(self, data): pass
    def gotSessionHeartbeat(self, data): pass
    def gotClientDisconnected(self, data): pass
    def gotServerDisconnected(self, data): pass
    def gotAll(self, data): pass
    def gotUnknownEvent(self, data): pass

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
	#print 'got command', ctx
	#print '\n'
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
	else: debug('[eventsocket] apiResponse got "%s": out of sync?' % cmd)

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
	    self._events_[name] or self.gotUnknownEvent
	return method(ctx.data)
	#try: method(ctx.data)
	#except Exception, e:
	#    debug('[eventsocket] cannot dispatch (plain) event: %s, "%s"' % (name, repr(e)))

    def eventUnknown(self, ctx):
	pass
