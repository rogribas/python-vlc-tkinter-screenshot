import vlc
import sys


import ffmpeg
from PIL import Image

import tkinter as Tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename
from tkinter.messagebox import showerror
from os.path import basename, expanduser, isfile, join as joined
from pathlib import Path
import time

import os
import queue
import threading
from datetime import datetime

_isMacOS   = sys.platform.startswith('darwin')
_isWindows = sys.platform.startswith('win')
_isLinux   = sys.platform.startswith('linux')


def datetime_to_seconds(datetime_obj):
    t = datetime(1970,1,1)
    return (datetime_obj - t).total_seconds()

if _isMacOS:
    from ctypes import c_void_p, cdll
    # libtk = cdll.LoadLibrary(ctypes.util.find_library('tk'))
    # returns the tk library /usr/lib/libtk.dylib from macOS,
    # but we need the tkX.Y library bundled with Python 3+,
    # to match the version number of tkinter, _tkinter, etc.
    try:
        libtk = 'libtk%s.dylib' % (Tk.TkVersion,)
        prefix = getattr(sys, 'base_prefix', sys.prefix)
        libtk = joined(prefix, 'lib', libtk)
        dylib = cdll.LoadLibrary(libtk)
        # getNSView = dylib.TkMacOSXDrawableView is the
        # proper function to call, but that is non-public
        # (in Tk source file macosx/TkMacOSXSubwindows.c)
        # and dylib.TkMacOSXGetRootControl happens to call
        # dylib.TkMacOSXDrawableView and return the NSView
        _GetNSView = dylib.TkMacOSXGetRootControl
        # C signature: void *_GetNSView(void *drawable) to get
        # the Cocoa/Obj-C NSWindow.contentView attribute, the
        # drawable NSView object of the (drawable) NSWindow
        _GetNSView.restype = c_void_p
        _GetNSView.argtypes = c_void_p,
        del dylib

    except (NameError, OSError):  # image or symbol not found
        def _GetNSView(unused):
            return None
        libtk = "N/A"

    C_Key = "Command-"  # shortcut key modifier

else:  # *nix, Xwindows and Windows, UNTESTED

    libtk = "N/A"
    C_Key = "Control-"  # shortcut key modifier


class _Tk_Menu(Tk.Menu):
    '''Tk.Menu extended with .add_shortcut method.
       Note, this is a kludge just to get Command-key shortcuts to
       work on macOS.  Other modifiers like Ctrl-, Shift- and Option-
       are not handled in this code.
    '''
    _shortcuts_entries = {}
    _shortcuts_widget  = None

    def add_shortcut(self, label='', key='', command=None, **kwds):
        '''Like Tk.menu.add_command extended with shortcut key.
           If needed use modifiers like Shift- and Alt_ or Option-
           as before the shortcut key character.  Do not include
           the Command- or Control- modifier nor the <...> brackets
           since those are handled here, depending on platform and
           as needed for the binding.
        '''
        # <https://TkDocs.com/tutorial/menus.html>
        if not key:
            self.add_command(label=label, command=command, **kwds)

        elif _isMacOS:
            # keys show as upper-case, always
            self.add_command(label=label, accelerator='Command-' + key,
                                          command=command, **kwds)
            self.bind_shortcut(key, command, label)

        else:  # XXX not tested, not tested, not tested
            self.add_command(label=label, underline=label.lower().index(key),
                                          command=command, **kwds)
            self.bind_shortcut(key, command, label)

    def bind_shortcut(self, key, command, label=None):
        """Bind shortcut key, default modifier Command/Control.
        """
        # The accelerator modifiers on macOS are Command-,
        # Ctrl-, Option- and Shift-, but for .bind[_all] use
        # <Command-..>, <Ctrl-..>, <Option_..> and <Shift-..>,
        # <https://www.Tcl.Tk/man/tcl8.6/TkCmd/bind.htm#M6>
        if self._shortcuts_widget:
            if C_Key.lower() not in key.lower():
                key = "<%s%s>" % (C_Key, key.lstrip('<').rstrip('>'))
            self._shortcuts_widget.bind(key, command)
            # remember the shortcut key for this menu item
            if label is not None:
                item = self.index(label)
                self._shortcuts_entries[item] = key
        # The Tk modifier for macOS' Command key is called
        # Meta, but there is only Meta_L[eft], no Meta_R[ight]
        # and both keyboard command keys generate Meta_L events.
        # Similarly for macOS' Option key, the modifier name is
        # Alt and there's only Alt_L[eft], no Alt_R[ight] and
        # both keyboard option keys generate Alt_L events.  See:
        # <https://StackOverflow.com/questions/6378556/multiple-
        # key-event-bindings-in-tkinter-control-e-command-apple-e-etc>

    def bind_shortcuts_to(self, widget):
        '''Set the widget for the shortcut keys, usually root.
        '''
        self._shortcuts_widget = widget

    def entryconfig(self, item, **kwds):
        """Update shortcut key binding if menu entry changed.
        """
        Tk.Menu.entryconfig(self, item, **kwds)
        # adjust the shortcut key binding also
        if self._shortcuts_widget:
            key = self._shortcuts_entries.get(item, None)
            if key is not None and "command" in kwds:
                self._shortcuts_widget.bind(key, kwds["command"])


