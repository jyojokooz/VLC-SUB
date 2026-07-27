import os
import sys

# Ensure VLC DLLs can be found before importing anything that imports vlc
vlc_dir = os.path.join(os.getcwd(), 'vlc_64')
if os.path.exists(vlc_dir):
    os.environ['PYTHON_VLC_MODULE_PATH'] = vlc_dir
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(vlc_dir)

import vlc
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt

from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Signal

class DropOverlay(QLabel):
    file_dropped = Signal(str)
    clicked = Signal()
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.reset_style()
        
    def reset_style(self):
        self.setStyleSheet("""
            QLabel {
                border: 3px dashed #666;
                border-radius: 15px;
                color: #888;
                font-size: 18px;
                font-weight: bold;
                background-color: rgba(20, 20, 20, 200);
            }
            QLabel:hover {
                border-color: #ff9900;
                color: #ff9900;
                background-color: rgba(40, 40, 40, 220);
            }
        """)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QLabel {
                    border: 3px dashed #ff9900;
                    border-radius: 15px;
                    color: #ff9900;
                    font-size: 18px;
                    font-weight: bold;
                    background-color: rgba(40, 40, 40, 220);
                }
            """)
            
    def dragLeaveEvent(self, event):
        self.reset_style()
            
    def dropEvent(self, event):
        self.reset_style()
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith(('.mp4', '.mkv', '.avi', '.ts', '.mov')):
                self.file_dropped.emit(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

class VLCPlayerWidget(QWidget):
    file_dropped = Signal(str)
    overlay_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_frame = QWidget(self)
        self.video_frame.setStyleSheet("background-color: black;")
        
        vf_layout = QVBoxLayout(self.video_frame)
        vf_layout.setContentsMargins(50, 50, 50, 50)
        
        self.overlay = DropOverlay("📁 Click to add video or drag video here to load", self.video_frame)
        self.overlay.file_dropped.connect(self.file_dropped.emit)
        self.overlay.clicked.connect(self.overlay_clicked.emit)
        vf_layout.addWidget(self.overlay)
        
        self.layout.addWidget(self.video_frame)
        
        # Determine VLC paths based on vlc_64 in current dir or system
        vlc_plugin_path = os.path.join(os.getcwd(), 'vlc_64', 'plugins')
        if os.path.exists(vlc_plugin_path):
            os.environ['VLC_PLUGIN_PATH'] = vlc_plugin_path
            
        args = [
            "--no-xlib",
            "--quiet",
            "--ignore-config",
        ]
        
        self.instance = vlc.Instance(args)
        self.media_player = self.instance.media_player_new()
        
        # Platform specific window handle binding
        if sys.platform.startswith('linux'): # for Linux using the X Server
            self.media_player.set_xwindow(self.video_frame.winId())
        elif sys.platform == "win32": # for Windows
            self.media_player.set_hwnd(self.video_frame.winId())
        elif sys.platform == "darwin": # for MacOS
            try:
                self.media_player.set_nsobject(int(self.video_frame.winId()))
            except:
                self.media_player.set_nsobject(self.video_frame.winId())

    def play(self, video_path):
        self.overlay.hide()
        media = self.instance.media_new(video_path)
        self.media_player.set_media(media)
        self.media_player.play()

    def set_subtitle(self, srt_path, force=False):
        if srt_path and os.path.exists(srt_path):
            file_url = "file:///" + srt_path.replace('\\', '/')
            self.media_player.video_set_spu(-1)  # Disable embedded subtitles
            self.media_player.add_slave(vlc.MediaSlaveType.subtitle, file_url, True)

    def pause(self):
        self.media_player.pause()

    def stop(self):
        self.media_player.stop()

    def get_time(self):
        return self.media_player.get_time() # in ms

    def set_time(self, time_ms):
        self.media_player.set_time(time_ms)
        
    def get_length(self):
        return self.media_player.get_length() # in ms
