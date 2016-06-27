Resilient-Circuits Sample Integrations
======================================

Python Circuits is a lightweight asynchronous event-driven application framework.  Resilient-Circuits uses this to provide a convenient mechanism for developing action module applications.  This directory contains a variety of simple examples to help you get started in developing your own integration with Resilient-Circuits.  The top-level run.py script can be used to run one or more of the circuits integrations together.

### csirt-action
Enables an automatic action on an incident to add another Incident Type value when a custom boolean field is set.


### file-lookup
Enables an automatic action to lookup values from one incident field in a local CSV file and store them in another incident field


### taskadd
Adds a manual action on an incident to create a new task


### taskcalendar
Enables an automatic action that will email calendar invites to a task owner when the owner or due date of a task is updated