class Video(object):

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.modification_date = datetime.utcfromtimestamp(os.path.getmtime(path))

    def __lt__(self, other):
        return self.modification_date < other.modification_date

class Player(Tk.Frame):
    """The main window has to deal with events.
    """
    _geometry = ''
    _stopped  = None

    COLOR_FRAMES1 = '#ececec'
    COLOR_FRAMES2 = '#999'
    COLOR_FRAMES3 = '#ccc'

    def __init__(self, parent, title=None, video=''):
        Tk.Frame.__init__(self, parent)

        self.parent = parent  # == root
        self.parent.title(title or "tkVLCplayer")
        self.video = expanduser(video)

        # Menu Bar
        #   File Menu
        menubar = Tk.Menu(self.parent)
        self.parent.config(menu=menubar)

        fileMenu = _Tk_Menu(menubar)
        fileMenu.bind_shortcuts_to(parent)  # XXX must be root?

        fileMenu.add_shortcut("Open...", 'o', self.OnOpen)
        fileMenu.add_separator()
        fileMenu.add_shortcut("Play", 'p', self.OnPlay)  # Play/Pause
        fileMenu.add_command(label="Stop", command=self.OnStop)
        fileMenu.add_separator()
        fileMenu.add_shortcut("Mute", 'm', self.OnMute)
        fileMenu.add_separator()
        fileMenu.add_shortcut("Close", 'w' if _isMacOS else 's', self.OnClose)
        menubar.add_cascade(label="File", menu=fileMenu)
        self.fileMenu = fileMenu
        self.playIndex = fileMenu.index("Play")
        self.muteIndex = fileMenu.index("Mute")

        # first, top panel shows video

        self.videopanel = ttk.Frame(self.parent)
        self.canvas = Tk.Canvas(self.videopanel)
        self.canvas.pack(fill=Tk.BOTH, expand=1)
        self.videopanel.pack(fill=Tk.BOTH, expand=1)

        # panel to hold buttons
        self.buttons_panel = Tk.Toplevel(self.parent, bg=self.COLOR_FRAMES2)
        self.buttons_panel.title("")

        # create all of the main containers
        self.frame_header = Tk.Frame(self.buttons_panel, padx=15, pady=5, bg=self.COLOR_FRAMES1)
        self.frame_list = Tk.Frame(self.buttons_panel, padx=15, pady=5, bg=self.COLOR_FRAMES2)
        self.frame_bottom = Tk.Frame(self.buttons_panel, padx=15, pady=15, bg=self.COLOR_FRAMES1)

        # layout all of the main containers
        self.buttons_panel.grid_rowconfigure(2, weight=1)
        self.buttons_panel.grid_columnconfigure(0, weight=1)

        self.frame_header.grid(row=0, sticky="ew")
        self.frame_list.grid(row=1, sticky="nsew")
        self.frame_bottom.grid(row=2, sticky="ews")

        # frames frame_center
        self.frame_header.grid_columnconfigure(0, weight=1)
        self.frame_header.grid_rowconfigure(3, weight=1)

        self.frame_header1 = Tk.Frame(self.frame_header, bg=self.COLOR_FRAMES1, padx=15, pady=5)
        self.frame_header1.grid(row=0, sticky="ew")
        self.label_title = Tk.Label(self.frame_header1, text='VIDEO SCREENSHOTER', font="-weight bold", bg=self.COLOR_FRAMES1)
        self.label_title.grid(row=0, sticky="ew")


        self.frame_header2 = Tk.Frame(self.frame_header, pady=15, bg=self.COLOR_FRAMES1)
        self.frame_header2.grid(row=1, column=0)
        self.frame_header2.grid_columnconfigure(0, weight=1)
        self.folder_path_out = Tk.StringVar()
        self.label_folder_out = Tk.Entry(self.frame_header2, state='disabled', width=40,
                                     textvariable=self.folder_path_out, highlightbackground=self.COLOR_FRAMES1)
        self.label_folder_out.grid(row=0, column=0)
        self.btn_browse_folder_out = Tk.Button(self.frame_header2, text="Output folder", command=self.action_browse_out, highlightbackground=self.COLOR_FRAMES1)
        self.btn_browse_folder_out.grid(row=0, column=1, padx=(5, 50))

        self.frame_header3 = Tk.Frame(self.frame_header, pady=15, bg=self.COLOR_FRAMES1)
        self.frame_header3.grid(row=2, column=0)
        self.frame_header3.grid_columnconfigure(0, weight=1)
        self.folder_path = Tk.StringVar()
        self.label_folder = Tk.Entry(self.frame_header3, state='disabled', width=40,
                                     textvariable=self.folder_path, highlightbackground=self.COLOR_FRAMES1)
        self.label_folder.grid(row=0, column=0)
        self.btn_browse_folder = Tk.Button(self.frame_header3, text="Choose folder", command=self.action_browse, highlightbackground=self.COLOR_FRAMES1)
        self.btn_browse_folder.grid(row=0, column=1, padx=(5, 50))


        # frames frame_bottom
        self.frame_bottom.grid_columnconfigure(0, weight=1)
        self.frame_bottom.grid_rowconfigure(2, weight=1)

        self.frame_bottom_info = Tk.Frame(self.frame_bottom, bg=self.COLOR_FRAMES1, padx=15, pady=5)
        self.frame_bottom_info.grid(row=0, sticky="ew")
        self.str_filename = Tk.StringVar()
        self.label_title = Tk.Label(self.frame_bottom_info, anchor="w", textvariable=self.str_filename, font="-weight bold", bg=self.COLOR_FRAMES1)
        self.label_title.grid(row=0, sticky="ew")
        self.str_modification_date = Tk.StringVar()
        self.label_title = Tk.Label(self.frame_bottom_info, anchor="w", textvariable=self.str_modification_date, bg=self.COLOR_FRAMES1)
        self.label_title.grid(row=1, sticky="ew")


        self.frame_bottom1 = Tk.Frame(self.frame_bottom, bg=self.COLOR_FRAMES1, padx=15, pady=5)
        self.frame_bottom1.grid(row=1, sticky="ew")
        self.frame_bottom2 = Tk.Frame(self.frame_bottom, bg=self.COLOR_FRAMES1, padx=15, pady=5)
        self.frame_bottom2.grid(row=2, sticky="ew")

        buttons = ttk.Frame(self.frame_bottom1)
        self.playButton = ttk.Button(buttons, text="Play", command=self.OnPlay)
        stop            = ttk.Button(buttons, text="Stop", command=self.OnStop)
        self.muteButton = ttk.Button(buttons, text="Mute", command=self.OnMute)
        self.playButton.pack(side=Tk.LEFT)
        stop.pack(side=Tk.LEFT)
        self.muteButton.pack(side=Tk.LEFT)

        self.volMuted = False
        self.volVar = Tk.IntVar()
        self.volSlider = Tk.Scale(buttons, variable=self.volVar, command=self.OnVolume,
                                  from_=0, to=100, orient=Tk.HORIZONTAL, length=200,
                                  showvalue=0, label='Volume', bg=self.COLOR_FRAMES1)
        self.volSlider.pack(side=Tk.RIGHT)
        buttons.grid(row=0, sticky="ew")

        # panel to hold player time slider
        timers = ttk.Frame(self.frame_bottom2)
        self.timeVar = Tk.DoubleVar()
        self.timeSliderLast = 0
        self.timeSlider = Tk.Scale(timers, variable=self.timeVar, command=self.OnTime,
                                   from_=0, to=1000, orient=Tk.HORIZONTAL, length=100,
                                   resolution=0.02, showvalue=0, bg=self.COLOR_FRAMES1)
        self.timeSlider.pack(side=Tk.BOTTOM, fill=Tk.X, expand=1)
        self.timeSliderUpdate = time.time()
        timers.grid(row=0, sticky="ew")
        timers.pack(side=Tk.TOP, fill=Tk.X)


        self.frame_bottom3 = Tk.Frame(self.frame_bottom, bg=self.COLOR_FRAMES1, padx=15, pady=5)
        self.frame_bottom3.grid(row=3, sticky="ew")
        self.btn_capture = Tk.Button(self.frame_bottom3, text="Capture (C)", command=self.capture,
                                     highlightbackground='#bbf', height=4, width=60)
        self.btn_capture.grid(row=0, column=0)

        # widgets frame_list
        self.frame_list.grid_rowconfigure(1, weight=2)
        self.frame_list.grid_columnconfigure(0, weight=1)
        self.label_list = Tk.Label(self.frame_list, text="Videos", bg=self.COLOR_FRAMES2)
        self.label_list.grid(row=0, sticky="ew")
        self.lb_ids = []
        self.lb = Tk.Listbox(self.frame_list, font=("Courier", 12), height=28)
        self.lb.bind('<<ListboxSelect>>', self.onselect)
        self.lb.unbind('<space>')
        self.lb.bind('<space>', self._Pause_Play)
        self.lb.bind('a', self._Pause_Play)
        self.lb.bind('c', self.capture)
        self.lb.bind("<Left>", self.move_time_slider)
        self.lb.bind("<Right>", self.move_time_slider)
        self.lb.grid(row=1, sticky="ew")

        # VLC player
        args = []
        if _isLinux:
            args.append('--no-xlib')
        self.Instance = vlc.Instance(args)
        self.player = self.Instance.media_player_new()

        self.parent.bind("<Configure>", self.OnConfigure)  # catch window resize, etc.
        self.parent.update()

        # After parent.update() otherwise panel is ignored.
        self.buttons_panel.overrideredirect(True)

        # Estetic, to keep our video panel at least as wide as our buttons panel.
        self.parent.minsize(width=502, height=0)

        # Windows positions
        width  = int(self.parent.winfo_screenwidth()/2)
        height = int(self.parent.winfo_screenheight())
        self.parent.geometry(f'{width}x{height}+0+0')
        self.buttons_panel.geometry(f'{width}x{height-54}+{width}+0')

        if _isMacOS:
            # Only tested on MacOS so far. Enable for other OS after verified tests.
            self.is_buttons_panel_anchor_active = True

            # Detect dragging of the buttons panel.
            self.buttons_panel.bind("<Button-1>", lambda event: setattr(self, "has_clicked_on_buttons_panel", event.y < 0))
            self.buttons_panel.bind("<B1-Motion>", self._DetectButtonsPanelDragging)
            self.buttons_panel.bind("<ButtonRelease-1>", lambda _: setattr(self, "has_clicked_on_buttons_panel", False))
            self.has_clicked_on_buttons_panel = False
        else:
            self.is_buttons_panel_anchor_active = False

        self.OnTick()  # set the timer up

    def move_time_slider(self, evt):
        if evt.keysym == 'Right':
            self.timeVar.set(self.timeVar.get() + 0.05)
            self.timeSlider.set(self.timeSlider.get() + 0.05)
        else:
            self.timeVar.set(self.timeVar.get() - 0.05)
            self.timeSlider.set(self.timeSlider.get() - 0.05)
        self.OnTime()


    def capture(self, evt=None):
        out_dir_path = self.folder_path_out.get()
        if (not out_dir_path):
            Tk.messagebox.showinfo("Error", "First you need to set the output directory")
        count = 0
        video = self.results[self.lb.curselection()[0]]
        folder_path = self.folder_path_out.get()
        v_name = video.name.split('.')[0]
        path_out = os.path.join(folder_path, v_name + f'{count:02d}' + '.png')
        while os.path.isfile(path_out):
            count += 1
            path_out = os.path.join(folder_path, v_name + f'{count:02d}' + '.png')
        self.player.video_take_snapshot(0, path_out, 0, 0)

        # Check if need to rotate
        ff_probe = ffmpeg.probe(video.path)
        if ff_probe and 'streams' in ff_probe and 'side_data_list' in ff_probe['streams'][0] \
                and 'rotation' in ff_probe['streams'][0]['side_data_list'][0]:

            img = Image.open(path_out)
            rotated_image = img.rotate(int(ff_probe['streams'][0]['side_data_list'][0]['rotation']), expand=True)
            rotated_image.save(path_out)

        # Update modification date (same as original video)
        t_seconds = datetime_to_seconds(video.modification_date)
        os.utime(path_out, (t_seconds, t_seconds))

    def onselect(self, evt):
        w = evt.widget
        index = int(w.curselection()[0])
        video = self.results[self.lb_ids[index]]
        self.str_filename.set(video.name)
        self.str_modification_date.set(video.modification_date.strftime("%d/%m/%Y, %H:%M:%S"))
        self._Play(video.path)

    # def update(self, outqueue):
    #     try:
    #         msg = outqueue.get_nowait()
    #         if isinstance(msg, list):


    #     except queue.Empty:
    #         self.buttons_panel.after(100, self.update, outqueue)


    def action_browse(self):
        folder_path = Tk.filedialog.askdirectory()
        self.folder_path.set(folder_path)
        self.btn_browse_folder.config(state='disabled')
        self.btn_capture.config(state='disabled')
        self.lb.delete(0,'end')

        def is_video(filename):
            f = filename.lower()
            return f.split('.')[-1] in ['mp4', 'mpeg', 'avi', 'mov', 'flv']

        results = []
        for path in os.listdir(folder_path):
            if is_video(path):
                results.append(Video(os.path.join(folder_path, path)))
        self.results = sorted(results)

        for i, r in enumerate(self.results):
            self.lb_ids.append(i)
            self.lb.insert(Tk.END, r.name)
        self.btn_browse_folder.config(state='normal')
        self.btn_capture.config(state='normal')

        if self.results:
            self.lb.select_set(0)
            self.lb.event_generate('<<ListboxSelect>>')
            # self.lb.focus_set(0)
            # self.lb.selection_set( first = 0 )
        else:
            Tk.messagebox.showinfo("Video capturer", "No videos found!")

        # self.outqueue = queue.Queue()
        # thr = threading.Thread(target=self.process_folder,
        #                        args=(self.folder_path.get(),
        #                              self.outqueue))
        # thr.start()
        # self.buttons_panel.after(250, self.update, self.outqueue)

    def action_browse_out(self):
        filename = Tk.filedialog.askdirectory()
        self.folder_path_out.set(filename)

    def OnClose(self, *unused):
        """Closes the window and quit.
        """
        self.parent.quit()  # stops mainloop
        self.parent.destroy()  # this is necessary on Windows to avoid
        # ... Fatal Python Error: PyEval_RestoreThread: NULL tstate

    def _DetectButtonsPanelDragging(self, _):
        """If our last click was on the boarder
           we disable the anchor.
        """
        if self.has_clicked_on_buttons_panel:
            self.is_buttons_panel_anchor_active = False
            self.buttons_panel.unbind("<Button-1>")
            self.buttons_panel.unbind("<B1-Motion>")
            self.buttons_panel.unbind("<ButtonRelease-1>")

    def OnConfigure(self, *unused):
        """Some widget configuration changed.
        """
        # <https://www.Tcl.Tk/man/tcl8.6/TkCmd/bind.htm#M12>
        self._geometry = ''  # force .OnResize in .OnTick, recursive?

        # if self.is_buttons_panel_anchor_active:
        #     self._AnchorButtonsPanel()

    def OnFullScreen(self, *unused):
        """Toggle full screen, macOS only.
        """
        # <https://www.Tcl.Tk/man/tcl8.6/TkCmd/wm.htm#M10>
        f = not self.parent.attributes("-fullscreen")  # or .wm_attributes
        if f:
            self._previouscreen = self.parent.geometry()
            self.parent.attributes("-fullscreen", f)  # or .wm_attributes
            self.parent.bind("<Escape>", self.OnFullScreen)
        else:
            self.parent.attributes("-fullscreen", f)  # or .wm_attributes
            self.parent.geometry(self._previouscreen)
            self.parent.unbind("<Escape>")

    def OnMute(self, *unused):
        """Mute/Unmute audio.
        """
        self.player.video_take_snapshot(0, "screentest3.png", 0, 0)
        # audio un/mute may be unreliable, see vlc.py docs.
        self.volMuted = m = not self.volMuted  # self.player.audio_get_mute()
        self.player.audio_set_mute(m)
        u = "Unmute" if m else "Mute"
        self.fileMenu.entryconfig(self.muteIndex, label=u)
        self.muteButton.config(text=u)
        # update the volume slider text
        self.OnVolume()

    def OnOpen(self, *unused):
        """Pop up a new dialow window to choose a file, then play the selected file.
        """
        # if a file is already running, then stop it.
        self.OnStop()
        # Create a file dialog opened in the current home directory, where
        # you can display all kind of files, having as title "Choose a video".
        video = askopenfilename(initialdir = Path(expanduser("~")),
                                title = "Choose a video",
                                filetypes = (("all files", "*.*"),
                                             ("mp4 files", "*.mp4"),
                                             ("mov files", "*.mov")))
        self._Play(video)

    def _Pause_Play(self, playing=None):
        if playing not in [True, False]:
            playing = self.player.is_playing()
            if playing:
                self.player.pause()
            else:
                self.player.play()
        # re-label menu item and button, adjust callbacks
        p = 'Pause (A)' if playing else 'Play (A)'
        c = self.OnPlay if playing is None else self.OnPause
        self.fileMenu.entryconfig(self.playIndex, label=p, command=c)
        # self.fileMenu.bind_shortcut('p', c)  # XXX handled
        self.playButton.config(text=p, command=c)
        self._stopped = False

    def _Play(self, video):
        # helper for OnOpen and OnPlay
        if isfile(video):  # Creation
            m = self.Instance.media_new(str(video))  # Path, unicode
            self.player.set_media(m)
            self.parent.title("tkVLCplayer - %s" % (basename(video),))

            # set the window id where to render VLC's video output
            h = self.videopanel.winfo_id()  # .winfo_visualid()?
            if _isWindows:
                self.player.set_hwnd(h)
            elif _isMacOS:
                # XXX 1) using the videopanel.winfo_id() handle
                # causes the video to play in the entire panel on
                # macOS, covering the buttons, sliders, etc.
                # XXX 2) .winfo_id() to return NSView on macOS?
                v = _GetNSView(h)
                if v:
                    self.player.set_nsobject(v)
                else:
                    self.player.set_xwindow(h)  # plays audio, no video
            else:
                self.player.set_xwindow(h)  # fails on Windows
            # FIXME: this should be made cross-platform
            self.OnPlay()

    def OnPause(self, *unused):
        """Toggle between Pause and Play.
        """
        if self.player.get_media():
            self._Pause_Play(not self.player.is_playing())
            self.player.pause()  # toggles

    def OnPlay(self, *unused):
        if self.player.play():  # == -1
            self.showError("Unable to play the video.")
        else:
            self._Pause_Play(True)
            # set volume slider to audio level
            vol = self.player.audio_get_volume()
            if vol > 0:
                self.volVar.set(vol)
                self.volSlider.set(vol)

    def OnResize(self, *unused):
        return
        """Adjust the window/frame to the video aspect ratio.
        """
        g = self.parent.geometry()
        if g != self._geometry and self.player:
            u, v = self.player.video_get_size()  # often (0, 0)
            if v > 0 and u > 0:
                # get window size and position
                g, x, y = g.split('+')
                w, h = g.split('x')
                # alternatively, use .winfo_...
                # w = self.parent.winfo_width()
                # h = self.parent.winfo_height()
                # x = self.parent.winfo_x()
                # y = self.parent.winfo_y()
                # use the video aspect ratio ...
                if u > v:  # ... for landscape
                    # adjust the window height
                    h = round(float(w) * v / u)
                else:  # ... for portrait
                    # adjust the window width
                    w = round(float(h) * u / v)
                self.parent.geometry("%sx%s+%s+%s" % (w, h, x, y))
                self._geometry = self.parent.geometry()  # actual

    def OnStop(self, *unused):
        """Stop the player, resets media.
        """
        if self.player:
            self.player.stop()
            self._Pause_Play(None)
            # reset the time slider
            self.timeSlider.set(0)
            self._stopped = True
        # XXX on macOS libVLC prints these error messages:
        # [h264 @ 0x7f84fb061200] get_buffer() failed
        # [h264 @ 0x7f84fb061200] thread_get_buffer() failed
        # [h264 @ 0x7f84fb061200] decode_slice_header error
        # [h264 @ 0x7f84fb061200] no frame!

    def OnTick(self):
        """Timer tick, update the time slider to the video time.
        """
        if self.player:
            # since the self.player.get_length may change while
            # playing, re-set the timeSlider to the correct range
            t = self.player.get_length() * 1e-3  # to seconds
            if t > 0:
                self.timeSlider.config(to=t)

                t = self.player.get_time() * 1e-3  # to seconds
                # don't change slider while user is messing with it
                if t > 0 and time.time() > (self.timeSliderUpdate + 2):
                    self.timeSlider.set(t)
                    self.timeSliderLast = int(self.timeVar.get())
        # start the 1 second timer again
        self.parent.after(500, self.OnTick)

    def OnTime(self, *unused):
        if self.player:
            t = self.timeVar.get()
            if self.timeSliderLast != int(t):
                # this is a hack. The timer updates the time slider.
                # This change causes this rtn (the 'slider has changed' rtn)
                # to be invoked.  I can't tell the difference between when
                # the user has manually moved the slider and when the timer
                # changed the slider.  But when the user moves the slider
                # tkinter only notifies this rtn about once per second and
                # when the slider has quit moving.
                # Also, the tkinter notification value has no fractional
                # seconds.  The timer update rtn saves off the last update
                # value (rounded to integer seconds) in timeSliderLast if
                # the notification time (sval) is the same as the last saved
                # time timeSliderLast then we know that this notification is
                # due to the timer changing the slider.  Otherwise the
                # notification is due to the user changing the slider.  If
                # the user is changing the slider then I have the timer
                # routine wait for at least 2 seconds before it starts
                # updating the slider again (so the timer doesn't start
                # fighting with the user).
                self.player.set_time(int(t * 1e3))  # milliseconds
                self.timeSliderUpdate = time.time()

    def OnVolume(self, *unused):
        """Volume slider changed, adjust the audio volume.
        """
        vol = min(self.volVar.get(), 100)
        v_M = "%d%s" % (vol, " (Muted)" if self.volMuted else '')
        self.volSlider.config(label="Volume " + v_M)
        if self.player and not self._stopped:
            # .audio_set_volume returns 0 if success, -1 otherwise,
            # e.g. if the player is stopped or doesn't have media
            if self.player.audio_set_volume(vol):  # and self.player.get_media():
                self.showError("Failed to set the volume: %s." % (v_M,))

    def showError(self, message):
        """Display a simple error dialog.
        """
        self.OnStop()
        showerror(self.parent.title(), message)


