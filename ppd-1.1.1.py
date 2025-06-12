#!/usr/bin/env python3
"""
Plex Playlist Downloader
A GUI application for downloading playlists from a local Plex Media Server

CHANGELOG:
v1.1.1 (2025-01-11):
- Added automatic installation of missing dependencies (plexapi and requests)
- Script now attempts to install packages if they're not found
- Falls back to manual installation instructions if auto-install fails

v1.1.0 (2025-01-11):
- Added multi-select capability for playlists (use Ctrl/Cmd+click or Shift+click)
- Added download queue window to manage multiple playlist downloads
- Queue shows playlist type, name, item count, and status
- Downloads process automatically one after another
- Can remove items from queue or clear entire queue
- Queue persists until cleared or all downloads complete

v1.0.9 (2025-01-11):
- Fixed individual file speed display to show real-time updates
- Changed to always use streaming downloads for accurate speed tracking
- Increased chunk size to 32KB for better performance
- Speed now updates every 0.1 seconds during download

v1.0.8 (2025-01-11):
- Added download speed display in MB/s for current file
- Added overall transfer speed in MB/s for entire playlist
- Shows total MB downloaded and average speed on completion
- Real-time speed updates during downloads

v1.0.7 (2025-01-11):
- FIXED: Major performance issue - playlist loading now instant instead of 5 minutes
- Changed to use leafCount instead of len(playlist.items()) to avoid fetching all items
- No longer downloads entire playlist content just to count items

v1.0.6 (2025-01-11):
- Added performance debugging to identify startup delays
- Added timing logs for all major operations
- Added Analyze button to check for performance issues
- Improved startup sequence logging

v1.0.5 (2025-01-11):
- Fixed startup delay by properly loading cached playlists
- Fixed folder structure - all files now download directly to playlist folder
- Music files no longer create individual subfolders
- Improved download method parameters for better control

v1.0.4 (2025-01-11):
- Fixed music file naming - removed incorrect TV show formatting
- Music files now named as: Artist - Album - Track# - Title
- Improved filename generation based on media type (track/episode/movie)
- Added year to movie filenames

v1.0.3 (2025-01-11):
- Fixed download functionality for different plexapi versions
- Improved filename generation for different media types
- Added fallback download method using direct URL requests
- Better progress tracking during downloads

v1.0.2 (2025-01-11):
- Added playlist caching functionality
- Added reload playlists button
- Playlists now load from cache on startup
- Cache updates automatically after successful connection

v1.0.1 (2025-01-11):
- Fixed connection issue by stripping whitespace from input fields
- Added automatic whitespace trimming for server address and token

v1.0.0 (2025-01-11):
- Initial release with full GUI interface
- Support for music and video playlist downloads
- Configuration save/load functionality
- Progress tracking and status updates
- Activity logging
- Stop download functionality
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import json
import os
import sys
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
import queue

# Set environment variable to disable Plex auto-discovery
os.environ['PLEXAPI_ENABLE_FAST_CONNECT'] = 'false'
os.environ['PLEXAPI_AUTORELOAD'] = 'false'
os.environ['PLEXAPI_LOG_BACKUP_COUNT'] = '0'

# Time the imports
import_start = time.time()
print(f"Starting PlexAPI import at {import_start}")

try:
    from plexapi.server import PlexServer
    from plexapi.exceptions import Unauthorized, NotFound
    import requests
    import_time = time.time() - import_start
    print(f"PlexAPI import completed in {import_time:.2f} seconds")
except ImportError as e:
    print(f"Missing required packages: {str(e)}")
    print("Attempting to install required packages...")

    try:
        import subprocess
        import sys

        # Install missing packages
        packages = ['plexapi', 'requests']
        for package in packages:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])

        print("Packages installed successfully. Attempting to import again...")

        # Try importing again
        from plexapi.server import PlexServer
        from plexapi.exceptions import Unauthorized, NotFound
        import requests

        print("Import successful after installation!")

    except subprocess.CalledProcessError:
        messagebox.showerror("Installation Error",
                           "Failed to install required packages automatically.\n\n"
                           "Please install manually by running:\n"
                           "pip install plexapi requests\n\n"
                           "Or if using pip3:\n"
                           "pip3 install plexapi requests")
        exit(1)
    except ImportError:
        messagebox.showerror("Import Error",
                           "Failed to import packages after installation.\n\n"
                           "Please install manually by running:\n"
                           "pip install plexapi requests")
        exit(1)
    except Exception as install_error:
        messagebox.showerror("Error",
                           f"An unexpected error occurred:\n{str(install_error)}\n\n"
                           "Please install packages manually:\n"
                           "pip install plexapi requests")
        exit(1)

# ===== CONFIGURATION SECTION =====
DEFAULT_CONFIG = {
    'plex_address': 'http://localhost:32400',
    'plex_token': '',
    'download_directory': str(Path.home() / 'Downloads' / 'PlexPlaylists')
}

CONFIG_FILE = 'plex_downloader_config.json'
LOG_FILE = 'plex_downloader.log'
CACHE_FILE = 'plex_playlist_cache.json'

# ===== LOGGING SETUP =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== LOCAL CONNECTION SECTION =====
class PlexConnection:
    def __init__(self):
        self.server = None
        self.connected = False

    def connect(self, address, token):
        """Connect to Plex server"""
        try:
            self.server = PlexServer(address, token)
            self.connected = True
            logger.info(f"Successfully connected to Plex server at {address}")
            return True, "Connected successfully"
        except Unauthorized:
            logger.error("Invalid Plex token")
            return False, "Invalid Plex token"
        except Exception as e:
            logger.error(f"Connection failed: {str(e)}")
            return False, f"Connection failed: {str(e)}"

    def disconnect(self):
        """Disconnect from Plex server"""
        self.server = None
        self.connected = False
        logger.info("Disconnected from Plex server")

# ===== MUSIC PLAYLISTS SECTION =====
class MusicPlaylistHandler:
    def __init__(self, plex_connection):
        self.plex = plex_connection

    def get_music_playlists(self):
        """Get all music playlists from server"""
        if not self.plex.connected:
            return []

        try:
            start_time = time.time()
            logger.info("Fetching all playlists from server...")
            playlists = self.plex.server.playlists()
            fetch_time = time.time() - start_time
            logger.info(f"Fetched {len(playlists)} total playlists in {fetch_time:.2f} seconds")

            music_playlists = []
            filter_start = time.time()

            for playlist in playlists:
                if hasattr(playlist, 'playlistType') and playlist.playlistType == 'audio':
                    # Use leafCount instead of len(playlist.items()) to avoid fetching all items
                    item_count = playlist.leafCount if hasattr(playlist, 'leafCount') else 0
                    music_playlists.append({
                        'title': playlist.title,
                        'items': item_count,
                        'object': playlist
                    })

            filter_time = time.time() - filter_start
            logger.info(f"Filtered {len(music_playlists)} music playlists in {filter_time:.2f} seconds")
            return music_playlists
        except Exception as e:
            logger.error(f"Error getting music playlists: {str(e)}")
            return []

# ===== VIDEO PLAYLISTS SECTION =====
class VideoPlaylistHandler:
    def __init__(self, plex_connection):
        self.plex = plex_connection

    def get_video_playlists(self):
        """Get all video playlists from server"""
        if not self.plex.connected:
            return []

        try:
            start_time = time.time()
            logger.info("Fetching all playlists from server...")
            playlists = self.plex.server.playlists()
            fetch_time = time.time() - start_time
            logger.info(f"Fetched {len(playlists)} total playlists in {fetch_time:.2f} seconds")

            video_playlists = []
            filter_start = time.time()

            for playlist in playlists:
                if hasattr(playlist, 'playlistType') and playlist.playlistType == 'video':
                    # Use leafCount instead of len(playlist.items()) to avoid fetching all items
                    item_count = playlist.leafCount if hasattr(playlist, 'leafCount') else 0
                    video_playlists.append({
                        'title': playlist.title,
                        'items': item_count,
                        'object': playlist
                    })

            filter_time = time.time() - filter_start
            logger.info(f"Filtered {len(video_playlists)} video playlists in {filter_time:.2f} seconds")
            return video_playlists
        except Exception as e:
            logger.error(f"Error getting video playlists: {str(e)}")
            return []

# ===== LOCAL DOWNLOADS SECTION =====
class DownloadManager:
    def __init__(self):
        self.current_download = None
        self.stop_flag = False
        self.download_thread = None
        self.progress_queue = queue.Queue()
        self.current_speed = 0
        self.overall_start_time = None
        self.overall_bytes_downloaded = 0

    def download_playlist(self, playlist, download_dir, progress_callback, status_callback):
        """Download all items in a playlist"""
        self.stop_flag = False
        self.overall_start_time = time.time()
        self.overall_bytes_downloaded = 0

        playlist_dir = os.path.join(download_dir, self._sanitize_filename(playlist.title))
        os.makedirs(playlist_dir, exist_ok=True)

        items = playlist.items()
        total_items = len(items)

        logger.info(f"Starting download of playlist '{playlist.title}' with {total_items} items")
        status_callback(f"Downloading playlist: {playlist.title}")

        for idx, item in enumerate(items):
            if self.stop_flag:
                logger.info("Download stopped by user")
                status_callback("Download stopped")
                break

            try:
                # Determine the filename based on item type
                if hasattr(item, 'type'):
                    if item.type == 'track':  # Music track
                        if hasattr(item, 'grandparentTitle') and hasattr(item, 'parentTitle'):
                            # Artist - Album - Track# - Title
                            track_num = f"{item.index:02d} - " if hasattr(item, 'index') and item.index else ""
                            filename = self._sanitize_filename(f"{item.grandparentTitle} - {item.parentTitle} - {track_num}{item.title}")
                        elif hasattr(item, 'originalTitle'):
                            # Artist - Title
                            filename = self._sanitize_filename(f"{item.originalTitle} - {item.title}")
                        else:
                            filename = self._sanitize_filename(item.title)
                    elif item.type == 'episode':  # TV Episode
                        filename = self._sanitize_filename(f"{item.grandparentTitle} - S{item.parentIndex:02d}E{item.index:02d} - {item.title}")
                    elif item.type == 'movie':  # Movie
                        year = f" ({item.year})" if hasattr(item, 'year') and item.year else ""
                        filename = self._sanitize_filename(f"{item.title}{year}")
                    else:
                        filename = self._sanitize_filename(item.title)
                else:
                    filename = self._sanitize_filename(item.title)

                # Get the file extension
                if hasattr(item, 'media') and item.media:
                    container = item.media[0].container
                    filename = f"{filename}.{container}"
                else:
                    filename = f"{filename}.mp4"  # Default extension

                # File goes directly in playlist directory
                filepath = os.path.join(playlist_dir, filename)

                # Skip if already exists
                if os.path.exists(filepath):
                    logger.info(f"Skipping existing file: {filename}")
                    progress_callback(idx + 1, total_items, filename, 100, 0, 0)
                    continue

                # Update progress
                self.current_download = filename
                progress_callback(idx + 1, total_items, filename, 0, 0, 0)

                # Always use streaming download for real-time progress
                # Get the download URL
                download_url = item._server.url(item.media[0].parts[0].key)

                # Download the file
                import requests
                response = requests.get(download_url, headers={'X-Plex-Token': item._server._token}, stream=True)
                response.raise_for_status()

                # Write the file with progress tracking
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                file_start_time = time.time()
                last_update = time.time()
                chunk_size = 32768  # 32KB chunks for better speed calculation

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if self.stop_flag:
                            break
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            self.overall_bytes_downloaded += len(chunk)

                            # Update progress every 0.1 seconds
                            current_time = time.time()
                            if current_time - last_update > 0.1:
                                if total_size > 0:
                                    percent = int((downloaded / total_size) * 100)
                                    elapsed = current_time - file_start_time
                                    speed = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                                    overall_elapsed = current_time - self.overall_start_time
                                    overall_speed = (self.overall_bytes_downloaded / (1024 * 1024)) / overall_elapsed if overall_elapsed > 0 else 0
                                    progress_callback(idx + 1, total_items, filename, percent, speed, overall_speed)
                                    last_update = current_time

                logger.info(f"Downloaded: {filename}")

                # Final update with 100%
                overall_elapsed = time.time() - self.overall_start_time
                overall_speed = (self.overall_bytes_downloaded / (1024 * 1024)) / overall_elapsed if overall_elapsed > 0 else 0
                progress_callback(idx + 1, total_items, filename, 100, 0, overall_speed)

            except Exception as e:
                logger.error(f"Error downloading {item.title}: {str(e)}")
                continue

        if not self.stop_flag:
            overall_elapsed = time.time() - self.overall_start_time
            total_mb = self.overall_bytes_downloaded / (1024 * 1024)
            avg_speed = total_mb / overall_elapsed if overall_elapsed > 0 else 0
            status_callback(f"Completed downloading playlist: {playlist.title} ({total_mb:.2f} MB at {avg_speed:.2f} MB/s)")
            logger.info(f"Completed downloading playlist: {playlist.title}")

    def stop_download(self):
        """Stop current download"""
        self.stop_flag = True
        logger.info("Stop download requested")

    def _sanitize_filename(self, filename):
        """Remove invalid characters from filename"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename

