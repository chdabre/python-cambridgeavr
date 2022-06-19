python-cambridgeavr
===============

This is a Python package to interface with Cambridge Audio Azur Receivers via a TCP/IP to RS232 Bridge. It uses the asyncio library to maintain an object-based
connection to the network port of the receiver with supporting methods
and properties to poll and adjust the receiver settings.

This package is a modified fork of the `python-anthemav <https://github.com/nugget/python-anthemav>`_ module by David McNett.

Requirements
------------

-  Python 3.6 or newer with asyncio
-  A Cambridge Audio Azur 551R Receiver (others untested)
-  Transparent TCP/IP to RS232 Bridge

Credits
-------

-  This package is written by Dario Breitenstein.

   -  https://github.com/chdabre


-  This package is a fork of python-anthemav written by David McNett.

   -  https://github.com/nugget
   -  https://keybase.io/nugget

-  The python-anthemav package is maintained by Alex Henry

   - https://github.com/hyralex