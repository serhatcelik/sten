"""Sten — LSB-based image steganography tool.

Copyright (C) 2023  Serhat Çelik

Sten is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Sten is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Sten.  If not, see <https://www.gnu.org/licenses/>.
"""

import ctypes
import dataclasses
import logging
import math
import os
import random
import sys
import tkinter as tk
import warnings
import webbrowser
from contextlib import suppress
from idlelib.tooltip import Hovertip  # type: ignore
from itertools import compress, product
from tkinter.filedialog import askopenfilename, asksaveasfilename
from tkinter.font import Font
from tkinter.messagebox import (
    askokcancel,
    askretrycancel,
    showerror,
    showinfo,
    showwarning,
)
from tkinter.scrolledtext import ScrolledText
from tkinter.ttk import Combobox
from typing import NoReturn
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

import numpy as np
from PIL import Image, UnidentifiedImageError
from numpy.typing import NDArray

import crypto
from __version__ import __version__
from consts import *
from db import Db
from error import CryptoErrorGroup
from icons import *
from utils import nonascii, splitext

# Turn matching warnings into exceptions
warnings.simplefilter('error', Image.DecompressionBombWarning)


@dataclasses.dataclass
class Globals:
    """Global "control" variables for the internal module."""

    band_lsb: tuple[tuple[int, int], ...]
    ch_limit: int
    is_bound: bool = False


@dataclasses.dataclass
class Picture:
    """Image properties of a previously opened picture file."""

    pixel: int
    imagedata: NDArray
    dimensions: tuple[int, int]
    mode: str

    filename: str
    extension: str

    properties: tuple[str, ...]


def open_file(event: tk.Event) -> str | None:
    """Open a picture file."""
    bg_old = button_open['bg']  # Backup
    button_open['bg'] = WHITE

    retry = True
    while retry:
        file = askopenfilename(
            filetypes=[('Picture Files', EXTENSIONS_PICTURE)],
            initialdir='~',
            title='Open File',
        )
        if not file:
            break

        filename, extension = splitext(file)

        if extension.casefold() not in EXTENSIONS_PICTURE:
            retry = askretrycancel(
                title='Open File',
                message=f'Not a valid extension: {extension}',
                detail=f'Valid extensions: {EXTENSIONS_PICTURE_PRETTY}',
            )
            continue

        try:
            with Image.open(file) as pic:
                pixel = math.prod(pic.size)
                imagedata = list(pic.getdata())
                dimensions = pic.size
                mode = pic.mode
        except (
                OSError,
                UnidentifiedImageError,
                Image.DecompressionBombError, Image.DecompressionBombWarning,
        ) as err:
            retry = askretrycancel(title='Open File', message=str(err))
            continue

        if mode not in MODES_PICTURE:
            retry = askretrycancel(
                title='Open File',
                message=f'Mode not supported: {mode}',
                detail=f'Supported modes: {MODES_PICTURE_PRETTY}',
            )
            continue

        if pixel < MIN_PIXEL:
            retry = askretrycancel(
                title='Open File',
                message=f'Need minimum {MIN_PIXEL} pixels.',
                detail=f'Provided: {pixel} pixels',
            )
            continue

        # Important! After all error checks are passed, set attributes here!
        Picture.pixel = pixel
        Picture.imagedata = np.array(imagedata)
        Picture.dimensions = (width, height) = dimensions
        Picture.mode = mode

        Picture.filename = os.path.basename(filename)
        Picture.extension = extension

        ch_capacity = (Picture.pixel * len(band_scale)) - len(DELIMITER)

        Picture.properties = (
            f'Capacity: {ch_capacity} characters',
            f'Width: {width} pixels',
            f'Height: {height} pixels',
            f'Bit depth: {B * len(Picture.mode)} ({Picture.mode})',
            f'Size: {os.stat(file).st_size} bytes',
        )

        VARIABLE_OPENED.set(file)
        VARIABLE_OUTPUT.set('')

        root.wm_title(root.wm_title().rstrip('*') + '*')

        button_show['state'] = tk.DISABLED

        button_open['bg'] = CYAN
        return None

    button_open['bg'] = bg_old  # Restore
    return 'break'  # No more event processing for "VIRTUAL_EVENT_OPEN_FILE"


def open_text(event: tk.Event) -> str | None:
    """Read the contents of a file as text."""
    retry = True
    while retry:
        file = askopenfilename(
            filetypes=[('All Files', EXTENSIONS_ALL)],
            initialdir='~',
            title='Open Text',
        )
        if not file:
            break

        try:
            with open(file, encoding='ascii', errors='ignore') as text:
                text_message.delete('1.0', tk.END)
                text_message.insert('1.0', text.read())
        except OSError as err:
            retry = askretrycancel(title='Open Text', message=str(err))
            continue
        else:
            return None

    return 'break'


