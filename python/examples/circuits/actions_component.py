#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Resilient Systems, Inc. ("Resilient") is willing to license software
# or access to software to the company or entity that will be using or
# accessing the software and documentation and that you represent as
# an employee or authorized agent ("you" or "your") only on the condition
# that you accept all of the terms of this license agreement.
#
# The software and documentation within Resilient's Development Kit are
# copyrighted by and contain confidential information of Resilient. By
# accessing and/or using this software and documentation, you agree that
# while you may make derivative works of them, you:
#
# 1)  will not use the software and documentation or any derivative
#     works for anything but your internal business purposes in
#     conjunction your licensed used of Resilient's software, nor
# 2)  provide or disclose the software and documentation or any
#     derivative works to any third party.
#
# THIS SOFTWARE AND DOCUMENTATION IS PROVIDED "AS IS" AND ANY EXPRESS
# OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL RESILIENT BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
# OF THE POSSIBILITY OF SUCH DAMAGE.

"""Circuits component for Actions Module subscription and message handling"""

from circuits import BaseComponent, Event, Timer
from circuits.core.handlers import handler

import co3
import stomp
from stomp.exception import ConnectFailedException
import ssl
import json
import re
from rest_helper import get_resilient_client
import logging
LOG = logging.getLogger(__name__)


def validate_cert(cert, hostname):
    """Utility wrapper for SSL validation on the STOMP connection"""
    try:
        co3.match_hostname(cert, hostname)
    except Exception as exc:
        return (False, str(exc))
    return (True, "Success")


class ResilientComponent(BaseComponent):
    """A Circuits base component with a connection to the Resilient REST API

       This is a convenient superclass for custom components that use the
       Resilient Actions Module.
    """
    def __init__(self, opts):
        super(ResilientComponent, self).__init__()
        assert isinstance(opts, dict)
        self.opts = opts

    def rest_client(self):
        """Return a connected instance of the Resilient REST SimpleClient"""
        return get_resilient_client(self.opts)


class ActionMessage(Event):
    """A Circuits event for a Resilient Actions Module message"""

    # This is a generic event that holds details of the Actions Module message,
    # including its context (the incident, task, artifact... where the action
    # was triggered).
    #
    # These events are named by the action that triggered them (lowercased).
    # So a custom action named "Manual Action" will generate an event with name
    # "manual_action".  To handle that event, you should implement a Component
    # that has a method named "manual_action":  the Circuits framework will call
    # your component's methods based on the name of the event.
    #
    # The parameters for your event-handler method are:
    #   event: this event object
    #   source: the component that fired the event
    #   headers: the Actions Module message headers (dict)
    #   message: the Actions Module message (dict)
    # For convenience, the message is also broken out onto event properties,
    #   event.incident: the incident that the event relates to
    #   event.artifact: the artifact that the event was triggered from (if any)
    #   event.task: the task that the event was triggered from (if any)
    #   (etc).
    #
    # To have your component's method with a different name from the action,
    # you can use the '@handler' decorator:
    #
    #    @handler("the_action_name")
    #    def _any_method_name(self, event, source=None, headers=None, message=None) ...
    #
    # To have a method handle *any* event on the component's channel,
    # use the '@handler' decorator with no event name,
    #
    #    @handler()
    #    def _any_method_name(self, event, source=None, headers=None, message=None) ...

    def __init__(self, source=None, headers=None, message=None):
        super(ActionMessage, self).__init__(source=source, headers=headers, message=message)
        if headers is None:
            headers = {}
        if message is None:
            message = {}
        LOG.debug("Source: %s", source)
        LOG.debug("Headers: %s", json.dumps(headers, indent=2))
        LOG.debug("Message: %s", json.dumps(message, indent=2))

        self.message = message
        self.context = headers.get("Co3ContextToken")
        self.action_id = message.get("action_id")
        self.object_type = message.get("object_type")

        if source is None:
            self.displayname = "Unknown"
        else:
            assert isinstance(source, Actions)
            self.displayname = source.action_name(self.action_id)

        # The name of this event (=the function that subscribers implement)
        # is determined from the name of the action.
        # In future, this should be the action's "programmatic name",
        # but for now it's the downcased displayname with underscores.
        self.name = re.sub(r'\W+', '_', self.displayname.strip().lower())

        # Fire a {name}_success event when this event is successfully processed
        self.success = True

    def __repr__(self):
        "x.__repr__() <==> repr(x)"
        if len(self.channels) > 1:
            channels = repr(self.channels)
        elif len(self.channels) == 1:
            channels = str(self.channels[0])
        else:
            channels = ""
        return "<%s[%s] (%s)>" % (self.name, channels, self.action_id)

    def __getattr__(self, name):
        """Message attributes are made accessible as properties
           ("incident", "task", "note", "milestone". "task", "artifact";
           and "properties" for the action fields on manual actions)
        """
        if name=="message":
            raise AttributeError()
        try:
            return self.message[name]
        except KeyError:
            raise AttributeError()

    def hdr(self):
        """Get the headers (dict)"""
        return self.kwargs["headers"]

    def msg(self):
        """Get the message (dict)"""
        return self.kwargs["message"]


