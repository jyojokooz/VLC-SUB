import os
import sys

# Ensure VLC DLLs can be found before importing anything that imports vlc
vlc_dir = os.path.join(os.getcwd(), 'vlc_64')
if os.path.exists(vlc_dir):
    os.environ['PYTHON_VLC_MODULE_PATH'] = vlc_dir
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(vlc_dir)

import threading
import subprocess
import time
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QPushButton, QComboBox, 
                               QLineEdit, QCheckBox, QStackedWidget, QProgressBar,
                               QFileDialog, QMessageBox, QFrame, QScrollArea, QListWidget, QListWidgetItem, QSlider)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QMimeData, QUrl
from PySide6.QtGui import QIcon, QFont, QColor, QDrag

class HistoryListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item: return
        path = item.data(Qt.UserRole)
        if not path or not os.path.exists(path): return
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path)])
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(supportedActions)

import ust_settings as config
from utils import clean_path, format_timestamp, parse_srt, get_available_subtitles, detect_paired_file, generate_ass_content, resource_path, get_ffmpeg_path
from engines import transcribe_audio_chunk, translate_batch, detect_sync_offset, fetch_online_subtitle
from security import save_api_key, load_api_key
from reframing import reframe_video

from ui_video_player import VLCPlayerWidget
from ui_timeline import TimelineWidget
from vlc_integration import apply_subtitle_to_vlc