def encode(event: tk.Event):
    """Create a stego-object."""
    cipher_name, key = box_ciphers.get(), entry_key.get()

    if (not key) and cipher_name:
        return

    message = text_message.get('1.0', tk.END)[:-1]

    if not message:
        return

    if char := nonascii(message):
        showerror(
            title='Encode',
            message='Message contains a non-ASCII character.',
            detail=f'Character: {char}',
        )
        return

    try:
        cipher = crypto.ciphers[cipher_name](key, message)
    except CryptoErrorGroup as err:
        showerror(title='Encode', message=str(err))
        return

    message = cipher.encrypt()

    # Check the character limit, for Hill cipher :/
    if (cipher.name == crypto.Hill.name) and (len(message) > Globals.ch_limit):
        showerror(
            title='Encode',
            message='Cipher text length exceeds the character limit.',
        )
        return

    if DELIMITER in message:
        if not askokcancel(
                title='Encode',
                message='Some data will be lost!',
                detail='(Message will contain the delimiter)',
                icon='warning',
        ):
            return

    output = asksaveasfilename(
        confirmoverwrite=True,
        defaultextension=Picture.extension,
        filetypes=[('Picture Files', EXTENSIONS_PICTURE)],
        initialfile=f'{Picture.filename}-encoded',
        title='Save As — Encode',
    )
    if not output:
        return

    _, extension = splitext(output)

    if extension.casefold() not in EXTENSIONS_PICTURE:
        showerror(
            title='Save As — Encode',
            message=f'Not a valid extension: {extension}',
            detail=f'Valid extensions: {EXTENSIONS_PICTURE_PRETTY}',
        )
        return

    message += DELIMITER

    image = Picture.imagedata.copy()

    # Characters -> Bits
    bits = ''.join(format(ord(c), f'0{B}b') for c in message)

    bits_length = len(bits)

    pixels = list(range(Picture.pixel))

    if seed := entry_prng.get():
        random.seed(seed)
        random.shuffle(pixels)

    i = 0

    for pix, (band, lsb) in product(pixels, Globals.band_lsb):
        if i >= bits_length:
            break

        val = format(image[pix][band], f'0{B}b')

        pack = val[:B - lsb] + (_ := bits[i:i + lsb]) + val[B - lsb + len(_):]

        # Bits -> File
        image[pix][band] = int(pack, 2)

        i += lsb

    shape = Picture.imagedata.shape[1]
    array = image.reshape((*Picture.dimensions[::-1], shape)).astype(np.uint8)

    try:
        Image.fromarray(array).save(output)
    except OSError as err:
        showerror(title='Save — Encode', message=str(err))
        return

    VARIABLE_OUTPUT.set(output)

    root.wm_title(root.wm_title().rstrip('*'))

    button_show['state'] = tk.NORMAL

    showinfo(title='Encode', message='File is encoded!')


def decode(event: tk.Event):
    """Extract a hidden message from a stego-object."""
    cipher_name, key = box_ciphers.get(), entry_key.get()

    if (not key) and cipher_name:
        return

    try:
        cipher = crypto.ciphers[cipher_name](key)
    except CryptoErrorGroup as err:
        showerror(title='Decode', message=str(err))
        return

    output = asksaveasfilename(
        confirmoverwrite=True,
        filetypes=[('All Files', EXTENSIONS_ALL)],
        initialfile=f'{Picture.filename}-decoded',
        title='Save As — Decode',
    )
    if not output:
        return

    pixels = list(range(Picture.pixel))

    if seed := entry_prng.get():
        random.seed(seed)
        random.shuffle(pixels)

    for band_lsb in al if config['brute'].get() else (Globals.band_lsb,):
        bits, message = '', ''

        for pix, (band, lsb) in product(pixels, band_lsb):
            if message.endswith(DELIMITER):
                break  # No need to go any further

            # File -> Bits
            bits += format(Picture.imagedata[pix][band], f'0{B}b')[-lsb:]

            if len(bits) >= B:
                # Bits -> Characters
                message += chr(int(bits[:B], 2))
                bits = bits[B:]

        if message.endswith(DELIMITER):
            break
    else:
        showwarning(title='Decode', message='No hidden message found.')
        return

    if nonascii(message):
        showerror(
            title='Decode',
            message='Message contains a non-ASCII character.',
            detail='Are you sure this message was created using Sten?',
        )
        return

    message = message.removesuffix(DELIMITER)

    cipher.txt = message
    message = cipher.decrypt()

    try:
        with open(output, 'w', encoding='ascii') as out:
            out.write(message)
    except OSError as err:
        showerror(title='Save As — Decode', message=str(err))
        return

    VARIABLE_OUTPUT.set(output)

    root.wm_title(root.wm_title().rstrip('*'))

    button_show['state'] = tk.NORMAL

    showinfo(title='Decode', message='File is decoded!')


def show():
    """Show a previously encoded/decoded file."""
    try:
        os.startfile(VARIABLE_OUTPUT.get(), operation='open')  # nosec
    except OSError as err:
        showerror(title='Show', message=str(err))


