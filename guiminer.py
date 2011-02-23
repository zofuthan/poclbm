import sys, os, subprocess, errno, re, threading
import wx
import json

from wx.lib.agw import flatnotebook as fnb
from wx.lib.newevent import NewEvent

def strip_whitespace(s):
    s = re.sub(r"( +)|\t+", " ", s)
    return s.strip()

def get_opencl_devices():
    import pyopencl
    platform = pyopencl.get_platforms()[0]
    devices = platform.get_devices()
    if len(devices) == 0:
        raise IOError
    return ['[%d] %s' % (i, strip_whitespace(device.name)[:25])
                         for (i, device) in enumerate(devices)]

def get_module_path():
    if hasattr(sys, 'frozen'):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(__file__)

def get_icon():
    image_path = os.path.join(get_module_path(), 'logo.png')
    image = wx.Image(image_path, wx.BITMAP_TYPE_PNG).ConvertToBitmap()
    icon = wx.EmptyIcon()
    icon.CopyFromBitmap(image)
    return icon
    
def _mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST:
            pass
        else: raise

(UpdateHashRateEvent, EVT_UPDATE_HASHRATE) = NewEvent()
(UpdateAcceptedEvent, EVT_UPDATE_ACCEPTED) = NewEvent()
(UpdateStatusdEvent, EVT_UPDATE_STATUS) = NewEvent()

class GUIMinerTaskBarIcon(wx.TaskBarIcon):
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

    def create_popup_menu(self):
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
            text = '\n'.join(p.get_tooltip_text() for p in objs)
            self.SetIcon(self.icon, text)    

class MinerListenerThread(threading.Thread):
    def __init__(self, parent, miner):
        threading.Thread.__init__(self)
        self.shutdown_event = threading.Event()
        self.parent = parent
        self.miner = miner

    def run(self):
        print 'Listener started'
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
            # Possible error or new message, just pipe it through
            event = UpdateStatusEvent(text=line)
            wx.PostEvent(self.parent, event)
        print 'Listener shutting down'
        
        
