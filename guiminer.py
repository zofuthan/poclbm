import sys, os, subprocess, errno, re, threading
import wx
import json

USE_MOCK = False

def strip_whitespace(s):
    s = re.sub(r"( +)|\t+", " ", s)
    return s.strip()

def get_opencl_devices():
    import pyopencl
    platform = pyopencl.get_platforms()[0]
    devices = platform.get_devices()
    if len(devices) == 0:
        raise IOError
    return ['[%d] %s' % (i, strip_whitespace(device.name))
                         for (i, device) in enumerate(devices)]
    
def _mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST:
            pass
        else: raise

class MinerListenerThread(threading.Thread):
    def __init__(self, parent, miner):
        threading.Thread.__init__(self)
        self.parent = parent
        self.miner = miner

    def run(self):
        print 'Listener started'
        while True:            
            line = self.miner.stdout.readline().strip()
            if not line: continue
            match = re.search(r"accepted", line, flags=re.I)
            if match is not None:
                wx.CallAfter(self.parent.update_shares, True)
                continue
            match = re.search(r"invalid|stale", line, flags=re.I)
            if match is not None:
                wx.CallAfter(self.parent.update_shares, False)
                continue
            match = re.search(r"(\d+) khash/s", line, flags=re.I)
            if match is not None:
                wx.CallAfter(self.parent.update_khash, int(match.group(1)))
                continue            
            # Possible error or new message, just pipe it through
            wx.CallAfter(self.parent.update_status, line)        
        
        
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
        grid_sizer_1.AddGrowableCol(0)
        grid_sizer_1.AddGrowableCol(1)
        grid_sizer_1.AddGrowableCol(2)
        grid_sizer_1.AddGrowableCol(3)
        sizer_2.Add(grid_sizer_1, 1, wx.EXPAND, 0)
        sizer_2.Add(self.start, 0, wx.ALIGN_BOTTOM|wx.ALIGN_CENTER_HORIZONTAL, 0)
        self.SetSizer(sizer_2)

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
        folder = os.path.dirname(__file__)
        if USE_MOCK:
            
            executable = "python mockBitcoinMiner.py"
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
        self.statusbar.SetStatusText("Starting...", 1)
        

    def stop_mining(self):
        if self.miner is not None:
            self.miner.terminate()
            self.miner = None
        if self.miner_listener is not None:
            self.miner_listener = None
            # TODO: kill the listener thread
        self.is_mining = False
        # TODO: stop all miners on program shutdown
        self.statusbar.SetStatusText("Stopped", 1)

    def update_khash(self, rate):
        if rate > 1000:
            text = "%.1f Mhash/s" % (rate/1000.)
        else:
            text = "%d khash/s" % rate
        self.statusbar.SetStatusText(text, ProfilePanel.KHASH_INDEX)
        if self.is_possible_error:
            set_shares_statusbar_text()
            self.is_possible_error = False

    def set_shares_statusbar_text(self):                     
        text = "Shares: %d accepted, %d stale/invalid" % \
               (self.accepted_shares, self.invalid_shares)
        self.statusbar.SetStatusText(text, ProfilePanel.SHARES_INDEX)        

    def update_shares(self, accepted):
        if accepted:
            self.accepted_shares += 1
        else:
            self.invalid_shares += 1
        self.set_shares_statusbar_text()

    def update_status(self, msg):
        self.statusbar.SetStatusText(msg, 0)
        self.is_possible_error = True



class MyFrame(wx.Frame):
    def __init__(self, *args, **kwds):
        kwds["style"] = wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)
        self.profiles = wx.Notebook(self, -1, style=0)
        self.profile_objects = []
                
        # Menu Bar
        self.menubar = wx.MenuBar()
        wxglade_tmp_menu = wx.Menu()
        #wxglade_tmp_menu.Append(wx.ID_NEW, _("&New profile"), "", wx.ITEM_NORMAL) # TODO
        wxglade_tmp_menu.Append(wx.ID_SAVE, _("&Save profile"), "", wx.ITEM_NORMAL)
        wxglade_tmp_menu.Append(wx.ID_OPEN, _("&Load profile"), "", wx.ITEM_NORMAL)
        self.menubar.Append(wxglade_tmp_menu, _("&File"))
        wxglade_tmp_menu = wx.Menu()
        self.ID_PATHS = wx.NewId()
        wxglade_tmp_menu.Append(self.ID_PATHS, _("&Paths..."), "", wx.ITEM_NORMAL)
        self.menubar.Append(wxglade_tmp_menu, _("&Settings"))
        wxglade_tmp_menu = wx.Menu()
        wxglade_tmp_menu.Append(wx.ID_ABOUT, _("&About..."), "", wx.ITEM_NORMAL)
        self.menubar.Append(wxglade_tmp_menu, _("&Help"))
        self.SetMenuBar(self.menubar)  
        self.statusbar = self.CreateStatusBar(2, 0)
         
        self.__set_properties()
        self.__do_layout()

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
        # TODO timer to check input from workers? self.Bind(wx.EVT_TIMER, callback)

        any_loaded = self.load_profile()
        if not any_loaded: # Create a default one for them to use 
            p = self._add_profile()
            p.set_data(dict(name="slush's pool"))

    
    def __set_properties(self):
        self.SetTitle(_("poclbm"))
        self.statusbar.SetStatusWidths([-1, 125])
        statusbar_fields = [_(""), _("Not started")]
        for i in range(len(statusbar_fields)):  
            self.statusbar.SetStatusText(statusbar_fields[i], i)  

    def __do_layout(self):
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        self.vertical_sizer.Add(self.profiles, 1, wx.EXPAND, 0)
        self.SetSizer(self.vertical_sizer)
        self.vertical_sizer.Fit(self)
        self.Layout()
        # end wxGlade

    def _add_profile(self):
        panel = ProfilePanel(self.profiles, -1, "Untitled", self.devices, self.statusbar)
        self.profile_objects.append(panel)
        self.profiles.AddPage(panel, panel.name)
        self.vertical_sizer.Fit(self)
        self.Layout()
        return panel

    def new_profile(self, event):
        print "Event handler `new_profile' not implemented!"
        event.Skip()

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
        print 'Saved ok'
    
    def load_profile(self, event=None):
        folder, config_filename = self._get_storage_location()
        if not os.path.exists(config_filename):
            return # Nothing to load yet
        with open(config_filename) as f:
            data = json.load(f)
        print 'Loaded:', data
        # Stop all miners before we clobber them
        for p in self.profile_objects:
            p.stop_mining()
            self.vertical_sizer.Detach(p)
        p = [] # TODO: see if this garbage collects the old profiles
        # Create new miners
        for d in data:
            panel = self._add_profile()
            panel.set_data(d)
        return any(data)
            
    def set_paths(self, event):
        print "Event handler `set_paths' not implemented!"
        event.Skip()


    def help_about(self, event):
        print "Event handler `help_about' not implemented"
        event.Skip()

if __name__ == "__main__":
    import gettext
    gettext.install("app") # replace with the appropriate catalog name

    app = wx.PySimpleApp(0)
    wx.InitAllImageHandlers()
    frame_1 = MyFrame(None, -1, "")
    app.SetTopWindow(frame_1)
    frame_1.Show()
    app.MainLoop()
