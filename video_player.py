import sys
import os
import vlc
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QFileDialog, QVBoxLayout, QListWidget, QLabel, QSplitter, QHBoxLayout, QSlider, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QKeyEvent
import datetime
import time

import ffmpeg
from PIL import Image
from PIL import ImageCms


class CustomListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent

    def keyPressEvent(self, event: QKeyEvent):
        if self.parent_widget:
            self.parent_widget.keyPressEvent(event)
        super().keyPressEvent(event)


class VideoPlayer(QWidget):
    def __init__(self):
        super().__init__()

        # Initialize VLC media player
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()

        # Default volume level
        self.default_volume = 0  # Set volume to 50% initially

        # To keep track of the folder and list of videos
        self.video_files = []
        self.current_video_path = ""
        self.screenshot_output_folder = os.getcwd()  # Default screenshot folder

        # Set up the GUI
        self.init_ui()

        # Timer for progress bar updates
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)

    def init_ui(self):
        self.setWindowTitle('Video Player')

        # Maximize the window on startup
        self.showMaximized()

        # Create a horizontal splitter
        splitter = QSplitter(Qt.Horizontal, self)

        # Left Panel
        self.left_panel = QWidget(self)
        left_layout = QVBoxLayout(self.left_panel)

        # Select Video Folder button
        self.select_folder_button = QPushButton('Select Video Folder', self)
        self.select_folder_button.setIcon(QIcon.fromTheme("folder-open"))
        self.select_folder_button.clicked.connect(self.open_video_folder)
        left_layout.addWidget(self.select_folder_button)

        # Text field to show selected video folder
        self.video_folder_display = QLineEdit(self)
        self.video_folder_display.setPlaceholderText("No video folder selected")
        self.video_folder_display.setReadOnly(True)
        left_layout.addWidget(self.video_folder_display)

        # Select Screenshot Folder button
        self.select_output_folder_button = QPushButton('Select Screenshot Folder', self)
        self.select_output_folder_button.setIcon(QIcon.fromTheme("folder"))
        self.select_output_folder_button.clicked.connect(self.select_screenshot_folder)
        left_layout.addWidget(self.select_output_folder_button)

        # Text field to show selected screenshot folder
        self.screenshot_folder_display = QLineEdit(self)
        self.screenshot_folder_display.setPlaceholderText("No screenshot folder selected")
        self.screenshot_folder_display.setReadOnly(True)
        left_layout.addWidget(self.screenshot_folder_display)

        # Video list
        self.video_list = CustomListWidget(self)
        self.video_list.currentRowChanged.connect(self.play_video_by_index)
        left_layout.addWidget(self.video_list)

        self.left_panel.setLayout(left_layout)

        # Right Panel
        self.right_panel = QWidget(self)
        right_layout = QVBoxLayout(self.right_panel)

        # Video widget
        self.video_widget = QWidget(self)
        self.video_widget.setStyleSheet("background-color: black;")
        right_layout.addWidget(self.video_widget)

        # Controls: Play, Pause, Stop, Capture, Progress bar, and Volume slider
        controls_layout = QHBoxLayout()

        self.play_button = QPushButton("Play", self)
        self.play_button.clicked.connect(self.play_video)
        controls_layout.addWidget(self.play_button)

        self.pause_button = QPushButton("Pause", self)
        self.pause_button.clicked.connect(self.pause_video)
        controls_layout.addWidget(self.pause_button)

        self.stop_button = QPushButton("Stop (D)", self)
        self.stop_button.clicked.connect(self.stop_video)
        controls_layout.addWidget(self.stop_button)

        self.capture_button = QPushButton("Capture (S)", self)
        self.capture_button.clicked.connect(self.capture_screenshot)
        controls_layout.addWidget(self.capture_button)

        # Progress bar
        self.progress_bar = QSlider(Qt.Horizontal, self)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.sliderMoved.connect(self.seek_video)
        controls_layout.addWidget(self.progress_bar)

        # Volume slider
        self.volume_slider = QSlider(Qt.Horizontal, self)
        self.volume_slider.setRange(0, 100)  # VLC volume range is 0 to 100
        self.volume_slider.setValue(self.default_volume)
        self.volume_slider.valueChanged.connect(self.change_volume)
        controls_layout.addWidget(QLabel("Volume"))
        controls_layout.addWidget(self.volume_slider)

        right_layout.addLayout(controls_layout)
        self.right_panel.setLayout(right_layout)

        # Add panels to the splitter
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([self.width() // 4, self.width() * 3 // 4])

        # Set main layout
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.setLayout(layout)

        # Set the initial volume
        self.change_volume(self.default_volume)

    def change_volume(self, value):
        """Set the VLC player's volume to the slider's value."""
        self.player.audio_set_volume(value)

    def open_video_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, 'Select Video Folder')
        if folder_path:
            self.load_videos_from_folder(folder_path)
            self.video_folder_display.setText(folder_path)

    def select_screenshot_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, 'Select Screenshot Folder')
        if folder_path:
            self.screenshot_output_folder = folder_path
            self.screenshot_folder_display.setText(folder_path)

    def load_videos_from_folder(self, folder_path):
        supported_formats = ['.mp4', '.avi', '.mov', '.mkv']
        
        # Get all video files and their modification times
        self.video_files = [(os.path.join(folder_path, f), os.path.getmtime(os.path.join(folder_path, f))) 
                            for f in os.listdir(folder_path) 
                            if os.path.splitext(f)[1].lower() in supported_formats]
        
        # Sort video files by modification time (oldest to newest)
        self.video_files.sort(key=lambda x: x[1])

        # Clear the list and add sorted videos
        self.video_list.clear()
        for video, _ in self.video_files:
            self.video_list.addItem(os.path.basename(video))
        
        if self.video_files:
            self.video_list.setCurrentRow(0)

    def play_video_by_index(self, index):
        if 0 <= index < len(self.video_files):
            self.current_video_path = self.video_files[index][0]  # Get the path from the sorted tuple
            media = self.instance.media_new(self.current_video_path)
            self.player.set_media(media)
            if sys.platform == "win32":
                self.player.set_hwnd(int(self.video_widget.winId()))
            elif sys.platform == "darwin":
                self.player.set_nsobject(int(self.video_widget.winId()))
            else:
                self.player.set_xwindow(int(self.video_widget.winId()))
            self.play_video()

    def play_video(self):
        if self.player.get_state() != vlc.State.Playing:
            self.player.play()
            self.player.audio_set_volume(self.volume_slider.value())  # Ensure volume is maintained
            self.timer.start(100)

    def pause_video(self):
        if self.player.get_state() == vlc.State.Playing:
            self.player.pause()
            self.timer.stop()

    def stop_video(self):
        self.player.stop()
        self.timer.stop()
        self.progress_bar.setValue(0)

    def seek_video(self, position):
        if self.player.get_state() in (vlc.State.Playing, vlc.State.Paused):
            duration = self.player.get_length()
            self.player.set_time(int(position * duration / 1000))

    def update_progress(self):
        if self.player.get_state() == vlc.State.Playing:
            duration = self.player.get_length()
            current_time = self.player.get_time()
            if duration > 0:
                self.progress_bar.setValue(int(current_time / duration * 1000))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_S and (self.player.is_playing() or self.player.get_state() == vlc.State.Paused):
            self.capture_screenshot()
        elif event.key() == Qt.Key_Right:  # Skip forward
            self.step_video(1)
        elif event.key() == Qt.Key_Left:  # Skip backward
            self.step_video(-1)
        elif event.key() == Qt.Key_Space:  # Play/Pause toggle
            if self.player.get_state() == vlc.State.Playing:
                self.pause_video()
            else:
                self.play_video()
        elif event.key() == Qt.Key_D:  # Stop video
            self.stop_video()

    def step_video(self, step_frames):
        fps = 25  # Default FPS
        current_time = self.player.get_time()
        step_time = int(1000 / fps) * step_frames
        self.player.set_time(max(0, current_time + step_time))
        self.update_progress()

    def capture_screenshot(self):
        if self.current_video_path:
            # Get the timestamp of the current video file (last modified time)
            video_modified_time = os.path.getmtime(self.current_video_path)
            modified_timestamp = datetime.datetime.fromtimestamp(video_modified_time).strftime('%Y%m%d_%H%M%S')
            
            # Save screenshot with the same timestamp format
            screenshot_filename = os.path.join(self.screenshot_output_folder, f"screenshot_{modified_timestamp}.png")
            
            # Capture the screenshot
            self.player.video_take_snapshot(0, screenshot_filename, 0, 0)

            # Check if need to rotate
            ff_probe = ffmpeg.probe(self.current_video_path)
            rotation = 0
            if ff_probe and 'streams' in ff_probe and 'side_data_list' in ff_probe['streams'][0]:
                if 'rotation' in ff_probe['streams'][0]['side_data_list'][0]:
                    rotation = ff_probe['streams'][0]['side_data_list'][0]['rotation']
                elif 'rotation' in ff_probe['streams'][0]['side_data_list'][1]:
                    rotation = ff_probe['streams'][0]['side_data_list'][1]['rotation']

            # Open the screenshot and rotate if necessary
            img = Image.open(screenshot_filename)
            rotated_image = img.rotate(int(rotation), expand=True)
            
            # Save the rotated image, and handle specific profiles if required
            if ff_probe and 'streams' in ff_probe \
                    and ff_probe['streams'][0].get('codec_name', None) == 'hevc':
                profile = ImageCms.getOpenProfile(os.path.join(
                                    os.path.dirname(os.path.realpath(__file__)),
                                    "DisplayP3Compat-v4.icc"))
                rotated_image.save(screenshot_filename, icc_profile=profile.tobytes())
            else:
                rotated_image.save(screenshot_filename)

            # Set the modified time of the screenshot to match the video's modified time
            os.utime(screenshot_filename, (video_modified_time, video_modified_time))


def main():
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