class ProfilePanel(wx.Panel):
    SHARES_INDEX = 0 # Indexes into the status bar
    KHASH_INDEX = 1    
    def __init__(self, parent, id, name, devices, statusbar):
        wx.Panel.__init__(self, parent, id)
        self.parent = parent
        self.name = name
        self.statusbar = statusbar
        self.is_mining = False
        self.is_possible_error = False
        self.miner = None
        self.miner_listener = None
        self.accepted_shares = 0
        self.invalid_shares = 0
        self.last_rate = 0
        self.server_lbl = wx.StaticText(self, -1, _("Server:"))
        self.txt_server = wx.TextCtrl(self, -1, _("mining.bitcoin.cz"))
        self.port_lbl = wx.StaticText(self, -1, _("Port:"))
        self.txt_port = wx.TextCtrl(self, -1, _("8332"))
        self.user_lbl = wx.StaticText(self, -1, _("Username:"))
        self.txt_username = wx.TextCtrl(self, -1, _(""))
        self.pass_lbl = wx.StaticText(self, -1, _("Password:"))
        self.txt_pass = wx.TextCtrl(self, -1, _(""), style=wx.TE_PASSWORD)
        self.device_lbl = wx.StaticText(self, -1, _("Device:"))
        self.combo_device = wx.ComboBox(self, -1, choices=devices, style=wx.CB_DROPDOWN)
        self.flags_lbl = wx.StaticText(self, -1, _("Extra flags:"))
        self.txt_flags = wx.TextCtrl(self, -1, _(""))
        self.start = wx.Button(self, -1, _("Start mining!"))        

        self.__set_properties()
        self.__do_layout()

        self.start.Bind(wx.EVT_BUTTON, self.toggle_mining)
        self.Bind(EVT_UPDATE_HASHRATE, self.on_update_khash)
        self.Bind(EVT_UPDATE_ACCEPTED, lambda event: self.update_shares(event.accepted))
        self.Bind(EVT_UPDATE_STATUS, lambda event: self.update_status(event.text))
        self.set_shares_statusbar_text()

    def __set_properties(self):
        self.combo_device.SetSelection(0)

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
        grid_sizer_1.Add(self.combo_device, 0, wx.EXPAND, 0)
        grid_sizer_1.Add(self.flags_lbl, 0, wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL, 0)
        grid_sizer_1.Add(self.txt_flags, 0, wx.EXPAND, 0)
        grid_sizer_1.AddGrowableCol(1)
        grid_sizer_1.AddGrowableCol(3)
        sizer_2.Add(grid_sizer_1, 1, wx.EXPAND, 0)
        sizer_2.Add(self.start, 0, wx.ALIGN_BOTTOM|wx.ALIGN_CENTER_HORIZONTAL, 0)
        self.SetSizerAndFit(sizer_2)

    def toggle_mining(self, event):
        if self.is_mining:
            self.stop_mining()
            self.start.SetLabel("Start mining!")
        else:
            self.start_mining()
            self.start.SetLabel("Stop mining")

    def get_data(self):
        return dict(name=self.name,
                    server=self.txt_server.GetValue(),
                    port=self.txt_port.GetValue(),
                    username=self.txt_username.GetValue(),
                    password=self.txt_pass.GetValue(),
                    device=self.combo_device.GetSelection(), # TODO this is probably not adequate
                    flags=self.txt_flags.GetValue())

    def set_data(self, data):
        if 'name' in data: self.name = data['name']
        if 'username' in data: self.txt_username.SetValue(data['username'])
        if 'server' in data: self.txt_server.SetValue(data['server'])
        if 'port' in data: self.txt_port.SetValue(data['port'])
        if 'password' in data: self.txt_pass.SetValue(data['password'])
        if 'device' in data: self.combo_device.SetSelection(data['device'])
        if 'flags' in data: self.txt_flags.SetValue(data['flags'])

    def start_mining(self):
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
                self.combo_device.GetSelection(),
                self.txt_flags.GetValue()
        )
        try:
            print 'Running command: ', cmd
            self.miner = subprocess.Popen(cmd, cwd=folder, stdout=subprocess.PIPE)
        except OSError:
            raise #TODO
        self.miner_listener = MinerListenerThread(self, self.miner)
        self.miner_listener.daemon = True
        self.miner_listener.start()
        self.is_mining = True
        self.set_status("Starting...", 1)
        
    def stop_mining(self):
        if self.miner is not None:
            self.miner.terminate()
            self.miner = None
        if self.miner_listener is not None:
            self.miner_listener.shutdown_event.set()
            self.miner_listener = None            
        self.is_mining = False
        self.set_status("Stopped", 1)

    def on_update_khash(self, event):
        self.update_khash(event.rate)
        event.Skip()

    def format_khash(self, rate):
        if rate > 1000:
            return"%.1f Mhash/s" % (rate/1000.)
        else:
            return "%d khash/s" % rate        
    
    def update_khash(self, rate):
        self.last_rate = rate
        self.set_status(self.format_khash(rate), ProfilePanel.KHASH_INDEX)
        if self.is_possible_error:
            self.set_shares_statusbar_text()
            self.is_possible_error = False

    def set_shares_statusbar_text(self):                     
        text = "Shares: %d accepted, %d stale/invalid" % \
               (self.accepted_shares, self.invalid_shares)
        self.set_status(text, ProfilePanel.SHARES_INDEX)

    def update_shares(self, accepted):
        if accepted:
            self.accepted_shares += 1
        else:
            self.invalid_shares += 1
        self.set_shares_statusbar_text()

    def update_status(self, msg):
        self.set_status(msg)
        self.is_possible_error = True

    def set_status(self, msg, index=0):
        """Set the current statusbar text, but only if we have focus."""
        if self.parent.GetSelection() == self.parent.GetPageIndex(self):
            self.statusbar.SetStatusText(msg, index)

    def on_focus(self):
        """When we receive focus, update our status."""
        self.set_shares_statusbar_text()
        if self.is_mining:
            self.update_khash(self.last_rate)
        else:
            self.set_status("Stopped", 1)

    def get_tooltip_text(self):
        if self.is_mining:
            return "%s: %s" % (self.name, self.format_khash(self.last_rate))
        else:
            return "%s: Stopped" % self.name

