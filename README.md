# Video Player with VLC - PyQt Version

This project is a simple **Video Player** built using the **VLC media player** and **PyQt5**. The application allows users to select video files, play, pause, stop, capture screenshots, and more. This is a new version of the video player that uses **PyQt5** instead of the previously used **Tkinter** for the graphical user interface (GUI).

## Features

- **Select video folder** to load and display video files.
- **Play, Pause, Stop** video controls.
- **Screenshot capture** functionality.
- **Progress bar** for tracking video playback.
- Supports multiple video formats: `.mp4`, `.avi`, `.mov`, `.mkv`.

## Requirements

- Python 3.x
- PyQt5
- VLC media player (libvlc)
- ffmpeg (for handling rotation of video screenshots)
- Pillow (for image processing)

You can install the required Python packages using the following commands:

`pip install PyQt5 python-vlc ffmpeg-python Pillow`

## Installation

1. Clone the repository:

`git clone https://github.com/your-username/video-player-pyqt.git`
`cd video-player-pyqt`

2. Install the required dependencies listed above.

3. Run the `video_player.py` script:

`python video_player.py`

## Screenshots

Here's a preview of the video player interface:

![Screenshot](screenshot_qt.png)

## Future Enhancements

- Add support for more video formats.
- Implement additional controls like volume control and video speed adjustments.
- Provide more customization options for the GUI.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
