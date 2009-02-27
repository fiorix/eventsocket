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

import os
from eventsocket import EventProtocol
from twisted.internet import reactor, protocol

class InboundProxy(EventProtocol):
    def authSuccess(self, ev):
        self.eventplain('CHANNEL_CREATE BACKGROUND_JOB')
        self.bgapi('originate sofia/internal/1001%192.168.0.3 9888 XML default')

    def authFailure(self, ev):
        print 'auth failure.'
        self.factory.reconnect = False

    def exitSuccess(self, ev):
        print 'exit success. ev:', ev
        self.factory.reconnect = False

    def bgapiSuccess(self, ev):
        print 'calling you. ev:', ev

    def bgapiFailure(self, ev):
        print 'bgapi failure. ev:', ev

    def gotBackgroundJob(self, ev):
        print 'background job. ev:', ev

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

if __name__ == '__main__':
    # outbound
    factory = InboundFactory('ClueCon')
    reactor.connectTCP('127.0.0.1', 8021, factory)

    # main loop
    reactor.run()