# A signal emitter for thread-safe UI updates
class WorkerSignals(QObject):
    update_status = Signal(str)
    update_progress = Signal(int, int, str)
    error = Signal(str)
    finished = Signal()
    populate_tabs = Signal(str)
    sync_offset_detected = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Subtitles (.vsub) Generate")
        self.resize(1200, 800)
        self.setStyleSheet("""
            QMainWindow { background-color: #111111; }
            QLabel { color: #ffffff; }
            QPushButton { 
                background-color: #2a2a2a; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #333333; }
            QPushButton.primary { background-color: #ff9900; color: black; }
            QPushButton.primary:hover { background-color: #e68a00; }
            QPushButton.secondary { background-color: #008cba; color: white; }
            QComboBox, QLineEdit { 
                background-color: #222222; color: white; border: 1px solid #333; border-radius: 4px; padding: 4px;
            }
            QFrame.sidebar { background-color: #1a1a1a; }
            QFrame.panel { background-color: #1a1a1a; border-radius: 8px; }
        """)

        self.signals = WorkerSignals()
        self.signals.update_status.connect(self.set_status)
        self.signals.update_progress.connect(self.set_progress)
        self.signals.error.connect(self.show_error)
        self.signals.populate_tabs.connect(self.populate_all_tabs)
        self.signals.sync_offset_detected.connect(self.on_sync_offset_detected)

        self.init_ui()

        # Update timer for timeline
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timeline)
        self.timer.start(100) # 100ms updates

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # LEFT SIDEBAR
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setProperty("class", "sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 20)

        brand_lbl = QLabel("(.vsub) Generate")
        brand_lbl.setStyleSheet("color: #ff9900; font-size: 16px; font-weight: bold;")
        sidebar_layout.addWidget(brand_lbl)
        sidebar_layout.addSpacing(30)

        self.tab_btns = []
        tabs = ["AI Generate", "Translate", "Sync", "Customize", "Reframe", "🌐 Web Search"]
        for i, t in enumerate(tabs):
            btn = QPushButton(t)
            btn.setCheckable(True)
            if i == 0: btn.setChecked(True)
            btn.clicked.connect(lambda checked, idx=i: self.switch_tab(idx))
            btn.setStyleSheet("""
                QPushButton { text-align: left; padding: 10px; background: transparent; color: #aaa; }
                QPushButton:checked { background: #ff9900; color: black; border-radius: 6px; }
            """)
            self.tab_btns.append(btn)
            sidebar_layout.addWidget(btn)
        
        sidebar_layout.addStretch()
        
        status_lbl = QLabel("Status: Ready")
        status_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self.status_bar_lbl = status_lbl
        sidebar_layout.addWidget(status_lbl)

        main_layout.addWidget(sidebar)

        # CENTER CONTENT (Video + Timeline)
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(20, 20, 20, 20)

        # Embedded Video Player
        self.player = VLCPlayerWidget()
        self.player.overlay_clicked.connect(self.browse_video)
        self.player.file_dropped.connect(self.load_dropped_video)
        center_layout.addWidget(self.player, stretch=1)

        # --- NEW: VLC-like Video Progress Slider ---
        video_slider_layout = QHBoxLayout()
        video_slider_layout.setContentsMargins(0, 5, 0, 5)

        self.time_current_lbl = QLabel("00:00")
        self.time_current_lbl.setStyleSheet("color: #aaa; font-size: 11px; min-width: 40px;")
        self.time_current_lbl.setAlignment(Qt.AlignCenter)

        self.video_slider = QSlider(Qt.Horizontal)
        self.video_slider.setRange(0, 1000)
        self.video_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #333;
                height: 6px;
                background: #222;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #ff9900;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #fff;
                border: 1px solid #111;
                width: 12px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 6px;
            }
        """)
        self.is_slider_pressed = False
        self.video_slider.sliderPressed.connect(self.slider_pressed)
        self.video_slider.sliderReleased.connect(self.slider_released)
        self.video_slider.sliderMoved.connect(self.slider_moved)

        self.time_total_lbl = QLabel("00:00")
        self.time_total_lbl.setStyleSheet("color: #aaa; font-size: 11px; min-width: 40px;")
        self.time_total_lbl.setAlignment(Qt.AlignCenter)

        video_slider_layout.addWidget(self.time_current_lbl)
        video_slider_layout.addWidget(self.video_slider, stretch=1)
        video_slider_layout.addWidget(self.time_total_lbl)
        center_layout.addLayout(video_slider_layout)
        # -------------------------------------------

        # Subtitle Timeline (Kept exactly as it was)
        self.timeline = TimelineWidget()
        self.timeline.setFixedHeight(80)
        self.timeline.seek_requested.connect(self.player.set_time)
        self.timeline.subtitle_dropped.connect(self.populate_all_tabs)
        self.timeline.subtitle_clicked.connect(self.browse_standalone_srt)
        self.timeline.subtitle_edited.connect(self.player.set_subtitle)
        center_layout.addWidget(self.timeline)
        
        # Playback & Export Controls
        ctrl_layout = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.clicked.connect(self.player.stop)
        
        self.preview_vlc_btn = QPushButton("📺 Open in External VLC")
        self.preview_vlc_btn.setProperty("class", "secondary")
        self.preview_vlc_btn.clicked.connect(self.preview_external_vlc)
        
        self.export_srt_btn = QPushButton("💾 Export SRT")
        self.export_srt_btn.clicked.connect(self.run_export_srt_dialog)
        
        self.export_ass_btn = QPushButton("💾 Export ASS (Styled)")
        self.export_ass_btn.clicked.connect(self.run_export_ass_dialog)

        ctrl_layout.addWidget(self.play_btn)
        ctrl_layout.addWidget(self.stop_btn)
        # Add Subtitle button
        self.add_sub_btn = QPushButton("📄 Add Subtitle")
        self.add_sub_btn.clicked.connect(self.browse_standalone_srt)
        ctrl_layout.addWidget(self.add_sub_btn)
        ctrl_layout.addWidget(self.preview_vlc_btn)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(QLabel("Download:"))
        ctrl_layout.addWidget(self.export_srt_btn)
        ctrl_layout.addWidget(self.export_ass_btn)
        center_layout.addLayout(ctrl_layout)

        main_layout.addWidget(center_widget, stretch=1)

        # RIGHT PANEL (Contextual Settings)
        right_panel = QFrame()
        right_panel.setFixedWidth(350)
        right_panel.setProperty("class", "panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 20, 20, 20)
        
        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack)

        self.setup_generate_tab()
        self.setup_translate_tab()
        self.setup_sync_tab()
        self.setup_customize_tab()
        self.setup_reframe_tab()
        self.setup_websearch_tab()

        # Shared Progress Bar at bottom of right panel
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: none; background: #333; }
            QProgressBar::chunk { background: #ff9900; }
        """)
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)
        
        self.progress_lbl = QLabel("")
        self.progress_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self.progress_lbl.setVisible(False)
        right_layout.addWidget(self.progress_lbl)

        main_layout.addWidget(right_panel)

    def format_time(self, ms):
        s = int(ms / 1000)
        h = s // 3600
        m = (s % 3600) // 60
        s = s % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def slider_pressed(self):
        self.is_slider_pressed = True

    def slider_released(self):
        self.is_slider_pressed = False
        dur = self.player.get_length()
        if dur > 0:
            pos = self.video_slider.value()
            target_time = int((pos / 1000.0) * dur)
            self.player.set_time(target_time)
            self.timeline.set_current_time(target_time)

    def slider_moved(self, position):
        dur = self.player.get_length()
        if dur > 0:
            ms = int((position / 1000.0) * dur)
            self.time_current_lbl.setText(self.format_time(ms))

    def switch_tab(self, idx):
        for i, btn in enumerate(self.tab_btns):
            btn.setChecked(i == idx)
        self.stack.setCurrentIndex(idx)

    def keyPressEvent(self, event):
        from PySide6.QtWidgets import QLineEdit, QTextEdit
        focus_widget = QApplication.focusWidget()
        if isinstance(focus_widget, (QLineEdit, QTextEdit)):
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key_Space:
            self.toggle_play()
        else:
            super().keyPressEvent(event)

    def setup_generate_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        
        l.addWidget(QLabel("<b>AI Generate Subtitles</b>"))
        l.addWidget(QLabel("Generate accurate subtitles from your videos using lightning fast AI.", wordWrap=True))
        l.addSpacing(15)

        l.addWidget(QLabel("Video File:"))
        self.gen_video_path = QLineEdit()
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_video)
        h = QHBoxLayout()
        h.addWidget(self.gen_video_path)
        h.addWidget(btn_browse)
        l.addLayout(h)

        l.addWidget(QLabel("Provider:"))
        self.gen_provider = QComboBox()
        self.gen_provider.addItems(["Groq (Lightning Fast)", "OpenAI (Standard)"])
        l.addWidget(self.gen_provider)

        l.addWidget(QLabel("API Key:"))
        self.gen_api = QLineEdit()
        self.gen_api.setEchoMode(QLineEdit.Password)
        self.gen_api.setText(load_api_key())
        l.addWidget(self.gen_api)

        l.addWidget(QLabel("Source Language:"))
        self.gen_src_lang = QComboBox()
        self.gen_src_lang.addItems(sorted(config.WHISPER_LANGUAGES.keys()))
        self.gen_src_lang.setCurrentText("Auto Detect (Recommended)")
        l.addWidget(self.gen_src_lang)

        l.addWidget(QLabel("Translate To:"))
        self.gen_target_lang = QComboBox()
        self.gen_target_lang.addItems(sorted(config.LANGUAGES.keys()))
        self.gen_target_lang.setCurrentText("English")
        l.addWidget(self.gen_target_lang)

        self.gen_romanize = QCheckBox("Write in English Letters (e.g. Manglish)")
        l.addWidget(self.gen_romanize)

        l.addSpacing(10)
        l.addWidget(QLabel("<b>Subtitle History:</b> (Double-click or drag to timeline)"))
        self.history_list = HistoryListWidget()
        self.history_list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 5px;
                padding: 5px;
                outline: none;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #2a2a2a;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #ff9900;
                color: black;
            }
        """)
        self.history_list.itemDoubleClicked.connect(self.load_history_item)
        l.addWidget(self.history_list)

        self.gen_btn = QPushButton("⚡ Generate Subtitles")
        self.gen_btn.setProperty("class", "primary")
        self.gen_btn.clicked.connect(self.run_generation)
        l.addWidget(self.gen_btn)

        self.stack.addWidget(w)

    def setup_translate_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        l.addWidget(QLabel("<b>Translate Existing Subtitles</b>"))
        
        l.addWidget(QLabel("SRT File:"))
        self.trans_srt_path = QLineEdit()
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(lambda: self.browse_srt(self.trans_srt_path))
        h = QHBoxLayout()
        h.addWidget(self.trans_srt_path)
        h.addWidget(btn_browse)
        l.addLayout(h)

        l.addWidget(QLabel("Translate To:"))
        self.trans_lang = QComboBox()
        self.trans_lang.addItems(sorted(config.LANGUAGES.keys()))
        self.trans_lang.setCurrentText("Malayalam")
        l.addWidget(self.trans_lang)

        self.trans_romanize = QCheckBox("Write in English Letters")
        l.addWidget(self.trans_romanize)

        l.addStretch()

        self.trans_btn = QPushButton("🌐 Translate & Apply")
        self.trans_btn.setProperty("class", "primary")
        self.trans_btn.clicked.connect(self.run_translation)
        l.addWidget(self.trans_btn)
        
        self.stack.addWidget(w)

    def setup_sync_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        l.addWidget(QLabel("<b>Sync Subtitles</b>"))
        
        l.addWidget(QLabel("SRT File:"))
        self.sync_srt_path = QLineEdit()
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(lambda: self.browse_srt(self.sync_srt_path))
        h = QHBoxLayout()
        h.addWidget(self.sync_srt_path)
        h.addWidget(btn_browse)
        l.addLayout(h)

        self.auto_sync_btn = QPushButton("🔍 Auto Detect Offset")
        self.auto_sync_btn.clicked.connect(self.run_auto_sync)
        l.addWidget(self.auto_sync_btn)

        l.addWidget(QLabel("Shift Seconds (+ delay, - advance):"))
        self.sync_offset = QLineEdit("+0.0")
        l.addWidget(self.sync_offset)

        l.addStretch()

        self.sync_btn = QPushButton("⏱️ Sync & Apply")
        self.sync_btn.setProperty("class", "primary")
        self.sync_btn.clicked.connect(self.run_sync)
        l.addWidget(self.sync_btn)

        self.stack.addWidget(w)

    def setup_customize_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        l.addWidget(QLabel("<b>Customize Style (.ass export)</b>"))
        
        l.addWidget(QLabel("SRT File:"))
        self.cust_srt_path = QLineEdit()
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(lambda: self.browse_srt(self.cust_srt_path))
        h = QHBoxLayout()
        h.addWidget(self.cust_srt_path)
        h.addWidget(btn_browse)
        l.addLayout(h)

        l.addWidget(QLabel("Font:"))
        self.cust_font = QComboBox()
        self.cust_font.addItems(config.COMMON_FONTS)
        l.addWidget(self.cust_font)

        l.addWidget(QLabel("Color (Hex):"))
        self.cust_color = QLineEdit("#FFFFFF")
        l.addWidget(self.cust_color)
        
        l.addWidget(QLabel("Background Box:"))
        self.cust_bg = QCheckBox("Enable Background Box")
        self.cust_bg.setChecked(True)
        l.addWidget(self.cust_bg)

        l.addWidget(QLabel("Position on Screen:"))
        self.cust_position = QComboBox()
        self.cust_position.addItems([
            "Bottom Center", "Bottom Left", "Bottom Right",
            "Top Center", "Top Left", "Top Right",
            "Middle Center"
        ])
        l.addWidget(self.cust_position)

        l.addStretch()

        self.export_btn = QPushButton("🎨 Export ASS & Apply")
        self.export_btn.setProperty("class", "primary")
        self.export_btn.clicked.connect(self.run_export_ass)
        l.addWidget(self.export_btn)
        
        self.stack.addWidget(w)

    def setup_reframe_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        l.addWidget(QLabel("<b>Reframe Video</b>"))
        
        l.addWidget(QLabel("Video File (Set in Gen tab):"))
        
        l.addWidget(QLabel("Ratio:"))
        self.ref_ratio = QComboBox()
        self.ref_ratio.addItems(["16:9", "9:16", "1:1", "4:5"])
        self.ref_ratio.setCurrentText("9:16")
        l.addWidget(self.ref_ratio)
        
        l.addStretch()
        
        self.ref_btn = QPushButton("✂️ Reframe Video")
        self.ref_btn.setProperty("class", "primary")
        self.ref_btn.clicked.connect(self.run_reframe)
        l.addWidget(self.ref_btn)

        self.stack.addWidget(w)

    def setup_websearch_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)

        title = QLabel("<b>⚡ Fast Download Subtitles</b>")
        title.setStyleSheet("font-size: 15px; color: #ff9900;")
        l.addWidget(title)
        l.addWidget(QLabel("Auto-download the best perfectly synced subtitle for your loaded video directly from online databases.", wordWrap=True))
        l.addSpacing(12)

        l.addWidget(QLabel("Language:"))
        self.ws_lang = QComboBox()
        self.ws_lang.addItems(sorted(config.LANGUAGES.keys()))
        self.ws_lang.setCurrentText("English")
        l.addWidget(self.ws_lang)
        
        l.addSpacing(10)

        self.ws_fast_btn = QPushButton("🌐 Fast Online Download")
        self.ws_fast_btn.setProperty("class", "primary")
        self.ws_fast_btn.setMinimumHeight(40)
        self.ws_fast_btn.clicked.connect(self.run_fast_download)
        l.addWidget(self.ws_fast_btn)

        self.ws_status_lbl = QLabel("Load a video first, then click Fast Download.")
        self.ws_status_lbl.setStyleSheet("color: #aaa; font-size: 12px; padding: 10px; background: #222; border-radius: 5px; margin-top: 10px;")
        self.ws_status_lbl.setWordWrap(True)
        l.addWidget(self.ws_status_lbl)

        l.addStretch()

        self.stack.addWidget(w)

    def run_fast_download(self):
        video_path = self.gen_video_path.text().strip()
        target_lang = self.ws_lang.currentText()
        
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self, "No Video", "Please load a video first using the AI Generate tab or drag a video onto the player.")
            return

        self.ws_fast_btn.setEnabled(False)
        self.ws_status_lbl.setText("🔍 Scanning video hash and searching online databases...")

        def _task():
            try:
                from engines import fetch_online_subtitle
                target_code = config.LANGUAGES.get(target_lang, "en")
                
                def status_cb(msg):
                    self.signals.update_status.emit(msg)
                    QTimer.singleShot(0, lambda m=msg: self.ws_status_lbl.setText(m))
                    
                out_path = fetch_online_subtitle(video_path, target_code, status_cb)
                if out_path:
                    QTimer.singleShot(0, lambda: self.ws_status_lbl.setText(f"✅ Downloaded successfully:\n{os.path.basename(out_path)}"))
                    self.signals.populate_tabs.emit(out_path)
                    QTimer.singleShot(0, self.refresh_history_list)
            except Exception as e:
                self.signals.error.emit(str(e))
                QTimer.singleShot(0, lambda err=str(e): self.ws_status_lbl.setText(f"❌ Error: {err}"))
            finally:
                QTimer.singleShot(0, lambda: self.ws_fast_btn.setEnabled(True))

        threading.Thread(target=_task, daemon=True).start()

    # --- UI Helpers ---

    def browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.mkv *.avi *.ts *.mov)")
        if path:
            self.load_dropped_video(path)

    def load_dropped_video(self, path):
        if not path: return
        self.gen_video_path.setText(clean_path(path))
        self.player.play(clean_path(path))
        
        self.refresh_history_list(clean_path(path))
        
        subs = get_available_subtitles(clean_path(path))
        best = detect_paired_file(clean_path(path), "srt")
        if best:
            self.populate_all_tabs(best)
        elif subs:
            self.populate_all_tabs(subs[0])

    def browse_srt(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select Subtitle", "", "Subtitle Files (*.srt *.ass)")
        if path:
            line_edit.setText(clean_path(path))
            self.populate_all_tabs(clean_path(path))
            
    def browse_standalone_srt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Subtitle", "", "Subtitle Files (*.srt *.ass)")
        if path:
            self.populate_all_tabs(clean_path(path))

    def refresh_history_list(self, video_path=None):
        self.history_list.clear()
        if not video_path:
            video_path = self.gen_video_path.text().strip()
        subs = get_available_subtitles(video_path)
        for sub in subs:
            item = QListWidgetItem(os.path.basename(sub))
            item.setData(Qt.UserRole, sub)
            self.history_list.addItem(item)
            
    def load_history_item(self, item):
        sub_path = item.data(Qt.UserRole)
        if sub_path and os.path.exists(sub_path):
            self.populate_all_tabs(sub_path)

    def populate_all_tabs(self, srt_path):
        self.trans_srt_path.setText(srt_path)
        self.sync_srt_path.setText(srt_path)
        self.cust_srt_path.setText(srt_path)
        
        # Load segments into timeline
        try:
            segments = parse_srt(srt_path)
            self.timeline.set_segments(segments)
            self.timeline.srt_path = srt_path  # Track file for saving double-click edits
            # Store the pending subtitle; apply immediately if playing, else on next play
            self._pending_subtitle = srt_path
            if self.player.media_player.is_playing():
                self.player.set_subtitle(srt_path)
        except Exception as e:
            print("Failed to parse SRT for timeline:", e)

    def toggle_play(self):
        if self.player.media_player.is_playing():
            self.player.pause()
            self.play_btn.setText("▶ Play")
        else:
            self.player.media_player.play()
            self.play_btn.setText("⏸ Pause")

    def update_timeline(self):
        t = self.player.get_time()
        if t >= 0:
            dur = self.player.get_length()
            if dur > 0:
                self.timeline.set_duration(dur)
                
                # Update Video Slider if not actively being dragged
                if not getattr(self, 'is_slider_pressed', False):
                    self.video_slider.setValue(int((t / dur) * 1000))
                    self.time_current_lbl.setText(self.format_time(t))
                    self.time_total_lbl.setText(self.format_time(dur))

            self.timeline.set_current_time(t)

            # If playing just started and we have a pending subtitle, apply it
            if self.player.media_player.is_playing():
                pending = getattr(self, '_pending_subtitle', None)
                if pending:
                    self._pending_subtitle = None
                    self.player.set_subtitle(pending, force=True)

            is_playing = self.player.media_player.is_playing()
            self.play_btn.setText("⏸ Pause" if is_playing else "▶ Play")

    def set_status(self, text):
        self.status_bar_lbl.setText(f"Status: {text}")

    def set_progress(self, done, total, label):
        pct = int((done / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_lbl.setText(f"{done}/{total} {label}")
        self.progress_bar.setVisible(True)
        self.progress_lbl.setVisible(True)

    def show_error(self, err):
        QMessageBox.critical(self, "Error", err)

    # --- Worker Methods ---
    def run_generation(self):
        if getattr(self, 'is_generating', False):
            if hasattr(self, 'current_task_token'):
                self.current_task_token["cancelled"] = True
                
            if hasattr(self, 'ffmpeg_proc') and self.ffmpeg_proc:
                try: self.ffmpeg_proc.kill()
                except: pass
                
            # Instantly reset the UI so user doesn't wait for the blocking HTTP request
            self.is_generating = False
            self.pulse_timer.stop()
            self.gen_btn.setStyleSheet("")
            self.gen_btn.setText("⚡ Generate Subtitles")
            self.gen_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.progress_lbl.setVisible(False)
            self.set_status("Generation Cancelled.")
            return

        video_path = self.gen_video_path.text().strip()
        target_lang = self.gen_target_lang.currentText()
        api_key = self.gen_api.text().strip()
        provider = self.gen_provider.currentText()
        romanize = self.gen_romanize.isChecked()
        source_lang_name = self.gen_src_lang.currentText()
        source_lang_code = config.WHISPER_LANGUAGES.get(source_lang_name)

        if not video_path or not os.path.exists(video_path):
            self.show_error("Please select a valid video file!")
            return
        if not api_key:
            self.show_error("Please enter your API Key!")
            return

        save_api_key(api_key)
        
        self.is_generating = True
        token = {"cancelled": False}
        self.current_task_token = token
        
        self.gen_btn.setText("🛑 Cancel Generation")
        self.gen_btn.setStyleSheet("background-color: #d9534f; color: white;")
        
        self.pulse_timer = QTimer(self)
        self.pulse_state = False
        def pulse():
            self.pulse_state = not self.pulse_state
            if self.pulse_state:
                self.gen_btn.setStyleSheet("background-color: #ff3333; color: white;")
            else:
                self.gen_btn.setStyleSheet("background-color: #cc0000; color: white;")
        self.pulse_timer.timeout.connect(pulse)
        self.pulse_timer.start(500)

        def _task():
            success = False
            try:
                if os.path.exists(config.TEMP_DIR):
                    for fn in os.listdir(config.TEMP_DIR):
                        try: os.remove(os.path.join(config.TEMP_DIR, fn))
                        except: pass

                self.signals.update_status.emit("Compressing audio for AI (Wait ~15s)...")
                chunk_pattern = os.path.join(config.TEMP_DIR, "chunk_%03d.m4a")
                cf = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                ffmpeg_path = get_ffmpeg_path()
                segment_time = str(config.AUDIO_SEGMENT_TIME)
                cmd = [ffmpeg_path, "-y", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "64k",
                       "-ar", "16000", "-ac", "1", "-af", "loudnorm", "-f", "segment",
                       "-segment_time", segment_time, chunk_pattern]

                self.ffmpeg_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cf)
                proc_out, proc_err = self.ffmpeg_proc.communicate()
                
                if token["cancelled"]:
                    raise Exception("Generation cancelled by user.")
                if self.ffmpeg_proc.returncode != 0:
                    raise Exception(f"FFmpeg failed. {proc_err.decode('utf-8', errors='ignore')[-400:]}")

                chunks = sorted([f for f in os.listdir(config.TEMP_DIR) if f.endswith('.m4a')])
                if not chunks: raise Exception("No audio chunks extracted.")

                all_segments = []
                for i, chunk in enumerate(chunks):
                    if token["cancelled"]:
                        raise Exception("Generation cancelled by user.")
                        
                    self.signals.update_status.emit(f"☁️ Transcribing Part {i+1}/{len(chunks)}...")
                    self.signals.update_progress.emit(i, len(chunks), "parts")
                    
                    ai_data = transcribe_audio_chunk(
                        os.path.join(config.TEMP_DIR, chunk), provider, api_key, source_lang_code, "https://api.openai.com/v1/audio/transcriptions"
                    )
                    offset = i * config.AUDIO_SEGMENT_TIME
                    for seg in ai_data.get("segments", []):
                        text = seg["text"].strip()
                        if text:
                            all_segments.append({"start": seg["start"] + offset, "end": seg["end"] + offset, "text": text})

                if not all_segments: raise Exception("No speech detected.")

                target_code = config.LANGUAGES.get(target_lang, "en")
                if target_code != "en":
                    if token["cancelled"]: raise Exception("Generation cancelled by user.")
                    self.signals.update_status.emit(f"🌐 Translating {len(all_segments)} lines...")
                    translate_batch(all_segments, target_code, romanize)

                srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                      for i, s in enumerate(all_segments) if s['text'])
                suffix = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
                srt_name = f"{os.path.splitext(os.path.basename(video_path))[0]}{suffix}.srt"
                srt_path = clean_path(os.path.join(config.SUB_DIR, srt_name))

                with open(srt_path, 'w', encoding='utf-8') as f: f.write(srt_content)
                
                self.signals.update_status.emit(f"✅ Done! {len(all_segments)} lines generated.")
                self.signals.update_progress.emit(100, 100, "%")
                self.signals.populate_tabs.emit(srt_path)
                # Refresh history list to show the new subtitle
                QTimer.singleShot(0, self.refresh_history_list)
                success = True
            except Exception as e:
                if str(e) == "Generation cancelled by user.":
                    pass # Handled by the main thread UI reset
                else:
                    self.signals.error.emit(str(e))
                    self.signals.update_status.emit("Error.")
            finally:
                if not token["cancelled"]:
                    self.is_generating = False
                    self.ffmpeg_proc = None
                    def reset_btn():
                        self.pulse_timer.stop()
                        if success:
                            self.gen_btn.setStyleSheet("background-color: #28a745; color: white;")
                            self.gen_btn.setText("✅ Successfully Generated!")
                            
                            def revert_default():
                                self.gen_btn.setStyleSheet("")
                                self.gen_btn.setText("⚡ Generate Subtitles")
                                self.gen_btn.setEnabled(True)
                                self.progress_bar.setVisible(False)
                                self.progress_lbl.setVisible(False)
                            QTimer.singleShot(3000, revert_default)
                        else:
                            self.gen_btn.setStyleSheet("")
                            self.gen_btn.setText("⚡ Generate Subtitles")
                            self.gen_btn.setEnabled(True)
                            self.progress_bar.setVisible(False)
                            self.progress_lbl.setVisible(False)
                    QTimer.singleShot(0, reset_btn)

        threading.Thread(target=_task, daemon=True).start()

    def run_translation(self):
        srt_path = self.trans_srt_path.text().strip()
        target_lang = self.trans_lang.currentText()
        romanize = self.trans_romanize.isChecked()

        if not srt_path or not os.path.exists(srt_path): return self.show_error("SRT file not found!")

        self.trans_btn.setEnabled(False)
        def _task():
            try:
                self.signals.update_status.emit("Parsing SRT...")
                segments = parse_srt(srt_path)
                target_code = config.LANGUAGES.get(target_lang, "en")
                
                self.signals.update_status.emit(f"Translating {len(segments)} lines...")
                translate_batch(segments, target_code, romanize)
                
                srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                      for i, s in enumerate(segments))
                base = os.path.splitext(os.path.basename(srt_path))[0]
                suffix = f"_{target_lang}_Romanized" if romanize else f"_{target_lang}"
                save_path = clean_path(os.path.join(config.SUB_DIR, f"{base}{suffix}.srt"))
                with open(save_path, 'w', encoding='utf-8') as f: f.write(srt_content)
                
                self.signals.update_status.emit("✅ Translation Done!")
                self.signals.populate_tabs.emit(save_path)
            except Exception as e:
                self.signals.error.emit(str(e))
            finally:
                QTimer.singleShot(0, lambda: self.trans_btn.setEnabled(True))
        threading.Thread(target=_task, daemon=True).start()

    def run_auto_sync(self):
        srt_path = self.sync_srt_path.text().strip()
        video_path = self.gen_video_path.text().strip()
        if not srt_path or not video_path: return self.show_error("Video and SRT needed!")
        self.auto_sync_btn.setEnabled(False)
        def _task():
            try:
                offset, info = detect_sync_offset(video_path, srt_path, lambda s: self.signals.update_status.emit(s))
                if offset is None: raise Exception(info)
                self.signals.sync_offset_detected.emit(f"{offset:+.2f}", info)
            except Exception as e:
                self.signals.error.emit(str(e))
            finally:
                QTimer.singleShot(0, lambda: self.auto_sync_btn.setEnabled(True))
        threading.Thread(target=_task, daemon=True).start()

    def on_sync_offset_detected(self, offset_str, info):
        self.sync_offset.setText(offset_str)
        self.set_status(f"✅ Auto-detected offset: {offset_str}s")
        QMessageBox.information(self, "Auto-Sync", f"Detected Offset: {offset_str}s\n\n{info}\nClick 'Sync & Apply' to save!")

    def run_sync(self):
        srt_path = self.sync_srt_path.text().strip()
        try: offset_val = float(self.sync_offset.text().strip().replace('+', ''))
        except: return self.show_error("Offset must be a number")
        
        self.sync_btn.setEnabled(False)
        def _task():
            try:
                segments = parse_srt(srt_path)
                for seg in segments:
                    seg['start'] = max(0, seg['start'] + offset_val)
                    seg['end'] = max(0.001, seg['end'] + offset_val)
                srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                      for i, s in enumerate(segments))
                base = os.path.splitext(os.path.basename(srt_path))[0].replace('_synced', '')
                save_path = clean_path(os.path.join(config.SUB_DIR, f"{base}_synced.srt"))
                with open(save_path, 'w', encoding='utf-8') as f: f.write(srt_content)
                self.signals.update_status.emit(f"✅ Sync done! Offset: {offset_val:+.2f}s")
                self.signals.populate_tabs.emit(save_path)
            except Exception as e:
                self.signals.error.emit(str(e))
            finally:
                QTimer.singleShot(0, lambda: self.sync_btn.setEnabled(True))
        threading.Thread(target=_task, daemon=True).start()

    def run_export_ass(self):
        srt_path = self.cust_srt_path.text().strip()
        if not srt_path: return self.show_error("No SRT selected")
        
        self.export_btn.setEnabled(False)
        def _task():
            try:
                segments = parse_srt(srt_path)
                
                # ASS Alignment Mapping (Numpad layout)
                pos_text = self.cust_position.currentText()
                alignment_map = {
                    "Bottom Left": 1, "Bottom Center": 2, "Bottom Right": 3,
                    "Middle Center": 5,
                    "Top Left": 7, "Top Center": 8, "Top Right": 9
                }
                alignment = alignment_map.get(pos_text, 2)
                
                style = {
                    "font_name": self.cust_font.currentText(),
                    "font_size": 20,
                    "primary_color": self.cust_color.text(),
                    "outline_color": "#000000",
                    "background": self.cust_bg.isChecked(),
                    "bold": False, "italic": False, "outline": 2, "shadow": 1, "alignment": alignment,
                }
                ass_content = generate_ass_content(segments, style)
                base = os.path.splitext(os.path.basename(srt_path))[0]
                ass_path = clean_path(os.path.join(config.SUB_DIR, f"{base}_styled.ass"))
                with open(ass_path, 'w', encoding='utf-8') as f: f.write(ass_content)
                self.signals.update_status.emit("✅ Exported .ASS")
                self.signals.populate_tabs.emit(ass_path)
            except Exception as e:
                self.signals.error.emit(str(e))
            finally:
                QTimer.singleShot(0, lambda: self.export_btn.setEnabled(True))
        threading.Thread(target=_task, daemon=True).start()

    def run_reframe(self):
        video_path = self.gen_video_path.text().strip()
        if not video_path: return self.show_error("Select video in Generate tab!")
        self.ref_btn.setEnabled(False)
        def _task():
            try:
                out_path = reframe_video(video_path, self.ref_ratio.currentText(), "Blurred Background (Professional)")
                self.signals.update_status.emit("✅ Reframe done!")
                QTimer.singleShot(0, lambda: QMessageBox.information(self, "Success", f"Saved to {out_path}"))
            except Exception as e:
                self.signals.error.emit(str(e))
            finally:
                QTimer.singleShot(0, lambda: self.ref_btn.setEnabled(True))
        threading.Thread(target=_task, daemon=True).start()

    def run_export_srt_dialog(self):
        if not hasattr(self.timeline, 'segments') or not self.timeline.segments:
            return self.show_error("No subtitles loaded in timeline!")
            
        save_path, _ = QFileDialog.getSaveFileName(self, "Export SRT", "", "Subtitles (*.srt)")
        if save_path:
            try:
                from utils import format_timestamp
                srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                      for i, s in enumerate(self.timeline.segments))
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(srt_content)
                self.set_status(f"Exported SRT: {save_path}")
                QMessageBox.information(self, "Success", "SRT Exported Successfully!")
            except Exception as e:
                self.show_error(f"Failed to export SRT: {e}")

    def run_export_ass_dialog(self):
        if not hasattr(self.timeline, 'segments') or not self.timeline.segments:
            return self.show_error("No subtitles loaded in timeline!")
            
        save_path, _ = QFileDialog.getSaveFileName(self, "Export ASS", "", "Advanced Subtitles (*.ass)")
        if save_path:
            try:
                # Use current customize tab settings
                pos_text = self.cust_position.currentText()
                alignment_map = {
                    "Bottom Left": 1, "Bottom Center": 2, "Bottom Right": 3,
                    "Middle Center": 5, "Top Left": 7, "Top Center": 8, "Top Right": 9
                }
                style = {
                    "font_name": self.cust_font.currentText(),
                    "font_size": 20,
                    "primary_color": self.cust_color.text(),
                    "outline_color": "#000000",
                    "background": self.cust_bg.isChecked(),
                    "bold": False, "italic": False, "outline": 2, "shadow": 1, "alignment": alignment_map.get(pos_text, 2),
                }
                ass_content = generate_ass_content(self.timeline.segments, style)
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(ass_content)
                self.set_status(f"Exported ASS: {save_path}")
                QMessageBox.information(self, "Success", "ASS Exported Successfully!")
            except Exception as e:
                self.show_error(f"Failed to export ASS: {e}")

    def preview_external_vlc(self):
        video_path = self.gen_video_path.text().strip()
        if not video_path:
            return self.show_error("Please select a video file first!")
            
        # We need an SRT or ASS to preview. Let's try to export current customized ASS to a temp file, or use timeline srt
        if not hasattr(self.timeline, 'segments') or not self.timeline.segments:
            return self.show_error("No subtitles available to preview!")
            
        import tempfile
        # Create temp ASS
        pos_text = self.cust_position.currentText()
        alignment_map = {
            "Bottom Left": 1, "Bottom Center": 2, "Bottom Right": 3,
            "Middle Center": 5, "Top Left": 7, "Top Center": 8, "Top Right": 9
        }
        style = {
            "font_name": self.cust_font.currentText(),
            "font_size": 20,
            "primary_color": self.cust_color.text(),
            "outline_color": "#000000",
            "background": self.cust_bg.isChecked(),
            "bold": False, "italic": False, "outline": 2, "shadow": 1, "alignment": alignment_map.get(pos_text, 2),
        }
        ass_content = generate_ass_content(self.timeline.segments, style)
        
        temp_dir = tempfile.gettempdir()
        temp_sub = os.path.join(temp_dir, "vsub_preview.ass")
        with open(temp_sub, 'w', encoding='utf-8') as f:
            f.write(ass_content)
            
        # Stop internal player so VLC can lock the file if needed
        self.player.stop()
        
        # Launch external VLC
        # Find vlc.exe in our local folder first, else try system PATH
        vlc_exe = os.path.join(os.getcwd(), 'vlc_64', 'vlc.exe')
        if not os.path.exists(vlc_exe):
            vlc_exe = "vlc"  # fallback to system PATH
            
        try:
            # We don't wait for it to finish
            subprocess.Popen([vlc_exe, video_path, f"--sub-file={temp_sub}"])
            self.set_status("Launched external VLC preview")
        except Exception as e:
            self.show_error(f"Failed to launch external VLC. Is it installed? {e}")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())