#!/usr/bin/env python
# coding: utf-8

import os
from twisted.internet import reactor, protocol
from eventsocket import EventProtocol

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
