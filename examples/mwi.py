#!/usr/bin/env python
# coding: utf-8

# copied from dialer :)

import sys
sys.path.append("../")

import eventsocket
from twisted.python import log
from twisted.internet import defer, reactor, protocol

unique_uuid = {}

class MyProtocol(eventsocket.EventProtocol):
    def __init__(self):
        self.job_uuid = {}
        eventsocket.EventProtocol.__init__(self)

    @defer.inlineCallbacks
    def authRequest(self, ev):
        try:
            yield self.auth(self.factory.password)
        except eventsocket.AuthError, e:
            self.factory.continueTrying = False
            self.factory.ready.errback(e)

        # Tell the factory that we're ready. Pass the protocol
        # instance as argument.
        self.factory.ready.callback(self)

    def mwi(self, ext):
        def _success(*a):
            print("done %s" % repr(a))

        deferred = defer.Deferred()
        body= """Messages-Waiting: yes"""
        params = {
                'profile': 'internal',
                'content-type': 'application/simple-message-summary',
                'to-uri': 'sip:%s@208.65.240.45' % ext,
                'from-uri': 'sip:ss@208.65.240.45',
                'content-length': len(body)
                }
        d = self.sendevent("NOTIFY", params, body)
        d.addCallback(_success)

        return deferred

    def onBackgroundJob(self, ev):
        data = self.job_uuid.pop(ev.Job_UUID, None)
        if data:
            response, content = ev.rawresponse.split()
            if response == "+OK":
                unique_uuid[content] = data
            else:
                d, ext, context = data
                d.errback(Exception("cannot make call to %s: %s" % (ext, content)))

    def onChannelHangup(self, ev):
        data = unique_uuid.pop(ev.Unique_ID, None)
        if data:
            d, ext, context = data
            start_usec = float(ev.Caller_Channel_Answered_Time)
            end_usec = float(ev.Event_Date_Timestamp)
            duration = (end_usec - start_usec) / 1000000.0
            d.callback("%s hang up: %s (call duration: %0.2f)" % \
                (ext, ev.Hangup_Cause, duration))

class MyFactory(protocol.ReconnectingClientFactory):
    maxDelay = 15
    protocol = MyProtocol

    def __init__(self, password):
        self.ready = defer.Deferred()
        self.password = password

@defer.inlineCallbacks
def main():
    factory = MyFactory(password="ClueCon")
    reactor.connectTCP("127.0.0.1", 8021, factory)

    # Wait for the connection to be established
    try:
        client = yield factory.ready
    except Exception, e:
        log.err("cannot connect: %s" % e)
        defer.returnValue(None)

    try:
        result = yield client.mwi('1000')
        log.msg(result)
    except Exception, e:
        log.err()
    
if __name__ == "__main__":
    log.startLogging(sys.stdout)
    main().addCallback(lambda ign: reactor.stop())
    reactor.run()
