
import sys,os,pty,fcntl,termios,struct,signal,shlex,json,threading,time,select,collections,re
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
from pathlib import Path
from PySide6.QtCore import Qt,QSocketNotifier,QTimer,QEvent,Signal,QSettings
from PySide6.QtGui import QFont,QKeyEvent,QTextCursor,QTextCharFormat,QBrush,QColor,QAction,QKeySequence
from PySide6.QtWidgets import *
from PySide6.QtWidgets import QTextEdit
import pyte,db
import app_lock

APP_NAME="NotRoyalTs"
APP_VERSION="1.1.2"

KIND=Qt.UserRole; ID=Qt.UserRole+1

class CompatibleScreen(pyte.Screen):
    """pyte 0.8.2 compatibility for private CSI SGR sequences.

    pyte's parser can dispatch SGR with private=True, but 0.8.2's
    Screen.select_graphic_rendition() does not accept that keyword.
    Newer upstream code does. Accept and ignore it here so malformed or
    vendor-specific private SGR sequences cannot break the terminal loop.
    """
    def select_graphic_rendition(self,*attrs,private=False):
        return super().select_graphic_rendition(*attrs)


class CompatibleHistoryScreen(pyte.HistoryScreen):
    def select_graphic_rendition(self,*attrs,private=False):
        return super().select_graphic_rendition(*attrs)


# ANSI/xterm palette used by the terminal renderer. pyte exposes the color
# attributes for each screen cell; earlier NotRoyalTs builds rendered only
# Screen.display, which kept the characters but discarded those attributes.
ANSI_COLORS = {
    "black": "#000000",
    "red": "#cd3131",
    "green": "#0dbc79",
    "brown": "#e5e510",
    "yellow": "#e5e510",
    "blue": "#2472c8",
    "magenta": "#bc3fbc",
    "cyan": "#11a8cd",
    "white": "#e5e5e5",
    "brightblack": "#666666",
    "brightred": "#f14c4c",
    "brightgreen": "#23d18b",
    "brightbrown": "#f5f543",
    "brightyellow": "#f5f543",
    "brightblue": "#3b8eea",
    "brightmagenta": "#d670d6",
    "brightcyan": "#29b8db",
    "brightwhite": "#ffffff",
}

def qt_terminal_color(value, default):
    if value is None or value == "default":
        return QColor(default)

    value = str(value).lower()
    if value in ANSI_COLORS:
        return QColor(ANSI_COLORS[value])

    # pyte may expose 256/true-color values as six-digit RGB strings.
    if len(value) == 6 and all(c in "0123456789abcdef" for c in value):
        return QColor("#" + value)

    if value.startswith("#") and QColor(value).isValid():
        return QColor(value)

    return QColor(default)

def sshargs(r):
    a=["/usr/bin/ssh"]
    if int(r["port"] or 22)!=22:a+=["-p",str(r["port"])]
    if r["identity_file"]:a+=["-i",os.path.expanduser(r["identity_file"])]
    if r["proxy_jump"]:a+=["-J",r["proxy_jump"]]
    if r["extra_args"]:a+=shlex.split(r["extra_args"])
    a+=[f'{r["username"]}@{r["host"]}'];return a