def preferences():
    """Show preferences."""
    toplevel = tk.Toplevel(root)

    toplevel.grab_set()  # Direct all events to this Toplevel

    toplevel.pack_propagate(True)

    toplevel.wm_title('Preferences')

    tk.Checkbutton(
        toplevel,
        anchor=tk.W,
        text='Confirm before exiting the program',
        variable=config['confirm'],
    ).pack_configure(expand=True, fill=tk.BOTH, side=tk.TOP)
    tk.Checkbutton(
        toplevel,
        anchor=tk.W,
        text='Use brute force technique to decode',
        variable=config['brute'],
    ).pack_configure(expand=True, fill=tk.BOTH, side=tk.TOP)
    tk.Checkbutton(
        toplevel,
        anchor=tk.W,
        text='Start the program in full-screen mode',
        variable=config['zoomed'],
    ).pack_configure(expand=True, fill=tk.BOTH, side=tk.TOP)


def properties():
    """Show image properties."""
    showinfo(title='Image Properties', message='\n'.join(Picture.properties))


def close():
    """Destroy the main window."""
    if config['confirm'].get():
        if not askokcancel(
                title='Confirm Exit',
                message='Are you sure you want to exit?',
                detail='(You can change this behaviour in configuration file)',
        ):
            return
    params = [(str(int(var.get())), k) for k, var in config.items()]
    database.update(*params)
    root.destroy()


def trigger(v_event: str):
    """Trigger the given virtual event."""
    root.event_generate(v_event)


def manipulate(v_event: str):
    """Use a manipulation by triggering the given virtual event."""
    widget = root.focus_get()

    if not widget:
        return

    widget.event_generate(v_event)


def popup(event: tk.Event):
    """Show context menu."""
    event.widget.focus_set()

    try:
        menu_edit.tk_popup(event.x_root, event.y_root)
    finally:
        menu_edit.grab_release()


def toggle_show_secrets():
    """Toggle "Show Secrets" state."""
    for entry in ALL_ENTRY_WITH_SECRET:
        entry['show'] = '' if (entry['show'] != '') else ENTRY_SHOW_CHAR


def toggle_always_on_top():
    """Toggle "Always on Top" state."""
    topmost = root.wm_attributes()[root.wm_attributes().index('-topmost') + 1]
    root.wm_attributes('-topmost', 1 - topmost)


def toggle_transparent():
    """Toggle "Transparent" state."""
    alpha = root.wm_attributes()[root.wm_attributes().index('-alpha') + 1]
    root.wm_attributes('-alpha', 1.5 - alpha)


def reset():
    """Reset window."""
    root.wm_state(WIDGET_WM_STATE[config['zoomed'].get()])
    root.wm_geometry(GEOMETRY)


def check_for_updates(current: str):
    """Check for program updates."""
    try:
        with urlopen(URL_LATEST_VERSION, timeout=9.) as answer:  # nosec
            latest = urlparse(answer.url).path.rstrip('/').rpartition('/')[-1]
    except URLError as err:
        showerror(title='Update', message=str(err))
    else:
        if current == latest:
            showinfo(title='Update', message='Up to date!')
            return
        if askokcancel(
                title='Update',
                message='Update available. Download?',
                detail=f'Latest version: {latest}',
                icon='warning',
        ):
            webbrowser.open_new_tab(urljoin(URL_ARCHIVE, f'{latest}.zip'))


def refresh_activate(event: tk.Event):
    """When a file is opened, this method binds widgets to "F5" once."""
    if Globals.is_bound:
        return

    Globals.is_bound = True

    menu_file.entryconfigure(MENU_ITEM_INDEX_OPEN_TEXT, state=tk.NORMAL)
    root.bind(VIRTUAL_EVENT_OPEN_TEXT, open_text)
    root.bind(VIRTUAL_EVENT_OPEN_TEXT, refresh, add='+')

    menu_file.entryconfigure(MENU_ITEM_INDEX_IMAGE_PROPERTIES, state=tk.NORMAL)

    menu.entryconfigure(MENU_INDEX_EDIT, state=tk.NORMAL)
    root.bind(VIRTUAL_EVENT_UNDO, refresh)
    root.bind(VIRTUAL_EVENT_REDO, refresh)
    root.bind(VIRTUAL_EVENT_CUT, refresh)
    root.bind(VIRTUAL_EVENT_PASTE, refresh)

    menu_win.entryconfigure(MENU_ITEM_INDEX_SHOW_SECRETS, state=tk.NORMAL)

    entry_prng['state'] = tk.NORMAL

    box_ciphers['state'] = 'readonly'
    box_ciphers.bind('<<ComboboxSelected>>', refresh)

    entry_key['state'] = tk.NORMAL
    entry_key.bind('<KeyRelease>', refresh)

    text_message['bg'] = WHITE
    text_message['selectbackground'] = HIGHLIGHT
    text_message['state'] = tk.NORMAL
    text_message.bind('<ButtonPress-3>', popup)
    text_message.bind('<KeyRelease>', refresh)

    for scl in band_scale.values():
        scl['state'] = tk.NORMAL
        scl.bind('<ButtonRelease-1>', refresh)  # Left mouse button release
        scl.bind('<ButtonRelease-2>', refresh)  # Middle mouse button release
        scl.bind('<ButtonRelease-3>', refresh)  # Right mouse button release
        scl.bind('<B1-Motion>', refresh)
        scl.bind('<B2-Motion>', refresh)
        scl.bind('<B3-Motion>', refresh)