class Actions(ResilientComponent):
    """Component that subscribes to Resilient Actions Module queues and fires message events"""

    # Whenever a component in the circuit is registered to a channel name "actions.xxxx",
    # this component will subscribe to the corresponding Actions Module queue (xxxx)
    # and then fire events for each message that arrives from the queue.
    # After the message is handled, or fails, it acks the message and updates the action status.

    def __init__(self, opts):
        super(Actions, self).__init__(opts)
        self.listeners = dict()

        # Read the action definitions, into a dict indexed by id
        # we'll refer to them later when dispatching
        rest_client = self.rest_client()
        self.org_id = rest_client.org_id
        list_action_defs = rest_client.get("/actions")["entities"]
        self.action_defs = {int(action["id"]): action for action in list_action_defs}

        # Set up a STOMP connection to the Resilient action services
        host_port = (opts["host"], opts["stomp_port"])
        self.conn = stomp.Connection(host_and_ports=[(host_port)], try_loopback_connect=False)

        # Give the STOMP library our TLS/SSL configuration.
        self.conn.set_ssl(for_hosts=[host_port],
                          ca_certs=opts.get("cafile"),
                          ssl_version=ssl.PROTOCOL_TLSv1,
                          cert_validator=validate_cert)

        class StompListener(object):
            """A shim for the STOMP callback"""

            def __init__(self, component):
                self.component = component

            def on_error(self, headers, message):
                """STOMP produced an error."""
                self.component.on_stomp_error(headers, message)

            def on_connected(self, headers, message):
                """Client has connected to the STOMP server"""
                self.component.on_stomp_connected(headers, message)

            def on_disconnected(self):
                """Client has disconnected from the STOMP server"""
                self.component.on_stomp_disconnected()

            def on_message(self, headers, message):
                """STOMP produced a message."""
                self.component.on_stomp_message(headers, message)

        # When queued events happen, the listener shim will handle them
        self.conn.set_listener('', StompListener(self))

    # Public Utility methods

    def action_name(self, action_id):
        """Get the name of an action, from its id"""
        try:
            defn = self.action_defs[action_id]
        except KeyError:
            LOG.exception("Action %s is not defined.  Was it configured after the service was started?", action_id)
            raise
        if defn:
            return defn["name"]

    # STOMP callbacks

    def on_stomp_connected(self, headers, message):
        """Client has connected to the STOMP server"""
        LOG.info("STOMP connected")
        for queue_name in self.listeners:
            self._subscribe(queue_name)

    def on_stomp_disconnected(self):
        """Client has disconnected from the STOMP server"""
        LOG.info("STOMP disconnected!")
        # Set a timer to automatically reconnect
        Timer(5, Event.create("reconnect")).register(self)

    def on_stomp_error(self, headers, message):
        """STOMP produced an error."""
        LOG.error('STOMP listener: Error:\n%s', message)
        # Just raise the event for anyone listening
        self.fire(Event("exception", "Actions", headers.get("message"), message))

    def on_stomp_message(self, headers, message):
        """STOMP produced a message."""
        # Find the queue name from the subscription id (stomp_listener_xxx)
        subscription = headers["subscription"]
        LOG.debug('STOMP listener: message for %s', subscription)
        queue_name = subscription.partition("-")[2]
        channel = "actions." + queue_name

        # Expect the message payload to always be JSON
        message = json.loads(message)

        # Construct a Circuits event with the message, and fire it on the channel
        event = ActionMessage(self, headers=headers, message=message)
        self.fire(event, channel)

    # Circuits event handlers

    @handler("registered")
    def registered(self, event, component, parent):
        """A component has registered.  Subscribe to its message queue(s)."""
        for channel in event.channels:
            if not channel.startswith("actions."):
                continue
            LOG.info("Component %s registered to %s", str(component), channel)
            queue_name = channel.partition(".")[2]
            if queue_name in self.listeners:
                comps = set([component])
                comps.update(self.listeners[queue_name])
                self.listeners[queue_name] = comps
            else:
                self.listeners[queue_name] = set([component])
                # Actually subscribe the STOMP connection
                self._subscribe(queue_name)
            LOG.debug("Listeners: %s", self.listeners)

    @handler("unregistered")
    def unregistered(self, event, component, parent):
        """A component has unregistered.  Unsubscribe its message queue(s)."""
        for channel in event.channels:
            if not channel.startswith("actions."):
                continue
            LOG.info("Component %s unregistered from %s", str(component), channel)
            queue_name = channel.partition(".")[2]
            if queue_name not in self.listeners:
                LOG.error("Channel %s was not subscribed", queue_name)
                continue
            comps = self.listeners[queue_name]
            if component not in comps:
                LOG.error("Component %s was not subscribed", component)
                continue
            comps.remove(component)
            if self.conn.is_connected() and not comps:
                # All components have unsubscribed this destination; stop listening
                self._unsubscribe(queue_name)
            self.listeners[queue_name] = comps
            LOG.debug("Listeners: %s", self.listeners)

    def _subscribe(self, queue_name):
        """Actually subscribe the STOMP queue.  Note: this use client-ack, not auto-ack"""
        if self.conn.is_connected() and self.listeners[queue_name]:
            LOG.info("Subscribe to '%s'", queue_name)
            self.conn.subscribe(id='stomp-{}'.format(queue_name),
                                destination="actions.{}.{}".format(self.org_id, queue_name),
                                ack='client')

    def _unsubscribe(self, queue_name):
        """Unsubscribe the STOMP queue"""
        if self.conn.is_connected() and self.listeners[queue_name]:
            LOG.info("Unsubscribe from '%s'", queue_name)
            self.conn.unsubscribe(id='stomp-{}'.format(queue_name),
                                  destination="actions.{}.{}".format(self.org_id, queue_name))

    @handler("started")
    def started(self, event, component):
        """Started Event Handler"""
        LOG.debug("Started")
        self.reconnect()

    @handler("stopped")
    def stopped(self, event, component):
        """Started Event Handler"""
        LOG.debug("Stopped")
        if self.conn.is_connected():
            for queue_name in self.listeners:
                self._unsubscribe(queue_name)
            self.conn.disconnect()

    @handler("reconnect")
    def reconnect(self):
        """Try (re)connect to the STOMP server"""
        if self.conn.is_connected():
            LOG.error("STOMP reconnect when already connected")
        else:
            LOG.debug("STOMP attempting to connect")
            try:
                self.conn.start()
                self.conn.connect(login=self.opts["email"], passcode=self.opts["password"])
            except ConnectFailedException:
                # Try again later
                Timer(5, Event.create("reconnect")).register(self)

    @handler("exception")
    def exception(self, etype, value, traceback, handler=None, fevent=None):
        """Report an exception thrown during handling of an action event"""
        LOG.error("exception! %s, %s", str(value), str(fevent))
        if fevent and isinstance(fevent, ActionMessage):
            fevent.stop()  # Stop further event processing
            message = str(value or "Processing failed")
            status = 1
            headers = fevent.hdr()
            # Ack the message
            message_id = headers['message-id']
            subscription = headers["subscription"]
            self.conn.ack(message_id, subscription, transaction=None)
            # Reply with error status
            reply_to = headers['reply-to']
            correlation_id = headers['correlation-id']
            reply_message = json.dumps({"message_type": status, "message": message, "complete": True})
            self.conn.send(reply_to, reply_message, headers={'correlation-id': correlation_id})

    @handler()
    def _on_event(self, event, *args, **kwargs):
        """Report the successful handling of an action event"""
        if isinstance(event.parent, ActionMessage) and event.name.endswith("_success"):
            fevent = event.parent
            value = event.parent.value
            LOG.debug("success! %s, %s", str(value), str(fevent))
            fevent.stop()  # Stop further event processing
            message = str(value or "Processing complete")
            status = 0
            headers = fevent.hdr()
            # Ack the message
            message_id = headers['message-id']
            subscription = headers["subscription"]
            self.conn.ack(message_id, subscription, transaction=None)
            # Reply with success status
            reply_to = headers['reply-to']
            correlation_id = headers['correlation-id']
            reply_message = json.dumps({"message_type": status, "message": message, "complete": True})
            self.conn.send(reply_to, reply_message, headers={'correlation-id': correlation_id})