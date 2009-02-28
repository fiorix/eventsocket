#!/usr/bin/env python
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

from Queue import Queue
from eventsocket import EventProtocol
from twisted.internet import reactor, protocol

port = 1905
unique_id = {}

class InboundProxy(EventProtocol):
    def __init__(self):
	self.job_uuid = {}
	self.calls = Queue()
	EventProtocol.__init__(self)

    def authSuccess(self, ev):
	self.eventplain('CHANNEL_HANGUP BACKGROUND_JOB')

    def authFailure(self, failure):
	self.factory.reconnect = False

    def eventplainSuccess(self, ev):
	for ext in ['1000', '1001', '1002']:
	    self.calls.put(ext)
	    print '[inboundproxy] originating call to extension %s' % ext

            # FreeSWITCH will park the call immediately if the destination is socket().
            # when we receive this call on the outbound side, there won't be an ANSWER
            # nor a PARK event we can watch; hence, we must start processing right away.
	    self.bgapi("originate sofia/internal/%s%%192.168.99.4 '&socket(127.0.0.1:%d async full)'" % (ext, port))

    def eventplainFailure(self, failure):
	self.factory.reconnect = False
	self.exit()

    def bgapiSuccess(self, ev):
	ext = self.calls.get()
	self.calls.task_done()
	self.job_uuid[ev.Job_UUID] = ext

    def bgapiFailure(self, failure):
	print '[inboundproxy] bgapi failure: %s' % failure.value
	self.exit()

    def onBackgroundJob(self, data):
	ext = self.job_uuid[data.Job_UUID]
	del self.job_uuid[data.Job_UUID]
	response, content = data.rawresponse.split()
	if response == '+OK': unique_id[content] = ext
	else: print '[inboundproxy] cannot call %s: %s' % (ext, content)

    def onChannelHangup(self, data):
	if unique_id.has_key(data.Unique_ID):
	    ext = unique_id[data.Unique_ID]
	    del unique_id[data.Unique_ID]
	    print '[inboundproxy] extension %s hung up: %s' % (ext, data.Hangup_Cause)

class InboundFactory(protocol.ClientFactory):
    protocol = InboundProxy

    def __init__(self, password):
	self.password = password
	self.reconnect = True

    def clientConnectionLost(self, connector, reason):
	if self.reconnect: connector.connect()
	else:
	    print '[inboundfactory] stopping reactor'
	    reactor.stop()

    def clientConnectionFailed(self, connector, reason):
	print '[inboundfactoy] cannot connect: %s' % reason
	reactor.stop()

class OutboundProxy(EventProtocol):
    def __init__(self):
	self.ext = None
	self.debug_enabled = False
	EventProtocol.__init__(self)

    # when we get connection from fs, send "connect"
    def connectionMade(self):
	self.connect()

    # when we get OK from connect, send "myevents" and "answer".
    def connectSuccess(self, ev):
	self.ext = unique_id[ev.Unique_ID]
	print '[outboundproxy] started controlling extension %s' % self.ext
	self.myevents()

    # after we get OK for myevents, send "answer".
    def myeventsSuccess(self, ev):
        self.answer()

    # when we get OK from answer, play something. Note: on default FreeSWITCH
    # deployments, the sounds directory is usually /usr/local/freeswitch/sounds
    def answerSuccess(self, ev):
	print '[outboundproxy] going to play audio file for extension %s' % self.ext
	self.playback('/opt/freeswitch/sounds/en/us/callie/ivr/8000/ivr-sample_submenu.wav',
	    terminators='123*#')

    # well well...
    def onDtmf(self, data):
	print '[outboundproxy] got dtmf "%s" from extension %s' % (data.DTMF_Digit, self.ext)

    # finished executing something
    def onChannelExecuteComplete(self, data):
	app = data.variable_current_application
	if app == 'playback':
	    terminator = data.get('variable_playback_terminator_used')
            response = data.get('variable_current_application_response')
	    print '[outboundproxy] extension %s finished playing file, terminator=%s, response=%s' % (self.ext, terminator, response)
	    print '[outboundproxy] bridging extension %s to public conference 888' % self.ext
	    self.bridge('sofia/external/888@conference.freeswitch.org')

	# it could also be done by onChannelUnbridge
	elif app == 'bridge':
	    print '[outboundproxy] extension %s finished the bridge' % self.ext
	    self.hangup()
    
    # goodbye...
    def exitSuccess(self, ev):
	print '[outboundproxy] control of extension %s has finished' % self.ext

class OutboundFactory(protocol.ServerFactory):
    protocol = OutboundProxy

if __name__ == '__main__':
    reactor.listenTCP(port, OutboundFactory())
    reactor.connectTCP('localhost', 8021, InboundFactory('ClueCon'))
    reactor.run()