if __name__ == "__main__":

    _video = 'video.mp4'

    while len(sys.argv) > 1:
        arg = sys.argv.pop(1)
        if arg.lower() in ('-v', '--version'):
            # show all versions, sample output on macOS:
            # % python3 ./tkvlc.py -v
            # tkvlc.py: 2019.07.28 (tkinter 8.6 /Library/Frameworks/Python.framework/Versions/3.7/lib/libtk8.6.dylib)
            # vlc.py: 3.0.6109 (Sun Mar 31 20:14:16 2019 3.0.6)
            # LibVLC version: 3.0.6 Vetinari (0x3000600)
            # LibVLC compiler: clang: warning: argument unused during compilation: '-mmacosx-version-min=10.7' [-Wunused-command-line-argument]
            # Plugin path: /Applications/VLC3.0.6.app/Contents/MacOS/plugins
            # Python: 3.7.4 (64bit) macOS 10.13.6

            # Print version of this vlc.py and of the libvlc
            print('%s: %s (%s %s %s)' % (basename(__file__), __version__,
                                         Tk.__name__, Tk.TkVersion, libtk))
            try:
                vlc.print_version()
                vlc.print_python()
            except AttributeError:
                pass
            sys.exit(0)

        elif arg.startswith('-'):
            print('usage: %s  [-v | --version]  [<video_file_name>]' % (sys.argv[0],))
            sys.exit(1)

        elif arg:  # video file
            _video = expanduser(arg)
            if not isfile(_video):
                print('%s error: no such file: %r' % (sys.argv[0], arg))
                sys.exit(1)

    # Create a Tk.App() to handle the windowing event loop
    root = Tk.Tk()
    player = Player(root, video=_video)
    root.protocol("WM_DELETE_WINDOW", player.OnClose)  # XXX unnecessary (on macOS)
    root.mainloop()