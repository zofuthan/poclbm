"""poclbm-gui - GUI miner for poclbm

Copyright 2011 Chris MacLeod
This program is released under the GNU GPL. See LICENSE.txt for details.
"""

import sys, os, subprocess, errno, re, threading, logging, time
import wx
import json

from wx.lib.agw import flatnotebook as fnb
from wx.lib.agw import hyperlink
from wx.lib.newevent import NewEvent

__version__ = '2011-03-13'

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

# Layout constants
LBL_STYLE = wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL

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
    """Return a list of available OpenCL devices."""
    import pyopencl
    platform = pyopencl.get_platforms()[0]
    devices = platform.get_devices()
    if len(devices) == 0:
        raise IOError
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
        
def add_tooltip(widget, text):
    """Add a tooltip to widget with the specified text."""
    tooltip = wx.ToolTip(_(text))
    widget.SetToolTip(tooltip)

def format_khash(rate):
    """Format rate for display. A rate of 0 means just connected."""
    if rate > 10**6:
        return "%.1f Ghash/s" % (rate / 1000000.)
    if rate > 10**3:
        return "%.1f Mhash/s" % (rate / 1000.)
    elif rate == 0:
        return "Connected"
    else:
        return "%d khash/s" % rate

def init_logger():
    """Set up and return the logging object and custom formatter."""
    logger = logging.getLogger("poclbm-gui")
    logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(
        os.path.join(get_module_path(), 'guiminer.log'), 'w')
    formatter = logging.Formatter("%(asctime)s: %(message)s",
                                  "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger, formatter

logger, formatter = init_logger()

class ConsolePanel(wx.Panel):
    """Panel that displays logging events.
    
    Uses with a StreamHandler to log events to a TextCtrl. Thread-safe.
    """
    def __init__(self, parent):
        wx.Panel.__init__(self, parent, -1)
        self.parent = parent
        
        vbox = wx.BoxSizer(wx.VERTICAL)
        style = wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL
        self.text = wx.TextCtrl(self, -1, "", style=style)
        vbox.Add(self.text, 1, wx.EXPAND)        
        self.SetSizer(vbox)
        
        self.handler = logging.StreamHandler(self)
        logger.addHandler(self.handler)
        
    def on_focus(self):
        """On focus, clear the status bar."""
        # TODO: could show something helpful on the statusbar instead
        self.parent.statusbar.SetStatusText("", 0)
        self.parent.statusbar.SetStatusText("", 1)
    
    def on_close(self):
        """On closing, stop handling logging events."""
        logger.removeHandler(self.handler)

    def write(self, text):
        """Forward logging events to our TextCtrl."""
        wx.CallAfter(self.text.WriteText, text)


class SummaryPanel(wx.Panel):
    """Panel that displays a summary of all miners."""
    
    def __init__(self, parent):
        wx.Panel.__init__(self, parent, -1)
        self.parent = parent
        self.timer = wx.Timer(self)
        self.timer.Start(2000)
        self.Bind(wx.EVT_TIMER, self.on_update_tooltip)
        
        flags = wx.ALIGN_CENTER_HORIZONTAL | wx.ALL
        border = 5
        self.column_headers = [
            (wx.StaticText(self, -1, _("Miner")), 0, flags, border),
            (wx.StaticText(self, -1, _("Speed")), 0, flags, border),
            (wx.StaticText(self, -1, _("Accepted")), 0, flags, border),
            (wx.StaticText(self, -1, _("Stale")), 0, flags, border),
            (wx.StaticText(self, -1, _("Start/Stop")), 0, flags, border),
            (wx.StaticText(self, -1, _("Autostart")), 0, flags, border),   
        ]
        font = wx.SystemSettings_GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font.SetUnderlined(True)
        for st in self.column_headers:
            st[0].SetFont(font) 
        
        self.grid = wx.FlexGridSizer(0, len(self.column_headers), 2, 2)

        self.grid.AddMany(self.column_headers)        
        self.add_miners_to_grid()
        
        self.grid.AddGrowableCol(0)
        self.grid.AddGrowableCol(1)
        self.grid.AddGrowableCol(2)
        self.grid.AddGrowableCol(3)
        self.SetSizer(self.grid)
        
    def add_miners_to_grid(self):
        """Add a summary row for each miner to the summary grid."""
        
        # Remove any existing widgets except the column headers.
        for i in reversed(range(len(self.column_headers), len(self.grid.GetChildren()))):
            self.grid.Hide(i)
            self.grid.Remove(i)
                
        for p in self.parent.profile_panels:
            p.clear_summary_widgets()                    
            self.grid.AddMany(p.get_summary_widgets(self))
            
        self.grid.Layout()
        
    def on_close(self):
        self.timer.Stop()
    
    def on_update_tooltip(self, event=None):
        if self.parent.nb.GetSelection() != self.parent.nb.GetPageIndex(self):
            return 
        
        for p in self.parent.profile_panels:
            p.update_summary()
        
        self.parent.statusbar.SetStatusText("", 0) # TODO: show something
        total_rate = sum(p.last_rate for p in self.parent.profile_panels
                         if p.is_mining)                
        if any(p.is_mining for p in self.parent.profile_panels):
            self.parent.statusbar.SetStatusText(format_khash(total_rate), 1)
        else:
            self.parent.statusbar.SetStatusText("", 0)       
    
    def on_focus(self):
        """On focus, show the statusbar text."""
        self.on_update_tooltip()

class GUIMinerTaskBarIcon(wx.TaskBarIcon):
    """Taskbar icon for the GUI.

    Shows status messages on hover and opens on click.
    """
    TBMENU_RESTORE = wx.NewId()
    TBMENU_CLOSE = wx.NewId()
    TBMENU_CHANGE = wx.NewId()
    TBMENU_REMOVE = wx.NewId()
    
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
        menu.Append(self.TBMENU_CLOSE, "Close")
        return menu
   
    def on_taskbar_activate(self, evt):
        if self.frame.IsIconized():
            self.frame.Iconize(False)
        if not self.frame.IsShown():
            self.frame.Show(True)
        self.frame.Raise()

    def on_taskbar_close(self, evt):
        wx.CallAfter(self.frame.Close, force=True)

    def on_update_tooltip(self, event):
        """Refresh the taskbar icon's status message."""
        objs = self.frame.profile_panels
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
        logger.debug('Listener for "%s" started' % self.parent.name)
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
            logger.info('Listener for "%s": %s', self.parent.name, line)
            wx.PostEvent(self.parent, event)
        logger.debug('Listener for "%s" shutting down' % self.parent.name)
        
        
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
    def __init__(self, parent, id, devices, servers, defaults, statusbar, data):
        wx.Panel.__init__(self, parent, id)
        self.parent = parent
        self.servers = servers
        self.defaults = defaults        
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
        self.last_update_time = None
        self.autostart = False
        self.server_lbl = wx.StaticText(self, -1, _("Server:"))                
        self.server = wx.ComboBox(self, -1, 
                                  choices=[s['name'] for s in servers], 
                                  style=wx.CB_READONLY)
        self.website_lbl = wx.StaticText(self, -1, _("Website:"))
        self.website = hyperlink.HyperLinkCtrl(self, -1, "")
        self.host_lbl = wx.StaticText(self, -1, _("Host:"))
        self.txt_host = wx.TextCtrl(self, -1, "")
        self.port_lbl = wx.StaticText(self, -1, _("Port:"))
        self.txt_port = wx.TextCtrl(self, -1, "")
        self.user_lbl = wx.StaticText(self, -1, _("Username:"))
        self.txt_username = wx.TextCtrl(self, -1, "")
        self.pass_lbl = wx.StaticText(self, -1, _("Password:"))
        self.txt_pass = wx.TextCtrl(self, -1, "", style=wx.TE_PASSWORD)
        self.device_lbl = wx.StaticText(self, -1, _("Device:"))
        self.device_listbox = wx.ComboBox(self, -1, choices=devices, style=wx.CB_READONLY)
        self.flags_lbl = wx.StaticText(self, -1, _("Extra flags:"))        
        self.txt_flags = wx.TextCtrl(self, -1, "")
        self.extra_info = wx.StaticText(self, -1, "")
        
        self.all_widgets = [self.server_lbl, self.server,
                            self.website_lbl, self.website,
                            self.host_lbl, self.txt_host,
                            self.port_lbl, self.txt_port,
                            self.user_lbl, self.txt_username,
                            self.pass_lbl, self.txt_pass,
                            self.device_lbl, self.device_listbox,
                            self.flags_lbl, self.txt_flags, 
                            self.extra_info]
        
        self.start = wx.Button(self, -1, _("Start mining!"))        

        self.device_listbox.SetSelection(0)
        self.server.SetStringSelection(self.defaults.get('default_server'))
        
        self.set_data(data)

        self.start.Bind(wx.EVT_BUTTON, self.toggle_mining)
        self.server.Bind(wx.EVT_COMBOBOX, self.on_select_server)
        self.Bind(EVT_UPDATE_HASHRATE, lambda event: self.update_khash(event.rate))
        self.Bind(EVT_UPDATE_ACCEPTED, lambda event: self.update_shares(event.accepted))
        self.Bind(EVT_UPDATE_STATUS, lambda event: self.update_status(event.text))
        self.Bind(EVT_UPDATE_SOLOCHECK, lambda event: self.update_solo())
        self.update_shares_on_statusbar()                       
        self.clear_summary_widgets()

    def get_data(self):
        """Return a dict of our profile data."""        
        return dict(name=self.name,
                    hostname=self.txt_host.GetValue(),
                    port=self.txt_port.GetValue(),
                    username=self.txt_username.GetValue(),
                    password=self.txt_pass.GetValue(),
                    device=self.device_listbox.GetSelection(),
                    flags=self.txt_flags.GetValue(),
                    autostart=self.autostart)

    def set_data(self, data):
        """Set our profile data to the information in data. See get_data()."""
        default_server = self.get_server_by_field(
                            self.defaults['default_server'], 'name')
        self.name = (data.get('name') or
                     default_server.get('name', 'Miner'))
                
        # Backwards compatibility: hostname key used to be called server.
        # We only save out hostname now but accept server from old INI files.
        hostname = (data.get('hostname') or
                    data.get('server') or
                    default_server['host'])
        self.txt_host.SetValue(hostname)
        server = self.get_server_by_field(hostname, 'host')
                                    
        self.server.SetStringSelection(server.get('name', "Other"))
                                            
        self.txt_username.SetValue(
            data.get('username') or 
            self.defaults.get('default_username', ''))
        
        self.txt_pass.SetValue(
            data.get('password') or
            self.defaults.get('default_password', ''))
                    
        self.txt_port.SetValue(str(
            data.get('port') or
            server.get('port', 8332)))
                
        self.txt_flags.SetValue(data.get('flags', ''))
        self.autostart = data.get('autostart', False)

        # Handle case where they removed devices since last run.
        device_index = data.get('device', None)
        if device_index is not None and device_index < self.device_listbox.GetCount():
            self.device_listbox.SetSelection(device_index)
                    
        self.change_server(server)            
        
    def clear_summary_widgets(self):
        """Release all our summary widgets."""
        self.summary_name = None
        self.summary_status = None
        self.summary_shares_accepted = None
        self.summary_shares_stale = None
        self.summary_start = None
        self.summary_autostart = None
    
    def get_start_stop_state(self):
        """Return appropriate text for the start/stop button."""
        return "Stop" if self.is_mining else "Start"
    
    def update_summary(self):
        """Update our summary fields if possible."""
        if not self.summary_panel:
            return
        
        self.summary_name.SetLabel(self.name)
        if not self.is_mining:
            text = "Stopped"
        elif self.is_possible_error:
            text = "Connection problems"
        else:
            text = format_khash(self.last_rate)        
        self.summary_status.SetLabel(text)
        
        if self.last_update_type == ProfilePanel.SOLO:            
            self.summary_shares_accepted.SetLabel(str(self.diff1_hashes))
            self.summary_shares_invalid.SetLabel("-")
        else: # TODO: we assume POOL here
            self.summary_shares_accepted.SetLabel(str(self.accepted_shares))
            self.summary_shares_invalid.SetLabel(str(self.invalid_shares))            

        self.summary_start.SetLabel(self.get_start_stop_state())
        self.summary_autostart.SetValue(self.autostart)
        self.summary_panel.grid.Layout() 
    
    def get_summary_widgets(self, summary_panel):
        """Return a list of summary widgets suitable for sizer.AddMany."""
        self.summary_panel = summary_panel
        self.summary_name = wx.StaticText(summary_panel, -1, self.name)
        self.summary_name.Bind(wx.EVT_LEFT_UP, self.show_this_panel)
                
        self.summary_status = wx.StaticText(summary_panel, -1, "Stopped")
        self.summary_shares_accepted = wx.StaticText(summary_panel, -1, "0")
        self.summary_shares_invalid = wx.StaticText(summary_panel, -1, "0")
        self.summary_start =  wx.Button(summary_panel, -1, self.get_start_stop_state(), style=wx.BU_EXACTFIT)
        self.summary_start.Bind(wx.EVT_BUTTON, self.toggle_mining)
        self.summary_autostart = wx.CheckBox(summary_panel, -1)
        self.summary_autostart.Bind(wx.EVT_CHECKBOX, self.toggle_autostart)
        self.summary_autostart.SetValue(self.autostart)
        return [
            (self.summary_name, 0, wx.ALIGN_CENTER_HORIZONTAL),
            (self.summary_status, 0, wx.ALIGN_CENTER_HORIZONTAL, 0),
            (self.summary_shares_accepted, 0, wx.ALIGN_CENTER_HORIZONTAL, 0),
            (self.summary_shares_invalid, 0, wx.ALIGN_CENTER_HORIZONTAL, 0),            
            (self.summary_start, 0, wx.ALIGN_CENTER, 0),
            (self.summary_autostart, 0, wx.ALIGN_CENTER, 0)
        ]

    def show_this_panel(self, event):
        """Set focus to this panel."""
        self.parent.SetSelection(self.parent.GetPageIndex(self))

    def toggle_autostart(self, event):
        self.autostart = event.IsChecked()

    def toggle_mining(self, event):
        """Stop or start the miner."""
        if self.is_mining:
            self.stop_mining()            
        else:
            self.start_mining()
        self.start.SetLabel("%s mining!" % self.get_start_stop_state())
        self.update_summary()
        
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
                self.txt_host.GetValue(),
                self.txt_port.GetValue(),
                self.device_listbox.GetSelection(),
                self.txt_flags.GetValue()
        )
        # Avoid showing a console window when frozen
        try: import win32process
        except ImportError: flags = 0
        else: flags = win32process.CREATE_NO_WINDOW
                
        try:
            logger.debug('Running command: ' + cmd)
            self.miner = subprocess.Popen(cmd, cwd=folder, 
                                          stdout=subprocess.PIPE,
                                          creationflags=flags)
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
          
    def update_khash(self, rate):
        """Update our rate according to a report from the listener thread.

        If we are receiving rate messages then it means poclbm is no longer
        reporting errors.
        """
        self.last_rate = rate
        self.set_status(format_khash(rate), 1)
        if self.is_possible_error:
            self.update_shares_on_statusbar()
            self.is_possible_error = False

    def update_shares_on_statusbar(self):
        """For pooled mining, show the shares on the statusbar."""
        text = "Shares: %d accepted" % self.accepted_shares
        if self.invalid_shares > 0:
            text += ", %d stale/invalid" % self.invalid_shares         
        text += " %s" % self.format_last_update_time()
        self.set_status(text, 0) 

    def update_last_time(self):
        """Set the last update time to now (in local time)."""
        self.last_update_time = time.localtime()
        
    def format_last_update_time(self):
        """Format last update time for display."""
        time_fmt = '%I:%M:%S%p'
        if self.last_update_time is None:
            return ""
        return "- last at %s" % time.strftime(time_fmt, self.last_update_time)

    def update_shares(self, accepted):
        """Update our shares with a report from the listener thread."""
        self.last_update_type = ProfilePanel.POOL
        if accepted:
            self.accepted_shares += 1
        else:
            self.invalid_shares += 1
        self.update_last_time()
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
            return "%s: %s" % (self.name, format_khash(self.last_rate))
        else:
            return "%s: Stopped" % self.name

    def update_solo_status(self):
        """For solo mining, show the number of easy hashes solved.

        This is a rough indicator of how fast the miner is going,
        since some small fraction of easy hashes are also valid solutions
        to the block.
        """
        text = "Difficulty 1 hashes: %d %s" % \
            (self.diff1_hashes, self.format_last_update_time())
        self.set_status(text, 0)

    def update_solo(self):
        """Update our easy hashes with a report from the listener thread."""
        self.last_update_type = ProfilePanel.SOLO
        self.diff1_hashes += 1
        self.update_last_time()
        self.update_solo_status()
        
    def on_select_server(self, event):
        """Update our info in response to a new server choice."""
        new_server_name = self.server.GetValue()
        new_server = self.get_server_by_field(new_server_name, 'name')    
        self.change_server(new_server)
    
    def get_server_by_field(self, target_val, field):
        """Return the first server dict with the specified val, or {}."""
        for s in self.servers:
            if s.get(field) == target_val:
                return s
        return {}

    def set_widgets_visible(self, widgets, show=False):
        """Show or hide each widget in widgets according to the show flag."""
        for w in widgets:
            if show:
                w.Show()
            else:
                w.Hide()        

    def set_tooltips(self):
        add_tooltip(self.server, "Server to connect to. Different servers have different fees and features.\nCheck their websites for full information.")
        add_tooltip(self.website, "Website of the currently selected server. Click to visit.")
        add_tooltip(self.device_listbox, "Available OpenCL devices on your system.")
        add_tooltip(self.txt_host, "Host address, without http:// prefix.")
        add_tooltip(self.txt_port, "Server port. This is usually 8332.")
        add_tooltip(self.txt_username, "The miner's username.\nMay be different than your account username.\nExample: Kiv.GPU")
        add_tooltip(self.txt_pass, "The miner's password.\nMay be different than your account password.")
        add_tooltip(self.txt_flags, "Extra flags to pass to the miner.\nFor Radeon HD 5xxx series use -v -w128 for best results.\nFor other cards consult the forum.")
    
    def change_server(self, new_server):
        """Change the server to new_server, updating fields as needed."""
        
        # Set defaults before we do server specific code
        self.set_tooltips()
        self.set_widgets_visible(self.all_widgets, True)        
               
        url = new_server.get('url', 'n/a')
        self.website.SetLabel(url)
        self.website.SetURL(url)
        
        if 'host' in new_server:
            self.txt_host.SetValue(new_server['host'])
        if 'port' in new_server:
            self.txt_port.SetValue(str(new_server['port']))
        
        # Call server specific code.
        name = new_server.get('name', 'Other').lower()
        if name == "slush's pool": self.layout_slush()
        elif name == "bitpenny": self.layout_bitpenny()
        elif name == "deepbit": self.layout_deepbit()        
        else: self.layout_default()
        
        self.Layout()
    
    def layout_init(self):
        """Create the sizers for this frame."""
        self.frame_sizer = wx.BoxSizer(wx.VERTICAL)
        self.frame_sizer.Add((20, 10), 0, wx.EXPAND, 0)
        self.inner_sizer = wx.GridBagSizer(10, 5)        
    
    def layout_server_and_website(self, row):
        """Lay out the server and website widgets in the specified row."""
        self.inner_sizer.Add(self.server_lbl, (row,0), flag=LBL_STYLE)
        self.inner_sizer.Add(self.server, (row,1), flag=wx.EXPAND)        
        self.inner_sizer.Add(self.website_lbl, (row,2), flag=LBL_STYLE)
        self.inner_sizer.Add(self.website, (row,3), flag=wx.ALIGN_CENTER_VERTICAL)        
    
    def layout_host_and_port(self, row):
        """Lay out the host and port widgets in the specified row."""
        self.inner_sizer.Add(self.host_lbl, (row,0), flag=LBL_STYLE)
        self.inner_sizer.Add(self.txt_host, (row,1), flag=wx.EXPAND)
        self.inner_sizer.Add(self.port_lbl, (row,2), flag=LBL_STYLE)
        self.inner_sizer.Add(self.txt_port, (row,3), flag=wx.EXPAND)
    
    def layout_user_and_pass(self, row):
        """Lay out the user and pass widgets in the specified row."""
        self.inner_sizer.Add(self.user_lbl, (row,0), flag=LBL_STYLE)
        self.inner_sizer.Add(self.txt_username, (row,1), flag=wx.EXPAND)
        self.inner_sizer.Add(self.pass_lbl, (row,2), flag=LBL_STYLE)
        self.inner_sizer.Add(self.txt_pass, (row,3), flag=wx.EXPAND)
            
    def layout_device_and_flags(self, row):
        """Lay out the device and flags widgets in the specified row."""
        self.inner_sizer.Add(self.device_lbl, (row,0), flag=LBL_STYLE)
        self.inner_sizer.Add(self.device_listbox, (row,1), flag=wx.EXPAND)
        self.inner_sizer.Add(self.flags_lbl, (row,2), flag=LBL_STYLE)
        self.inner_sizer.Add(self.txt_flags, (row,3), flag=wx.EXPAND)
    
    def layout_finish(self):
        """Lay out the start button and fit the sizer to the window."""
        self.frame_sizer.Add(self.inner_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)        
        self.frame_sizer.Add(self.start, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)        
        self.inner_sizer.AddGrowableCol(1)
        self.inner_sizer.AddGrowableCol(3)        
        self.SetSizerAndFit(self.frame_sizer)
    
    def layout_default(self):
        """Lay out a default miner with no custom changes."""
        self.user_lbl.SetLabel("Username:")
        
        self.set_widgets_visible([self.extra_info], False)
        self.layout_init()
        self.layout_server_and_website(row=0)
        is_custom = self.server.GetStringSelection().lower() in ["other", "solo"]
        if is_custom:
            self.layout_host_and_port(row=1)
        else:
            self.set_widgets_visible([self.host_lbl, self.txt_host, 
                                      self.port_lbl, self.txt_port], False)
            
        self.layout_user_and_pass(row=1 + int(is_custom))
        self.layout_device_and_flags(row=2 + int(is_custom))
        self.layout_finish()
    
    ############################            
    # Begin server specific code
    def layout_bitpenny(self):
        """BitPenny doesn't require registration or a password.
        
        The username is just their receiving address.
        """
        invisible = [self.txt_pass, self.txt_host, self.txt_port,
                     self.pass_lbl, self.host_lbl, self.port_lbl]
        self.set_widgets_visible(invisible, False)
            
        self.layout_init()
        self.layout_server_and_website(row=0)                            
        self.inner_sizer.Add(self.user_lbl, (1,0), flag=LBL_STYLE)
        self.inner_sizer.Add(self.txt_username, (1,1), span=(1,3), flag=wx.EXPAND)        
        self.layout_device_and_flags(row=2)        
        self.inner_sizer.Add(self.extra_info,(3,0), span=(1,4), flag=wx.EXPAND)                
        self.layout_finish()
        
        self.extra_info.SetLabel("No registration is required - just enter an address and press Start.")
        self.txt_pass.SetValue('poclbm-gui')
        self.user_lbl.SetLabel("Address:")
        add_tooltip(self.txt_username,
            "Your receiving address for Bitcoins.\nE.g.: 1A94cjRpaPBMV9ZNWFihB5rTFEeihBALgc")        
    
    def layout_slush(self):
        """Slush's pool uses a separate username for each miner."""
        self.layout_default()
        add_tooltip(self.txt_username,
            "Your miner username (not your account username).\nExample: Kiv.GPU")
        add_tooltip(self.txt_pass,
            "Your miner password (not your account password).")

    def layout_deepbit(self):
        """Deepbit uses an email address for a username."""
        self.layout_default()
        add_tooltip(self.txt_username,
            "The e-mail address you registered with.")
        self.user_lbl.SetLabel("Email:")
        
    # End server specific code
    ##########################                 

                                