class Term(QPlainTextEdit):
    sessionEnded = Signal()
    def __init__(self,args,connection_id=None):
        super().__init__()
        self.args=args
        self.connection_id=connection_id
        self.fd=None
        self.pid=None
        self.scr=CompatibleHistoryScreen(120,35,history=10000,ratio=0.10)
        self.stream=pyte.Stream(self.scr)
        self.history_view=False
        self.app_cursor=False
        self.bracketed_paste=False
        self.alt_screen=False
        self.saved_screen=None
        self.saved_stream=None
        self.output_pending=b""
        self.last_pty_size=None

        # PTY master is non-blocking. A single os.write() is not guaranteed to
        # accept the entire payload (especially clipboard pastes), so preserve
        # unwritten bytes here and drain them asynchronously in order.
        self.tx_buffer=bytearray()

        # Some remote bash/readline setups emit the first prompt, then shortly
        # afterward send CR + ESC[K + the exact same prompt to redraw it in
        # place. Native terminals overwrite the current line; pyte was showing
        # that redraw as a second visible prompt. Track the last printable
        # startup line so we can discard only an exact duplicate redraw.
        self.startup_filter_until=time.monotonic()+8.0
        self.startup_last_printable=None

        self.setFont(QFont("Menlo",12))
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        # Keep the viewport geometry stable from the moment the terminal is
        # created. If Qt adds a scrollbar after the first render, the viewport
        # shrinks and resizepty() can reduce the pyte screen by one row, pushing
        # the top visible line (such as "Last login") into scrollback/history.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background:#111;color:#eee;border:0")

        # Blinking terminal cursor.
        self.cursor_on=True
        self.cursor_timer=QTimer(self)
        self.cursor_timer.setInterval(500)
        self.cursor_timer.timeout.connect(self.blink_cursor)
        self.cursor_timer.start()

        self.process_timer=QTimer(self)
        self.process_timer.setInterval(250)
        self.process_timer.timeout.connect(self.check_process)

        # Terminal output can arrive much faster than Qt can repaint a fully
        # color-formatted screen. Coalesce redraws so keyboard input (notably
        # Ctrl-C) remains responsive even during very noisy commands.
        self.render_timer=QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(75)
        self.render_timer.timeout.connect(self.render)

        # Drain ssh's PTY independently of Qt rendering.
        self.rx_lock=threading.Lock()
        self.rx_chunks=collections.deque()
        self.reader_stop=threading.Event()
        self.reader_thread=None

        # After Ctrl-C, stale queued output is discarded until the stream
        # briefly goes quiet; only a small final tail is kept for ^C/prompt.
        self.drop_after_interrupt=False
        self.interrupt_tail=b""
        self.interrupt_last=0.0

        self.pump_timer=QTimer(self)
        self.pump_timer.setInterval(5)
        self.pump_timer.timeout.connect(self.pump_output)

        self.tx_timer=QTimer(self)
        self.tx_timer.setInterval(5)
        self.tx_timer.timeout.connect(self.pump_input)

        QTimer.singleShot(0,self.start)

    def start(self):
        # Work out the terminal geometry before forking. If ssh starts with the
        # PTY at its default size and we resize only after login, some remote
        # shells redraw the first prompt when they receive the initial WINCH.
        # That is what produced two identical prompts on login while subsequent
        # commands behaved normally.
        fm=self.fontMetrics()
        initial_cols=max(20,(self.viewport().width()-4)//max(1,fm.horizontalAdvance("M")))
        initial_rows=max(5,self.viewport().height()//max(1,fm.height()))
        initial_size=(initial_rows,initial_cols)

        pid,fd=pty.fork()
        if pid==0:
            try:
                # In the child, fd 0 is the slave PTY. Set its size before
                # exec'ing ssh so the remote session starts with the correct
                # dimensions and never needs an immediate post-login redraw.
                fcntl.ioctl(
                    0,
                    termios.TIOCSWINSZ,
                    struct.pack("HHHH",initial_rows,initial_cols,0,0)
                )
            except OSError:
                pass

            os.environ["TERM"]="xterm-256color"
            os.execv(self.args[0],self.args)

        self.pid,self.fd=pid,fd
        self.last_pty_size=initial_size

        # Keep pyte's initial model in sync with the PTY before output arrives.
        self.scr.resize(lines=initial_rows,columns=initial_cols)

        fcntl.fcntl(fd,fcntl.F_SETFL,fcntl.fcntl(fd,fcntl.F_GETFL)|os.O_NONBLOCK)

        self.note=None
        self.reader_stop.clear()
        self.reader_thread=threading.Thread(
            target=self._reader_loop,
            name="NotRoyalTs-PTY",
            daemon=True,
        )
        self.reader_thread.start()

        self.process_timer.start()
        self.pump_timer.start()
        self.tx_timer.start()
        self.setFocus()

    def filter_startup_duplicate_redraw(self,data):
        """Drop only an exact startup redraw of the current printable line.

        The captured affected sequence is:
            <prompt>
            CR ESC[K <same prompt>

        This helper works at the raw PTY-read level, before pyte sees the bytes.
        It does not delay startup output and it does not touch a redraw whose
        replacement text differs from the previous printable line.
        """
        if not data:
            return data

        now=time.monotonic()
        if now > self.startup_filter_until:
            return data

        redraw_prefix=b"\r\x1b[K"

        if data.startswith(redraw_prefix) and self.startup_last_printable:
            replacement=data[len(redraw_prefix):]

            # Only suppress when the redraw is exactly the same printable bytes
            # as the immediately preceding line/prompt.
            if replacement == self.startup_last_printable:
                return b""

        # Remember the trailing printable run from this chunk. This correctly
        # captures prompts that follow OSC title sequences ending in BEL.
        m=re.search(rb'([^\x00-\x1f\x7f]{1,512})$',data)
        if m:
            self.startup_last_printable=m.group(1)

        return data

    def _reader_loop(self):
        while not self.reader_stop.is_set():
            fd=self.fd
            if fd is None:
                return

            try:
                ready,_,_=select.select([fd],[],[],0.05)
            except (OSError,ValueError):
                return

            now=time.monotonic()

            if not ready:
                with self.rx_lock:
                    if (
                        self.drop_after_interrupt
                        and self.interrupt_last
                        and now-self.interrupt_last >= 0.060
                    ):
                        tail=self.interrupt_tail
                        self.interrupt_tail=b""
                        self.drop_after_interrupt=False
                        if tail:
                            self.rx_chunks.append(tail)
                continue

            while not self.reader_stop.is_set():
                try:
                    data=os.read(fd,65536)
                    if not data:
                        return
                except BlockingIOError:
                    break
                except OSError:
                    return

                now=time.monotonic()

                # Handle the one confirmed startup redraw quirk before the data
                # enters the GUI/parser pipeline.
                data=self.filter_startup_duplicate_redraw(data)
                if not data:
                    continue

                with self.rx_lock:
                    if self.drop_after_interrupt:
                        self.interrupt_tail=(self.interrupt_tail+data)[-4096:]
                        self.interrupt_last=now
                    else:
                        self.rx_chunks.append(data)

    def pump_output(self):
        # Keep each Qt callback small so keyboard events stay responsive.
        budget=4096
        pieces=[]
        total=0

        with self.rx_lock:
            while self.rx_chunks and total < budget:
                chunk=self.rx_chunks.popleft()
                remaining=budget-total

                if len(chunk) > remaining:
                    pieces.append(chunk[:remaining])
                    self.rx_chunks.appendleft(chunk[remaining:])
                    total += remaining
                    break

                pieces.append(chunk)
                total += len(chunk)

        if not pieces:
            return

        self.process_output(b"".join(pieces))
        if not self.render_timer.isActive():
            self.render_timer.start()

    def begin_interrupt_drop(self):
        self.render_timer.stop()
        with self.rx_lock:
            self.rx_chunks.clear()
            self.drop_after_interrupt=True
            self.interrupt_tail=b""
            self.interrupt_last=time.monotonic()

    def process_output(self, data):
        tokens = {
            b"\x1b[?1h": "cursor_on",
            b"\x1b[?1l": "cursor_off",
            b"\x1b[?2004h": "paste_on",
            b"\x1b[?2004l": "paste_off",
            b"\x1b[?47h": "alt_on",
            b"\x1b[?47l": "alt_off",
            b"\x1b[?1047h": "alt_on",
            b"\x1b[?1047l": "alt_off",
            b"\x1b[?1049h": "alt_on",
            b"\x1b[?1049l": "alt_off",
        }

        buf = self.output_pending + data
        self.output_pending = b""

        # Preserve a short trailing fragment if it could be the beginning of
        # one of the control sequences above.
        keep = 0
        max_token = max(len(t) for t in tokens)
        for n in range(1, min(len(buf), max_token - 1) + 1):
            suffix = buf[-n:]
            if any(t.startswith(suffix) for t in tokens):
                keep = n

        if keep:
            work = buf[:-keep]
            self.output_pending = buf[-keep:]
        else:
            work = buf

        while work:
            pos = None
            token = None
            for candidate in tokens:
                p = work.find(candidate)
                if p != -1 and (pos is None or p < pos):
                    pos = p
                    token = candidate

            if token is None:
                self.feed_terminal_bytes(work)
                break

            if pos:
                self.feed_terminal_bytes(work[:pos])

            action = tokens[token]
            if action == "cursor_on":
                self.app_cursor = True
            elif action == "cursor_off":
                self.app_cursor = False
            elif action == "paste_on":
                self.bracketed_paste = True
            elif action == "paste_off":
                self.bracketed_paste = False
            elif action == "alt_on":
                self.enter_alt_screen()
            elif action == "alt_off":
                self.leave_alt_screen()

            work = work[pos + len(token):]

    def feed_terminal_bytes(self, data):
        if data:
            self.stream.feed(data.decode("utf-8", errors="replace"))

    def enter_alt_screen(self):
        if self.alt_screen:
            return

        self.saved_screen = self.scr
        self.saved_stream = self.stream

        cols = getattr(self.scr, "columns", 120)
        rows = getattr(self.scr, "lines", 35)
        self.scr = CompatibleScreen(cols, rows)
        self.stream = pyte.Stream(self.scr)
        self.alt_screen = True

    def leave_alt_screen(self):
        if not self.alt_screen:
            return

        if self.saved_screen is not None:
            self.scr = self.saved_screen
            self.stream = self.saved_stream

        self.saved_screen = None
        self.saved_stream = None
        self.alt_screen = False

    def render(self):
        # pyte's Screen.display contains the visible characters, while the
        # per-cell buffer contains ANSI attributes such as foreground color,
        # background color, bold, underline, reverse video, etc.
        self.setPlainText("\n".join(self.scr.display))
        self.apply_terminal_formatting()

        # Follow the live terminal cursor only while viewing the current screen.
        # When the user pages back into history, leave the viewport alone.
        if not self.history_view:
            cur=self.textCursor()
            row=max(0,min(self.scr.cursor.y,self.document().blockCount()-1))
            block=self.document().findBlockByNumber(row)
            if block.isValid():
                col=max(0,min(self.scr.cursor.x,max(0,block.length()-1)))
                cur.setPosition(block.position()+col)
                self.setTextCursor(cur)
                self.ensureCursorVisible()

        self.draw_cursor()

    def apply_terminal_formatting(self):
        default_fg="#e8e8e8"
        default_bg="#111111"

        # Walk each pyte screen row and format runs with identical attributes.
        # At typical terminal sizes this is only a few thousand cells and is
        # fast enough while preserving full xterm color output from ls, grep,
        # vim, systemd tools, etc.
        rows=getattr(self.scr,"lines",0)
        cols=getattr(self.scr,"columns",0)

        for y in range(rows):
            block=self.document().findBlockByNumber(y)
            if not block.isValid():
                continue

            rowbuf=self.scr.buffer[y]
            run_start=0
            run_key=None

            def cell_key(x):
                ch=rowbuf[x]
                return (
                    getattr(ch,"fg","default"),
                    getattr(ch,"bg","default"),
                    bool(getattr(ch,"bold",False)),
                    bool(getattr(ch,"italics",False)),
                    bool(getattr(ch,"underscore",False)),
                    bool(getattr(ch,"strikethrough",False)),
                    bool(getattr(ch,"reverse",False)),
                )

            def apply_run(x0,x1,key):
                if x1<=x0:
                    return

                fg,bg,bold,italics,underline,strike,reverse=key
                fg_color=qt_terminal_color(fg,default_fg)
                bg_color=qt_terminal_color(bg,default_bg)

                if reverse:
                    fg_color,bg_color=bg_color,fg_color

                fmt=QTextCharFormat()
                fmt.setForeground(QBrush(fg_color))
                fmt.setBackground(QBrush(bg_color))
                fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)
                fmt.setFontItalic(italics)
                fmt.setFontUnderline(underline)
                fmt.setFontStrikeOut(strike)

                # QTextBlock includes a paragraph separator at the end, so cap
                # formatting at the visible characters in this block.
                visible=max(0,block.length()-1)
                x0=min(x0,visible)
                x1=min(x1,visible)
                if x1<=x0:
                    return

                c=QTextCursor(self.document())
                c.setPosition(block.position()+x0)
                c.setPosition(block.position()+x1,QTextCursor.KeepAnchor)
                c.setCharFormat(fmt)

            for x in range(cols):
                key=cell_key(x)
                if run_key is None:
                    run_key=key
                    run_start=x
                elif key!=run_key:
                    apply_run(run_start,x,run_key)
                    run_start=x
                    run_key=key

            if run_key is not None:
                apply_run(run_start,cols,run_key)


    def draw_cursor(self):
        if not self.hasFocus() or not self.cursor_on or self.history_view:
            self.setExtraSelections([])
            return

        row=max(0,min(self.scr.cursor.y,self.document().blockCount()-1))
        block=self.document().findBlockByNumber(row)
        if not block.isValid():
            self.setExtraSelections([])
            return

        col=max(0,min(self.scr.cursor.x,max(0,block.length()-1)))
        c=QTextCursor(self.document())
        c.setPosition(block.position()+col)
        c.movePosition(QTextCursor.Right,QTextCursor.KeepAnchor,1)

        sel=QTextEdit.ExtraSelection()
        sel.cursor=c
        fmt=QTextCharFormat()
        fmt.setBackground(QBrush(QColor("#e8e8e8")))
        fmt.setForeground(QBrush(QColor("#111111")))
        sel.format=fmt
        self.setExtraSelections([sel])

    def blink_cursor(self):
        self.cursor_on=not self.cursor_on
        self.draw_cursor()

    def focusInEvent(self,e):
        super().focusInEvent(e)
        self.cursor_on=True
        self.draw_cursor()

    def focusOutEvent(self,e):
        super().focusOutEvent(e)
        self.setExtraSelections([])

    def event(self,e):
        # Qt normally treats Tab as "move focus to the next widget".
        # Intercept it at the event level so shells receive a real TAB byte
        # for filename/command completion.
        if e.type()==QEvent.KeyPress:
            if e.key()==Qt.Key_Tab:
                self.send(b"\t")
                return True
            if e.key()==Qt.Key_Backtab:
                self.send(b"\x1b[Z")
                return True
        return super().event(e)

    def focusNextPrevChild(self,next):
        # Keep keyboard focus inside the terminal. Tab/Shift-Tab belong to
        # the remote shell/application, not the Qt widget hierarchy.
        return False

    def send(self,b):
        if self.fd is None or not b:
            return

        # Preserve strict byte ordering. If an earlier write was partial, new
        # keystrokes must follow the queued remainder rather than overtaking it.
        if self.tx_buffer:
            self.tx_buffer.extend(b)
            return

        try:
            written=os.write(self.fd,b)
        except BlockingIOError:
            written=0
        except OSError:
            return

        if written < len(b):
            self.tx_buffer.extend(b[written:])

    def pump_input(self):
        if self.fd is None or not self.tx_buffer:
            return

        # Keep each GUI callback small while allowing large pastes to drain
        # quickly. os.write() may still accept fewer bytes than requested.
        chunk=bytes(self.tx_buffer[:65536])

        try:
            written=os.write(self.fd,chunk)
        except BlockingIOError:
            return
        except OSError:
            self.tx_buffer.clear()
            return

        if written > 0:
            del self.tx_buffer[:written]

    def copy_selection(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        # Qt uses paragraph separators internally for multi-line selections.
        selected = cursor.selectedText().replace("\u2029", "\n")
        QApplication.clipboard().setText(selected)

    def paste_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            return

        data = text.encode("utf-8")

        # Modern shells/editors can request bracketed paste mode. Wrapping the
        # clipboard payload tells the remote application that the characters
        # arrived as a paste rather than as individually typed keystrokes.
        if self.bracketed_paste:
            data = b"\x1b[200~" + data + b"\x1b[201~"

        self.send(data)

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(self.textCursor().hasSelection())
        copy_action.triggered.connect(self.copy_selection)

        paste_action = menu.addAction("Paste")
        paste_action.setEnabled(bool(QApplication.clipboard().text()))
        paste_action.triggered.connect(self.paste_clipboard)

        menu.addSeparator()

        select_all = menu.addAction("Select All")
        select_all.triggered.connect(self.selectAll)

        menu.exec(event.globalPos())

    def scrollback_up(self,pages=1):
        if self.alt_screen or not hasattr(self.scr,"prev_page"):
            return False
        for _ in range(max(1,int(pages))):
            self.scr.prev_page()
        self.history_view=True
        self.render()
        return True

    def scrollback_down(self,pages=1):
        if self.alt_screen or not hasattr(self.scr,"next_page"):
            return False
        for _ in range(max(1,int(pages))):
            self.scr.next_page()

        # pyte exposes history position/size on HistoryScreen.history. If we
        # reached the bottom, resume normal cursor following.
        h=getattr(self.scr,"history",None)
        if h is not None:
            try:
                self.history_view = h.position < h.size
            except Exception:
                pass
        self.render()
        return True

    def wheelEvent(self,e):
        if self.alt_screen:
            return super().wheelEvent(e)

        delta=e.angleDelta().y()
        if delta>0:
            self.scrollback_up(1)
            e.accept()
            return
        if delta<0:
            self.scrollback_down(1)
            e.accept()
            return
        super().wheelEvent(e)

    def keyPressEvent(self,e):
        k=e.key()
        m=e.modifiers()

        # IMPORTANT: On macOS, Qt maps the physical Command key to
        # Qt.ControlModifier and the physical Control key to Qt.MetaModifier.
        # So Command-C/V use ControlModifier here, while physical Ctrl-C/V
        # must fall through to the terminal-control handler below.
        if (m & Qt.ControlModifier) and not (m & Qt.MetaModifier) and not (m & Qt.ShiftModifier) and k == Qt.Key_C:
            self.copy_selection()
            return

        if (m & Qt.ControlModifier) and not (m & Qt.MetaModifier) and not (m & Qt.ShiftModifier) and k == Qt.Key_V:
            self.paste_clipboard()
            return

        # Physical Ctrl+Shift+C/V on macOS arrive as Meta+Shift.
        if (m & Qt.MetaModifier) and (m & Qt.ShiftModifier) and k == Qt.Key_C:
            self.copy_selection()
            return

        if (m & Qt.MetaModifier) and (m & Qt.ShiftModifier) and k == Qt.Key_V:
            self.paste_clipboard()
            return

        if (m & Qt.ShiftModifier) and k == Qt.Key_Insert:
            self.paste_clipboard()
            return

        # Full-screen terminal apps (vi/vim, less, etc.) often enable
        # DECCKM "application cursor keys". In that mode xterm sends SS3
        # sequences (ESC O A/B/C/D) instead of the normal CSI sequences.
        app_cursor = getattr(self, "app_cursor", False)

        if k == Qt.Key_Up:
            self.send(b"\x1bOA" if app_cursor else b"\x1b[A")
            return
        if k == Qt.Key_Down:
            self.send(b"\x1bOB" if app_cursor else b"\x1b[B")
            return
        if k == Qt.Key_Right:
            self.send(b"\x1bOC" if app_cursor else b"\x1b[C")
            return
        if k == Qt.Key_Left:
            self.send(b"\x1bOD" if app_cursor else b"\x1b[D")
            return

        if (m & Qt.ShiftModifier) and k == Qt.Key_PageUp and not self.alt_screen:
            self.scrollback_up(5)
            return
        if (m & Qt.ShiftModifier) and k == Qt.Key_PageDown and not self.alt_screen:
            self.scrollback_down(5)
            return

        seq={
            Qt.Key_Return:b"\r",
            Qt.Key_Enter:b"\r",
            Qt.Key_Backspace:b"\x7f",
            Qt.Key_Escape:b"\x1b",
            Qt.Key_Home:b"\x1bOH" if app_cursor else b"\x1b[H",
            Qt.Key_End:b"\x1bOF" if app_cursor else b"\x1b[F",
            Qt.Key_Insert:b"\x1b[2~",
            Qt.Key_Delete:b"\x1b[3~",
            Qt.Key_PageUp:b"\x1b[5~",
            Qt.Key_PageDown:b"\x1b[6~",
        }
        if k in seq:
            self.send(seq[k])
            return

        # On macOS the physical Control key is Qt.MetaModifier.
        if (m & Qt.MetaModifier) and not (m & Qt.ControlModifier) and Qt.Key_A <= k <= Qt.Key_Z:
            if k == Qt.Key_C:
                self.begin_interrupt_drop()
            self.send(bytes([k-Qt.Key_A+1]))
            return

        if e.text():
            self.send(e.text().encode())

    def resizeEvent(self,e):
        super().resizeEvent(e)
        self.resizepty()

    def resizepty(self):
        if self.fd is None:
            return

        fm=self.fontMetrics()
        cols=max(20,(self.viewport().width()-4)//max(1,fm.horizontalAdvance("M")))
        rows=max(5,self.viewport().height()//max(1,fm.height()))

        # Qt can emit several identical resize events while a tab is created or
        # the main window is laid out. Sending repeated WINCH notifications while
        # a shell is sitting at its prompt can make readline redraw the prompt,
        # which appears as a duplicate "~#" / "$" line on some hosts.
        size=(rows,cols)
        if size == self.last_pty_size:
            return

        try:
            # TIOCSWINSZ is sufficient. The PTY kernel handles the terminal
            # window-size change; manually sending SIGWINCH to ssh as well is
            # redundant and can provoke an extra prompt redraw.
            fcntl.ioctl(
                self.fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH",rows,cols,0,0)
            )
            self.last_pty_size=size

            self.scr.resize(lines=rows,columns=cols)
            if self.alt_screen and self.saved_screen is not None:
                self.saved_screen.resize(lines=rows,columns=cols)

        except OSError:
            pass


    def check_process(self):
        if not self.pid:
            return

        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pid = self.pid

        if pid == 0:
            return

        # The local ssh process has ended, either because the user typed exit,
        # the remote side closed the connection, or ssh itself failed.
        self.process_timer.stop()
        self.cursor_timer.stop()
        self.render_timer.stop()
        self.pump_timer.stop()
        self.tx_timer.stop()
        self.tx_buffer.clear()
        self.reader_stop.set()

        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=0.15)

        self.reader_thread=None

        self.pid = None
        QTimer.singleShot(0, self.sessionEnded.emit)


    def stop(self):
        self.cursor_timer.stop()
        self.process_timer.stop()
        self.render_timer.stop()
        self.pump_timer.stop()
        self.reader_stop.set()
        if self.pid:
            try:
                os.kill(self.pid,signal.SIGHUP)
            except OSError:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except (OSError, ChildProcessError):
                pass
            self.pid=None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd=None

        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=0.15)
        self.reader_thread=None

class ConnDialog(QDialog):
    def __init__(self,parent,folders,row=None):
        super().__init__(parent);self.setWindowTitle("Connection");f=QFormLayout(self)
        self.name=QLineEdit();self.folder=QComboBox();self.folder.addItem("(No folder)",None)
        for i,n in folders:self.folder.addItem(n,i)
        self.host=QLineEdit();self.port=QSpinBox();self.port.setRange(1,65535);self.port.setValue(22)
        self.user=QLineEdit()
        self.key=QLineEdit()

        self.key_browse=QPushButton("Browse…")
        self.key_browse.clicked.connect(self.browse_key)
        key_row=QWidget()
        key_layout=QHBoxLayout(key_row)
        key_layout.setContentsMargins(0,0,0,0)
        key_layout.addWidget(self.key)
        key_layout.addWidget(self.key_browse)

        self.jump=QLineEdit()
        self.extra=QLineEdit()
        self.notes=QTextEdit()

        for label,w in [
            ("Name",self.name),
            ("Folder",self.folder),
            ("Host/IP",self.host),
            ("Port",self.port),
            ("Username",self.user),
            ("SSH key",key_row),
            ("ProxyJump",self.jump),
            ("Extra SSH args",self.extra),
            ("Notes",self.notes)
        ]:
            f.addRow(label,w)
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(self.accept);b.rejected.connect(self.reject);f.addRow(b)
        if row:
            self.name.setText(row["name"]);self.host.setText(row["host"]);self.port.setValue(row["port"]);self.user.setText(row["username"]);self.key.setText(row["identity_file"] or "");self.jump.setText(row["proxy_jump"] or "");self.extra.setText(row["extra_args"] or "");self.notes.setPlainText(row["notes"] or "")
            i=self.folder.findData(row["folder_id"])
            if i>=0:self.folder.setCurrentIndex(i)
    def browse_key(self):
        start_dir=str(Path.home()/".ssh")
        path,_=QFileDialog.getOpenFileName(
            self,
            "Choose SSH private key",
            start_dir,
            "All Files (*)"
        )
        if path:
            home=str(Path.home())
            if path.startswith(home + "/"):
                path="~/" + path[len(home)+1:]
            self.key.setText(path)

    def data(self):return {"name":self.name.text(),"folder_id":self.folder.currentData(),"host":self.host.text(),"port":self.port.value(),"username":self.user.text(),"identity_file":self.key.text(),"proxy_jump":self.jump.text(),"extra_args":self.extra.text(),"notes":self.notes.toPlainText()}


def app_lock_enabled():
    return QSettings("NotRoyalTs","NotRoyalTs").value(
        "app_lock_enabled",
        False,
        type=bool,
    )


class UnlockDialog(QDialog):
    def __init__(self,parent=None,title="Unlock NotRoyalTs",message=None):
        super().__init__(parent)
        self.failures=0
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)

        layout=QVBoxLayout(self)

        label=QLabel(
            message
            or "Enter the NotRoyalTs App Lock password to continue."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        self.password=QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Password")
        self.password.returnPressed.connect(self.tryUnlock)
        layout.addWidget(self.password)

        self.error=QLabel("")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        self.buttons=QDialogButtonBox(
            QDialogButtonBox.Ok|QDialogButtonBox.Cancel
        )
        self.ok_button=self.buttons.button(QDialogButtonBox.Ok)
        self.buttons.accepted.connect(self.tryUnlock)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        QTimer.singleShot(0,self.password.setFocus)

    def tryUnlock(self):
        password=self.password.text()

        try:
            unlocked=app_lock.verify_password(password)
        except app_lock.KeychainError as exc:
            QMessageBox.critical(
                self,
                "NotRoyalTs App Lock",
                str(exc),
            )
            return

        if unlocked:
            self.password.clear()
            super().accept()
            return

        self.failures+=1
        self.password.clear()
        self.error.setText("Incorrect password.")
        self.password.setFocus()

        if self.failures%3==0:
            self.password.setEnabled(False)
            self.ok_button.setEnabled(False)
            self.error.setText("Incorrect password. Try again in 2 seconds.")
            QTimer.singleShot(2000,self.enableRetry)

    def enableRetry(self):
        self.password.setEnabled(True)
        self.ok_button.setEnabled(True)
        self.error.setText("")
        self.password.setFocus()


class AppLockSettingsDialog(QDialog):
    def __init__(self,parent=None,enabled=False):
        super().__init__(parent)
        self.original_enabled=bool(enabled)
        self.setWindowTitle("App Lock Settings")
        self.setMinimumWidth(480)

        layout=QVBoxLayout(self)

        self.enable_lock=QCheckBox("Require password when NotRoyalTs starts")
        self.enable_lock.setChecked(self.original_enabled)
        layout.addWidget(self.enable_lock)

        note=QLabel(
            "App Lock prevents casual access to the NotRoyalTs interface. "
            "It does not encrypt the SQLite database, exported backup files, "
            "or SSH private keys."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        form=QFormLayout()
        self.password=QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.confirm=QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        form.addRow(
            "New password:",
            self.password,
        )
        form.addRow(
            "Confirm password:",
            self.confirm,
        )
        layout.addLayout(form)

        hint=QLabel(
            "Leave both password fields blank to keep the current password."
            if self.original_enabled
            else "Set a password to enable App Lock."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.enable_lock.toggled.connect(self.updatePasswordFields)
        self.updatePasswordFields(self.enable_lock.isChecked())

        buttons=QDialogButtonBox(
            QDialogButtonBox.Save|QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.validateAndAccept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def updatePasswordFields(self,checked):
        self.password.setEnabled(checked)
        self.confirm.setEnabled(checked)

    def validateAndAccept(self):
        enabled=self.enable_lock.isChecked()
        password=self.password.text()
        confirm=self.confirm.text()

        if enabled and not self.original_enabled and not password:
            QMessageBox.warning(
                self,
                "App Lock",
                "Enter a password before enabling App Lock.",
            )
            return

        if password or confirm:
            if password!=confirm:
                QMessageBox.warning(
                    self,
                    "App Lock",
                    "The new passwords do not match.",
                )
                return
            if not password:
                QMessageBox.warning(
                    self,
                    "App Lock",
                    "The password cannot be empty.",
                )
                return

        super().accept()

    def lockEnabled(self):
        return self.enable_lock.isChecked()

    def newPassword(self):
        return self.password.text()


class Win(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1400,850)

        self.settings=QSettings("NotRoyalTs","NotRoyalTs")
        legacy_settings=QSettings("SSHDesk","SSHDesk")
        if self.settings.value("settings_migrated",False,type=bool) is False:
            legacy_expanded=legacy_settings.value("expanded_folders",[],type=list)
            if legacy_expanded and not self.settings.value("expanded_folders",[],type=list):
                self.settings.setValue("expanded_folders",legacy_expanded)
            self.settings.setValue("settings_migrated",True)
        self.expanded_folders=set(
            int(x) for x in self.settings.value("expanded_folders", [], type=list)
            if str(x).isdigit()
        )

        self.search=QLineEdit()
        self.search.setPlaceholderText("Search connections…")
        self.search.textChanged.connect(self.reload)

        self.tree=QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(lambda *_:self.connect())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.menu)
        self.tree.itemExpanded.connect(self.folder_expanded)
        self.tree.itemCollapsed.connect(self.folder_collapsed)

        left=QWidget()
        l=QVBoxLayout(left)
        l.setContentsMargins(8,8,8,8)
        l.addWidget(self.search)
        l.addWidget(self.tree)

        self.tabs=QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.closeTab)
        self.tabs.currentChanged.connect(self.activateCurrentTab)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.tabMenu)

        # Small + button in the tab corner. It focuses connection search so
        # opening another session stays keyboard-friendly.
        self.plus_button=QToolButton()
        self.plus_button.setText("+")
        self.plus_button.setToolTip("Find another connection (use File → Open Local Terminal for a local shell)")
        self.plus_button.clicked.connect(self.focusSearch)
        self.tabs.setCornerWidget(self.plus_button, Qt.TopRightCorner)

        sp=QSplitter()
        sp.addWidget(left)
        sp.addWidget(self.tabs)
        sp.setSizes([320,1080])
        self.setCentralWidget(sp)

        self.makeMenus()
        self.reload()

    def makeMenus(self):
        fm=self.menuBar().addMenu("File")

        a=QAction("New Folder",self)
        a.triggered.connect(self.newFolder)
        fm.addAction(a)

        a=QAction("New Connection",self)
        a.setShortcut(QKeySequence("Ctrl+N"))
        a.triggered.connect(self.newConn)
        fm.addAction(a)

        a=QAction("Open Local Terminal",self)
        a.setShortcut(QKeySequence("Ctrl+Shift+T"))
        a.triggered.connect(self.openLocalTerminal)
        fm.addAction(a)

        fm.addSeparator()

        a=QAction("Import Royal TS Document…",self)
        a.triggered.connect(self.importRoyalTS)
        fm.addAction(a)

        fm.addSeparator()

        a=QAction("Export NotRoyalTs Backup…",self)
        a.triggered.connect(self.exportBackup)
        fm.addAction(a)

        a=QAction("Import NotRoyalTs Backup…",self)
        a.triggered.connect(self.importBackup)
        fm.addAction(a)

        security_menu=self.menuBar().addMenu("Security")

        a=QAction("App Lock Settings…",self)
        a.triggered.connect(self.configureAppLock)
        security_menu.addAction(a)

        security_menu.addSeparator()

        self.lock_action=QAction("Lock NotRoyalTs",self)
        self.lock_action.setEnabled(app_lock_enabled())
        self.lock_action.triggered.connect(self.lockApp)
        security_menu.addAction(self.lock_action)

        sm=self.menuBar().addMenu("Session")

        a=QAction("Reconnect Current Tab",self)
        a.setShortcut(QKeySequence("Ctrl+R"))
        a.triggered.connect(self.reconnectCurrent)
        sm.addAction(a)

        a=QAction("Duplicate Current Session",self)
        a.setShortcut(QKeySequence("Ctrl+Shift+D"))
        a.triggered.connect(self.duplicateCurrentSession)
        sm.addAction(a)

        a=QAction("Close Current Tab",self)
        a.setShortcut(QKeySequence("Ctrl+W"))
        a.triggered.connect(self.closeCurrentTab)
        sm.addAction(a)

        sm.addSeparator()

        for n in range(1,10):
            a=QAction(f"Go to Tab {n}",self)
            a.setShortcut(QKeySequence(f"Ctrl+{n}"))
            a.triggered.connect(lambda checked=False, idx=n-1:self.goToTab(idx))
            self.addAction(a)

        a=QAction("Find Connection",self)
        a.setShortcut(QKeySequence("Ctrl+K"))
        a.triggered.connect(self.focusSearch)
        self.addAction(a)

    def configureAppLock(self):
        was_enabled=app_lock_enabled()

        if was_enabled:
            if not app_lock.is_configured():
                QMessageBox.critical(
                    self,
                    "NotRoyalTs App Lock",
                    (
                        "App Lock is enabled, but its Keychain verifier "
                        "could not be found. No settings were changed."
                    ),
                )
                return

            unlock=UnlockDialog(
                self,
                "Authenticate App Lock Settings",
                "Enter the current App Lock password to change security settings.",
            )
            if unlock.exec()!=QDialog.Accepted:
                return

        dialog=AppLockSettingsDialog(self,was_enabled)
        if dialog.exec()!=QDialog.Accepted:
            return

        enable=dialog.lockEnabled()
        new_password=dialog.newPassword()

        try:
            if enable:
                if new_password:
                    app_lock.set_password(new_password)
                elif not was_enabled:
                    QMessageBox.warning(
                        self,
                        "NotRoyalTs App Lock",
                        "A password is required to enable App Lock.",
                    )
                    return

                self.settings.setValue("app_lock_enabled",True)
            else:
                app_lock.clear_password()
                self.settings.setValue("app_lock_enabled",False)

            self.settings.sync()
        except (app_lock.KeychainError,ValueError) as exc:
            QMessageBox.critical(
                self,
                "NotRoyalTs App Lock",
                str(exc),
            )
            return

        enabled=app_lock_enabled()
        self.lock_action.setEnabled(enabled)

        QMessageBox.information(
            self,
            "NotRoyalTs App Lock",
            (
                "App Lock is enabled."
                if enabled
                else "App Lock is disabled."
            ),
        )

    def lockApp(self):
        if not app_lock_enabled():
            return

        self.hide()
        QApplication.processEvents()

        unlock=UnlockDialog(
            None,
            "NotRoyalTs Locked",
            "NotRoyalTs is locked. Enter the App Lock password to continue.",
        )

        if unlock.exec()==QDialog.Accepted:
            self.show()
            self.raise_()
            self.activateWindow()
            return

        # Canceling a manual lock closes the application instead of revealing
        # the previously hidden connection UI.
        self.close()

    def focusSearch(self):
        self.search.setFocus()
        self.search.selectAll()

    def openLocalTerminal(self):
        shell=os.environ.get("SHELL") or "/bin/zsh"
        argv=[shell, "-l"]
        t=Term(argv,connection_id=None)
        t.sessionEnded.connect(lambda term=t:self.closeTerm(term))
        n=self.tabs.addTab(t,"Local Terminal")
        self.tabs.setCurrentIndex(n)
        t.setFocus()

    def exportBackup(self):
        default_name=f"NotRoyalTs-backup-{datetime.now().strftime('%Y-%m-%d')}.notroyalts.json"
        path,_=QFileDialog.getSaveFileName(
            self,
            "Export NotRoyalTs Backup",
            str(Path.home()/default_name),
            "NotRoyalTs Backup (*.notroyalts.json);;JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return

        # Ensure our preferred extension is present when the user supplies only
        # a bare filename in the save dialog.
        if not path.lower().endswith((".notroyalts.json",".json")):
            path += ".notroyalts.json"

        folders=[]
        for r in db.folders():
            folders.append({
                "id": int(r["id"]),
                "name": r["name"],
                "parent_id": int(r["parent_id"]) if r["parent_id"] is not None else None,
                "sort_order": int(r["sort_order"] or 0),
            })

        connections=[]
        for r in db.conns():
            connections.append({
                "id": int(r["id"]),
                "name": r["name"],
                "folder_id": int(r["folder_id"]) if r["folder_id"] is not None else None,
                "host": r["host"],
                "port": int(r["port"] or 22),
                "username": r["username"],
                "identity_file": r["identity_file"] or "",
                "proxy_jump": r["proxy_jump"] or "",
                "extra_args": r["extra_args"] or "",
                "notes": r["notes"] or "",
                "sort_order": int(r["sort_order"] or 0),
            })

        payload={
            "format": "NotRoyalTs Backup",
            "format_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "folders": folders,
            "connections": connections,
        }

        try:
            Path(path).write_text(
                json.dumps(payload,indent=2,ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "NotRoyalTs Export",
                f"Could not write the backup:\\n\\n{e}"
            )
            return

        QMessageBox.information(
            self,
            "NotRoyalTs Export Complete",
            (
                f"Backup created successfully.\\n\\n"
                f"Folders: {len(folders)}\\n"
                f"Connections: {len(connections)}\\n\\n"
                f"{path}\\n\\n"
                "SSH private key files are NOT embedded in the backup. "
                "Only their configured paths are exported."
            )
        )

    def importBackup(self):
        path,_=QFileDialog.getOpenFileName(
            self,
            "Import NotRoyalTs Backup",
            str(Path.home()),
            "NotRoyalTs Backup (*.notroyalts.json *.json);;All Files (*)"
        )
        if not path:
            return

        try:
            payload=json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(
                self,
                "NotRoyalTs Import",
                f"Could not read the backup:\\n\\n{e}"
            )
            return

        if (
            not isinstance(payload,dict)
            or payload.get("format")!="NotRoyalTs Backup"
            or int(payload.get("format_version",0))!=1
        ):
            QMessageBox.warning(
                self,
                "NotRoyalTs Import",
                "This file is not a supported NotRoyalTs backup."
            )
            return

        folders=payload.get("folders") or []
        connections=payload.get("connections") or []

        reply=QMessageBox.question(
            self,
            "Import NotRoyalTs Backup",
            (
                f"Backup file:\\n{Path(path).name}\\n\\n"
                f"Folders: {len(folders)}\\n"
                f"Connections: {len(connections)}\\n\\n"
                "Existing matching folders will be reused.\\n"
                "Existing matching connections will be skipped.\\n\\n"
                "Import this backup?"
            ),
            QMessageBox.Yes|QMessageBox.No
        )
        if reply!=QMessageBox.Yes:
            return

        try:
            old_to_new={}
            pending=list(folders)
            folders_created=0
            folders_reused=0

            # Parent-first import. If the export contains IDs in any order,
            # children wait until their parent has been mapped.
            while pending:
                progressed=False
                remain=[]

                for f in pending:
                    old_id=int(f["id"])
                    old_parent=f.get("parent_id")

                    if old_parent is not None and int(old_parent) not in old_to_new:
                        remain.append(f)
                        continue

                    parent_id=old_to_new.get(int(old_parent)) if old_parent is not None else None
                    name=str(f.get("name") or "").strip()
                    if not name:
                        progressed=True
                        continue

                    existing=db.find_folder(name,parent_id)
                    if existing:
                        new_id=int(existing["id"])
                        folders_reused+=1
                    else:
                        new_id=db.import_folder(
                            name,
                            parent_id,
                            int(f.get("sort_order") or 0)
                        )
                        folders_created+=1

                    old_to_new[old_id]=new_id
                    progressed=True

                if not progressed and remain:
                    raise ValueError("Backup contains an invalid or circular folder hierarchy.")

                pending=remain

            connections_created=0
            connections_skipped=0

            for c in connections:

                old_folder=c.get("folder_id")
                folder_id=old_to_new.get(int(old_folder)) if old_folder is not None else None

                name=str(c.get("name") or "").strip()
                host=str(c.get("host") or "").strip()
                username=str(c.get("username") or "").strip()
                port=int(c.get("port") or 22)

                if not name or not host or not username:
                    # Do not manufacture required connection fields.
                    continue

                if db.connection_exists(folder_id,name,host,port):
                    connections_skipped+=1
                    continue

                db.save_conn({
                    "name": name,
                    "folder_id": folder_id,
                    "host": host,
                    "port": port,
                    "username": username,
                    "identity_file": c.get("identity_file") or "",
                    "proxy_jump": c.get("proxy_jump") or "",
                    "extra_args": c.get("extra_args") or "",
                    "notes": c.get("notes") or "",
                })
                connections_created+=1

        except Exception as e:
            QMessageBox.critical(
                self,
                "NotRoyalTs Import",
                f"Import failed:\\n\\n{e}"
            )
            return

        self.reload()

        QMessageBox.information(
            self,
            "NotRoyalTs Import Complete",
            (
                f"Folders created: {folders_created}\\n"
                f"Folders reused: {folders_reused}\\n"
                f"Connections imported: {connections_created}\\n"
                f"Existing connections skipped: {connections_skipped}\\n\\n"
                "SSH key files themselves are not part of the backup; "
                "their configured paths were restored."
            )
        )

    def importRoyalTS(self):
        path,_=QFileDialog.getOpenFileName(
            self,
            "Import Royal TS Document",
            str(Path.home()),
            "Royal TS Documents (*.rtsz *.xml);;All Files (*)"
        )
        if not path:
            return

        try:
            root=ET.parse(path).getroot()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Royal TS Import",
                f"Could not parse the Royal TS document:\n\n{e}"
            )
            return

        folders=[e for e in root if e.tag=="RoyalFolder"]
        ssh_entries=[
            e for e in root
            if e.tag=="RoyalSSHConnection"
            and self.xmltext(e,"ConnectionType") in ("","ssh;SSH")
            and self.xmltext(e,"URI")
        ]
        ignored=sum(
            1 for e in root
            if e.tag=="RoyalSSHConnection"
            and (
                self.xmltext(e,"ConnectionType") not in ("","ssh;SSH")
                or not self.xmltext(e,"URI")
            )
        )

        missing_users=sum(
            1 for e in ssh_entries
            if not self.xmltext(e,"CredentialUsername")
        )

        default_user=""
        if missing_users:
            default_user,ok=QInputDialog.getText(
                self,
                "Royal TS Import",
                (
                    f"{missing_users} SSH connection(s) do not contain a username "
                    "inside this Royal TS document.\n\n"
                    "Enter the default username for those connections.\n"
                    "You can edit individual connections after import:"
                ),
                QLineEdit.Normal,
                "root"
            )
            if not ok:
                return
            default_user=default_user.strip()
            if not default_user:
                QMessageBox.warning(
                    self,
                    "Royal TS Import",
                    "A username is required for NotRoyalTs connections."
                )
                return

        reply=QMessageBox.question(
            self,
            "Import Royal TS Document",
            (
                f"Royal TS document:\n{Path(path).name}\n\n"
                f"Folders found: {len(folders)}\n"
                f"SSH connections found: {len(ssh_entries)}\n"
                f"Connections needing the default username: {missing_users}\n"
                f"Non-SSH/unsupported entries that will be ignored: {ignored}\n\n"
                "Existing matching folders will be reused.\n"
                "Existing matching connections will be skipped.\n"
                "Royal TS password fields will NOT be imported.\n\n"
                "Start import?"
            ),
            QMessageBox.Yes|QMessageBox.No
        )
        if reply!=QMessageBox.Yes:
            return

        try:
            result=self.performRoyalTSImport(root,default_user)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Royal TS Import",
                f"Import failed:\n\n{e}"
            )
            return

        self.reload()

        QMessageBox.information(
            self,
            "Royal TS Import Complete",
            (
                f"Folders created: {result['folders_created']}\n"
                f"Folders reused: {result['folders_reused']}\n"
                f"SSH connections imported: {result['connections_created']}\n"
                f"Existing connections skipped: {result['connections_skipped']}\n"
                f"Unsupported entries ignored: {result['ignored']}\n"
                f"Connections given default username: {result['defaulted_users']}\n\n"
                "Passwords were not imported."
            )
        )

    def xmltext(self,element,tag,default=""):
        child=element.find(tag)
        if child is None or child.text is None:
            return default
        return child.text.strip()

    def normalizeRoyalPath(self,path):
        if not path:
            return ""
        home=str(Path.home())
        if path.startswith(home+"/"):
            return "~/" + path[len(home)+1:]
        return path

    def performRoyalTSImport(self,root,default_user):
        royal_folders=[e for e in root if e.tag=="RoyalFolder"]
        idmap={}
        folders_created=0
        folders_reused=0

        royal_document_ids={
            self.xmltext(e,"ID")
            for e in root if e.tag=="RoyalDocument"
        }

        pending=list(royal_folders)
        for _ in range(len(pending)+5):
            if not pending:
                break

            progressed=False
            for e in pending[:]:
                rid=self.xmltext(e,"ID")
                name=self.xmltext(e,"Name")
                parent_rid=self.xmltext(e,"ParentID")
                try:
                    sort_order=int(self.xmltext(e,"PositionNr","0") or 0)
                except ValueError:
                    sort_order=0

                if not rid or not name:
                    pending.remove(e)
                    progressed=True
                    continue

                if not parent_rid or parent_rid in royal_document_ids:
                    parent_id=None
                elif parent_rid in idmap:
                    parent_id=idmap[parent_rid]
                else:
                    continue

                existing=db.find_folder(name,parent_id)
                if existing:
                    sshdesk_id=existing["id"]
                    db.update_folder_sort(sshdesk_id,sort_order)
                    folders_reused+=1
                else:
                    sshdesk_id=db.import_folder(name,parent_id,sort_order)
                    folders_created+=1

                idmap[rid]=sshdesk_id

                if self.xmltext(e,"IsExpanded").lower()=="true":
                    self.expanded_folders.add(int(sshdesk_id))

                pending.remove(e)
                progressed=True

            if not progressed:
                break

        connections_created=0
        connections_skipped=0
        defaulted_users=0
        ignored=0

        for e in root:
            if e.tag!="RoyalSSHConnection":
                continue

            connection_type=self.xmltext(e,"ConnectionType")
            host=self.xmltext(e,"URI")

            if connection_type not in ("","ssh;SSH") or not host:
                ignored+=1
                continue

            name=self.xmltext(e,"Name") or host
            folder_id=idmap.get(self.xmltext(e,"ParentID"))

            try:
                port=int(self.xmltext(e,"Port","22") or 22)
            except ValueError:
                port=22

            user=self.xmltext(e,"CredentialUsername")
            used_default=False
            if not user:
                user=default_user
                used_default=True

            key=(
                self.xmltext(e,"PrivateKeyPath")
                or self.xmltext(e,"CredentialKeyFile")
            )
            key=self.normalizeRoyalPath(key)

            if db.connection_exists(folder_id,name,host,port):
                connections_skipped+=1
                continue

            notes=self.xmltext(e,"Description")
            if used_default:
                defaulted_users+=1
                imported_note=f"Imported from Royal TS; username defaulted to {user}."
                notes=(notes+"\n\n"+imported_note).strip()

            data={
                "name":name,
                "folder_id":folder_id,
                "host":host,
                "port":port,
                "username":user,
                "identity_file":key,
                "proxy_jump":"",
                "extra_args":"",
                "notes":notes,
            }
            db.save_conn(data)
            connections_created+=1

        self.saveExpandedFolders()

        return {
            "folders_created":folders_created,
            "folders_reused":folders_reused,
            "connections_created":connections_created,
            "connections_skipped":connections_skipped,
            "defaulted_users":defaulted_users,
            "ignored":ignored,
        }

    def folderlabels(self):
        F={r["id"]:r for r in db.folders()}

        def path(i):
            a=[]
            seen=set()
            while i and i not in seen:
                seen.add(i)
                r=F.get(i)
                if not r:
                    break
                a.append(r["name"])
                i=r["parent_id"]
            return " / ".join(reversed(a))

        return [(i,path(i)) for i in F]

    def saveExpandedFolders(self):
        self.settings.setValue(
            "expanded_folders",
            [str(i) for i in sorted(self.expanded_folders)]
        )

    def folder_expanded(self,item):
        if item.data(0,KIND)=="f":
            folder_id=item.data(0,ID)
            if folder_id is not None:
                self.expanded_folders.add(int(folder_id))
                self.saveExpandedFolders()

    def folder_collapsed(self,item):
        if item.data(0,KIND)=="f":
            folder_id=item.data(0,ID)
            if folder_id is not None:
                self.expanded_folders.discard(int(folder_id))
                self.saveExpandedFolders()

    def reload(self):
        q=self.search.text().strip()

        # Preserve the selected connection/folder while rebuilding the tree.
        selected_kind,selected_id=self.selected()
        self.tree.blockSignals(True)
        self.tree.clear()

        if q:
            for r in db.conns(q):
                it=QTreeWidgetItem([r["name"]])
                it.setData(0,KIND,"c")
                it.setData(0,ID,r["id"])
                it.setToolTip(0,f'{r["username"]}@{r["host"]}:{r["port"]}')
                self.tree.addTopLevelItem(it)
                if selected_kind=="c" and selected_id==r["id"]:
                    self.tree.setCurrentItem(it)
            self.tree.blockSignals(False)
            return

        items={}
        folder_rows=list(db.folders())
        children={}
        roots=[]

        for r in folder_rows:
            parent_id=r["parent_id"]
            if parent_id is None:
                roots.append(r)
            else:
                children.setdefault(parent_id,[]).append(r)

        def sort_rows(rows):
            return sorted(
                rows,
                key=lambda r: (r["name"] or "").lower()
            )

        def add_folder_row(r,parent_item=None):
            it=QTreeWidgetItem([r["name"]])
            it.setData(0,KIND,"f")
            it.setData(0,ID,r["id"])

            if parent_item is None:
                self.tree.addTopLevelItem(it)
            else:
                parent_item.addChild(it)

            items[r["id"]]=it

            for child in sort_rows(children.get(r["id"],[])):
                add_folder_row(child,it)

        for r in sort_rows(roots):
            add_folder_row(r)

        for r in db.conns():

            it=QTreeWidgetItem([r["name"]])
            it.setData(0,KIND,"c")
            it.setData(0,ID,r["id"])
            it.setToolTip(0,f'{r["username"]}@{r["host"]}:{r["port"]}')
            p=items.get(r["folder_id"])
            if p:
                p.addChild(it)
            else:
                self.tree.addTopLevelItem(it)
            if selected_kind=="c" and selected_id==r["id"]:
                self.tree.setCurrentItem(it)

        # Restore each folder's previous expanded/collapsed state.
        for folder_id,item in items.items():
            item.setExpanded(folder_id in self.expanded_folders)
            if selected_kind=="f" and selected_id==folder_id:
                self.tree.setCurrentItem(item)

        self.tree.blockSignals(False)

    def selected(self):
        i=self.tree.currentItem()
        return (None,None) if not i else (i.data(0,KIND),i.data(0,ID))

    def openConnection(self,connection_id):
        r=db.conn(connection_id)
        if not r:
            return
        t=Term(sshargs(r),connection_id=connection_id)
        t.sessionEnded.connect(lambda term=t:self.closeTerm(term))
        n=self.tabs.addTab(t,r["name"])
        self.tabs.setCurrentIndex(n)
        t.setFocus()

    def connect(self):
        k,i=self.selected()
        if k=="c":
            self.openConnection(i)

    def activateCurrentTab(self,index):
        """Restore terminal focus and the software cursor after tab changes.

        Qt can select another tab after closing a session without delivering a
        fresh focus-in event to the terminal widget. Input still works in that
        state, but our software-rendered blinking cursor can remain hidden.
        """
        if index < 0:
            return

        w=self.tabs.widget(index)
        if not isinstance(w,Term):
            return

        def restore():
            if self.tabs.currentWidget() is not w:
                return
            w.setFocus()
            w.cursor_on=True
            w.draw_cursor()

        # Run after QTabWidget finishes its own close/switch bookkeeping.
        QTimer.singleShot(0,restore)

    def activeTerm(self):
        w=self.tabs.currentWidget()
        return w if isinstance(w,Term) else None

    def reconnectCurrent(self):
        term=self.activeTerm()
        if not term or term.connection_id is None:
            return
        connection_id=term.connection_id
        idx=self.tabs.currentIndex()
        self.closeTab(idx)
        self.openConnection(connection_id)

    def duplicateCurrentSession(self):
        term=self.activeTerm()
        if term and term.connection_id is not None:
            self.openConnection(term.connection_id)

    def goToTab(self,index):
        if 0<=index<self.tabs.count():
            self.tabs.setCurrentIndex(index)
            w=self.tabs.widget(index)
            if w:
                w.setFocus()

    def closeCurrentTab(self):
        i=self.tabs.currentIndex()
        if i>=0:
            self.closeTab(i)

    def closeTerm(self,term):
        i=self.tabs.indexOf(term)
        if i>=0:
            self.closeTab(i)

    def closeTab(self,i):
        w=self.tabs.widget(i)
        if hasattr(w,"stop"):
            w.stop()
        self.tabs.removeTab(i)
        w.deleteLater()

        if self.tabs.count():
            QTimer.singleShot(
                0,
                lambda:self.activateCurrentTab(self.tabs.currentIndex())
            )

    def tabMenu(self,pos):
        index=self.tabs.tabBar().tabAt(pos)
        if index<0:
            return

        self.tabs.setCurrentIndex(index)
        menu=QMenu(self)

        a=menu.addAction("Reconnect")
        a.triggered.connect(self.reconnectCurrent)

        a=menu.addAction("Duplicate Session")
        a.triggered.connect(self.duplicateCurrentSession)

        menu.addSeparator()

        a=menu.addAction("Close")
        a.triggered.connect(self.closeCurrentTab)

        menu.exec(self.tabs.tabBar().mapToGlobal(pos))

    def newFolder(self):
        p=None
        k,i=self.selected()
        if k=="f":
            p=i
        n,ok=QInputDialog.getText(self,"New Folder","Folder name:")
        if ok and n.strip():
            db.add_folder(n.strip(),p)
            if p is not None:
                self.expanded_folders.add(int(p))
                self.saveExpandedFolders()
            self.reload()

    def newConn(self):
        d=ConnDialog(self,self.folderlabels())
        if d.exec():
            data=d.data()
            if not data["name"].strip() or not data["host"].strip() or not data["username"].strip():
                QMessageBox.warning(self,"Missing fields","Name, host and username are required.")
                return
            db.save_conn(data)
            self.reload()

    def duplicateConnection(self):
        k,i=self.selected()
        if k!="c":
            return
        row=db.conn(i)
        if not row:
            return

        data={
            "name":f'{row["name"]} Copy',
            "folder_id":row["folder_id"],
            "host":row["host"],
            "port":row["port"],
            "username":row["username"],
            "identity_file":row["identity_file"] or "",
            "proxy_jump":row["proxy_jump"] or "",
            "extra_args":row["extra_args"] or "",
            "notes":row["notes"] or "",
        }

        d=ConnDialog(self,self.folderlabels())
        d.name.setText(data["name"])
        d.host.setText(data["host"])
        d.port.setValue(int(data["port"] or 22))
        d.user.setText(data["username"])
        d.key.setText(data["identity_file"])
        d.jump.setText(data["proxy_jump"])
        d.extra.setText(data["extra_args"])
        d.notes.setPlainText(data["notes"])
        idx=d.folder.findData(data["folder_id"])
        if idx>=0:
            d.folder.setCurrentIndex(idx)

        if d.exec():
            db.save_conn(d.data())
            self.reload()

    def edit(self):
        k,i=self.selected()
        if k=="f":
            old=next((r["name"] for r in db.folders() if r["id"]==i),"")
            n,ok=QInputDialog.getText(self,"Rename","Folder name:",text=old)
            if ok and n.strip():
                db.rename_folder(i,n.strip())
                self.reload()
        elif k=="c":
            d=ConnDialog(self,self.folderlabels(),db.conn(i))
            if d.exec():
                db.save_conn(d.data(),i)
                self.reload()

    def delete(self):
        k,i=self.selected()
        if not k:
            return
        if QMessageBox.question(
            self,"Delete","Delete selected item?",
            QMessageBox.Yes|QMessageBox.No
        )==QMessageBox.Yes:
            if k=="c":
                db.del_conn(i)
            else:
                db.del_folder(i)
                self.expanded_folders.discard(int(i))
                self.saveExpandedFolders()
            self.reload()

    def menu(self,pos):
        item=self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)

        m=QMenu(self)
        k,i=self.selected()

        if k=="c":
            a=m.addAction("Connect")
            a.triggered.connect(self.connect)

            a=m.addAction("Duplicate Connection")
            a.triggered.connect(self.duplicateConnection)

            m.addSeparator()

        if k:
            a=m.addAction("Edit")
            a.triggered.connect(self.edit)

            a=m.addAction("Delete")
            a.triggered.connect(self.delete)

        if k=="f":
            m.addSeparator()
            a=m.addAction("New Subfolder")
            a.triggered.connect(self.newFolder)

            a=m.addAction("New Connection")
            a.triggered.connect(self.newConn)

        if not k:
            a=m.addAction("New Folder")
            a.triggered.connect(self.newFolder)

            a=m.addAction("New Connection")
            a.triggered.connect(self.newConn)

        m.exec(self.tree.viewport().mapToGlobal(pos))

    def closeEvent(self,e):
        self.saveExpandedFolders()
        for i in range(self.tabs.count()):
            w=self.tabs.widget(i)
            if hasattr(w,"stop"):
                w.stop()
        e.accept()

def main():
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    if app_lock_enabled():
        try:
            configured=app_lock.is_configured()
        except app_lock.KeychainError as exc:
            QMessageBox.critical(
                None,
                "NotRoyalTs App Lock",
                str(exc),
            )
            return 1

        if not configured:
            QMessageBox.critical(
                None,
                "NotRoyalTs App Lock",
                (
                    "App Lock is enabled, but its macOS Keychain verifier "
                    "could not be found. NotRoyalTs will remain locked."
                ),
            )
            return 1

        unlock=UnlockDialog(None)
        if unlock.exec()!=QDialog.Accepted:
            return 0

    # Do not initialize or display the connection database until App Lock has
    # been satisfied.
    db.init()

    w=Win()
    w.show()
    return app.exec()


if __name__=="__main__":
    sys.exit(main())