# ===== MAIN GUI APPLICATION =====
class PlexPlaylistDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Plex Playlist Downloader v1.0.0")
        self.root.geometry("1000x900")
        self.root.minsize(900, 700)  # Set minimum window size

        # Debug timing
        start_time = time.time()
        logger.info("=== STARTUP BEGIN ===")

        # Run analysis first to catch early issues
        self.early_analysis()

        # Initialize components
        logger.info("Initializing components...")
        self.plex_connection = PlexConnection()
        self.music_handler = MusicPlaylistHandler(self.plex_connection)
        self.video_handler = VideoPlaylistHandler(self.plex_connection)
        self.download_manager = DownloadManager()

        # Variables
        self.config = DEFAULT_CONFIG.copy()
        self.music_playlists = []
        self.video_playlists = []
        self.download_queue = []
        self.queue_window = None
        self.is_downloading = False
        self.current_queue_item = None

        # Create GUI
        logger.info("Creating GUI widgets...")
        self.create_widgets()

        logger.info("Loading configuration...")
        self.load_config()

        logger.info("Loading cached playlists...")
        self.load_cached_playlists()

        # Log startup
        elapsed = time.time() - start_time
        logger.info(f"=== STARTUP COMPLETE in {elapsed:.2f} seconds ===")
        self.update_activity(f"Application started (took {elapsed:.2f}s)")

        # Run post-startup analysis
        self.post_startup_analysis()

    def create_widgets(self):
        """Create all GUI widgets"""
        # Top third - Configuration
        config_frame = ttk.LabelFrame(self.root, text="Configuration", padding=10)
        config_frame.pack(fill=tk.X, padx=10, pady=5)

        # Server address
        ttk.Label(config_frame, text="Plex Server Address:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.address_var = tk.StringVar(value=self.config['plex_address'])
        self.address_entry = ttk.Entry(config_frame, textvariable=self.address_var, width=40)
        self.address_entry.grid(row=0, column=1, padx=5, pady=2)

        # Token
        ttk.Label(config_frame, text="Plex Token:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.token_var = tk.StringVar(value=self.config['plex_token'])
        self.token_entry = ttk.Entry(config_frame, textvariable=self.token_var, width=40, show="*")
        self.token_entry.grid(row=1, column=1, padx=5, pady=2)

        # Download directory
        ttk.Label(config_frame, text="Download Directory:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.download_dir_var = tk.StringVar(value=self.config['download_directory'])
        self.download_dir_entry = ttk.Entry(config_frame, textvariable=self.download_dir_var, width=40)
        self.download_dir_entry.grid(row=2, column=1, padx=5, pady=2)
        self.browse_button = ttk.Button(config_frame, text="Browse", command=self.browse_directory)
        self.browse_button.grid(row=2, column=2, padx=5, pady=2)

        # Control buttons
        button_frame = ttk.Frame(config_frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=10)

        self.connect_button = ttk.Button(button_frame, text="Connect to Plex", command=self.connect_to_plex)
        self.connect_button.pack(side=tk.LEFT, padx=5)

        self.reload_button = ttk.Button(button_frame, text="Reload Playlists", command=self.reload_playlists, state=tk.DISABLED)
        self.reload_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(button_frame, text="Save Config", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Load Config", command=self.load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Analyze", command=self.analyze_performance).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Quit", command=self.quit_app).pack(side=tk.LEFT, padx=5)

        # Middle - Playlists
        playlist_frame = ttk.LabelFrame(self.root, text="Playlists", padding=10)
        playlist_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Selection tip
        tip_label = ttk.Label(playlist_frame,
                            text="Tip: Double-click to add individual playlists. Use Shift+click for range selection. Click buttons below to add multiple selected playlists.",
                            font=('Arial', 9, 'italic'), foreground='gray')
        tip_label.pack(pady=(0, 5))

        # Music playlists
        music_frame = ttk.Frame(playlist_frame)
        music_frame.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=5)

        music_header_frame = ttk.Frame(music_frame)
        music_header_frame.pack(fill=tk.X)

        ttk.Label(music_header_frame, text="Music Playlists", font=('Arial', 10, 'bold')).pack(side=tk.LEFT)

        # Create frame for listbox and scrollbar
        music_list_frame = ttk.Frame(music_frame)
        music_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.music_listbox = tk.Listbox(music_list_frame, selectmode=tk.EXTENDED, width=50)
        self.music_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind double-click event
        self.music_listbox.bind('<Double-Button-1>', self.on_music_double_click)

        music_scrollbar = ttk.Scrollbar(music_list_frame, orient=tk.VERTICAL)
        music_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.music_listbox.config(yscrollcommand=music_scrollbar.set)
        music_scrollbar.config(command=self.music_listbox.yview)

        # Add horizontal scrollbar for long playlist names
        music_h_scrollbar = ttk.Scrollbar(music_frame, orient=tk.HORIZONTAL)
        music_h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.music_listbox.config(xscrollcommand=music_h_scrollbar.set)
        music_h_scrollbar.config(command=self.music_listbox.xview)

        # Video playlists
        video_frame = ttk.Frame(playlist_frame)
        video_frame.pack(fill=tk.BOTH, expand=True, side=tk.RIGHT, padx=5)

        video_header_frame = ttk.Frame(video_frame)
        video_header_frame.pack(fill=tk.X)

        ttk.Label(video_header_frame, text="Video Playlists", font=('Arial', 10, 'bold')).pack(side=tk.LEFT)

        # Create frame for listbox and scrollbar
        video_list_frame = ttk.Frame(video_frame)
        video_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.video_listbox = tk.Listbox(video_list_frame, selectmode=tk.EXTENDED, width=50)
        self.video_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind double-click event
        self.video_listbox.bind('<Double-Button-1>', self.on_video_double_click)

        video_scrollbar = ttk.Scrollbar(video_list_frame, orient=tk.VERTICAL)
        video_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.video_listbox.config(yscrollcommand=video_scrollbar.set)
        video_scrollbar.config(command=self.video_listbox.yview)

        # Add horizontal scrollbar for long playlist names
        video_h_scrollbar = ttk.Scrollbar(video_frame, orient=tk.HORIZONTAL)
        video_h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.video_listbox.config(xscrollcommand=video_h_scrollbar.set)
        video_h_scrollbar.config(command=self.video_listbox.xview)

        # Download status
        status_frame = ttk.LabelFrame(self.root, text="Download Status", padding=10)
        status_frame.pack(fill=tk.X, padx=10, pady=5)

        self.status_label = ttk.Label(status_frame, text="Not connected to Plex server")
        self.status_label.pack(pady=5)

        # Queue status
        self.queue_status_label = ttk.Label(status_frame, text="Queue: 0 playlists", font=('Arial', 9, 'italic'))
        self.queue_status_label.pack(pady=2)

        # Download buttons
        download_button_frame = ttk.Frame(status_frame)
        download_button_frame.pack(pady=5)

        self.download_music_button = ttk.Button(download_button_frame, text="Add Music Playlists to Queue",
                                               command=self.add_music_to_queue, state=tk.DISABLED)
        self.download_music_button.pack(side=tk.LEFT, padx=5)

        self.download_video_button = ttk.Button(download_button_frame, text="Add Video Playlists to Queue",
                                               command=self.add_video_to_queue, state=tk.DISABLED)
        self.download_video_button.pack(side=tk.LEFT, padx=5)

        self.show_queue_button = ttk.Button(download_button_frame, text="Show Queue (0)",
                                           command=self.show_queue_window)
        self.show_queue_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(download_button_frame, text="Stop Download",
                                     command=self.stop_download, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # Progress bar
        progress_frame = ttk.LabelFrame(self.root, text="Current Download Progress", padding=10)
        progress_frame.pack(fill=tk.X, padx=10, pady=5)

        self.file_label = ttk.Label(progress_frame, text="No active download")
        self.file_label.pack(pady=2)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100,
                                           length=700, mode='determinate')
        self.progress_bar.pack(pady=5)

        # Progress info frame for percentage and speed
        progress_info_frame = ttk.Frame(progress_frame)
        progress_info_frame.pack()

        self.progress_label = ttk.Label(progress_info_frame, text="0%")
        self.progress_label.pack(side=tk.LEFT, padx=10)

        self.speed_label = ttk.Label(progress_info_frame, text="0.0 MB/s")
        self.speed_label.pack(side=tk.LEFT, padx=10)

        # Activity window
        activity_frame = ttk.LabelFrame(self.root, text="Activity Log", padding=10)
        activity_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.activity_text = scrolledtext.ScrolledText(activity_frame, height=8, wrap=tk.WORD)
        self.activity_text.pack(fill=tk.BOTH, expand=True)

    def browse_directory(self):
        """Browse for download directory"""
        directory = filedialog.askdirectory(initialdir=self.download_dir_var.get())
        if directory:
            self.download_dir_var.set(directory)
            self.update_activity(f"Download directory set to: {directory}")

    def connect_to_plex(self):
        """Connect to Plex server"""
        start_time = time.time()
        logger.info("=== CONNECT TO PLEX BEGIN ===")

        address = self.address_var.get().strip()
        token = self.token_var.get().strip()

        if not address or not token:
            messagebox.showerror("Error", "Please enter both server address and token")
            return

        # Update the variables with stripped values
        self.address_var.set(address)
        self.token_var.set(token)

        self.update_activity(f"Connecting to Plex server at {address}...")
        logger.info(f"Attempting connection to {address}")

        success, message = self.plex_connection.connect(address, token)

        connect_time = time.time() - start_time
        logger.info(f"Connection attempt took {connect_time:.2f} seconds")

        if success:
            self.status_label.config(text="Connected to Plex server")
            self.connect_button.config(text="Reconnect")
            self.reload_button.config(state=tk.NORMAL)
            self.download_music_button.config(state=tk.NORMAL)
            self.download_video_button.config(state=tk.NORMAL)
            self.update_activity("Successfully connected to Plex server")

            logger.info("Starting playlist refresh...")
            refresh_start = time.time()
            self.refresh_playlists()
            refresh_time = time.time() - refresh_start
            logger.info(f"Playlist refresh took {refresh_time:.2f} seconds")

            total_time = time.time() - start_time
            logger.info(f"=== CONNECT TO PLEX COMPLETE in {total_time:.2f} seconds ===")
        else:
            messagebox.showerror("Connection Error", message)
            self.update_activity(f"Connection failed: {message}")
            logger.info(f"=== CONNECT TO PLEX FAILED in {connect_time:.2f} seconds ===")

    def refresh_playlists(self):
        """Refresh playlist lists"""
        # Clear existing lists
        self.music_listbox.delete(0, tk.END)
        self.video_listbox.delete(0, tk.END)

        # Get music playlists
        self.music_playlists = self.music_handler.get_music_playlists()
        for playlist in self.music_playlists:
            self.music_listbox.insert(tk.END, f"{playlist['title']} ({playlist['items']} items)")

        # Get video playlists
        self.video_playlists = self.video_handler.get_video_playlists()
        for playlist in self.video_playlists:
            self.video_listbox.insert(tk.END, f"{playlist['title']} ({playlist['items']} items)")

        self.update_activity(f"Found {len(self.music_playlists)} music and {len(self.video_playlists)} video playlists")

        # Cache the playlists
        self.cache_playlists()

    def reload_playlists(self):
        """Reload playlists from server"""
        if not self.plex_connection.connected:
            messagebox.showwarning("Not Connected", "Please connect to Plex server first")
            return

        self.update_activity("Reloading playlists from server...")
        self.refresh_playlists()
        self.update_activity("Playlists reloaded successfully")

    def cache_playlists(self):
        """Cache playlists to file"""
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'music_playlists': [
                {'title': p['title'], 'items': p['items']}
                for p in self.music_playlists
            ],
            'video_playlists': [
                {'title': p['title'], 'items': p['items']}
                for p in self.video_playlists
            ]
        }

        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(cache_data, f, indent=4)
            logger.info("Playlists cached successfully")
        except Exception as e:
            logger.error(f"Error caching playlists: {str(e)}")

    def load_cached_playlists(self):
        """Load playlists from cache file"""
        if not os.path.exists(CACHE_FILE):
            self.update_activity("No playlist cache found")
            return

        try:
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)

            # Clear existing lists
            self.music_listbox.delete(0, tk.END)
            self.video_listbox.delete(0, tk.END)

            # Store cached data without objects
            self.music_playlists = cache_data.get('music_playlists', [])
            self.video_playlists = cache_data.get('video_playlists', [])

            # Load music playlists
            for playlist in self.music_playlists:
                self.music_listbox.insert(tk.END, f"{playlist['title']} ({playlist['items']} items)")

            # Load video playlists
            for playlist in self.video_playlists:
                self.video_listbox.insert(tk.END, f"{playlist['title']} ({playlist['items']} items)")

            timestamp = cache_data.get('timestamp', 'Unknown')
            cache_time = datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            self.update_activity(f"Loaded playlists from cache (cached at {cache_time})")

            # Update status to show cached data
            self.status_label.config(text="Playlists loaded from cache - Connect to server to download")

        except Exception as e:
            logger.error(f"Error loading cached playlists: {str(e)}")
            self.update_activity(f"Error loading playlist cache: {str(e)}")

    def add_music_to_queue(self):
        """Add selected music playlists to download queue"""
        selections = self.music_listbox.curselection()
        if not selections:
            messagebox.showwarning("No Selection", "Please select at least one music playlist")
            return

        added = 0
        for idx in selections:
            if idx < len(self.music_playlists) and 'object' in self.music_playlists[idx]:
                playlist_info = {
                    'playlist': self.music_playlists[idx]['object'],
                    'title': self.music_playlists[idx]['title'],
                    'items': self.music_playlists[idx]['items'],
                    'type': 'Music',
                    'status': 'Queued',
                    'downloaded': 0,
                    'remaining': self.music_playlists[idx]['items']
                }
                # Check if already in queue
                if not any(q['title'] == playlist_info['title'] for q in self.download_queue):
                    self.download_queue.append(playlist_info)
                    added += 1

        if added > 0:
            self.update_activity(f"Added {added} music playlist(s) to queue. Total in queue: {len(self.download_queue)}")
            self.update_queue_window()

    def add_video_to_queue(self):
        """Add selected video playlists to download queue"""
        selections = self.video_listbox.curselection()
        if not selections:
            messagebox.showwarning("No Selection", "Please select at least one video playlist")
            return

        added = 0
        for idx in selections:
            if idx < len(self.video_playlists) and 'object' in self.video_playlists[idx]:
                playlist_info = {
                    'playlist': self.video_playlists[idx]['object'],
                    'title': self.video_playlists[idx]['title'],
                    'items': self.video_playlists[idx]['items'],
                    'type': 'Video',
                    'status': 'Queued',
                    'downloaded': 0,
                    'remaining': self.video_playlists[idx]['items']
                }
                # Check if already in queue
                if not any(q['title'] == playlist_info['title'] for q in self.download_queue):
                    self.download_queue.append(playlist_info)
                    added += 1

        if added > 0:
            self.update_activity(f"Added {added} video playlist(s) to queue. Total in queue: {len(self.download_queue)}")
            self.update_queue_window()

    def on_music_double_click(self, event):
        """Handle double-click on music playlist"""
        selection = self.music_listbox.curselection()
        if selection and self.plex_connection.connected:
            idx = selection[0]
            if idx < len(self.music_playlists) and 'object' in self.music_playlists[idx]:
                playlist_info = {
                    'playlist': self.music_playlists[idx]['object'],
                    'title': self.music_playlists[idx]['title'],
                    'items': self.music_playlists[idx]['items'],
                    'type': 'Music',
                    'status': 'Queued',
                    'downloaded': 0,
                    'remaining': self.music_playlists[idx]['items']
                }
                # Check if already in queue
                if not any(q['title'] == playlist_info['title'] for q in self.download_queue):
                    self.download_queue.append(playlist_info)
                    self.update_activity(f"Double-clicked: Added '{playlist_info['title']}' to queue")
                    self.update_queue_window()
                else:
                    self.update_activity(f"'{playlist_info['title']}' is already in queue")

    def on_video_double_click(self, event):
        """Handle double-click on video playlist"""
        selection = self.video_listbox.curselection()
        if selection and self.plex_connection.connected:
            idx = selection[0]
            if idx < len(self.video_playlists) and 'object' in self.video_playlists[idx]:
                playlist_info = {
                    'playlist': self.video_playlists[idx]['object'],
                    'title': self.video_playlists[idx]['title'],
                    'items': self.video_playlists[idx]['items'],
                    'type': 'Video',
                    'status': 'Queued',
                    'downloaded': 0,
                    'remaining': self.video_playlists[idx]['items']
                }
                # Check if already in queue
                if not any(q['title'] == playlist_info['title'] for q in self.download_queue):
                    self.download_queue.append(playlist_info)
                    self.update_activity(f"Double-clicked: Added '{playlist_info['title']}' to queue")
                    self.update_queue_window()
                else:
                    self.update_activity(f"'{playlist_info['title']}' is already in queue")

    def show_queue_window(self):
        """Show the download queue window"""
        if self.queue_window and self.queue_window.winfo_exists():
            self.queue_window.lift()
            return

        self.queue_window = tk.Toplevel(self.root)
        self.queue_window.title("Download Queue")
        self.queue_window.geometry("900x500")

        # Queue list frame
        list_frame = ttk.Frame(self.queue_window, padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        # Create Treeview for better column alignment
        columns = ('Type', 'Playlist', 'Total', 'Downloaded', 'Remaining', 'Status')
        self.queue_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)

        # Define column headings and widths
        self.queue_tree.heading('Type', text='Type', anchor='center')
        self.queue_tree.heading('Playlist', text='Playlist', anchor='center')
        self.queue_tree.heading('Total', text='Total Items', anchor='center')
        self.queue_tree.heading('Downloaded', text='Downloaded', anchor='center')
        self.queue_tree.heading('Remaining', text='Remaining', anchor='center')
        self.queue_tree.heading('Status', text='Status', anchor='center')

        # Configure column widths and alignment
        self.queue_tree.column('Type', width=80, minwidth=60, anchor='center')
        self.queue_tree.column('Playlist', width=350, minwidth=200, anchor='w')  # Left align playlist names
        self.queue_tree.column('Total', width=100, minwidth=80, anchor='center')
        self.queue_tree.column('Downloaded', width=100, minwidth=80, anchor='center')
        self.queue_tree.column('Remaining', width=100, minwidth=80, anchor='center')
        self.queue_tree.column('Status', width=120, minwidth=80, anchor='center')

        # Add scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=scrollbar.set)

        # Pack treeview and scrollbar
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Totals frame
        totals_frame = ttk.LabelFrame(self.queue_window, text="Queue Totals", padding=10)
        totals_frame.pack(fill=tk.X, padx=10, pady=5)

        # Create labels for totals
        self.total_items_label = ttk.Label(totals_frame, text="Total Items: 0", font=('Arial', 10, 'bold'))
        self.total_items_label.pack(side=tk.LEFT, padx=20)

        self.total_downloaded_label = ttk.Label(totals_frame, text="Downloaded: 0", font=('Arial', 10, 'bold'))
        self.total_downloaded_label.pack(side=tk.LEFT, padx=20)

        self.total_remaining_label = ttk.Label(totals_frame, text="Remaining: 0", font=('Arial', 10, 'bold'))
        self.total_remaining_label.pack(side=tk.LEFT, padx=20)

        # Buttons
        button_frame = ttk.Frame(self.queue_window, padding=10)
        button_frame.pack(fill=tk.X)

        ttk.Button(button_frame, text="Remove Selected", command=self.remove_from_queue).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear Queue", command=self.clear_queue).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Start Downloads", command=self.process_queue).pack(side=tk.LEFT, padx=5)

        # Stop button (only enabled during downloads)
        self.queue_stop_button = ttk.Button(button_frame, text="Stop Download",
                                           command=self.stop_download,
                                           state=tk.DISABLED if not self.is_downloading else tk.NORMAL)
        self.queue_stop_button.pack(side=tk.LEFT, padx=5)

        # Update the queue display
        self.update_queue_window()

    def update_queue_window(self):
        """Update the queue window display"""
        # Update queue count in main window
        queued_count = len([q for q in self.download_queue if q['status'] == 'Queued'])
        total_count = len(self.download_queue)
        self.queue_status_label.config(text=f"Queue: {queued_count} waiting, {total_count} total")

        # Update Show Queue button text
        self.show_queue_button.config(text=f"Show Queue ({total_count})")

        if not self.queue_window or not self.queue_window.winfo_exists():
            return

        # Clear existing items
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        # Calculate totals
        total_items = 0
        total_downloaded = 0
        total_remaining = 0

        # Add queue items to treeview
        for queue_item in self.download_queue:
            total_items += queue_item['items']
            total_downloaded += queue_item.get('downloaded', 0)
            total_remaining += queue_item.get('remaining', queue_item['items'])

            self.queue_tree.insert('', 'end', values=(
                queue_item['type'],
                queue_item['title'],
                queue_item['items'],
                queue_item.get('downloaded', 0),
                queue_item.get('remaining', queue_item['items']),
                queue_item['status']
            ))

        # Update totals labels
        self.total_items_label.config(text=f"Total Items: {total_items}")
        self.total_downloaded_label.config(text=f"Downloaded: {total_downloaded}")
        self.total_remaining_label.config(text=f"Remaining: {total_remaining}")

    def remove_from_queue(self):
        """Remove selected item from queue"""
        if not self.queue_window or not self.queue_window.winfo_exists():
            return

        selection = self.queue_tree.selection()
        if selection:
            # Get the index of the selected item
            selected_item = selection[0]
            index = self.queue_tree.index(selected_item)

            if index < len(self.download_queue):
                removed = self.download_queue.pop(index)
                self.update_activity(f"Removed '{removed['title']}' from queue")
                self.update_queue_window()

    def clear_queue(self):
        """Clear the entire download queue"""
        if self.is_downloading:
            messagebox.showwarning("Download Active", "Cannot clear queue while downloading")
            return

        if messagebox.askyesno("Clear Queue", "Are you sure you want to clear the entire queue?"):
            self.download_queue.clear()
            self.update_activity("Download queue cleared")
            self.update_queue_window()

    def clear_queue(self):
        """Clear the entire download queue"""
        if self.is_downloading:
            messagebox.showwarning("Download Active", "Cannot clear queue while downloading")
            return

        if messagebox.askyesno("Clear Queue", "Are you sure you want to clear the entire queue?"):
            self.download_queue.clear()
            self.update_activity("Download queue cleared")
            self.update_queue_window()

    def process_queue(self):
        """Process the download queue"""
        if self.is_downloading:
            messagebox.showinfo("Already Downloading", "Downloads are already in progress")
            return

        if not self.download_queue:
            messagebox.showinfo("Empty Queue", "No playlists in the download queue")
            return

        if not self.plex_connection.connected:
            messagebox.showerror("Not Connected", "Please connect to Plex server before downloading")
            return

        # Find first queued item
        next_item = None
        for i, item in enumerate(self.download_queue):
            if item['status'] == 'Queued':
                next_item = item
                break

        if not next_item:
            self.update_activity("All playlists in queue have been processed")
            return

        # Start download
        self.is_downloading = True
        next_item['status'] = 'Downloading'
        self.update_queue_window()

        # Disable/enable buttons
        self.download_music_button.config(state=tk.DISABLED)
        self.download_video_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

        # Enable queue window stop button if it exists
        if hasattr(self, 'queue_stop_button') and self.queue_window and self.queue_window.winfo_exists():
            self.queue_stop_button.config(state=tk.NORMAL)

        # Start download in thread
        download_dir = self.download_dir_var.get()
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)

        thread = threading.Thread(
            target=self._download_with_queue_update,
            args=(next_item['playlist'], download_dir, next_item)
        )
        thread.daemon = True
        thread.start()

    def _download_with_queue_update(self, playlist, download_dir, queue_item):
        """Download playlist and update queue status"""
        # Store reference to queue item for progress updates
        self.current_queue_item = queue_item

        def progress_callback(current, total, filename, percent, speed, overall_speed):
            # Update the queue item's downloaded count
            queue_item['downloaded'] = current - 1 if percent < 100 else current
            queue_item['remaining'] = total - queue_item['downloaded']
            self.update_queue_window()
            # Call the regular progress update
            self.update_progress(current, total, filename, percent, speed, overall_speed)

        def status_callback(status):
            self.update_status(status)
            if "Completed" in status:
                queue_item['status'] = 'Completed'
                queue_item['downloaded'] = queue_item['items']
                queue_item['remaining'] = 0
            elif "stopped" in status:
                queue_item['status'] = 'Stopped'
            self.update_queue_window()

            # If completed or stopped, process next in queue
            if "Completed" in status or "stopped" in status:
                self.is_downloading = False
                self.current_queue_item = None
                self.root.after(1000, self.process_queue)  # Process next after 1 second

        self.download_manager.download_playlist(
            playlist, download_dir, progress_callback, status_callback
        )

    def _start_download(self, playlist):
        """Start downloading a playlist"""
        download_dir = self.download_dir_var.get()
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)

        # Disable download buttons
        self.download_music_button.config(state=tk.DISABLED)
        self.download_video_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

        # Start download in thread
        thread = threading.Thread(
            target=self.download_manager.download_playlist,
            args=(playlist, download_dir, self.update_progress, self.update_status)
        )
        thread.daemon = True
        thread.start()

    def stop_download(self):
        """Stop current download"""
        self.download_manager.stop_download()
        self.stop_button.config(state=tk.DISABLED)
        self.download_music_button.config(state=tk.NORMAL)
        self.download_video_button.config(state=tk.NORMAL)
        self.update_activity("Download stopped by user")

    def update_progress(self, current, total, filename, percent, speed, overall_speed):
        """Update progress display"""
        overall_percent = (current / total) * 100
        self.status_label.config(text=f"Downloading item {current} of {total} ({overall_percent:.1f}%) - Overall: {overall_speed:.2f} MB/s")
        self.file_label.config(text=f"Current file: {filename}")
        self.progress_var.set(percent)
        self.progress_label.config(text=f"{percent}%")

        # Update speed label
        if speed > 0:
            self.speed_label.config(text=f"{speed:.2f} MB/s")
        else:
            self.speed_label.config(text="")

        if percent == 100:
            self.update_activity(f"Downloaded: {filename}")

    def update_status(self, status):
        """Update status display"""
        self.status_label.config(text=status)
        self.update_activity(status)

        # Re-enable buttons if download complete
        if "Completed" in status or "stopped" in status:
            self.download_music_button.config(state=tk.NORMAL)
            self.download_video_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)

            # Update queue window stop button if it exists
            if hasattr(self, 'queue_stop_button') and self.queue_window and self.queue_window.winfo_exists():
                self.queue_stop_button.config(state=tk.DISABLED)

            self.progress_var.set(0)
            self.file_label.config(text="No active download")
            self.progress_label.config(text="0%")
            self.speed_label.config(text="")

    def update_activity(self, message):
        """Update activity log"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.activity_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.activity_text.see(tk.END)
        self.root.update()

    def save_config(self):
        """Save configuration to file"""
        self.config = {
            'plex_address': self.address_var.get().strip(),
            'plex_token': self.token_var.get().strip(),
            'download_directory': self.download_dir_var.get().strip()
        }

        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.update_activity(f"Configuration saved to {CONFIG_FILE}")
            messagebox.showinfo("Success", "Configuration saved successfully")
        except Exception as e:
            logger.error(f"Error saving config: {str(e)}")
            messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")

    def load_config(self):
        """Load configuration from file"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    self.config = json.load(f)

                self.address_var.set(self.config.get('plex_address', DEFAULT_CONFIG['plex_address']))
                self.token_var.set(self.config.get('plex_token', DEFAULT_CONFIG['plex_token']))
                self.download_dir_var.set(self.config.get('download_directory', DEFAULT_CONFIG['download_directory']))

                self.update_activity(f"Configuration loaded from {CONFIG_FILE}")
            except Exception as e:
                logger.error(f"Error loading config: {str(e)}")
                self.update_activity(f"Error loading configuration: {str(e)}")

    def early_analysis(self):
        """Early startup analysis before GUI creation"""
        logger.info("=== EARLY STARTUP ANALYSIS ===")

        # Check environment
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Platform: {sys.platform}")
        logger.info(f"Current directory: {os.getcwd()}")

        # Check if plexapi import is slow
        import_start = time.time()
        import plexapi
        import_time = time.time() - import_start
        logger.info(f"PlexAPI import took: {import_time:.2f} seconds")
        logger.info(f"PlexAPI version: {plexapi.__version__}")

        # Check for config file
        if os.path.exists(CONFIG_FILE):
            logger.info(f"Config file exists: {CONFIG_FILE}")
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                logger.info(f"Config contains server: {config.get('plex_address', 'Not set')}")
            except:
                logger.info("Could not read config file")

        # Check for cache file
        if os.path.exists(CACHE_FILE):
            size = os.path.getsize(CACHE_FILE) / 1024
            logger.info(f"Cache file exists: {CACHE_FILE} ({size:.2f} KB)")

        # Check network interfaces (might be slow on macOS)
        try:
            import socket
            hostname = socket.gethostname()
            logger.info(f"Hostname: {hostname}")
        except:
            logger.info("Could not get hostname")

        logger.info("=== END EARLY ANALYSIS ===")

    def post_startup_analysis(self):
        """Analysis after GUI is created"""
        self.update_activity("\n=== POST-STARTUP ANALYSIS ===")

        # Check threads
        import threading
        threads = threading.enumerate()
        self.update_activity(f"Active threads after startup: {len(threads)}")
        for thread in threads:
            self.update_activity(f"  - {thread.name}: {thread.is_alive()}")

        # Check if any network activity happened
        if hasattr(self.plex_connection, 'server') and self.plex_connection.server:
            self.update_activity("WARNING: Plex connection exists at startup!")

        self.update_activity("=== END POST-STARTUP ANALYSIS ===\n")

    def analyze_performance(self):
        """Analyze what might be causing performance issues"""
        self.update_activity("\n=== PERFORMANCE ANALYSIS ===")

        # Check if PlexAPI is doing something on import
        try:
            import plexapi
            self.update_activity(f"PlexAPI version: {plexapi.__version__}")
        except:
            pass

        # Check for any background threads
        import threading
        threads = threading.enumerate()
        self.update_activity(f"Active threads: {len(threads)}")
        for thread in threads:
            self.update_activity(f"  - {thread.name}: {thread.is_alive()}")

        # Check if there's a connection attempt happening
        if hasattr(self, 'plex_connection') and self.plex_connection:
            self.update_activity(f"Plex connection status: {self.plex_connection.connected}")
            if self.plex_connection.server:
                try:
                    # This might trigger a connection
                    self.update_activity(f"Server friendly name: {self.plex_connection.server.friendlyName}")
                except:
                    self.update_activity("Could not get server info")

        # Check cache file size
        if os.path.exists(CACHE_FILE):
            size = os.path.getsize(CACHE_FILE) / 1024  # KB
            self.update_activity(f"Cache file size: {size:.2f} KB")

        # Check if config has auto-connect settings
        self.update_activity(f"Current config: {self.config}")

        self.update_activity("=== END ANALYSIS ===\n")

    def quit_app(self):
        """Quit application"""
        if messagebox.askyesno("Quit", "Are you sure you want to quit?"):
            logger.info("Application shutting down")
            self.root.destroy()

# ===== MAIN ENTRY POINT =====
def main():
    root = tk.Tk()
    app = PlexPlaylistDownloaderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