class PoclbmFrame(wx.Frame):
    def __init__(self, *args, **kwds):
        wx.Frame.__init__(self, *args, **kwds)
        style = fnb.FNB_X_ON_TAB | fnb.FNB_FF2 | fnb.FNB_HIDE_ON_SINGLE_TAB
        self.nb = fnb.FlatNotebook(self, -1, style=style)        
        self.console_panel = None
        self.summary_panel = None
        
        # Servers and defaults are required, it's a fatal error not to have
        # them.  
        server_config_path = os.path.join(get_module_path(), 'servers.ini')
        with open(server_config_path) as f:
            data = json.load(f)
            self.servers = data.get('servers')
                    
        defaults_config_path = os.path.join(get_module_path(), 'defaults.ini')
        with open(defaults_config_path) as f:
            self.defaults = json.load(f)
               
        self.menubar = wx.MenuBar()
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, _("&New miner..."), _("Create a new miner profile"), wx.ITEM_NORMAL)
        file_menu.Append(wx.ID_SAVE, _("&Save settings"), _("Save your settings"), wx.ITEM_NORMAL)
        file_menu.Append(wx.ID_OPEN, _("&Load settings"), _("Load stored settings"), wx.ITEM_NORMAL)
        file_menu.Append(wx.ID_EXIT, "", "", wx.ITEM_NORMAL)
        self.menubar.Append(file_menu, _("&File"))

        ID_SUMMARY, ID_CONSOLE = wx.NewId(), wx.NewId()
        view_menu = wx.Menu()
        view_menu.Append(ID_SUMMARY, _("Show summary"), "Show summary of all miners", wx.ITEM_NORMAL)
        view_menu.Append(ID_CONSOLE, _("Show console"), "Show console logs", wx.ITEM_NORMAL)
        self.menubar.Append(view_menu, _("&View"))

        ID_SOLO, ID_PATHS, ID_LAUNCH = wx.NewId(), wx.NewId(), wx.NewId()
        solo_menu = wx.Menu()
        solo_menu.Append(ID_SOLO, "&Create solo password...", _("Configure a user/pass for solo mining"), wx.ITEM_NORMAL)
        solo_menu.Append(ID_PATHS, "&Set Bitcoin client path...", _("Set the location of the official Bitcoin client"), wx.ITEM_NORMAL)
        solo_menu.Append(ID_LAUNCH, "&Launch Bitcoin client", _("Launch the official Bitcoin client for solo mining"), wx.ITEM_NORMAL)
        self.menubar.Append(solo_menu, _("&Solo utilities"))
                      
        help_menu = wx.Menu()
        help_menu.Append(wx.ID_ABOUT, _("&About/Donate..."), "", wx.ITEM_NORMAL)
        
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
        self.Bind(wx.EVT_MENU, self.save_config, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.load_config, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.on_menu_exit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self.set_official_client_path, id=ID_PATHS)
        self.Bind(wx.EVT_MENU, self.show_console, id=ID_CONSOLE)
        self.Bind(wx.EVT_MENU, self.show_summary, id=ID_SUMMARY)
        self.Bind(wx.EVT_MENU, self.show_about_dialog, id=wx.ID_ABOUT)
        self.Bind(wx.EVT_MENU, self.create_solo_password, id=ID_SOLO)
        self.Bind(wx.EVT_MENU, self.launch_solo_server, id=ID_LAUNCH)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ICONIZE, lambda event: self.Hide())
        self.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSING, self.on_page_closing)
        self.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSED, self.on_page_closed)
        self.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CHANGED, self.on_page_changed)

        self.load_config()           
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
        self.vertical_sizer.Add(self.nb, 1, wx.EXPAND, 20)
        self.SetSizer(self.vertical_sizer)
        self.vertical_sizer.SetSizeHints(self)
        self.SetSizerAndFit(self.vertical_sizer)
        self.Layout()

    @property
    def profile_panels(self):
        """Return a list of currently available ProfilePanel."""
        pages = [self.nb.GetPage(i) for i in range(self.nb.GetPageCount())]
        return [p for p in pages if 
                p != self.console_panel and p != self.summary_panel]
    
    def add_profile(self, data={}):
        """Add a new ProfilePanel to the list of tabs."""
        panel = ProfilePanel(self.nb, -1, self.devices, self.servers, 
                             self.defaults, self.statusbar, data)
        self.nb.AddPage(panel, panel.name)
        # The newly created profile should have focus.
        self.nb.EnsureVisible(self.nb.GetPageCount() - 1)
        
        if self.summary_panel is not None:
            self.summary_panel.add_miners_to_grid() # Show new entry on summary
        
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
            name = dialog.GetValue().strip()
            if not name: name = "Untitled"
            self.add_profile(dict(name=name))

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
        """Minimize to tray if they click "close" but exit otherwise.
        
        On closing, stop any miners that are currently working.
        """
        if event.CanVeto():
            self.Hide()
            event.Veto()
        else:
            if self.console_panel is not None:
                self.console_panel.on_close()
            if self.summary_panel is not None:
                self.summary_panel.on_close()
            for p in self.profile_panels:
                p.stop_mining()
            if self.tbicon is not None:
                self.tbicon.RemoveIcon()
                self.tbicon.timer.Stop()
                self.tbicon.Destroy()
            event.Skip()

    def save_config(self, event):
        """Save the current miner profiles to our config file in JSON format."""
        folder, config_filename = self.get_storage_location()
        mkdir_p(folder)
        profile_data = [p.get_data() for p in self.profile_panels]
        config_data = dict(show_console=self.is_console_visible(),
                           show_summary=self.is_summary_visible(),
                           profiles=profile_data,
                           bitcoin_executable=self.bitcoin_executable)
        logger.debug('Saving: ' + json.dumps(config_data))
        with open(config_filename, 'w') as f:
            json.dump(config_data, f, indent=4)
            self.message("Profiles saved OK to %s." % config_filename,
                          "Save successful", wx.OK | wx.ICON_INFORMATION)
        # TODO: handle save failed
    
    def load_config(self, event=None):
        """Load JSON profile info from the config file."""
        config_data = {}
        
        _, config_filename = self.get_storage_location()        
        if os.path.exists(config_filename):
            with open(config_filename) as f:
                config_data.update(json.load(f))
            logger.debug('Loaded: ' + json.dumps(config_data))
        
        executable = config_data.get('bitcoin_executable', None)
        if executable is not None:
            self.bitcoin_executable = executable
            
        # Shut down any existing miners before they get clobbered
        if(any(p.is_mining for p in self.profile_panels)):
            result = self.message(
                "Loading profiles will stop any currently running miners. Continue?",
                "Load profile", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
            if result == wx.ID_NO:
                return                      
        for p in reversed(self.profile_panels):            
            p.stop_mining()
            self.nb.DeletePage(self.nb.GetPageIndex(p))

        # If present, summary should be the leftmost tab on startup.
        if config_data.get('show_summary', False):
            self.show_summary() 
                
        profile_data = config_data.get('profiles', [])
        for d in profile_data:
            self.add_profile(d)
            
        if not any(profile_data):  
            self.add_profile() # Create a default one using defaults.ini         
                    
        if config_data.get('show_console', False):
            self.show_console()
            
        for p in self.profile_panels:
            if p.autostart:
                p.start_mining()
                                                       
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
        
        If they are closing a special panel, we have to shut it down.
        If the tab has a miner running in it, we have to stop the miner
        before letting the tab be removed.
        """
        p = self.nb.GetPage(event.GetSelection())
        
        if p == self.console_panel:
            self.console_panel.on_close()
            self.console_panel = None
            event.Skip()
            return
        if p == self.summary_panel:
            self.summary_panel.on_close()
            self.summary_panel = None
            event.Skip()
            return
                   
        if p.is_mining:
            result = self.message(
                "Closing this miner will stop it. Continue?", "Close miner",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
            if result == wx.ID_NO:
                event.Veto()
                return            
        p.stop_mining()
        event.Skip() # OK to close the tab now
    
    def on_page_closed(self, event):
        if self.summary_panel is not None:
            self.summary_panel.add_miners_to_grid() # Remove miner summary

    def on_page_changed(self, event):
        """Handle a tab change event.

        Ensures the status bar shows the status of the tab that has focus.
        """
        p = self.nb.GetPage(event.GetSelection())
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
                "Launch failed", wx.ICON_ERROR | wx.OK)
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

    def is_console_visible(self):
        """Return True if the console is visible."""
        return self.nb.GetPageIndex(self.console_panel) != -1
                                  
    def show_console(self, event=None):
        """Show the console log in its own tab."""
        if self.is_console_visible():
            return # Console already shown
        self.console_panel = ConsolePanel(self)
        self.nb.AddPage(self.console_panel, "Console")
        self.nb.EnsureVisible(self.nb.GetPageCount() - 1)
    
    def is_summary_visible(self):
        """Return True if the summary is visible."""
        return self.nb.GetPageIndex(self.summary_panel) != -1
    
    def show_summary(self, event=None):
        """Show the summary window in its own tab."""
        if self.is_summary_visible():
            return
        self.summary_panel = SummaryPanel(self)
        self.nb.AddPage(self.summary_panel, "Summary")
        index = self.nb.GetPageIndex(self.summary_panel)
        self.nb.SetSelection(index)
    
    def on_menu_exit(self, event):
        self.Close(force=True)
                                       

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
        grid_sizer_1.Add(self.user_lbl, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_username, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.pass_lbl, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_pass, 0, wx.EXPAND, 0)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(grid_sizer_1, wx.EXPAND | wx.ALL, 10)
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
        vbox = wx.BoxSizer(wx.VERTICAL)

        text = ABOUT_TEXT % (__version__, AboutGuiminer.donation_address)
        self.about_text = wx.StaticText(self, -1, text)
        self.copy_btn = wx.Button(self, -1, "Copy address to clipboard")                            
        vbox.Add(self.about_text)
        vbox.Add(self.copy_btn, 0, wx.ALIGN_BOTTOM | wx.ALIGN_CENTER_HORIZONTAL, 0)
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
        frame_1 = PoclbmFrame(None, -1, "")
        app.SetTopWindow(frame_1)
        frame_1.Show()
        app.MainLoop()
    except:
        logging.exception("Exception:")
        raise
