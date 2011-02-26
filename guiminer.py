import sys, os, subprocess, errno, re, threading, logging
import wx
import json

from wx.lib.agw import flatnotebook as fnb
from wx.lib.newevent import NewEvent

__version__ = '2011-02-25'

ABOUT_TEXT = \
"""Python OpenCL Bitcoin Miner GUI

Version: %s

GUI by Chris 'Kiv' MacLeod
Original poclbm miner by m0mchil

Get the source code or file issues at GitHub:
    https://github.com/Kiv/poclbm

If you enjoyed this software, support its development
by donating to:

%s
"""

# Events sent from the worker threads
(UpdateHashRateEvent, EVT_UPDATE_HASHRATE) = NewEvent()
(UpdateAcceptedEvent, EVT_UPDATE_ACCEPTED) = NewEvent()
(UpdateSoloCheckEvent, EVT_UPDATE_SOLOCHECK) = NewEvent()
(UpdateStatusEvent, EVT_UPDATE_STATUS) = NewEvent()

# Utility functions
def merge_whitespace(s):
    """Combine multiple whitespace characters found in s into one."""
    s = re.sub(r"( +)|\t+", " ", s)
    return s.strip()

def get_opencl_devices():
    import pyopencl
    platform = pyopencl.get_platforms()[0]
    devices = platform.get_devices()
    if len(devices) == 0:
        raise IOError
    # TODO: maybe use horizontal scrollbar to show long device names?
    # Or maybe it's nice if we can show device aliases.
    return ['[%d] %s' % (i, merge_whitespace(device.name)[:25])
                         for (i, device) in enumerate(devices)]

def get_module_path():
    """Return the folder containing this script (or its .exe)."""
    module_name = sys.executable if hasattr(sys, 'frozen') else __file__
    return os.path.dirname(module_name)

def get_icon():
    """Return the Bitcoin program icon."""
    image_path = os.path.join(get_module_path(), 'logo.png')
    image = wx.Image(image_path, wx.BITMAP_TYPE_PNG).ConvertToBitmap()
    icon = wx.EmptyIcon()
    icon.CopyFromBitmap(image)
    return icon
    
def mkdir_p(path):
    """If the directory 'path' doesn't exist, create it. Same as mkdir -p."""
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise

logging.basicConfig(filename=os.path.join(get_module_path(), 'guiminer.log'),
                    filemode='w',
                    level=logging.DEBUG)

class GUIMinerTaskBarIcon(wx.TaskBarIcon):
    """Taskbar icon for the GUI.

    Shows status messages on hover and opens on click.
    TODO: right click on taskbar icon to open menu with some stuff in it.
    """
    TBMENU_RESTORE = wx.NewId()
    TBMENU_CLOSE   = wx.NewId()
    TBMENU_CHANGE  = wx.NewId()
    TBMENU_REMOVE  = wx.NewId()
    
    def __init__(self, frame):
        wx.TaskBarIcon.__init__(self)
        self.frame = frame
        self.icon = get_icon()
        self.timer = wx.Timer(self)
        self.timer.Start(1000)

        self.SetIcon(self.icon, "poclbm-gui")
        self.imgidx = 1
        self.Bind(wx.EVT_TASKBAR_LEFT_DCLICK, self.on_taskbar_activate)
        self.Bind(wx.EVT_MENU, self.on_taskbar_activate, id=self.TBMENU_RESTORE)
        self.Bind(wx.EVT_MENU, self.on_taskbar_close, id=self.TBMENU_CLOSE)
        self.Bind(wx.EVT_TIMER, self.on_update_tooltip)

    def CreatePopupMenu(self):
        """Override from wx.TaskBarIcon. Creates the right-click menu."""
        menu = wx.Menu()
        menu.Append(self.TBMENU_RESTORE, "Restore")
        menu.Append(self.TBMENU_CLOSE,   "Close")
        return menu
   
    def on_taskbar_activate(self, evt):
        if self.frame.IsIconized():
            self.frame.Iconize(False)
        if not self.frame.IsShown():
            self.frame.Show(True)
        self.frame.Raise()

    def on_taskbar_close(self, evt):
        wx.CallAfter(self.frame.Close)

    def on_update_tooltip(self, event):
        """Refresh the taskbar icon's status message."""
        objs = self.frame.profile_objects
        if objs:
            text = '\n'.join(p.get_taskbar_text() for p in objs)
            self.SetIcon(self.icon, text)    

