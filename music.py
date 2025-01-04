import os
import threading
import time
import random
import logging
from collections import deque
from mutagen import File as MutagenFile
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QSlider, QMessageBox, QDialog, QLineEdit, QComboBox,
    QInputDialog, QMenu, QAction, QShortcut, QStyle
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QIcon, QKeySequence
import pyaudio
import pyqtgraph as pg
import numpy as np
import soundfile as sf

logging.basicConfig(filename='audioplayer.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

class AudioTrack:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.metadata = self.extract_metadata()
        self.duration = self.get_duration()

    def extract_metadata(self):
        try:
            audio = MutagenFile(self.path, easy=True)
            if audio:
                return {
                    'title': audio.get('title', [self.name])[0],
                    'artist': audio.get('artist', ['Unknown Artist'])[0],
                    'album': audio.get('album', ['Unknown Album'])[0],
                }
        except Exception as e:
            logging.error(f"Error extracting metadata from {self.path}: {e}")
        return {'title': self.name, 'artist': 'Unknown Artist', 'album': 'Unknown Album'}

    def get_duration(self):
        try:
            with sf.SoundFile(self.path) as f:
                duration = len(f) / f.samplerate
            return duration
        except Exception as e:
            logging.error(f"Error getting duration of {self.path}: {e}")
            return 0

class AudioThread(threading.Thread):
    def __init__(self, player):
        super().__init__()
        self.player = player
        self.stop_flag = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.muted = False
        self.volume = self.player.volume_level / 100.0
        self.lock = threading.Lock()

    def run(self):
        audio_path = self.player.currentTrack.path
        if not os.path.isfile(audio_path):
            logging.error(f"File not found: {audio_path}")
            self.player.show_error_message(f"File not found: {audio_path}")
            return
        try:
            data, samplerate = sf.read(audio_path, dtype='int16')
            if len(data.shape) == 1:
                data = np.expand_dims(data, axis=1)
            channels = data.shape[1]
            logging.debug(f"Audio data shape: {data.shape}, Sample rate: {samplerate}")
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16,
                            channels=channels,
                            rate=int(samplerate),
                            output=True)
            logging.info(f"Opened PyAudio stream for {audio_path}")
        except Exception as e:
            logging.error(f"Error opening audio file {audio_path}: {e}")
            self.player.show_error_message(f"Error opening audio file: {e}")
            return
        chunk_size = 1024
        current_frame = int((self.player.playback_position / 1000.0) * samplerate)
        data = data[current_frame:]
        logging.info(f"Starting playback: {audio_path} from frame {current_frame}")
        try:
            for i in range(0, len(data), chunk_size):
                if self.stop_flag:
                    logging.info("Stop flag detected. Stopping playback thread.")
                    break
                self.pause_event.wait()
                chunk = data[i:i + chunk_size]
                if len(chunk) == 0:
                    logging.debug("Reached end of audio data.")
                    break
                if self.muted:
                    chunk = np.zeros_like(chunk)
                with self.lock:
                    current_volume = self.volume
                chunk = (chunk * current_volume).astype(np.int16)
                try:
                    stream.write(chunk.tobytes())
                    logging.debug(f"Wrote chunk {i // chunk_size + 1} to stream.")
                except Exception as e:
                    logging.error(f"Error writing to stream: {e}")
                    self.player.show_error_message(f"Playback error: {e}")
                    break
                with self.lock:
                    self.player.playback_position = (current_frame + i + len(chunk)) / samplerate * 1000.0
                self.player.update_visualization(chunk, len(chunk))
        except Exception as e:
            logging.error(f"Exception during playback: {e}")
            self.player.show_error_message(f"Playback exception: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            logging.info("Playback finished.")
            self.player.playback_finished()

class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shortcuts")
        self.setModal(True)
        self.resize(400, 250)
        layout = QVBoxLayout(self)
        title = QLabel("Keyboard Shortcuts", self)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #f33; margin-bottom: 10px;")
        layout.addWidget(title)
        shortcuts_info = [
            "Ctrl+Shift+Space = Play/Pause",
            "Ctrl+Shift+ArrowLeft = Previous Track",
            "Ctrl+Shift+ArrowRight = Next Track",
            "Ctrl+Shift+Number (1-9) = Jump to Track Number",
            "Ctrl+M = Mute/Unmute",
            "Ctrl+S = Shuffle",
            "Ctrl+R = Repeat",
            "Ctrl+F = Forward 15s",
            "Ctrl+B = Rewind 15s"
        ]
        for info in shortcuts_info:
            lbl = QLabel(info, self)
            lbl.setStyleSheet("font-size: 14px;")
            layout.addWidget(lbl)
        layout.addStretch(1)
        closeBtn = QPushButton("Close", self)
        closeBtn.setStyleSheet(
            "QPushButton { border: 1px solid #f33; background: none; color: #f33; font-size: 14px; padding: 8px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #f33; color: #fff; }"
        )
        closeBtn.clicked.connect(self.accept)
        layout.addWidget(closeBtn)

class AudioPlayerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Enhanced PyAudio + PyQt5 Player")
        self.resize(1200, 800)
        container = QWidget()
        self.setCentralWidget(container)
        mainLayout = QVBoxLayout(container)
        mainLayout.setContentsMargins(10, 10, 10, 10)
        mainLayout.setSpacing(10)
        topLayout = QHBoxLayout()
        mainLayout.addLayout(topLayout)
        addTrackLayout = QVBoxLayout()
        topLayout.addLayout(addTrackLayout, stretch=3)
        addLabel = QLabel("Add Audio Tracks")
        addLabel.setStyleSheet("font-size: 20px; font-weight: bold; color: #f33;")
        addTrackLayout.addWidget(addLabel, alignment=Qt.AlignLeft)
        addTrackForm = QHBoxLayout()
        addTrackLayout.addLayout(addTrackForm)
        self.fileButton = QPushButton("Choose Audio Files…")
        addTrackForm.addWidget(self.fileButton)
        self.addFilesBtn = QPushButton("Add Selected Audio Files")
        addTrackForm.addWidget(self.addFilesBtn)
        searchLayout = QHBoxLayout()
        topLayout.addLayout(searchLayout, stretch=2)
        searchLabel = QLabel("Search:")
        searchLayout.addWidget(searchLabel)
        self.searchBar = QLineEdit()
        self.searchBar.setPlaceholderText("Search by track name, artist, album...")
        searchLayout.addWidget(self.searchBar)
        self.trackList = QListWidget()
        self.trackList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trackList.customContextMenuRequested.connect(self.showTrackContextMenu)
        mainLayout.addWidget(self.trackList)
        controlsLayout = QHBoxLayout()
        mainLayout.addLayout(controlsLayout)
        btnStyle = (
            "QPushButton { border: none; background: none; width: 40px; height: 40px; }"
            "QPushButton:hover { background-color: rgba(255, 0, 0, 30); border-radius: 20px; }"
        )
        self.shuffleBtn = QPushButton()
        self.shuffleBtn.setToolTip("Shuffle")
        self.shuffleBtn.setCheckable(True)
        self.shuffleBtn.setIcon(QIcon("shuffle.png"))  # Ensure 'shuffle.png' exists
        self.shuffleBtn.setIconSize(QSize(32, 32))
        self.shuffleBtn.setStyleSheet(btnStyle)
        controlsLayout.addWidget(self.shuffleBtn)
        self.repeatBtn = QPushButton()
        self.repeatBtn.setToolTip("Repeat")
        self.repeatBtn.setCheckable(True)
        self.repeatBtn.setIcon(QIcon("repeat.png"))  # Ensure 'repeat.png' exists
        self.repeatBtn.setIconSize(QSize(32, 32))
        self.repeatBtn.setStyleSheet(btnStyle)
        controlsLayout.addWidget(self.repeatBtn)
        self.prevBtn = QPushButton()
        self.prevBtn.setToolTip("Previous Track")
        self.prevBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.prevBtn.setIconSize(QSize(32, 32))
        self.prevBtn.setStyleSheet(btnStyle)
        controlsLayout.addWidget(self.prevBtn)
        self.playPauseBtn = QPushButton()
        self.playPauseBtn.setToolTip("Play/Pause")
        self.playPauseBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.playPauseBtn.setIconSize(QSize(32, 32))
        self.playPauseBtn.setStyleSheet(btnStyle)
        controlsLayout.addWidget(self.playPauseBtn)
        self.nextBtn = QPushButton()
        self.nextBtn.setToolTip("Next Track")
        self.nextBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        self.nextBtn.setIconSize(QSize(32, 32))
        self.nextBtn.setStyleSheet(btnStyle)
        controlsLayout.addWidget(self.nextBtn)
        self.muteBtn = QPushButton()
        self.muteBtn.setToolTip("Mute/Unmute")
        self.muteBtn.setCheckable(True)
        self.muteBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self.muteBtn.setIconSize(QSize(32, 32))
        self.muteBtn.setStyleSheet(btnStyle)
        controlsLayout.addWidget(self.muteBtn)
        progressLayout = QHBoxLayout()
        mainLayout.addLayout(progressLayout)
        self.currentTimeLabel = QLabel("00:00")
        progressLayout.addWidget(self.currentTimeLabel)
        self.progressSlider = QSlider(Qt.Horizontal)
        self.progressSlider.setRange(0, 1000)
        self.progressSlider.setValue(0)
        self.progressSlider.setToolTip("Seek")
        progressLayout.addWidget(self.progressSlider)
        self.totalTimeLabel = QLabel("00:00")
        progressLayout.addWidget(self.totalTimeLabel)
        volumeSpeedLayout = QHBoxLayout()
        mainLayout.addLayout(volumeSpeedLayout)
        volLayout = QHBoxLayout()
        volumeSpeedLayout.addLayout(volLayout)
        volLabel = QLabel("Volume")
        volLayout.addWidget(volLabel)
        self.volumeSlider = QSlider(Qt.Horizontal)
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setValue(80)
        self.volumeSlider.setFixedWidth(150)
        volLayout.addWidget(self.volumeSlider)
        speedLayout = QHBoxLayout()
        volumeSpeedLayout.addLayout(speedLayout)
        speedLabel = QLabel("Speed")
        speedLayout.addWidget(speedLabel)
        self.speedSlider = QSlider(Qt.Horizontal)
        self.speedSlider.setRange(50, 150)
        self.speedSlider.setValue(100)
        self.speedSlider.setFixedWidth(150)
        speedLayout.addWidget(self.speedSlider)
        self.speedValueLabel = QLabel("1.0x")
        speedLayout.addWidget(self.speedValueLabel)
        eqLayout = QHBoxLayout()
        mainLayout.addLayout(eqLayout)
        eqLabel = QLabel("Equalizer")
        eqLayout.addWidget(eqLabel)
        self.eqComboBox = QComboBox()
        self.eqComboBox.addItems(["Normal", "Bass Boost", "Treble Boost"])
        eqLayout.addWidget(self.eqComboBox)
        self.visualization = pg.PlotWidget()
        self.visualization.setYRange(-32768, 32767)
        self.visualization.hideAxis('bottom')
        self.visualization.hideAxis('left')
        mainLayout.addWidget(self.visualization)
        self.plot_data = self.visualization.plot(pen='y')
        self.nowPlaying = QLabel("Now Playing: None")
        self.nowPlaying.setStyleSheet("font-weight: bold; color: #f33; font-size: 16px;")
        mainLayout.addWidget(self.nowPlaying)
        historyLayout = QHBoxLayout()
        mainLayout.addLayout(historyLayout)
        historyLabel = QLabel("Playback History:")
        historyLayout.addWidget(historyLabel)
        self.historyList = QListWidget()
        self.historyList.setFixedHeight(100)
        historyLayout.addWidget(self.historyList)
        bottomLayout = QHBoxLayout()
        mainLayout.addLayout(bottomLayout)
        self.savePlaylistBtn = QPushButton("Save Playlist")
        bottomLayout.addWidget(self.savePlaylistBtn)
        self.loadPlaylistBtn = QPushButton("Load Playlist")
        bottomLayout.addWidget(self.loadPlaylistBtn)
        self.editTrackBtn = QPushButton("Edit Track Info")
        bottomLayout.addWidget(self.editTrackBtn)
        self.visualizationToggleBtn = QPushButton("Toggle Visualization")
        bottomLayout.addWidget(self.visualizationToggleBtn)
        self.shortcutsBtn = QPushButton("Shortcuts")
        bottomLayout.addWidget(self.shortcutsBtn)
        self.toggleThemeBtn = QPushButton("Toggle Theme")
        bottomLayout.addWidget(self.toggleThemeBtn)
        self.tracks = []
        self.filtered_tracks = []
        self.currentTrackIndex = -1
        self.currentTrack = None
        self.playback_position = 0
        self.audio_thread = None
        self.isUserSeeking = False
        self.isDarkTheme = True
        self.shuffle = False
        self.repeat = False
        self.playback_history = deque(maxlen=100)
        self.eq_settings = "Normal"
        self.visualization_enabled = True
        self.fade_in_duration = 2000
        self.fade_out_duration = 2000
        self.volume_level = 80
        self.playback_speed = 1.0
        self.fileButton.clicked.connect(self.openFileDialog)
        self.addFilesBtn.clicked.connect(self.addSelectedFiles)
        self.playPauseBtn.clicked.connect(self.togglePlayPause)
        self.prevBtn.clicked.connect(self.prevTrack)
        self.nextBtn.clicked.connect(self.nextTrack)
        self.volumeSlider.valueChanged.connect(self.changeVolume)
        self.muteBtn.clicked.connect(self.toggleMute)
        self.speedSlider.valueChanged.connect(self.changeSpeed)
        self.eqComboBox.currentTextChanged.connect(self.changeEQ)
        self.shuffleBtn.clicked.connect(self.toggleShuffle)
        self.repeatBtn.clicked.connect(self.toggleRepeat)
        self.progressSlider.sliderPressed.connect(self.onSeekStart)
        self.progressSlider.sliderReleased.connect(self.onSeekEnd)
        self.savePlaylistBtn.clicked.connect(self.savePlaylist)
        self.loadPlaylistBtn.clicked.connect(self.loadPlaylist)
        self.editTrackBtn.clicked.connect(self.editTrackInfo)
        self.visualizationToggleBtn.clicked.connect(self.toggleVisualization)
        self.searchBar.textChanged.connect(self.filterTracks)
        self.trackList.itemDoubleClicked.connect(self.playSelectedTrack)
        self.historyList.itemDoubleClicked.connect(self.playHistoryTrack)
        self.shortcutsBtn.clicked.connect(self.showShortcutsDialog)
        self.toggleThemeBtn.clicked.connect(self.toggleTheme)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateUI)
        self.timer.start(500)
        self.applyDarkTheme()
        self.setupShortcuts()

    def setupShortcuts(self):
        shortcut_play_pause = QShortcut(QKeySequence("Ctrl+Shift+Space"), self)
        shortcut_play_pause.activated.connect(self.togglePlayPause)
        shortcut_prev = QShortcut(QKeySequence("Ctrl+Shift+Left"), self)
        shortcut_prev.activated.connect(self.prevTrack)
        shortcut_next = QShortcut(QKeySequence("Ctrl+Shift+Right"), self)
        shortcut_next.activated.connect(self.nextTrack)
        for num in range(1, 10):
            key_seq = f"Ctrl+Shift+{num}"
            shortcut = QShortcut(QKeySequence(key_seq), self)
            shortcut.activated.connect(lambda checked, n=num: self.jumpToTrackByNumber(n))
        shortcut_mute = QShortcut(QKeySequence("Ctrl+M"), self)
        shortcut_mute.activated.connect(self.toggleMute)
        shortcut_shuffle = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_shuffle.activated.connect(self.toggleShuffle)
        shortcut_repeat = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut_repeat.activated.connect(self.toggleRepeat)
        shortcut_forward = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_forward.activated.connect(self.forward15)
        shortcut_rewind = QShortcut(QKeySequence("Ctrl+B"), self)
        shortcut_rewind.activated.connect(self.rewind15)

    def applyDarkTheme(self):
        self.isDarkTheme = True
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #222; 
                color: #fff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QPushButton {
                padding: 8px 14px;
                cursor: pointer;
                font-weight: bold;
                border-radius: 4px;
                background: #f33;
                color: #fff;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #c00;
            }
            QSlider {
                background: #222; 
                border-radius: 3px;
            }
            QSlider::groove:horizontal {
                background: #444;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #f33;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #f33;
                border-radius: 4px;
            }
            QListWidget {
                background-color: #111;
                color: #fff;
                border: none;
                font-size: 16px;
            }
            QListWidget::item {
                background-color: #111;
                border-radius: 6px;
                margin: 4px 0;
                padding: 10px;
            }
            QListWidget::item:hover {
                background-color: #222;
            }
            QListWidget::item:selected {
                background-color: #333;
            }
            QLineEdit {
                padding: 5px;
                border: 1px solid #555;
                border-radius: 4px;
                background: #333;
                color: #fff;
            }
            QComboBox {
                padding: 5px;
                border: 1px solid #555;
                border-radius: 4px;
                background: #333;
                color: #fff;
            }
        """)

    def applyLightTheme(self):
        self.isDarkTheme = False
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #f0f0f0; 
                color: #000;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QPushButton {
                padding: 8px 14px;
                cursor: pointer;
                font-weight: bold;
                border-radius: 4px;
                background: #f33;
                color: #fff;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #c00;
            }
            QSlider {
                background: #eee; 
                border-radius: 3px;
            }
            QSlider::groove:horizontal {
                background: #ccc;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #f33;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #f33;
                border-radius: 4px;
            }
            QListWidget {
                background-color: #fff;
                color: #000;
                border: none;
                font-size: 16px;
            }
            QListWidget::item {
                background-color: #fff;
                border-radius: 6px;
                margin: 4px 0;
                padding: 10px;
            }
            QListWidget::item:hover {
                background-color: #ddd;
            }
            QListWidget::item:selected {
                background-color: #bbb;
            }
            QLineEdit {
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background: #fff;
                color: #000;
            }
            QComboBox {
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background: #fff;
                color: #000;
            }
        """)

    def toggleTheme(self):
        if self.isDarkTheme:
            self.applyLightTheme()
        else:
            self.applyDarkTheme()

    def openFileDialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Audio Files", "",
            "Audio Files (*.wav *.aiff *.aif *.ogg *.mp3);;All Files (*)"
        )
        self._pendingFiles = files if files else []

    def addSelectedFiles(self):
        if hasattr(self, '_pendingFiles') and self._pendingFiles:
            start_number = len(self.tracks) + 1
            for idx, f in enumerate(self._pendingFiles, start=start_number):
                trk = AudioTrack(f)
                self.tracks.append(trk)
                self.trackList.addItem(f"{idx}. {trk.metadata['title']} - {trk.metadata['artist']}")
            self._pendingFiles = []
            logging.info("Added selected audio files.")
        else:
            QMessageBox.information(self, "No files selected", "No audio files were chosen.")

    def togglePlayPause(self):
        if self.currentTrackIndex < 0:
            if len(self.tracks) > 0:
                self.currentTrackIndex = 0
                self.playCurrentTrack()
            else:
                QMessageBox.information(self, "No Tracks", "No tracks to play.")
            return
        if not self.audio_thread:
            self.playCurrentTrack()
            return
        if self.audio_thread.pause_event.is_set():
            self.audio_thread.pause_event.clear()
            self.playPauseBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            logging.info("Playback paused.")
        else:
            self.audio_thread.pause_event.set()
            self.playPauseBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            logging.info("Playback resumed.")

    def playCurrentTrack(self):
        self.stopPlayback()
        if not (0 <= self.currentTrackIndex < len(self.tracks)):
            logging.warning(f"Invalid track index: {self.currentTrackIndex}")
            return
        self.currentTrack = self.tracks[self.currentTrackIndex]
        self.nowPlaying.setText(f"Now Playing: {self.currentTrack.metadata['title']} - {self.currentTrack.metadata['artist']}")
        self.playPauseBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.audio_thread = AudioThread(self)
        self.audio_thread.start()
        self.trackList.setCurrentRow(self.currentTrackIndex)
        self.addToHistory(self.currentTrack)
        logging.info(f"Playing track: {self.currentTrack.name}")

    def stopPlayback(self):
        if self.audio_thread:
            self.audio_thread.stop_flag = True
            self.audio_thread.pause_event.set()
            self.audio_thread.join()
            self.audio_thread = None
            self.playPauseBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            logging.info("Playback stopped.")

    def prevTrack(self):
        if len(self.tracks) > 0:
            self.currentTrackIndex = (self.currentTrackIndex - 1) % len(self.tracks)
            self.playback_position = 0
            self.playCurrentTrack()
            logging.info("Switched to previous track.")

    def nextTrack(self):
        if len(self.tracks) > 0:
            if self.shuffle:
                self.currentTrackIndex = random.randint(0, len(self.tracks) - 1)
            else:
                self.currentTrackIndex = (self.currentTrackIndex + 1) % len(self.tracks)
            self.playback_position = 0
            self.playCurrentTrack()
            logging.info("Switched to next track.")

    def rewind15(self):
        self.playback_position = max(0, self.playback_position - 15000)
        if self.audio_thread:
            self.playCurrentTrack()
        logging.info("Rewinded 15 seconds.")

    def forward15(self):
        if not self.currentTrack:
            return
        new_position = self.playback_position + 15000
        if new_position < self.currentTrack.duration * 1000:
            self.playback_position = new_position
            if self.audio_thread:
                self.playCurrentTrack()
            logging.info("Forwarded 15 seconds.")

    def changeVolume(self, value):
        self.volume_level = value
        if self.audio_thread and not self.audio_thread.muted:
            with self.audio_thread.lock:
                self.audio_thread.volume = value / 100.0
            logging.info(f"Volume changed to {value}%.")

    def toggleMute(self):
        if self.audio_thread:
            self.audio_thread.muted = not self.audio_thread.muted
            if self.audio_thread.muted:
                self.muteBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
                logging.info("Audio muted.")
            else:
                self.muteBtn.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
                logging.info("Audio unmuted.")

    def changeSpeed(self, value):
        self.playback_speed = value / 100.0
        self.speedValueLabel.setText(f"{self.playback_speed:.1f}x")
        logging.info(f"Playback speed changed to {self.playback_speed}x.")

    def changeEQ(self, setting):
        self.eq_settings = setting
        logging.info(f"Equalizer setting changed to {setting}.")

    def toggleShuffle(self):
        self.shuffle = self.shuffleBtn.isChecked()
        logging.info(f"Shuffle mode {'enabled' if self.shuffle else 'disabled'}.")

    def toggleRepeat(self):
        self.repeat = self.repeatBtn.isChecked()
        logging.info(f"Repeat mode {'enabled' if self.repeat else 'disabled'}.")

    def onSeekStart(self):
        self.isUserSeeking = True

    def onSeekEnd(self):
        self.isUserSeeking = False
        slider_val = self.progressSlider.value()
        if not self.currentTrack:
            return
        pos_ms = int((slider_val / 1000.0) * self.currentTrack.duration * 1000)
        self.playback_position = pos_ms
        if self.audio_thread:
            self.playCurrentTrack()
        logging.info(f"Seeked to {pos_ms / 1000.0} seconds.")

    def updateUI(self):
        if self.isUserSeeking or not self.currentTrack:
            return
        if self.currentTrack.duration > 0:
            progress_val = int((self.playback_position / (self.currentTrack.duration * 1000)) * 1000)
            progress_val = max(0, min(1000, progress_val))
            self.progressSlider.setValue(progress_val)
            current_sec = self.playback_position // 1000
            total_sec = int(self.currentTrack.duration)
            self.currentTimeLabel.setText(time.strftime('%M:%S', time.gmtime(current_sec)))
            self.totalTimeLabel.setText(time.strftime('%M:%S', time.gmtime(total_sec)))

    def update_visualization(self, chunk, chunk_length):
        if not self.visualization_enabled:
            return
        chunk = chunk.flatten()
        if len(chunk) == 0:
            return
        self.plot_data.setData(chunk)

    def showShortcutsDialog(self):
        dlg = ShortcutsDialog(self)
        dlg.exec_()

    def addToHistory(self, track):
        if track not in self.playback_history:
            self.playback_history.appendleft(track)
            self.historyList.addItem(f"{track.metadata['title']} - {track.metadata['artist']}")

    def playHistoryTrack(self, item):
        index = self.historyList.row(item)
        if index < len(self.playback_history):
            track = self.playback_history[index]
            self.currentTrackIndex = self.tracks.index(track)
            self.playback_position = 0
            self.playCurrentTrack()

    def savePlaylist(self):
        if not self.tracks:
            QMessageBox.information(self, "No Tracks", "There are no tracks to save.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Playlist", "", "M3U Playlist (*.m3u);;Text File (*.txt)")
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    for track in self.tracks:
                        f.write(f"{track.path}\n")
                QMessageBox.information(self, "Success", "Playlist saved successfully.")
                logging.info(f"Playlist saved to {file_path}.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save playlist: {e}")
                logging.error(f"Failed to save playlist: {e}")

    def loadPlaylist(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Playlist", "", "M3U Playlist (*.m3u);;Text File (*.txt)")
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                self.tracks.clear()
                self.trackList.clear()
                for idx, line in enumerate(lines, start=1):
                    path = line.strip()
                    if os.path.isfile(path):
                        trk = AudioTrack(path)
                        self.tracks.append(trk)
                        self.trackList.addItem(f"{idx}. {trk.metadata['title']} - {trk.metadata['artist']}")
                QMessageBox.information(self, "Success", "Playlist loaded successfully.")
                logging.info(f"Playlist loaded from {file_path}.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load playlist: {e}")
                logging.error(f"Failed to load playlist: {e}")

    def editTrackInfo(self):
        selected_items = self.trackList.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a track to edit.")
            return
        item = selected_items[0]
        index = self.trackList.row(item)
        track = self.tracks[index]
        title, ok1 = QInputDialog.getText(self, "Edit Title", "Enter new title:", text=track.metadata['title'])
        if ok1:
            artist, ok2 = QInputDialog.getText(self, "Edit Artist", "Enter new artist:", text=track.metadata['artist'])
            if ok2:
                album, ok3 = QInputDialog.getText(self, "Edit Album", "Enter new album:", text=track.metadata['album'])
                if ok3:
                    track.metadata['title'] = title
                    track.metadata['artist'] = artist
                    track.metadata['album'] = album
                    self.trackList.item(index).setText(f"{index + 1}. {title} - {artist}")
                    QMessageBox.information(self, "Success", "Track information updated.")
                    logging.info(f"Edited track info: {track.name}")

    def toggleVisualization(self):
        self.visualization_enabled = not self.visualization_enabled
        if not self.visualization_enabled:
            self.visualization.hide()
            self.visualizationToggleBtn.setText("Show Visualization")
        else:
            self.visualization.show()
            self.visualizationToggleBtn.setText("Hide Visualization")
        logging.info(f"Visualization {'enabled' if self.visualization_enabled else 'disabled'}.")

    def filterTracks(self, text):
        self.trackList.clear()
        for idx, track in enumerate(self.tracks, start=1):
            if (text.lower() in track.metadata['title'].lower() or
                text.lower() in track.metadata['artist'].lower() or
                text.lower() in track.metadata['album'].lower()):
                self.trackList.addItem(f"{idx}. {track.metadata['title']} - {track.metadata['artist']}")
        logging.info(f"Filtered tracks with search text: '{text}'.")

    def playSelectedTrack(self, item):
        index = self.trackList.row(item)
        if index < len(self.tracks):
            self.currentTrackIndex = index
            self.playback_position = 0
            self.playCurrentTrack()

    def playback_finished(self):
        self.audio_thread = None
        if self.repeat:
            self.playCurrentTrack()
        else:
            self.nextTrack()

    def showTrackContextMenu(self, position):
        menu = QMenu()
        removeAction = QAction("Remove Track", self)
        removeAction.triggered.connect(lambda: self.removeTrackAt(position))
        menu.addAction(removeAction)
        menu.exec_(self.trackList.viewport().mapToGlobal(position))

    def removeTrackAt(self, position):
        row = self.trackList.indexAt(position).row()
        if row >= 0 and row < len(self.tracks):
            removed_track = self.tracks.pop(row)
            self.trackList.takeItem(row)
            QMessageBox.information(self, "Removed", f"Removed track: {removed_track.name}")
            logging.info(f"Removed track: {removed_track.name}")
            if row == self.currentTrackIndex:
                self.stopPlayback()
            elif row < self.currentTrackIndex:
                self.currentTrackIndex -= 1

    def jumpToTrackByNumber(self, track_number):
        if 1 <= track_number <= len(self.tracks):
            self.currentTrackIndex = track_number - 1
            self.playback_position = 0
            self.playCurrentTrack()
            logging.info(f"Jumped to track number: {track_number}")
        else:
            QMessageBox.warning(self, "Invalid Track Number", "Track number out of range.")

    def show_error_message(self, message):
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        self.stopPlayback()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = AudioPlayerWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