class MyFrame(wx.Frame):
    def __init__(self, *args, **kwds):
        wx.Frame.__init__(self, *args, **kwds)
        style = fnb.FNB_X_ON_TAB | fnb.FNB_FF2 | fnb.FNB_NO_NAV_BUTTONS
        self.profiles = fnb.FlatNotebook(self, -1, style=style)
        self.profile_objects = []
                
        # Menu Bar
        self.menubar = wx.MenuBar()
        wxglade_tmp_menu = wx.Menu()
        wxglade_tmp_menu.Append(wx.ID_NEW, _("&New profiles..."), "", wx.ITEM_NORMAL) # TODO
        wxglade_tmp_menu.Append(wx.ID_SAVE, _("&Save profiles"), "", wx.ITEM_NORMAL)
        wxglade_tmp_menu.Append(wx.ID_OPEN, _("&Load profiles"), "", wx.ITEM_NORMAL)
        self.menubar.Append(wxglade_tmp_menu, _("&File"))
        #wxglade_tmp_menu = wx.Menu()
        self.ID_PATHS = wx.NewId()
        #wxglade_tmp_menu.Append(self.ID_PATHS, _("&Paths..."), "", wx.ITEM_NORMAL)
        #self.menubar.Append(wxglade_tmp_menu, _("&Settings"))
        wxglade_tmp_menu = wx.Menu()
        wxglade_tmp_menu.Append(wx.ID_ABOUT, _("&About..."), "", wx.ITEM_NORMAL)
        self.menubar.Append(wxglade_tmp_menu, _("&Help"))
        self.SetMenuBar(self.menubar)  
        self.statusbar = self.CreateStatusBar(2, 0)


        try:
            self.tbicon = GUIMinerTaskBarIcon(self)
        except:
            self.tbicon = None
            raise
        
        self.SetIcon(get_icon())
        
         
        self.__set_properties()

        try:
            self.devices = get_opencl_devices()
        except:
            dialog = wx.MessageDialog(self,
"""Couldn't find any OpenCL devices.
Check that your video card supports OpenCL and that you have a working version of OpenCL installed.
If you have an AMD/ATI card you may need to install the ATI Stream SDK.""",
                "No OpenCL devices found.",
                wx.OK | wx.ICON_ERROR)
            dialog.ShowModal()
            dialog.Destroy()
            sys.exit(1)        

        self.Bind(wx.EVT_MENU, self.new_profile, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.save_profile, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.load_profile, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.set_paths, id=self.ID_PATHS)
        self.Bind(wx.EVT_MENU, self.help_about, id=wx.ID_ABOUT)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ICONIZE, self.on_minimize)

        self.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSING, self.on_page_closing)
        self.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CHANGED, self.on_page_changed)

        any_loaded = self.load_profile() 
        if not any_loaded: # Create a default one for them to use 
            p = self._add_profile(name="slush's pool")

        self.__do_layout()
    
    def __set_properties(self):
        self.SetTitle(_("poclbm-gui"))
        self.statusbar.SetStatusWidths([-1, 125])
        statusbar_fields = [_(""), _("Not started")]
        for i in range(len(statusbar_fields)):  
            self.statusbar.SetStatusText(statusbar_fields[i], i)  

    def __do_layout(self):
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        self.vertical_sizer.Add(self.profiles, 1, wx.EXPAND, 0)
        self.SetSizer(self.vertical_sizer)
        self.vertical_sizer.SetSizeHints(self)
        self.SetSizerAndFit(self.vertical_sizer)

    def _add_profile(self, name="Default miner"):
        panel = ProfilePanel(self.profiles, -1, name, self.devices, self.statusbar)
        self.profile_objects.append(panel)
        self.profiles.AddPage(panel, panel.name)
        # Select new profile which is the last one.
        self.profiles.EnsureVisible(self.profiles.GetPageCount()-1)
        self.__do_layout()
        return panel

    def new_profile(self, event):
        dialog = wx.TextEntryDialog(self, "Name this miner:", "New miner")
        if dialog.ShowModal() == wx.ID_OK:
            self._add_profile(dialog.GetValue())

    def _get_storage_location(self):
        if sys.platform == 'win32':
            folder = os.path.join(os.environ['AppData'], 'poclbm')
            config_filename = os.path.join(folder, 'poclbm.ini')
        else: # Assume linux? TODO test
            folder = os.environ['HOME']
            config_filename = os.path.join(folder, '.poclbm')
        return folder, config_filename

    def save_profile(self, event):
        folder, config_filename = self._get_storage_location()
        _mkdir_p(folder)
        data = [p.get_data() for p in self.profile_objects]
        print 'Saving:', data
        with open(config_filename, 'w') as f:
            json.dump(data, f)
        dlg = wx.MessageDialog(self, "Profiles saved successfully!",
                               "Save successful", wx.OK|wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def on_close(self, event):
        """On closing, stop any miners that are currently working."""
        for p in self.profile_objects:
            p.stop_mining()
        if self.tbicon is not None:
            self.tbicon.RemoveIcon()
            self.tbicon.Destroy()
        event.Skip()
    
    def load_profile(self, event=None):
        """Load JSON profile info from the poclbm config file."""
        folder, config_filename = self._get_storage_location()
        if not os.path.exists(config_filename):
            return # Nothing to load yet
        with open(config_filename) as f:
            data = json.load(f)
        print 'Loaded:', data
        if(any(p.is_mining for p in self.profile_objects)):
            dlg = wx.MessageDialog(self,
                "Loading profiles will stop any currently running miners. Continue?",
                "Load profile", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
            do_stop = dlg.ShowModal() == wx.ID_NO
            dlg.Destroy()
            if do_stop:
                return                      
        while self.profile_objects:
            p = self.profile_objects.pop()
            p.stop_mining()
        for i in reversed(range(self.profiles.GetPageCount())):
            self.profiles.DeletePage(i)            
        # Create new miners
        for d in data:
            panel = self._add_profile()
            panel.set_data(d)
        return any(data)
            
    def set_paths(self, event):
        print "Event handler `set_paths' not implemented!"
        event.Skip()

    def help_about(self, event):
        info = wx.AboutDialogInfo()
        info.Name = "Python OpenCL Bitcoin Miner GUI"
        info.Website = ("https://github.com/Kiv/poclbm", "poclbm at Github")
        info.Developers = ['Chris "Kiv" MacLeod', 'm0mchil']
        wx.AboutBox(info)
        
    def on_page_closing(self, event):
        try:
            p = self.profile_objects[event.GetSelection()]
        except IndexError:
            return # TODO
        if p.is_mining:
            dlg = wx.MessageDialog(self,
                "Closing this miner will stop it. Continue?", "Close miner",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
            do_stop = dlg.ShowModal() == wx.ID_NO
            dlg.Destroy()
            if do_stop:
                event.Veto()
            else:
                p = self.profile_objects.pop(event.GetSelection())
                p.stop_mining()
                event.Skip()

    def on_page_changed(self, event):
        try:
            p = self.profile_objects[event.GetSelection()]
        except IndexError:
            return # TODO
        p.on_focus()

    def on_minimize(self, event):
        self.Hide()

if __name__ == "__main__":
    import gettext
    gettext.install("app") # replace with the appropriate catalog name

    global USE_MOCK
    USE_MOCK = '--mock' in sys.argv

    app = wx.PySimpleApp(0)
    wx.InitAllImageHandlers()
    frame_1 = MyFrame(None, -1, "")
    app.SetTopWindow(frame_1)
    frame_1.Show()
    app.MainLoop()
