Python OpenCL Bitcoin Miner GUI (poclbm-gui)
============================================

by Chris 'Kiv' MacLeod
based on "poclbm" by m0mchil

What is it?
-----------

poclbm-gui is a GUI front end for the poclbm Bitcoin miner by m0mchil. It
allows you to use an OpenCL compatible video card to mine Bitcoins, without
having to use the command line. It supports both pooled mining and solo
mining.

What is it not?
---------------

poclbm-gui does not replace the standard Bitcoin client from bitcoin.org - you
still need that program to view your account balance and send transactions.
It is not a server, so it has to connect either to a mining pool, or to your
computer's 'bitcoin.exe' if mining solo.

The Latest Version
------------------

You can get the latest version on the project page at GitHub:
    
    https://github.com/Kiv/poclbm

Features
--------

- Supports multiple miners in a tabbed interface.
- Remembers your login info between sessions.
- Supports both solo and pooled mining.
- Minimizes to tray. Hover on tray icon to see status.
- Displays your accepted and stale/invalid shares over time.    

Requirements
------------

- You need an OpenCL compatible GPU with a working version of OpenCL. If you
are unsure whether your GPU supports OpenCL, try the GPU Caps Viewer:

    http://www.ozone3d.net/gpu_caps_viewer/
    
For AMD/ATI cards, to get a version of OpenCL you need the Stream SDK which is
available here:

    http://developer.amd.com/gpu/AMDAPPSDK/downloads/pages/AMDAPPSDKDownloadArchive.aspx
    
Instructions for Pooled Mining
------------------------------

Pooled mining is recommended for most users, since it gives steadier payouts
than solo mining. To mine in a pool, you need to register an account with a mining pool.
A good one by slush is here:

    http://mining.bitcoin.cz/
    
Once you have an account, double-click guiminer.exe to open it and enter your
miner account. You need a miner account for each GPU you have, so if you have two GPUs 
you will need two separate accounts. If you have a multi-core CPU, one account is
enough but be warned that CPU mining is extremely slow compared to GPU mining and
probably not worth the electricity.

Click "Start mining!" to connect to the server. The miner should connect and start
showing your hash rate. This is the number of attempts per second to solve the
current block. After a while the miner will also show "shares" accepted
by the pool. The more shares you have, the larger your share will be of
the 50 Bitcoins when the block is solved.

To see if your hashing rate is comparable to others, you can look up your GPU on
this chart:
    
    http://pastebin.com/AvymGnMJ

You can save your login info for next time by using File -> Save. Next time
you open the GUI your login will be remembered.

You can run multiple CPUs/GPUs in separate tabs by using File -> New and entering
the new miner's login info. Remember to save your login info after it's entered.

Solo Mining
-----------

Solo mining is recommended for users with a lot of computing power available,
or if you can't find or connect to any pools. It doesn't give any award at 
all unless you find a block (which takes weeks to months), at which point you
get 50 BTC all at once.

For solo mining, instead of connecting to a pool server you connect to your own
local machine's copy of 'bitcoin.exe'. Instead of registering with the pool
server, you put your login info in a special file called 'bitcoin.conf'. 

poclbm-gui has utilities to help with these tasks. To create the bitcoin.conf,
choose "Solo utilities -> Create solo password..." and create a user and
password. It should show a message saying that it was successful.

To launch bitcoin.exe in server mode, you might need to point poclbm-gui to
the location of bitcoin.exe. If you installed Bitcoin in the regular location
of Program Files/Bitcoin, you can skip this step. Otherwise choose "Solo
utilities -> Set Bitcoin client path".

Then make sure bitcoin.exe is not running already and choose "Solo
utilities -> Launch Bitcoin client". This should bring up the official
Bitcoin client. You will need to leave this open while you are solo mining.

Now you can enter your information in the text boxes. For "Server" type
"localhost" since the server is on your own machine. Put your username and
password that you chose earlier. Then press "Start mining!" to connect and
start mining.



Running From Source
-------------------

Running poclbm-gui from source requires:
    - Python 2.6 or higher (Python 3 not supported)
    - PyOpenCL
    - wxPython
    - numpy

Once these are installed run "guiminer.py" to start.

Bug Reporting
-------------

This is very early software, so any bug reports are appreciated. Issues and
forks can be created at:

    https://github.com/Kiv/poclbm    