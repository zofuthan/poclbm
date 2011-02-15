import sys, os, subprocess, errno
import wx
import json


def get_opencl_devices():
    # TODO: get the real devices from opencl
    return [_("[0] Juniper"), _("[1] Intel")]
    
def _mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST:
            pass
        else: raise
        
class ProfilePanel(wx.Panel):
    def __init__(self, parent, id, name, devices):
        wx.Panel.__init__(self, parent, id)
        self.name = name
        self.is_mining = False
        self.miner = None
        self.server_lbl = wx.StaticText(self, -1, _("Server:"))
        self.txt_server = wx.TextCtrl(self, -1, _("mining.bitcoin.cz"))
        self.port_lbl = wx.StaticText(self, -1, _("Port:"))
        self.txt_port = wx.TextCtrl(self, -1, _("8332"))
        self.user_lbl = wx.StaticText(self, -1, _("Username:"))
        self.txt_username = wx.TextCtrl(self, -1, _("Kiv.GPU"))
        self.pass_lbl = wx.StaticText(self, -1, _("Password:"))
        self.txt_pass = wx.TextCtrl(self, -1, _("gpumine6794"), style=wx.TE_PASSWORD)
        self.device_lbl = wx.StaticText(self, -1, _("Device:"))
        self.combo_device = wx.ComboBox(self, -1, choices=devices, style=wx.CB_DROPDOWN)
        self.flags_lbl = wx.StaticText(self, -1, _("Extra flags:"))
        self.txt_flags = wx.TextCtrl(self, -1, _("-v -w128 -r5"))
        self.start = wx.Button(self, -1, _("Start mining!"))        

        self.__set_properties()
        self.__do_layout()

        self.start.Bind(wx.EVT_BUTTON, self.toggle_mining)

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
        self.name = data['name']
        self.txt_server.SetValue(data['server'])
        self.txt_port.SetValue(data['port'])
        self.txt_pass.SetValue(data['password'])
        self.combo_device.SetSelection(data['device'])
        self.txt_flags.SetValue(data['flags'])

    def start_mining(self):
        # TODO handle no devices found
        folder = "c:/program files (x86)/Bitcoin/" # TODO
        executable = os.path.join(folder, "poclbm.exe")
        cmd = "%s --user=%s --pass=%s -o %s -p %s -d%d %s" % (
                executable,
                self.txt_username.GetValue(),
                self.txt_pass.GetValue(),
                self.txt_server.GetValue(),
                self.txt_port.GetValue(),
                self.combo_device.GetSelection(),
                self.txt_flags.GetValue()
        )
        try:
            self.miner = subprocess.Popen(cmd, cwd=folder)
        except OSError:
            raise #TODO
        self.is_mining = True

    def stop_mining(self):
        if self.miner is not None:
            self.miner.terminate()
        self.is_mining = False
        # TODO: stop all miners on program shutdown

class MyFrame(wx.Frame):
    def __init__(self, *args, **kwds):
        kwds["style"] = wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)
        self.profiles = wx.Notebook(self, -1, style=0)
        self.profile_objects = []
                
        # Menu Bar
        self.menubar = wx.MenuBar()
        wxglade_tmp_menu = wx.Menu()
        wxglade_tmp_menu.Append(wx.ID_NEW, _("&New profile"), "", wx.ITEM_NORMAL)
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

        self.Bind(wx.EVT_MENU, self.new_profile, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.save_profile, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.load_profile, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.set_paths, id=self.ID_PATHS)
        self.Bind(wx.EVT_MENU, self.help_about, id=wx.ID_ABOUT)
        # TODO timer to check input from workers? self.Bind(wx.EVT_TIMER, callback)
        self._add_profile(dict(name="slush's pool"))
        self._add_profile(dict(name="Bitpenny's pool"))        
        self.load_profile()
        

    def __set_properties(self):
        self.SetTitle(_("poclbm"))
        self.statusbar.SetStatusWidths([-1, 125])
        statusbar_fields = [_("Shares accepted:172 (last at 13:29)"), _("161200 khash/s")]
        for i in range(len(statusbar_fields)):
            self.statusbar.SetStatusText(statusbar_fields[i], i)  

    def __do_layout(self):
        self.vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        self.vertical_sizer.Add(self.profiles, 1, wx.EXPAND, 0)
        self.SetSizer(self.vertical_sizer)
        self.vertical_sizer.Fit(self)
        self.Layout()
        # end wxGlade

    def _add_profile(self, data={}):
        name = data.get('name', "Untitled")
        panel = ProfilePanel(self.profiles, -1, name, get_opencl_devices())
        self.profile_objects.append(panel)
        self.profiles.AddPage(panel, panel.name)
        self.Layout()

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
            self._add_profile(d)
            
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
