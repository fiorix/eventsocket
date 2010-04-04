#!/usr/bin/env python
# coding: utf-8

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
        # Try to authenticate in the eventsocket (Inbound)
        # Please refer to http://wiki.freeswitch.org/wiki/Mod_event_socket#auth
        # for more information.
        try:
            yield self.auth(self.factory.password)
        except eventsocket.AuthError, e:
            self.factory.continueTrying = False
            self.factory.ready.errback(e)

        # Set the events we want to get.
        yield self.eventplain("BACKGROUND_JOB CHANNEL_HANGUP")

        # Tell the factory that we're ready. Pass the protocol
        # instance as argument.
        self.factory.ready.callback(self)

    def make_call(self, ext, context):
        def _success(ev, data):
            self.job_uuid[ev.Job_UUID] = data

        def _failure(error, deferred):
            deferred.errback(error)

        deferred = defer.Deferred()
        d = self.bgapi("originate %s %s" % (ext, context))
        d.addCallback(_success, (deferred, ext, context))
        d.addErrback(_failure, deferred)

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

    # Place the call
    try:
        # Don't forget to replace ext with your own destination number.
        # You may also place the call to an eventsocket (Outbound) server,
        # like our server.tac using:
        #  context="'&socket(127.0.0.1:8888 async full)'")

        result = yield client.make_call(
            ext="sofia/internal/1000%127.0.0.1",
            context="9888 XML default")
        log.msg(result)
    except Exception, e:
        log.err()
    
if __name__ == "__main__":
    log.startLogging(sys.stdout)
    main().addCallback(lambda ign: reactor.stop())
    reactor.run()
