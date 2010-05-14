#!/usr/bin/env twistd --pidfile=server.pid -ny
# coding: utf-8
# using:
#  1. register your sip client as 1000 in the freeswitch server
#  2. run this server (twistd --pidfile=server.pid -ny server.py)
#  3. open the freeswitch console and place a call to 1000 using
#     this server as context:
#     originate sofia/internal/1000%127.0.0.1 '&socket(127.0.0.1:8888 async full)'

import sys, os.path
sys.path.append("../")

import eventsocket
from twisted.internet import defer, protocol
from twisted.application import service, internet

class MyProtocol(eventsocket.EventProtocol):
    """our protocol class for receiving calls"""

    @defer.inlineCallbacks
    def connectionMade(self):
        # Once the call is originated, the freeswitch will connect
        # to our service and a new MyProtocol instance is created.
        #
        # Please refer to http://wiki.freeswitch.org/wiki/Event_Socket_Outbound
        # for more information.
        #
        # Anyway, the first thing to do when receiving such connections
        # from the freeswitch, is to send the `connect` command. We do this by
        # calling self.connect().
        data = yield self.connect()
        #print "data is:", data

        # After the connection with the eventsocket is established, we may
        # inform the server about what type of events we want to receive.
        # This may be done by self.eventplain("LIST_OF EVENT_NAMES") or
        # the self.myevents().
        # Please refer to http://wiki.freeswitch.org/wiki/Event_Socket_Outbound#Events
        # for more information.
        yield self.myevents()

        # The next thing is to `answer` the call. This is done by calling
        # self.answer(). After answering the call, our service will begin
        # receiving events from the freeswitch. 
        yield self.answer()

        # And now, a little trick.
        # Keep in mind that commands like `playback` will return an +OK
        # from the server, "immediately". However, the only way to know
        # that the audio file being played has finished, is by handling
        # CHANNEL_EXECUTE_COMPLETE events.
        #
        # Such events are received by the onChannelExecuteComplete method 
        # of an EventProtocol instance - like this one.
        #
        # In order to "block" the execution of our service until the
        # playback is finished, we create a DeferredQueue and wait for 
        # such event to come. The onChannelExecuteComplete method will
        # put that event in the queue, then we may continue working.
        #
        # However, our service will still allow other events to come, like,
        # for instance, DTMF. This is easily implemented in the asynchronous
        # server thanks to the Twisted's inlineCallbacks decorator.
        self.playback_queue = defer.DeferredQueue()
        soundfile = os.path.abspath("sample.wav")
        yield self.playback(soundfile)
        ev = yield self.playback_queue.get()
        assert soundfile == ev.variable_current_application_data

        # That's it.
        yield self.hangup()

    def onDtmf(self, ev):
        # for k, v in sorted(ev.items()):
        #   print k, "=", v
        print "GOT DTMF:", ev.DTMF_Digit

    def onChannelExecuteComplete(self, ev):
        if ev.variable_current_application == "playback":
            self.playback_queue.put(ev)

    def onChannelHangup(self, ev):
        start_usec = float(ev.Caller_Channel_Answered_Time)
        end_usec = float(ev.Event_Date_Timestamp)
        duration = (end_usec - start_usec) / 1000000.0
        print "%s hung up: %s (call duration: %0.2f)" % \
            (ev.variable_presence_id, ev.Hangup_Cause, duration)

    # To avoid 'unbound Event' messages in the log, you may
    # define the unboundEvent method in your class:
    # def unboundEvent(self, evdata, evname):
    #    pass
    #
    # This is the original method in eventsocket.py:
    # def unboundEvent(self, evdata, evname):
    #    log.err("[eventsocket] unbound Event: %s" % evname)
 

class MyFactory(protocol.ServerFactory):
    """our server factory"""
    protocol = MyProtocol

application = service.Application("eventsocket_server")
internet.TCPServer(8888, MyFactory(),
    interface="127.0.0.1").setServiceParent(application)
