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

"""Action Module circuits component to lookup a value in a local CSV file"""

from __future__ import print_function
from circuits import Component, Debugger
from circuits.core.handlers import handler
from resilient_circuits.actions_component import ResilientComponent, ActionMessage
import os
import csv
import logging
LOG = logging.getLogger(__name__)

CONFIG_DATA_SECTION = 'lookup'

class FileLookupComponent(ResilientComponent):
    """Lookup a value in a CSV file"""

    # This component receives custom actions from Resilient and
    # executes searches in a local CSV file and stores it

    def __init__(self, opts):
        super(FileLookupComponent, self).__init__(opts)
        self.options = opts.get(CONFIG_DATA_SECTION, {})
        LOG.debug(self.options)

        # The queue name can be specified in the config file, or default to 'filelookup'
        self.channel = "actions." + self.options.get("queue", "filelookup")


    @handler()
    def _lookup_action(self, event, *args, **kwargs):
        """The @handler() annotation without an event name makes this
           a default handler - for all events on this component's queue.
           This will be called with some "internal" events from Circuits,
           so you must declare the method with the generic parameters
           (event, *args, **kwargs), and ignore any messages that are not
           from the Action Module.
        """
        if not isinstance(event, ActionMessage):
            # Some event we are not interested in
            return

        incident = event.message["incident"]
        inc_id = incident["id"]
        source_fieldname = self.options["source_field"]
        dest_fieldname = self.options["dest_field"]
        source_value = incident["properties"].get(source_fieldname, "") 

        # Open local file 
        with open(self.options["reference_file"]) as ref_file:
            # Lookup value in file
            reader = csv.reader(ref_file)
            value = ""
            for row in reader:
                if row[0] == source_value:
                    value = row[1]
                    break
            else:
                # Value not present in CSV file
                LOG.warning("No entry for [%s] in [%s]" % (
                    source_value, 
                    self.options["reference_file"]))
                yield "field %s not updated" % dest_fieldname
                return
                    
        LOG.info("READ %s:%s  STORED %s:%s", 
                 source_fieldname, source_value,
                 dest_fieldname, value)

        def update_field(incident, fieldname, value):
            incident["properties"][fieldname] = value

        # Store value in specified incident field
        self.rest_client().get_put("/incidents/{0}".format(inc_id),
                                   lambda incident: update_field(incident, dest_fieldname, value))

        yield "field %s updated" % dest_fieldname
    #end _lookup_action