class MinerListenerThread(threading.Thread):
    def __init__(self, parent, miner):
        threading.Thread.__init__(self)
        self.shutdown_event = threading.Event()
        self.parent = parent
        self.miner = miner

    def run(self):
        logging.debug('Listener started')
        while not self.shutdown_event.is_set():            
            line = self.miner.stdout.readline().strip()
            if not line: continue
            match = re.search(r"accepted", line, flags=re.I)
            if match is not None:
                event = UpdateAcceptedEvent(accepted=True)
                wx.PostEvent(self.parent, event)
                continue
            match = re.search(r"invalid|stale", line, flags=re.I)
            if match is not None:
                event = UpdateAcceptedEvent(accepted=False)
                wx.PostEvent(self.parent, event)
                continue
            match = re.search(r"(\d+) khash/s", line, flags=re.I)
            if match is not None:
                event = UpdateHashRateEvent(rate=int(match.group(1)))
                wx.PostEvent(self.parent, event)
                continue
            match = re.search(r"checking (\d+)", line, flags=re.I)
            if match is not None:
                event = UpdateSoloCheckEvent()
                wx.PostEvent(self.parent, event)
                continue
            # Possible error or new message, just pipe it through
            event = UpdateStatusEvent(text=line)
            wx.PostEvent(self.parent, event)
        logging.debug('Listener shutting down')
        
        