def refresh(event: tk.Event):
    """The ultimate refresh function, aka F5."""
    widget = event.widget

    cipher_name = box_ciphers.get()

    if widget is not box_ciphers:
        pass
    else:
        entry_key.delete('0', tk.END)
        entry_key['vcmd'] = name_vcmd[cipher_name]  # Update validate command

    message = text_message.get('1.0', tk.END)[:-1]

    key = entry_key.get()

    # Activate/deactivate encode/decode features
    if (not key) and cipher_name:
        root.unbind(VIRTUAL_EVENT_ENCODE)
        root.unbind(VIRTUAL_EVENT_DECODE)
        menu_file.entryconfigure(MENU_ITEM_INDEX_ENCODE, state=tk.DISABLED)
        menu_file.entryconfigure(MENU_ITEM_INDEX_DECODE, state=tk.DISABLED)
        button_encode['state'] = tk.DISABLED
        button_decode['state'] = tk.DISABLED
    else:
        root.bind(VIRTUAL_EVENT_DECODE, decode)
        menu_file.entryconfigure(MENU_ITEM_INDEX_DECODE, state=tk.NORMAL)
        button_decode['state'] = tk.NORMAL
        if message:
            root.bind(VIRTUAL_EVENT_ENCODE, encode)
            menu_file.entryconfigure(MENU_ITEM_INDEX_ENCODE, state=tk.NORMAL)
            button_encode['state'] = tk.NORMAL
        else:
            root.unbind(VIRTUAL_EVENT_ENCODE)
            menu_file.entryconfigure(MENU_ITEM_INDEX_ENCODE, state=tk.DISABLED)
            button_encode['state'] = tk.DISABLED

    band_lsb = {
        band: int(lsb)
        for band, scl in band_scale.items() if (lsb := scl.get()) != 0
    }

    if widget not in band_scale.values():
        pass
    else:
        if len(band_lsb) != 0:
            # n-LSB warning?
            widget['fg'] = RED if (widget.get() > 3) else BLACK
        # Fix n-LSB
        else:
            widget['fg'] = BLACK
            widget.set(1)
            band_lsb = {list(band_scale.values()).index(widget): 1}

    ch_limit = ((Picture.pixel * sum(band_lsb.values())) // B) - len(DELIMITER)

    if len(message) > ch_limit:
        # Delete excess message
        text_message.delete('1.0', tk.END)
        text_message.insert('1.0', message[:ch_limit])

    ch_used = len(text_message.get('1.0', tk.END)[:-1])

    ch_left = ch_limit - ch_used

    region_msg['text'] = f'{ch_used}+{ch_left}={ch_limit}'

    if event.char in ['']:
        pass
    else:
        if (widget is text_message) or (ch_left == 0):
            # Scroll such that the character at "INSERT" index is visible
            text_message.see(text_message.index(tk.INSERT))

    Globals.band_lsb = tuple(band_lsb.items())

    Globals.ch_limit = ch_limit


def exception(*args) -> NoReturn:
    """Report callback exception."""
    logging.critical(args, exc_info=(args[0], args[1], args[2]))
    showerror(title='Fatal Error', message=str(args))
    os._exit(-1)  # This line of code is important!


sys.excepthook = exception

# = DPI AWARENESS =
PROCESS_PER_MONITOR_DPI_AWARE = 2
PROCESS_DPI_AWARENESS = PROCESS_PER_MONITOR_DPI_AWARE

ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_DPI_AWARENESS)

# = /!\ LOGGING /!\ =
with suppress(OSError):
    logging.basicConfig(
        filename=os.path.join(os.path.dirname(__file__), 'sten.log'),
        filemode='a',
        format='\n%(levelname)s %(asctime)s %(message)s\n',
        datefmt='%m/%d/%Y %I:%M %p',
        level=logging.WARNING,
    )

# = TK =
root = tk.Tk()

# = CONFIGURATION =
name = os.path.join(os.path.dirname(__file__), 'sten.db')

defaults = [('confirm', '1'), ('brute', '0'), ('zoomed', '0')]

database = Db(name, 'sten', *defaults)

data = database.fetch()

config = {k: tk.BooleanVar(value=bool(int(v))) for k, v in data}

# = Window Root =
root.report_callback_exception = exception

root.pack_propagate(True)

root.wm_protocol('WM_DELETE_WINDOW', close)

root.wm_iconphoto(True, tk.PhotoImage(data=ICON_DATA_STEN))

ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('taskbar')

root.wm_title(f'Sten {__version__}')

SCREEN_W = root.winfo_screenwidth()
SCREEN_H = root.winfo_screenheight()

WINDOW_W = 1000
WINDOW_H = 550
WINDOW_W = SCREEN_W if (SCREEN_W < WINDOW_W) else WINDOW_W
WINDOW_H = SCREEN_H if (SCREEN_H < WINDOW_H) else WINDOW_H

