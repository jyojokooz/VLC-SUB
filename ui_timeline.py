from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPainterPath, QLinearGradient
from PySide6.QtCore import Qt, QRectF, QPoint, Signal

class TimelineWidget(QWidget):
    seek_requested = Signal(int)
    subtitle_dropped = Signal(str)
    subtitle_clicked = Signal()
    subtitle_edited = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self.duration_ms = 0
        self.current_time_ms = 0
        self.segments = [] # List of dicts: {'start': ms, 'end': ms, 'text': str}
        
        # UI settings
        self.pixels_per_second = 50  # zoom level
        self.scroll_x = 0
        self.is_panning = False
        self.pan_last_x = 0

    def set_duration(self, duration_ms):
        self.duration_ms = max(duration_ms, 1)
        self.update()

    def set_current_time(self, time_ms):
        if time_ms == self.current_time_ms:
            return  # No change (e.g. paused), don't force auto-scroll
            
        is_playing = abs(time_ms - self.current_time_ms) < 1000
        self.current_time_ms = time_ms
        
        if not self.is_panning:
            playhead_x = (self.current_time_ms / 1000.0) * self.pixels_per_second
            
            if is_playing:
                # During playback, only scroll when playhead hits the right edge (90%)
                if playhead_x - self.scroll_x > self.width() * 0.9:
                    self.scroll_x = max(0, playhead_x - self.width() * 0.1)
            else:
                # If user jumped/seeked, center the playhead if it's off-screen
                if playhead_x < self.scroll_x or playhead_x > self.scroll_x + self.width():
                    self.scroll_x = max(0, playhead_x - self.width() / 2)
                
        self.update()

    def set_segments(self, segments):
        self.segments = segments
        self.update()

    def format_time(self, ms):
        s = int(ms / 1000)
        h = s // 3600
        m = (s % 3600) // 60
        s = s % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        width = rect.width()
        height = rect.height()

        # Background
        painter.fillRect(rect, QColor("#141414"))

        if self.duration_ms <= 0:
            # Draw empty state for video
            painter.setPen(QPen(QColor("#444"), 2, Qt.DashLine))
            box_rect = rect.adjusted(10, 10, -10, -10)
            painter.drawRoundedRect(box_rect, 10, 10)
            painter.setPen(QColor("#666"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(rect, Qt.AlignCenter, "Load a video to unlock timeline")
            return

        # Subtitle track area background
        sub_track = QRectF(0, 30, width, height - 30)
        painter.fillRect(sub_track, QColor("#1a1a1a"))

        if len(self.segments) == 0:
            # Empty state for subtitles
            is_hover = getattr(self, 'is_hovering_sub', False)
            color = "#ff9900" if is_hover else "#666"
            painter.setPen(QPen(QColor(color), 2, Qt.DashLine))
            box_rect = QRectF(10, 40, width - 20, height - 50)
            painter.drawRoundedRect(box_rect, 10, 10)
            painter.setPen(QColor(color))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(box_rect, Qt.AlignCenter, "📁 Click here or Drag & Drop a .srt file to add subtitles")

        # Time track area (top 30px)
        track_rect = QRectF(0, 0, width, 30)
        painter.fillRect(track_rect, QColor("#1e1e1e"))

        # Draw ticks and time labels
        painter.setPen(QPen(QColor("#666666")))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        
        visible_start_s = self.scroll_x / self.pixels_per_second
        visible_end_s = (self.scroll_x + width) / self.pixels_per_second
        
        # Tick interval logic
        tick_interval_s = 10 # 10 seconds default
        if self.pixels_per_second < 10:
            tick_interval_s = 60
        elif self.pixels_per_second > 100:
            tick_interval_s = 5

        start_tick = int(visible_start_s // tick_interval_s) * tick_interval_s
        
        for t in range(start_tick, int(visible_end_s) + tick_interval_s, tick_interval_s):
            x = (t * self.pixels_per_second) - self.scroll_x
            if x < 0 or x > width:
                continue
                
            # Major tick
            painter.drawLine(x, 15, x, 30)
            
            # Minor ticks (every 1 second if zoomed in enough)
            if self.pixels_per_second >= 20:
                minor_interval = tick_interval_s // 5
                for mt in range(1, 5):
                    mx = ((t + mt * minor_interval) * self.pixels_per_second) - self.scroll_x
                    if 0 <= mx <= width:
                        painter.drawLine(mx, 22, mx, 30)
                        
            time_str = self.format_time(t * 1000)
            painter.setPen(QColor("#aaaaaa"))
            painter.drawText(QRectF(x - 25, 0, 50, 15), Qt.AlignCenter, time_str)
            painter.setPen(QColor("#666666"))

        # Draw segments
        font.setPointSize(9)
        painter.setFont(font)
        fm = QFontMetrics(font)
        
        for seg in self.segments:
            start_s = seg['start']
            end_s = seg['end']
            
            x_start = (start_s * self.pixels_per_second) - self.scroll_x
            x_end = (end_s * self.pixels_per_second) - self.scroll_x
            
            if x_end < 0 or x_start > width:
                continue # Outside visible area
                
            seg_width = max(2, x_end - x_start)
            seg_rect = QRectF(x_start, 40, seg_width, height - 60)
            
            # Subtitle Block Background (translucent dark)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(30, 30, 30, 200)))
            painter.drawRoundedRect(seg_rect, 6, 6)
            
            # Subtitle Block Border (Orange)
            painter.setPen(QPen(QColor("#ff9900"), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(seg_rect, 6, 6)
            
            # Top little handles/decorations
            painter.setBrush(QBrush(QColor("#ff9900")))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon([
                QPoint(int(x_start + seg_width/2 - 4), 36),
                QPoint(int(x_start + seg_width/2 + 4), 36),
                QPoint(int(x_start + seg_width/2), 40)
            ])

            # Text inside
            painter.setPen(QPen(Qt.white))
            text_rect = seg_rect.adjusted(6, 4, -6, -4)
            # Elide text if it's too long
            elided_text = fm.elidedText(seg['text'].replace('\n', ' '), Qt.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, elided_text)

        # Draw playhead
        playhead_x = (self.current_time_ms / 1000.0 * self.pixels_per_second) - self.scroll_x
        if 0 <= playhead_x <= width:
            painter.setPen(QPen(QColor("#ff9900"), 2))
            painter.drawLine(playhead_x, 0, playhead_x, height)
            
            # Playhead top handle
            painter.setBrush(QBrush(QColor("#ff9900")))
            painter.setPen(Qt.NoPen)
            painter.drawRect(playhead_x - 4, 0, 8, 10)
            painter.drawPolygon([
                QPoint(int(playhead_x - 4), 10),
                QPoint(int(playhead_x + 4), 10),
                QPoint(int(playhead_x), 15)
            ])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            y = event.position().y()
            
            # If we have a duration but no subtitles, clicking the bottom area opens file dialog
            if self.duration_ms > 0 and len(self.segments) == 0 and y > 30:
                self.subtitle_clicked.emit()
                return
                
            # If clicked in the top ruler area (y <= 30) or near the playhead, we scrub
            playhead_x = (self.current_time_ms / 1000.0 * self.pixels_per_second) - self.scroll_x
            is_near_playhead = abs(x - playhead_x) < 15
            
            if y <= 30 or is_near_playhead:
                self.is_scrubbing = True
                self.handle_scrub(x)
            else:
                self.is_panning = True
                self.pan_last_x = x
                self.setCursor(Qt.ClosedHandCursor)

    def handle_scrub(self, mouse_x):
        time_s = (mouse_x + self.scroll_x) / self.pixels_per_second
        time_ms = int(time_s * 1000)
        time_ms = max(0, min(time_ms, self.duration_ms))
        self.seek_requested.emit(time_ms)
        self.set_current_time(time_ms)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_panning = False
            if hasattr(self, 'is_scrubbing'):
                self.is_scrubbing = False
            self.setCursor(Qt.ArrowCursor)

    def mouseMoveEvent(self, event):
        if hasattr(self, 'is_scrubbing') and self.is_scrubbing:
            self.handle_scrub(event.position().x())
        elif self.is_panning:
            dx = event.position().x() - self.pan_last_x
            self.scroll_x -= dx
            self.scroll_x = max(0, self.scroll_x)
            self.pan_last_x = event.position().x()
            self.update()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self.duration_ms > 0:
            event.acceptProposedAction()
            self.is_hovering_sub = True
            self.update()
            
    def dragLeaveEvent(self, event):
        self.is_hovering_sub = False
        self.update()
        
    def dropEvent(self, event):
        self.is_hovering_sub = False
        self.update()
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith(('.srt', '.ass')):
                self.subtitle_dropped.emit(path)

    def wheelEvent(self, event):
        delta_y = event.angleDelta().y()
        delta_x = event.angleDelta().x()

        if delta_y != 0:
            # Zoom in/out with scroll wheel (vertical)
            zoom_factor = 1.1 if delta_y > 0 else 0.9
            old_pixels_per_second = self.pixels_per_second
            self.pixels_per_second *= zoom_factor
            
            # Clamp zoom
            self.pixels_per_second = max(5, min(500, self.pixels_per_second))
            
            # Adjust scroll_x so the time under cursor stays in place
            mouse_x = event.position().x()
            time_under_cursor = (self.scroll_x + mouse_x) / old_pixels_per_second
            self.scroll_x = (time_under_cursor * self.pixels_per_second) - mouse_x
            self.scroll_x = max(0, self.scroll_x)
            
        if delta_x != 0:
            # Pan timeline with horizontal slide (trackpad)
            # Some trackpads send negative delta for right slide, some positive.
            self.scroll_x -= delta_x
            self.scroll_x = max(0, self.scroll_x)
            
        self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            y = event.position().y()
            
            # Check if clicked inside any segment
            for i, seg in enumerate(self.segments):
                start_s = seg['start']
                end_s = seg['end']
                
                x_start = (start_s * self.pixels_per_second) - self.scroll_x
                x_end = (end_s * self.pixels_per_second) - self.scroll_x
                seg_width = max(2, x_end - x_start)
                
                # Check click bounds
                if x_start <= x <= x_start + seg_width and 40 <= y <= self.height() - 20:
                    from PySide6.QtWidgets import QInputDialog
                    new_text, ok = QInputDialog.getMultiLineText(self, "Edit Subtitle", "Subtitle Text:", seg['text'])
                    if ok and new_text:
                        self.segments[i]['text'] = new_text.strip()
                        self.update()
                        
                        # Save back to file if we know the path
                        if hasattr(self, 'srt_path') and self.srt_path:
                            self.save_srt()
                            self.subtitle_edited.emit(self.srt_path)
                    return

    def save_srt(self):
        try:
            from utils import format_timestamp
            srt_content = "".join(f"{i+1}\n{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n{s['text']}\n\n"
                                  for i, s in enumerate(self.segments))
            with open(self.srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
        except Exception as e:
            print("Failed to save edited subtitle:", e)