class ProfilePanel(wx.Panel):
    """A tab in the GUI representing a miner instance.

    Each ProfilePanel has these responsibilities:
    - Persist its data to and from the config file
    - Launch a poclbm subprocess and monitor its progress
      by creating a MinerListenerThread.
    - Post updates to the GUI's statusbar; the format depends
      whether the poclbm instance is working solo or in a pool.
    """
    SOLO, POOL = range(2)
    def __init__(self, parent, id, devices, statusbar):
        wx.Panel.__init__(self, parent, id)
        self.parent = parent
        self.name = "Miner"
        self.statusbar = statusbar
        self.is_mining = False
        self.is_possible_error = False
        self.miner = None # subprocess.Popen instance when mining
        self.miner_listener = None # MinerListenerThread when mining
        self.accepted_shares = 0 # POOL mode only
        self.invalid_shares = 0 # POOL mode only
        self.diff1_hashes = 0 # SOLO mode only
        self.last_rate = 0 # units of khash/s
        self.last_update_type = ProfilePanel.POOL
        self.server_lbl = wx.StaticText(self, -1, _("Server:"))
        self.txt_server = wx.TextCtrl(self, -1, "mining.bitcoin.cz")
        self.port_lbl = wx.StaticText(self, -1, _("Port:"))
        self.txt_port = wx.TextCtrl(self, -1, "8332")
        self.user_lbl = wx.StaticText(self, -1, _("Username:"))
        self.txt_username = wx.TextCtrl(self, -1, _(""))
        self.pass_lbl = wx.StaticText(self, -1, _("Password:"))
        self.txt_pass = wx.TextCtrl(self, -1, "", style=wx.TE_PASSWORD)
        self.device_lbl = wx.StaticText(self, -1, _("Device:"))
        self.device_listbox = wx.ComboBox(self, -1, choices=devices, style=wx.CB_DROPDOWN)
        self.flags_lbl = wx.StaticText(self, -1, _("Extra flags:"))
        self.txt_flags = wx.TextCtrl(self, -1, "")
        self.start = wx.Button(self, -1, _("Start mining!"))        

        self.device_listbox.SetSelection(0)
        self.__do_layout()

        self.start.Bind(wx.EVT_BUTTON, self.toggle_mining)
        self.Bind(EVT_UPDATE_HASHRATE, lambda event: self.update_khash(event.rate))
        self.Bind(EVT_UPDATE_ACCEPTED, lambda event: self.update_shares(event.accepted))
        self.Bind(EVT_UPDATE_STATUS, lambda event: self.update_status(event.text))
        self.Bind(EVT_UPDATE_SOLOCHECK, lambda event: self.update_solo())
        self.update_shares_on_statusbar()      

    def __do_layout(self):
        sizer_2 = wx.BoxSizer(wx.VERTICAL)
        grid_sizer_1 = wx.FlexGridSizer(3, 4, 5, 5)
        sizer_2.Add((20, 10), 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.server_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_server, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.port_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_port, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.user_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_username, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.pass_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_pass, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.device_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.device_listbox, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.flags_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_flags, 0, wx.EXPAND, 0)
        grid_sizer_1.AddGrowableCol(1)
        grid_sizer_1.AddGrowableCol(3)
        sizer_2.Add(grid_sizer_1, 1, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        sizer_2.Add(self.start, 0, wx.ALIGN_BOTTOM|wx.ALIGN_CENTER_HORIZONTAL|wx.BOTTOM, 5)
        self.SetSizerAndFit(sizer_2)

    def toggle_mining(self, event):
        """Stop or start the miner."""
        if self.is_mining:
            self.stop_mining()
            self.start.SetLabel("Start mining!")
        else:
            self.start_mining()
            self.start.SetLabel("Stop mining")

    def get_data(self):
        """Return a dict of our profile data."""        
        return dict(name=self.name,
                    server=self.txt_server.GetValue(),
                    port=self.txt_port.GetValue(),
                    username=self.txt_username.GetValue(),
                    password=self.txt_pass.GetValue(),
                    device=self.device_listbox.GetSelection(),
                    flags=self.txt_flags.GetValue())

    def set_data(self, data):
        """Set our profile data to the information in data. See get_data()."""
        if 'name' in data: self.name = data['name']
        if 'username' in data: self.txt_username.SetValue(data['username'])
        if 'server' in data: self.txt_server.SetValue(data['server'])
        if 'port' in data: self.txt_port.SetValue(data['port'])
        if 'password' in data: self.txt_pass.SetValue(data['password'])
        if 'flags' in data: self.txt_flags.SetValue(data['flags'])

        # Handle case where they removed devices since last run.
        device_index = data.get('device', None)
        if device_index is not None and device_index < self.device_listbox.GetCount():
            self.device_listbox.SetSelection(device_index)

    def start_mining(self):
        """Launch a poclbm subprocess and attach a MinerListenerThread."""
        folder = get_module_path()  
        if USE_MOCK:            
            executable = "python mockBitcoinMiner.py"
        else:
            if hasattr(sys, 'frozen'):
                executable = "poclbm.exe"
            else:
                executable = "python poclbm.py"
        cmd = "%s --user=%s --pass=%s -o %s -p %s -d%d --verbose %s" % (
                executable,
                self.txt_username.GetValue(),
                self.txt_pass.GetValue(),
                self.txt_server.GetValue(),
                self.txt_port.GetValue(),
                self.device_listbox.GetSelection(),
                self.txt_flags.GetValue()
        )
        try:
            logging.debug('Running command: '+ cmd)
            self.miner = subprocess.Popen(cmd, cwd=folder, stdout=subprocess.PIPE)
        except OSError:
            raise #TODO
        self.miner_listener = MinerListenerThread(self, self.miner)
        self.miner_listener.daemon = True
        self.miner_listener.start()
        self.is_mining = True
        self.set_status("Starting...", 1)
        
    def stop_mining(self):
        """Terminate the poclbm process if able and its associated listener."""
        if self.miner is not None:
            if self.miner.returncode is None:
                # It didn't return yet so it's still running.
                try:
                    self.miner.terminate()
                except OSError:
                    pass # TODO: Guess it wasn't still running?
            self.miner = None
        if self.miner_listener is not None:
            self.miner_listener.shutdown_event.set()
            self.miner_listener = None            
        self.is_mining = False
        self.set_status("Stopped", 1)

    def format_khash(self, rate):
        """Format rate for display. A rate of 0 means just connected."""
        if rate > 1000:
            return "%.1f Mhash/s" % (rate/1000.)
        elif rate == 0:
            return "Connected."
        else:
            return "%d khash/s" % rate
           
    def update_khash(self, rate):
        """Update our rate according to a report from the listener thread.

        If we are receiving rate messages then it means poclbm is no longer
        reporting errors.
        """
        self.last_rate = rate
        self.set_status(self.format_khash(rate), 1)
        if self.is_possible_error:
            self.update_shares_on_statusbar()
            self.is_possible_error = False

    def update_shares_on_statusbar(self):
        """For pooled mining, show the shares on the statusbar."""
        text = "Shares: %d accepted, %d stale/invalid" % \
               (self.accepted_shares, self.invalid_shares)
        self.set_status(text, 0) 

    def update_shares(self, accepted):
        """Update our shares with a report from the listener thread."""
        self.last_update_type = ProfilePanel.POOL
        if accepted:
            self.accepted_shares += 1
        else:
            self.invalid_shares += 1
        self.update_shares_on_statusbar()

    def update_status(self, msg):
        """Update our status with a report from the listener thread.

        If we receive a message from poclbm we don't know how to interpret,
        it's probably some kind of error state - in this case the best
        thing to do is just show it to the user on the status bar.
        """
        self.set_status(msg)
        self.is_possible_error = True

    def set_status(self, msg, index=0):
        """Set the current statusbar text, but only if we have focus."""
        if self.parent.GetSelection() == self.parent.GetPageIndex(self):
            self.statusbar.SetStatusText(msg, index)

    def on_focus(self):
        """When we receive focus, update our status.

        This ensures that when switching tabs, the statusbar always
        shows the current tab's status.
        """
        self.update_shares_on_statusbar()
        if self.is_mining:
            self.update_khash(self.last_rate)
        else:
            self.set_status("Stopped", 1)

    def get_taskbar_text(self):
        """Return text for the hover state of the taskbar."""
        if self.is_mining:
            return "%s: %s" % (self.name, self.format_khash(self.last_rate))
        else:
            return "%s: Stopped" % self.name

    def update_solo_status(self):
        """For solo mining, show the number of easy hashes solved.

        This is a rough indicator of how fast the miner is going,
        since some small fraction of easy hashes are also valid solutions
        to the block.
        """
        text = "Difficulty 1 hashes: %d" % self.diff1_hashes
        self.set_status(text, 0)

    def update_solo(self):
        """Update our easy hashes with a report from the listener thread."""
        self.last_update_type = ProfilePanel.SOLO
        self.diff1_hashes += 1
        self.update_solo_status()

class MyFrame(wx.Frame):
    def __init__(self, *args, **kwds):
        wx.Frame.__init__(self, *args, **kwds)
        style = fnb.FNB_X_ON_TAB | fnb.FNB_FF2 | fnb.FNB_NO_NAV_BUTTONS | fnb.FNB_HIDE_ON_SINGLE_TAB
        self.profiles = fnb.FlatNotebook(self, -1, style=style)
        self.profile_objects = [] # List of ProfilePanel. # TODO: can we just get this from self.profiles?
               
        self.menubar = wx.MenuBar()
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, _("&New miner..."), _("Create a new miner profile"), wx.ITEM_NORMAL)
        file_menu.Append(wx.ID_SAVE, _("&Save settings"), _("Save your settings"), wx.ITEM_NORMAL)
        file_menu.Append(wx.ID_OPEN, _("&Load settings"), _("Load stored settings"), wx.ITEM_NORMAL)
        self.menubar.Append(file_menu, _("&File"))

        ID_SOLO, ID_PATHS, ID_LAUNCH = wx.NewId(), wx.NewId(), wx.NewId()
        solo_menu = wx.Menu()
        solo_menu.Append(ID_SOLO, "&Create solo password...", _("Configure a user/pass for solo mining"), wx.ITEM_NORMAL)
        solo_menu.Append(ID_PATHS, "&Set Bitcoin client path...", _("Set the location of the official Bitcoin client"), wx.ITEM_NORMAL)
        solo_menu.Append(ID_LAUNCH, "&Launch Bitcoin client", _("Launch the official Bitcoin client for solo mining"), wx.ITEM_NORMAL)
        self.menubar.Append(solo_menu, _("&Solo utilities"))
        
        help_menu = wx.Menu()
        help_menu.Append(wx.ID_ABOUT, _("&About..."), "", wx.ITEM_NORMAL)
        self.menubar.Append(help_menu, _("&Help"))
        self.SetMenuBar(self.menubar)  
        self.statusbar = self.CreateStatusBar(2, 0)

        try:
            self.bitcoin_executable = os.path.join(os.getenv("PROGRAMFILES"), "Bitcoin", "bitcoin.exe")
        except:
            self.bitcoin_executable = "" # TODO: where would Bitcoin probably be on Linux/Mac?       

        try:
            self.tbicon = GUIMinerTaskBarIcon(self)
        except:
            self.tbicon = None # TODO: what happens on Linux?
                         
        self.__set_properties()

        try:
            self.devices = get_opencl_devices()
        except:
            self.message("""Couldn't find any OpenCL devices.
Check that your video card supports OpenCL and that you have a working version of OpenCL installed.
If you have an AMD/ATI card you may need to install the ATI Stream SDK.""",
                "No OpenCL devices found.",
                wx.OK | wx.ICON_ERROR)
            sys.exit(1)        

        self.Bind(wx.EVT_MENU, self.name_new_profile, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.save_profiles, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.load_profiles, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.set_official_client_path, id=ID_PATHS)
        self.Bind(wx.EVT_MENU, self.show_about_dialog, id=wx.ID_ABOUT)
        self.Bind(wx.EVT_MENU, self.create_solo_password, id=ID_SOLO)
        self.Bind(wx.EVT_MENU, self.launch_solo_server, id=ID_LAUNCH)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ICONIZE, lambda event: self.Hide())
        self.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSING, self.on_page_closing)
        self.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CHANGED, self.on_page_changed)

        any_loaded = self.load_profiles() 
        if not any_loaded: # Create a default one for them to use 
            p = self.add_profile(dict(name="slush's pool"))

        self.__do_layout()
    
    def __set_properties(self):
        self.SetIcon(get_icon())        
        self.SetTitle(_("poclbm-gui"))
        self.statusbar.SetStatusWidths([-1, 125])
        statusbar_fields = [_(""), _("Not started")]
        for i in range(len(statusbar_fields)):  
            self.statusbar.SetStatusText(statusbar_fields[i], i)  

    def __do_layout(self):
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        self.vertical_sizer.Add(self.profiles, 1, wx.EXPAND, 20)
        self.SetSizer(self.vertical_sizer)
        self.vertical_sizer.SetSizeHints(self)
        self.SetSizerAndFit(self.vertical_sizer)

    def add_profile(self, data):
        """Add a new ProfilePanel to the list of tabs."""
        panel = ProfilePanel(self.profiles, -1, self.devices, self.statusbar)
        panel.set_data(data)
        self.profile_objects.append(panel)
        self.profiles.AddPage(panel, panel.name)
        # The newly created profile should have focus.
        self.profiles.EnsureVisible(self.profiles.GetPageCount()-1)
        self.__do_layout()
        return panel

    def message(self, *args, **kwargs):
        """Utility method to show a message dialog and return their choice."""
        dialog = wx.MessageDialog(self, *args, **kwargs)
        retval = dialog.ShowModal()
        dialog.Destroy()
        return retval

    def name_new_profile(self, event):
        """Prompt for the new miner's name."""
        dialog = wx.TextEntryDialog(self, "Name this miner:", "New miner")
        if dialog.ShowModal() == wx.ID_OK:
            self.add_profile(dict(name=dialog.GetValue()))

    def get_storage_location(self):
        """Get the folder and filename to store our JSON config."""
        if sys.platform == 'win32':
            folder = os.path.join(os.environ['AppData'], 'poclbm')
            config_filename = os.path.join(folder, 'poclbm.ini')
        else: # Assume linux? TODO test
            folder = os.environ['HOME']
            config_filename = os.path.join(folder, '.poclbm')
        return folder, config_filename

    def on_close(self, event):
        """On closing, stop any miners that are currently working."""
        for p in self.profile_objects:
            p.stop_mining()
        if self.tbicon is not None:
            self.tbicon.RemoveIcon()
            self.tbicon.timer.Stop()
            self.tbicon.Destroy()
        event.Skip()

    def save_profiles(self, event):
        """Save the current miner profiles to our config file in JSON format."""
        folder, config_filename = self.get_storage_location()
        mkdir_p(folder)
        profile_data = [p.get_data() for p in self.profile_objects]
        config_data = dict(profiles=profile_data,
                           bitcoin_executable=self.bitcoin_executable)
        logging.debug('Saving: '+ str(config_data))
        with open(config_filename, 'w') as f:
            json.dump(config_data, f)
            self.message("Profiles saved OK to %s." % config_filename,
                          "Save successful", wx.OK|wx.ICON_INFORMATION)
        # TODO: handle save failed
    
    def load_profiles(self, event=None):
        """Load JSON profile info from the config file."""
        folder, config_filename = self.get_storage_location()
        if not os.path.exists(config_filename):
            return # Nothing to load yet
        with open(config_filename) as f:
            config_data = json.load(f)
        logging.debug('Loaded: ' + str(config_data))
        # TODO: handle load failed or corrupted data
        
        executable = config_data.get('bitcoin_executable', None)
        if executable is not None:
            self.bitcoin_executable = executable

        # Shut down any existing miners before they get clobbered
        if(any(p.is_mining for p in self.profile_objects)):
            result = self.message(
                "Loading profiles will stop any currently running miners. Continue?",
                "Load profile", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
            if result == wx.ID_NO:
                return                      
        while self.profile_objects:
            p = self.profile_objects.pop()
            p.stop_mining()
        for i in reversed(range(self.profiles.GetPageCount())):
            self.profiles.DeletePage(i)            
        # Create new miners
        data = config_data.get('profiles', [])
        for d in data:
            panel = self.add_profile(d)
        return any(data)
            
    def set_official_client_path(self, event):
        """Set the path to the official Bitcoin client."""
        dialog = wx.FileDialog(self,
                               "Select path to Bitcoin.exe",
                               defaultFile="bitcoin.exe",
                               wildcard="bitcoin.exe",
                               style=wx.OPEN)
        if dialog.ShowModal() == wx.ID_OK:
            path = os.path.join(dialog.GetDirectory(), dialog.GetFilename())
            if os.path.exists(path):
                self.bitcoin_executable = path
        dialog.Destroy()
            
    def show_about_dialog(self, event):
        """Show the 'about' dialog."""
        dialog = AboutGuiminer(self, -1, 'About')
        dialog.ShowModal()
        dialog.Destroy()
        
    def on_page_closing(self, event):
        """Handle a tab closing event.

        If the tab has a miner running in it, we have to stop the miner
        before letting the tab be removed.
        """
        try:
            p = self.profile_objects[event.GetSelection()]
        except IndexError:
            return # TODO
        if p.is_mining:
            result = self.message(
                "Closing this miner will stop it. Continue?", "Close miner",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
            if result == wx.ID_NO:
                event.Veto()
                return            
        p = self.profile_objects.pop(event.GetSelection())
        p.stop_mining()
        event.Skip() # OK to close the tab now

    def on_page_changed(self, event):
        """Handle a tab change event.

        Ensures the status bar shows the status of the tab that has focus.
        """
        try:
            p = self.profile_objects[event.GetSelection()]
        except IndexError:
            return # TODO
        p.on_focus()

    def launch_solo_server(self, event):
        """Launch the official bitcoin client in server mode.

        This allows poclbm to connect to it for mining solo.
        """
        try:
            subprocess.Popen(self.bitcoin_executable + " -server")
        except OSError:
            self.message(
                "Couldn't find Bitcoin at %s. Is your path set correctly?" % self.bitcoin_executable,
                "Launch failed", wx.ICON_ERROR|wx.OK)
            return
        self.message(
            "Client launched ok. You can start the miner now.",
            "Launched ok.",
            wx.OK)
        
    def create_solo_password(self, event):
        """Prompt the user for login credentials to the bitcoin client.

        These are required to connect to the client over JSON-RPC and are
        stored in 'bitcoin.conf'.
        """
        filename = os.path.join(os.getenv("APPDATA"), "Bitcoin", "bitcoin.conf")
        if os.path.exists(filename):
            result = self.message("%s already exists. Overwrite?" % filename,
                "bitcoin.conf already exists.",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
            if result == wx.ID_NO:
                return

        dialog = SoloPasswordRequest(self, 'Enter password')
        result = dialog.ShowModal()
        dialog.Destroy()
        if result == wx.ID_CANCEL:
            return
        
        with open(filename, "w") as f:
            f.write('\nrpcuser=%s\nrpcpassword=%s' % dialog.get_value())
            f.close()

        self.message("Wrote bitcoin.conf ok.", "Success", wx.OK)
                                  

class SoloPasswordRequest(wx.Dialog):
    """Dialog prompting user for login credentials for solo mining."""
    def __init__(self, parent, title):
        style = wx.DEFAULT_DIALOG_STYLE
        vbox = wx.BoxSizer(wx.VERTICAL)
        wx.Dialog.__init__(self, parent, -1, title, style=style)
        self.user_lbl = wx.StaticText(self, -1, _("Username:"))
        self.txt_username = wx.TextCtrl(self, -1, _(""))
        self.pass_lbl = wx.StaticText(self, -1, _("Password:"))
        self.txt_pass = wx.TextCtrl(self, -1, _(""), style=wx.TE_PASSWORD)
        grid_sizer_1 = wx.FlexGridSizer(2, 2, 5, 5)
        grid_sizer_1.Add(self.user_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_username, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.pass_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_pass, 0, wx.EXPAND, 0)
        buttons = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        vbox.Add(grid_sizer_1, wx.EXPAND|wx.ALL, 10)
        vbox.Add(buttons)
        self.SetSizerAndFit(vbox)

    def get_value(self):
        """Return the (username, password) supplied by the user."""
        return self.txt_username.GetValue(), self.txt_pass.GetValue()

class AboutGuiminer(wx.Dialog):
    """About dialog for the app with a donation address."""
    donation_address = "1MDDh2h4cAZDafgc94mr9q95dhRYcJbNQo"
    def __init__(self, parent, id, title):
        wx.Dialog.__init__(self, parent, id, title)
        panel = wx.Panel(self, -1)
        vbox = wx.BoxSizer(wx.VERTICAL)

        text = ABOUT_TEXT % (__version__, AboutGuiminer.donation_address)
        self.about_text = wx.StaticText(self, -1, text)
        self.copy_btn = wx.Button(self, -1, "Copy address to clipboard")                            
        vbox.Add(self.about_text)
        vbox.Add(self.copy_btn, 0, wx.ALIGN_BOTTOM|wx.ALIGN_CENTER_HORIZONTAL, 0)
        self.SetSizer(vbox)

        self.copy_btn.Bind(wx.EVT_BUTTON, self.on_copy)        

    def on_copy(self, event):
        """Copy the donation address to the clipboard."""
        if wx.TheClipboard.Open():
            data = wx.TextDataObject()
            data.SetText(AboutGuiminer.donation_address)
            wx.TheClipboard.SetData(data)
        wx.TheClipboard.Close()
        

if __name__ == "__main__":
    import gettext
    gettext.install("app") # replace with the appropriate catalog name

    global USE_MOCK
    USE_MOCK = '--mock' in sys.argv

    try:
        app = wx.PySimpleApp(0)
        wx.InitAllImageHandlers()
        frame_1 = MyFrame(None, -1, "")
        app.SetTopWindow(frame_1)
        frame_1.Show()
        app.MainLoop()
    except:
        logging.exception("Exception:")
        raise
