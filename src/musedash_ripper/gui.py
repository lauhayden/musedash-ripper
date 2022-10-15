"""Tkinter-based GUI"""

import logging
import multiprocessing
import queue
import threading

import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import scrolledtext

from musedash_ripper import core

logger = logging.getLogger(__name__)


# we cannot control how many ancestors are in the tkinter library
class Application(ttk.Frame):  # pylint: disable=too-many-ancestors
    """Main application window"""

    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title("Muse Dash Ripper")
        self.pack(expand="y", fill="both", padx="0.2c", pady="0.2c", ipadx="0.1c", ipady="0.1c")
        self.create_widgets()

        self.rip_thread = None
        self.close_event = threading.Event()

        self.done_messagebox = None
        self.bind("<<done_rip>>", self.done_rip)

        self.log_empty = True
        self.log_queue = queue.SimpleQueue()
        self.bind("<<emit_log>>", self.emit_log)

    def create_widgets(self):
        """Create all widgets in the main window"""
        self.main_label = ttk.Label(
            self,
            text=(
                "Select the folder MuseDash.exe is located in, "
                "then choose where to put the exported files."
            ),
        )
        self.main_label.pack(pady="0.2c")

        self.gd_frame = ttk.Frame(self)
        self.gd_label = ttk.Label(self.gd_frame, width=12, text="Game folder")
        self.gd_label.pack(side="left")
        self.gd_entry = ttk.Entry(
            self.gd_frame,
        )
        self.gd_entry.insert(0, core.DEFAULT_GAME_DIR)
        self.gd_entry.pack(side="left", expand="y", fill="x", padx="0.1c")
        self.gd_button = ttk.Button(self.gd_frame, text="Browse...", command=self.set_gamedir)
        self.gd_button.pack(side="left")
        self.gd_frame.pack(fill="x", pady="0.1c")

        self.od_frame = ttk.Frame(self)
        self.od_label = ttk.Label(self.od_frame, width=12, text="Output folder")
        self.od_label.pack(side="left")
        self.od_entry = ttk.Entry(self.od_frame)
        self.od_entry.insert(0, core.DEFAULT_OUT_DIR)
        self.od_entry.pack(side="left", expand="y", fill="x", padx="0.1c")
        self.od_button = ttk.Button(self.od_frame, text="Browse...", command=self.set_outdir)
        self.od_button.pack(side="left")
        self.od_frame.pack(fill="x", pady="0.1c")

        self.options_frame = ttk.Frame(self)
        self.language_var = tk.StringVar(self, "None")
        self.language_menu = ttk.Combobox(
            self.options_frame,
            textvariable=self.language_var,
            values=list(core.LANGUAGES.keys()),
            state="readonly",
            width=17,
        )
        self.language_menu.pack(side="left", expand="y")
        self.ad_var = tk.BooleanVar(self, True)
        self.ad_checkbutton = ttk.Checkbutton(
            self.options_frame, variable=self.ad_var, text="Album folders"
        )
        self.ad_checkbutton.pack(side="left", expand="y")
        self.sc_var = tk.BooleanVar(self, False)
        self.sc_checkbutton = ttk.Checkbutton(
            self.options_frame, variable=self.sc_var, text="Export covers"
        )
        self.sc_checkbutton.pack(side="left", expand="y")
        self.ssc_var = tk.BooleanVar(self, False)
        self.ssc_checkbutton = ttk.Checkbutton(
            self.options_frame, variable=self.ssc_var, text="Export songs.csv"
        )
        self.ssc_checkbutton.pack(side="left", expand="y")
        self.options_frame.pack(fill="x", pady="0.1c")

        self.sep = ttk.Separator(self)
        self.sep.pack(fill="x", pady="0.1c")

        self.progress_var = tk.DoubleVar(self, 0.0)
        self.progress_bar = ttk.Progressbar(self, variable=self.progress_var, mode="determinate")
        self.progress_bar.pack(fill="x", pady="0.1c")

        self.log = scrolledtext.ScrolledText(self, height=10, state="disabled")
        # TODO: use keybinds to disable cursor, instead of toggling state?
        # see https://stackoverflow.com/questions/3842155/is-there-a-way-to-make-the-tkinter-text-widget-read-only  pylint: disable=line-too-long
        self.log.bind("<Control-c>", self.copy_log)
        self.log.pack(expand="y", fill="both")

        self.start = ttk.Button(self, text="Start!", command=self.start_rip)
        self.start.pack(side="bottom", pady="0.1c")

    def set_gamedir(self):
        """Open a file dialog to browse to the Muse Dash game directory"""
        gamedir = filedialog.askdirectory(
            parent=self, initialdir=self.gd_entry.get(), mustexist=True
        )
        if gamedir:
            self.gd_entry.delete(0, "end")
            self.gd_entry.insert(0, gamedir.replace("/", "\\"))

    def set_outdir(self):
        """Open a file dialog to browse to an output directory"""
        outdir = filedialog.askdirectory(parent=self, initialdir=self.od_entry.get())
        if outdir:
            self.od_entry.delete(0, "end")
            self.od_entry.insert(0, outdir.replace("/", "\\"))

    def copy_log(self, _event=None):
        """Copy the entire log to clipboard"""
        self.clipboard_clear()
        self.clipboard_append(self.log.get("sel.first", "sel.last"))

    def start_rip(self):
        """Start the ripping process on another thread"""
        self.start["state"] = "disabled"  # prevent multiple presses

        # clear log
        self.log["state"] = "normal"
        self.log.delete(1.0, "end")
        self.log["state"] = "disabled"
        self.log_empty = True

        self.start["state"] = "disabled"

        self.rip_thread = threading.Thread(target=self.rip, name="rip_thread")
        self.rip_thread.start()

    def rip(self):
        """Worker function for the ripping thread

        Don't directly call Tkinter stuff in here, instead generate a event with event_generate
        and handle gui updates on the main thread
        """
        try:
            rip_done = core.rip(
                self.gd_entry.get(),
                self.od_entry.get(),
                self.language_var.get(),
                self.ad_var.get(),
                self.sc_var.get(),
                self.ssc_var.get(),
                self.progress_var.set,
                self.close_event,
            )
            if rip_done:
                # don't show done message if user is exiting the application
                self.done_messagebox = ("Done", "Ripping complete! Enjoy your music!")
        except core.UserError as err:
            logger.error("Error: %s", err.message)
            self.done_messagebox = ("Error", err.message)
        except Exception:  # pylint: disable=broad-except
            # we catch and log any exception in the core ripping logic
            logger.exception("Exception in rip thread")
            self.done_messagebox = (
                "Error",
                (
                    "An error occurred while ripping. "
                    "Please submit an issue at https://github.com/lauhayden/musedash-ripper/issues "
                    "with the log contents."
                ),
            )
        self.event_generate("<<done_rip>>")

    def done_rip(self, _event=None):
        """Handler for <<done_rip>> event, finishing up the ripping process"""
        self.rip_thread = None
        self.start["state"] = "normal"
        if self.done_messagebox:
            if self.done_messagebox[0] == "Error":
                messagebox.showerror(*self.done_messagebox)
            else:
                messagebox.showinfo(*self.done_messagebox)

    def emit_log(self, _event=None):
        """Handler for <<emit_log>> event, emitting a single log message"""
        # true if the widget has been scrolled up
        keep_position = self.log.yview()[1] != 1.0
        self.log["state"] = "normal"
        msg = self.log_queue.get()
        if self.log_empty:
            self.log_empty = False
        else:
            msg = "\n" + msg
        self.log.insert("end", msg)
        self.log["state"] = "disabled"
        if not keep_position:
            self.log.yview_moveto(1.0)

    def close(self, chained=False):
        """Hook for X button, to exit gracefully"""
        if self.rip_thread is not None and self.rip_thread.is_alive():
            # ripping is currently in progress
            if not self.close_event.is_set():
                # first time close() is being called
                self.close_event.set()
                logger.info("Cancelling...")
                # schedule initial check
                # TODO: disable all widgets while waiting for close
                self.master.after(100, self.close, True)
            if chained:
                # chain checks
                self.master.after(100, self.close, True)
        else:
            self.master.destroy()


class TkinterEventHandler(logging.Handler):
    """Log handler that emits into a scrolledtextwidget

    Shoves formatted records into a queue and fire events.
    """

    def __init__(self, app: Application, record_q: queue.SimpleQueue):
        super().__init__()
        self.app = app
        self.record_q = record_q

    def handle(self, record: logging.LogRecord):
        retval = super().handle(record)
        if retval:
            # generating an event requires some sort of lock that the main loop holds while
            # processing events, so  we generate the event after releasing the handler's IO lock
            # or else we will deadlock if the main thread and the rip thread both want to log
            self.app.event_generate("<<emit_log>>")
        return retval

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.record_q.put(self.format(record))
        except Exception:  # pylint: disable=broad-except
            # catching Exception is standard in handlers' emit()
            self.handleError(record)


def run():
    """Main entry point of the GUI application"""
    root = tk.Tk()
    app = Application(master=root)

    sthandler = TkinterEventHandler(app, app.log_queue)
    formatter = logging.Formatter("%(message)s")
    sthandler.setFormatter(formatter)
    root_logger = logging.getLogger("")
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(sthandler)

    root.protocol("WM_DELETE_WINDOW", app.close)
    app.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run()