CENTER_X = (SCREEN_W // 2) - (WINDOW_W // 2)
CENTER_Y = (SCREEN_H // 2) - (WINDOW_H // 2)

root.wm_resizable(width=True, height=True)

WINDOW_W_MIN = WINDOW_W // 2
WINDOW_H_MIN = WINDOW_H

root.wm_minsize(width=WINDOW_W_MIN, height=WINDOW_H_MIN)

GEOMETRY = f'{WINDOW_W}x{WINDOW_H}-{CENTER_X}-{CENTER_Y}'

reset()

font = Font(family='Consolas', size=9, weight='normal')
root.option_add(pattern='*Font', value=font)

# = Menu Root =
menu = tk.Menu(root, tearoff=False)

root.configure(menu=menu)

MENU_INDEX_EDIT = 1

# == Menu File ==
menu_file = tk.Menu(menu, tearoff=False)

menu.add_cascade(label='File', menu=menu_file, state=tk.NORMAL, underline=0)

MENU_ITEM_INDEX_OPEN_TEXT = 1
MENU_ITEM_INDEX_ENCODE = 3
MENU_ITEM_INDEX_DECODE = 4
MENU_ITEM_INDEX_PREFERENCES = 6
MENU_ITEM_INDEX_IMAGE_PROPERTIES = 7

ICON_OPEN_FILE = tk.PhotoImage(data=ICON_DATA_OPEN_FILE)
ICON_ENCODE = tk.PhotoImage(data=ICON_DATA_ENCODE)
ICON_DECODE = tk.PhotoImage(data=ICON_DATA_DECODE)
ICON_PREFERENCES = tk.PhotoImage(data=ICON_DATA_PREFERENCES)

# Stay away from <Control-Key-o> key sequence!
root.event_add(VIRTUAL_EVENT_OPEN_FILE, *SEQUENCE_OPEN_FILE)
root.event_add(VIRTUAL_EVENT_ENCODE, *SEQUENCE_ENCODE)
root.event_add(VIRTUAL_EVENT_DECODE, *SEQUENCE_DECODE)

menu_file.add_command(
    accelerator=SHORTCUT_OPEN_FILE,
    command=lambda: trigger(VIRTUAL_EVENT_OPEN_FILE),
    compound=tk.LEFT,
    image=ICON_OPEN_FILE,
    label='Open File...',
    state=tk.NORMAL,
    underline=3,
)
root.bind(VIRTUAL_EVENT_OPEN_FILE, open_file)
root.bind(VIRTUAL_EVENT_OPEN_FILE, refresh_activate, add='+')
root.bind(VIRTUAL_EVENT_OPEN_FILE, refresh, add='+')
menu_file.add_command(
    command=lambda: trigger(VIRTUAL_EVENT_OPEN_TEXT),
    label='Open Text...',
    state=tk.DISABLED,
    underline=5,
)
menu_file.add_separator()
menu_file.add_command(
    accelerator=SHORTCUT_ENCODE,
    command=lambda: trigger(VIRTUAL_EVENT_ENCODE),
    compound=tk.LEFT,
    image=ICON_ENCODE,
    label='Encode...',
    state=tk.DISABLED,
    underline=0,
)
menu_file.add_command(
    accelerator=SHORTCUT_DECODE,
    command=lambda: trigger(VIRTUAL_EVENT_DECODE),
    compound=tk.LEFT,
    image=ICON_DECODE,
    label='Decode...',
    state=tk.DISABLED,
    underline=0,
)
menu_file.add_separator()
menu_file.add_command(
    command=preferences,
    compound=tk.LEFT,
    image=ICON_PREFERENCES,
    label='Preferences',
    state=tk.NORMAL,
    underline=0,
)
menu_file.add_command(
    command=properties,
    compound=tk.LEFT,
    label='Image Properties',
    state=tk.DISABLED,
    underline=7,
)
menu_file.add_separator()
menu_file.add_command(
    command=close,
    label='Exit',
    state=tk.NORMAL,
    underline=1,
)

# == Menu Edit ==
menu_edit = tk.Menu(menu, tearoff=False)

menu.add_cascade(label='Edit', menu=menu_edit, state=tk.DISABLED, underline=0)

ICON_UNDO = tk.PhotoImage(data=ICON_DATA_UNDO)
ICON_REDO = tk.PhotoImage(data=ICON_DATA_REDO)
ICON_CUT = tk.PhotoImage(data=ICON_DATA_CUT)
ICON_COPY = tk.PhotoImage(data=ICON_DATA_COPY)
ICON_PASTE = tk.PhotoImage(data=ICON_DATA_PASTE)
ICON_SELECT_ALL = tk.PhotoImage(data=ICON_DATA_SELECT_ALL)

# Delete all defaults...
root.event_delete(VIRTUAL_EVENT_UNDO)
root.event_delete(VIRTUAL_EVENT_REDO)
root.event_delete(VIRTUAL_EVENT_CUT)
root.event_delete(VIRTUAL_EVENT_COPY)
root.event_delete(VIRTUAL_EVENT_PASTE)
root.event_delete(VIRTUAL_EVENT_SELECT_ALL)

# ...then add new ones
root.event_add(VIRTUAL_EVENT_UNDO, *SEQUENCE_UNDO)
root.event_add(VIRTUAL_EVENT_REDO, *SEQUENCE_REDO)
root.event_add(VIRTUAL_EVENT_CUT, *SEQUENCE_CUT)
root.event_add(VIRTUAL_EVENT_COPY, *SEQUENCE_COPY)
root.event_add(VIRTUAL_EVENT_PASTE, *SEQUENCE_PASTE)
root.event_add(VIRTUAL_EVENT_SELECT_ALL, *SEQUENCE_SELECT_ALL)

menu_edit.add_command(
    accelerator=SHORTCUT_UNDO,
    command=lambda: manipulate(VIRTUAL_EVENT_UNDO),
    compound=tk.LEFT,
    image=ICON_UNDO,
    label='Undo',
    state=tk.NORMAL,
    underline=0,
)
menu_edit.add_command(
    accelerator=SHORTCUT_REDO,
    command=lambda: manipulate(VIRTUAL_EVENT_REDO),
    compound=tk.LEFT,
    image=ICON_REDO,
    label='Redo',
    state=tk.NORMAL,
    underline=0,
)
menu_edit.add_separator()
menu_edit.add_command(
    accelerator=SHORTCUT_CUT,
    command=lambda: manipulate(VIRTUAL_EVENT_CUT),
    compound=tk.LEFT,
    image=ICON_CUT,
    label='Cut',
    state=tk.NORMAL,
    underline=2,
)
menu_edit.add_command(
    accelerator=SHORTCUT_COPY,
    command=lambda: manipulate(VIRTUAL_EVENT_COPY),
    compound=tk.LEFT,
    image=ICON_COPY,
    label='Copy',
    state=tk.NORMAL,
    underline=0,
)
menu_edit.add_command(
    accelerator=SHORTCUT_PASTE,
    command=lambda: manipulate(VIRTUAL_EVENT_PASTE),
    compound=tk.LEFT,
    image=ICON_PASTE,
    label='Paste',
    state=tk.NORMAL,
    underline=0,
)
menu_edit.add_separator()
menu_edit.add_command(
    accelerator=SHORTCUT_SELECT_ALL,
    command=lambda: manipulate(VIRTUAL_EVENT_SELECT_ALL),
    compound=tk.LEFT,
    image=ICON_SELECT_ALL,
    label='Select All',
    state=tk.NORMAL,
    underline=7,
)

# == Menu Window ==
menu_win = tk.Menu(menu, tearoff=False)

menu.add_cascade(label='Window', menu=menu_win, state=tk.NORMAL, underline=0)

MENU_ITEM_INDEX_SHOW_SECRETS = 0

ICON_RESET = tk.PhotoImage(data=ICON_DATA_RESET)

menu_win.add_checkbutton(
    command=toggle_show_secrets,
    label='Show Secrets',
    state=tk.DISABLED,
    underline=5,
)
menu_win.add_separator()
menu_win.add_checkbutton(
    command=toggle_always_on_top,
    label='Always on Top',
    state=tk.NORMAL,
    underline=0,
)
menu_win.add_checkbutton(
    command=toggle_transparent,
    label='Transparent',
    state=tk.NORMAL,
    underline=0,
)
menu_win.add_separator()
menu_win.add_command(
    command=reset,
    compound=tk.LEFT,
    image=ICON_RESET,
    label='Reset',
    state=tk.NORMAL,
    underline=0,
)

# == Menu Help ==
menu_help = tk.Menu(menu, tearoff=False)

menu.add_cascade(label='Help', menu=menu_help, state=tk.NORMAL, underline=0)

ICON_ABOUT = tk.PhotoImage(data=ICON_DATA_ABOUT)
ICON_WEB_SITE = tk.PhotoImage(data=ICON_DATA_WEB_SITE)

menu_help.add_command(
    command=lambda: webbrowser.open_new_tab(URL),
    compound=tk.LEFT,
    image=ICON_WEB_SITE,
    label='Web Site...',
    state=tk.NORMAL,
    underline=0,
)
menu_help.add_separator()
menu_help.add_command(
    command=lambda: check_for_updates(__version__),
    label='Check for Updates...',
    state=tk.NORMAL,
    underline=10,
)
menu_help.add_command(
    command=lambda: showinfo(title='About Sten', message=__doc__),
    compound=tk.LEFT,
    image=ICON_ABOUT,
    label='About',
    state=tk.NORMAL,
    underline=0,
)

# = Region Root =
region = tk.Frame(
    root,
    bd=0,
    bg=BLACK,
    relief=tk.FLAT,
)
region.grid_propagate(True)
region.grid_rowconfigure(index=0, weight=0)
region.grid_rowconfigure(index=1, weight=0)
region.grid_rowconfigure(index=2, weight=0)
region.grid_rowconfigure(index=3, weight=1)
region.grid_columnconfigure(index=0, weight=0)
region.grid_columnconfigure(index=1, weight=1)
region.pack_configure(expand=True, fill=tk.BOTH, side=tk.TOP)

# = Region Steganography =
region_stego = tk.Frame(
    region,
    bd=2,
    bg=BLACK,
    relief=tk.RIDGE,
)
region_stego.pack_propagate(True)
region_stego.grid_configure(
    row=0, column=0, padx=PADX, pady=PADY, sticky=tk.NSEW
)

# == Button Encode ==
button_encode = tk.Button(
    region_stego,
    activebackground=WHITE,
    anchor=tk.CENTER,
    bd=5,
    bg=WHITE,
    command=lambda: trigger(VIRTUAL_EVENT_ENCODE),
    compound=tk.LEFT,
    fg=BLACK,
    image=ICON_ENCODE,
    relief=tk.FLAT,
    state=tk.DISABLED,
    text='Encode',
)
button_encode.pack_configure(
    expand=True, fill=tk.BOTH, padx=PADX, pady=PADY, side=tk.LEFT
)
Hovertip(
    button_encode,
    text=f'[{SHORTCUT_ENCODE}]\n{encode.__doc__}',
    hover_delay=750,
)

# == Button Decode ==
button_decode = tk.Button(
    region_stego,
    activebackground=WHITE,
    anchor=tk.CENTER,
    bd=5,
    bg=WHITE,
    command=lambda: trigger(VIRTUAL_EVENT_DECODE),
    compound=tk.LEFT,
    fg=BLACK,
    image=ICON_DECODE,
    relief=tk.FLAT,
    state=tk.DISABLED,
    text='Decode',
)
button_decode.pack_configure(
    expand=True, fill=tk.BOTH, padx=PADX, pady=PADY, side=tk.LEFT
)
Hovertip(
    button_decode,
    text=f'[{SHORTCUT_DECODE}]\n{decode.__doc__}',
    hover_delay=750,
)

# = Region Information =
region_info = tk.Frame(
    region,
    bd=2,
    bg=BLACK,
    relief=tk.RIDGE,
)
region_info.grid_propagate(True)
region_info.grid_rowconfigure(index=0, weight=1)
region_info.grid_rowconfigure(index=1, weight=1)
region_info.grid_columnconfigure(index=0, weight=0)
region_info.grid_columnconfigure(index=1, weight=1)
region_info.grid_columnconfigure(index=2, weight=0)
region_info.grid_configure(
    row=0, column=1, padx=PADX, pady=PADY, sticky=tk.NSEW
)

# == Section Opened File ==
tk.Label(
    region_info,
    anchor=tk.CENTER,
    bd=0,
    bg=BLACK,
    fg=WHITE,
    relief=tk.FLAT,
    state=tk.NORMAL,
    text='Opened',
).grid_configure(row=0, column=0, padx=PADX, pady=PADY, sticky=tk.NSEW)
tk.Entry(
    region_info,
    bd=0,
    fg=BLACK,
    readonlybackground=BUTTON,
    relief=tk.FLAT,
    state='readonly',
    textvariable=(VARIABLE_OPENED := tk.StringVar()),
).grid_configure(row=0, column=1, padx=PADX, pady=PADY, sticky=tk.NSEW)
button_open = tk.Button(
    region_info,
    activebackground=WHITE,
    anchor=tk.CENTER,
    bd=5,
    bg=WHITE,
    command=lambda: trigger(VIRTUAL_EVENT_OPEN_FILE),
    fg=BLACK,
    relief=tk.FLAT,
    state=tk.NORMAL,
    text='Open',
)
button_open.grid_configure(
    row=0, column=2, padx=PADX, pady=PADY, sticky=tk.NSEW
)
Hovertip(
    button_open,
    text=f'[{SHORTCUT_OPEN_FILE}]\n{open_file.__doc__}',
    hover_delay=750,
)

# == Section Output File ==
tk.Label(
    region_info,
    anchor=tk.CENTER,
    bd=0,
    bg=BLACK,
    fg=WHITE,
    relief=tk.FLAT,
    state=tk.NORMAL,
    text='Output',
).grid_configure(row=1, column=0, padx=PADX, pady=PADY, sticky=tk.NSEW)
tk.Entry(
    region_info,
    bd=0,
    fg=BLACK,
    readonlybackground=BUTTON,
    relief=tk.FLAT,
    state='readonly',
    textvariable=(VARIABLE_OUTPUT := tk.StringVar()),
).grid_configure(row=1, column=1, padx=PADX, pady=PADY, sticky=tk.NSEW)
button_show = tk.Button(
    region_info,
    activebackground=WHITE,
    anchor=tk.CENTER,
    bd=5,
    bg=WHITE,
    command=show,
    fg=BLACK,
    relief=tk.FLAT,
    state=tk.DISABLED,
    text='Show',
)
button_show.grid_configure(
    row=1, column=2, padx=PADX, pady=PADY, sticky=tk.NSEW
)
Hovertip(
    button_show,
    text=show.__doc__,
    hover_delay=750,
)

# = Region PRNG =
region_prng = tk.LabelFrame(
    region,
    bd=2,
    bg=BLACK,
    fg=WHITE,
    labelanchor=tk.S,
    relief=tk.RIDGE,
    text='PRNG',
)
region_prng.pack_propagate(True)
region_prng.grid_configure(
    row=1, column=0, padx=PADX, pady=PADY, sticky=tk.NSEW
)

# == PRNG Seed ==
entry_prng = tk.Entry(
    region_prng,
    bd=0,
    bg=WHITE,
    disabledbackground=BUTTON,
    fg=BLACK,
    relief=tk.FLAT,
    show=ENTRY_SHOW_CHAR,
    state=tk.DISABLED,
)
entry_prng.bind(VIRTUAL_EVENT_PASTE, lambda e: 'break')  # No paste
entry_prng.pack_configure(
    expand=True, fill=tk.BOTH, ipady=IPADY, padx=PADX, pady=PADY, side=tk.TOP
)
Hovertip(
    entry_prng,
    text='Pseudo-random number generator seed.',
    hover_delay=750,
)

# = Region Cryptography =
region_crypto = tk.LabelFrame(
    region,
    bd=2,
    bg=BLACK,
    fg=WHITE,
    labelanchor=tk.S,
    relief=tk.RIDGE,
    text='Encryption',
)
region_crypto.pack_propagate(True)
region_crypto.grid_configure(
    row=2, column=0, padx=PADX, pady=PADY, sticky=tk.NSEW
)

# == Ciphers ==
box_ciphers = Combobox(
    region_crypto,
    background=WHITE,
    foreground=BLACK,
    state=tk.DISABLED,
    values=list(crypto.ciphers),
)
box_ciphers.current(1)
box_ciphers.pack_configure(
    expand=True, fill=tk.BOTH, ipady=IPADY, padx=PADX, pady=PADY, side=tk.TOP
)
Hovertip(
    box_ciphers,
    text=crypto.__doc__,
    hover_delay=750,
)

# == Cipher Key ==
name_vcmd = {
    name: (root.register(cipher.validate), *cipher.code)
    for name, cipher in crypto.ciphers.items()
}

entry_key = tk.Entry(
    region_crypto,
    bd=0,
    bg=WHITE,
    disabledbackground=BUTTON,
    fg=BLACK,
    relief=tk.FLAT,
    show=ENTRY_SHOW_CHAR,
    state=tk.DISABLED,
    validate='key',
    vcmd=name_vcmd[box_ciphers.get()],
)
entry_key.bind(VIRTUAL_EVENT_PASTE, lambda e: 'break')  # No paste
entry_key.pack_configure(
    expand=True, fill=tk.BOTH, ipady=IPADY, padx=PADX, pady=PADY, side=tk.TOP
)
Hovertip(
    entry_key,
    text='Cipher key.',
    hover_delay=750,
)

# = Region LSB =
region_lsb = tk.LabelFrame(
    region,
    bd=2,
    bg=BLACK,
    fg=WHITE,
    labelanchor=tk.S,
    relief=tk.RIDGE,
    text='n-LSB',
)
region_lsb.pack_propagate(True)
region_lsb.grid_configure(
    row=3, column=0, padx=PADX, pady=PADY, sticky=tk.NSEW
)

# == n-LSB ==
band_scale = {
    0: tk.Scale(region_lsb, fg=BLACK, from_=B, to=0, troughcolor=RED),
    1: tk.Scale(region_lsb, fg=BLACK, from_=B, to=0, troughcolor=GREEN),
    2: tk.Scale(region_lsb, fg=BLACK, from_=B, to=0, troughcolor=BLUE),
}  # Stick with this order!

al = tuple(
    tuple(compress(zip(band_scale, t), t))
    for t in product(range(B + 1), repeat=len(band_scale))
)  # All possibilities

for scale in band_scale.values():
    scale.set(1)
    scale.configure(
        bd=2,
        relief=tk.FLAT,
        sliderlength=50,
        sliderrelief=tk.RAISED,
        state=tk.DISABLED,
    )
    scale.pack_configure(
        expand=True, fill=tk.BOTH, padx=PADX, pady=PADY, side=tk.LEFT
    )

# = Region Message =
region_msg = tk.LabelFrame(
    region,
    bd=2,
    bg=BLACK,
    fg=WHITE,
    labelanchor=tk.SE,
    relief=tk.RIDGE,
    text='0+0=0',
)
region_msg.pack_propagate(True)
region_msg.grid_configure(
    row=1, rowspan=3, column=1, padx=PADX, pady=PADY, sticky=tk.NSEW
)

# == Message ==
text_message = ScrolledText(
    region_msg,
    bd=0,
    bg=BUTTON,
    fg=BLACK,
    relief=tk.FLAT,
    selectbackground=BUTTON,
    state=tk.DISABLED,
    tabs=1,
    undo=True,
    wrap='char',
)
text_message.pack_configure(
    expand=True, fill=tk.BOTH, padx=PADX, pady=PADY, side=tk.TOP
)

# = ALL =
ALL_ENTRY_WITH_SECRET = (
    entry_prng,
    entry_key,
)

if __name__ == '__main__':
    root.mainloop()
