import os
import re
import sys
import time
import json
import subprocess
import importlib.util
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import math
from urllib.parse import urlparse
import socket

# --- CONSTANTS ---
REQUIRED_PACKAGES = ["plexapi", "cloudscraper", "requests"]
CONFIG_FILE = "plex_downloader_config.json"

# --- Download Strategy Constants ---
REMOTE_MAX_DOWNLOAD_RETRIES = 3
REMOTE_INITIAL_RETRY_DELAY = 5 # seconds
REMOTE_CONNECT_TIMEOUT = 15
REMOTE_READ_TIMEOUT = 180

LOCAL_MAX_DOWNLOAD_RETRIES = 2
LOCAL_INITIAL_RETRY_DELAY = 3 # seconds
LOCAL_CONNECT_TIMEOUT = 10
LOCAL_READ_TIMEOUT = 60

# --- DEPENDENCY MANAGEMENT ---

def check_and_install_packages(required_packages):
    """Checks if required packages are installed and prompts to install them if not."""
    missing_packages = [pkg for pkg in required_packages if importlib.util.find_spec(pkg) is None]
    if not missing_packages:
        print("All required packages are already installed.")
        return True

    proceed = messagebox.askyesno(
        "Missing Dependencies",
        f"The following required packages are missing: {', '.join(missing_packages)}.\n\nDo you want to try and install them now?"
    )
    if not proceed:
        messagebox.showwarning("Dependencies Missing", "Application may not function correctly without the required packages.")
        return False

    try:
        print("Installing missing packages...")
        for pkg in missing_packages:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        print("Packages installed successfully. Please restart the application.")
        messagebox.showinfo("Installation Complete", "Packages installed. Please restart the application for changes to take effect.")
        return False # A restart is required
    except (subprocess.CalledProcessError, Exception) as e:
        print(f"Error installing packages: {e}")
        messagebox.showerror("Installation Error", f"Error installing packages: {e}\nPlease install them manually: pip install {' '.join(missing_packages)}")
        return False

# --- UTILITY FUNCTIONS ---

def sanitize_filename(filename):
    """Remove or replace characters that are invalid in filenames."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = sanitized.replace(":", " - ")
    return re.sub(r'\s+', ' ', sanitized).strip()[:200]

def get_item_details(item):
    """Determines media item type, returns descriptive filename and extension."""
    filename = ""
    extension = "unknown"
    try:
        if item.media and len(item.media) > 0 and item.media[0].parts:
            part = item.media[0].parts[0]
            extension = part.container if part.container else 'mkv'
            if hasattr(part, 'file') and '.' in part.file:
                file_ext = part.file.split('.')[-1]
                if len(file_ext) <= 4:
                    extension = file_ext

        if item.type == 'movie':
            title = item.title
            year = getattr(item, 'year', "")
            filename = f"{title} ({year})" if year else title
        elif item.type == 'episode':
            show_title = getattr(item, 'grandparentTitle', "Unknown Show")
            season_num = getattr(item, 'parentIndex', "XX")
            episode_num = getattr(item, 'index', "YY")
            episode_title = getattr(item, 'title', "Unknown Episode")
            filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {episode_title}"
        elif item.type == 'track':
            artist_title = getattr(item, 'grandparentTitle', "Unknown Artist")
            album_title = getattr(item, 'parentTitle', "Unknown Album")
            track_num_val = getattr(item, 'index', 0)
            track_title = getattr(item, 'title', "Unknown Track")
            filename = f"{artist_title} - {album_title} - {track_num_val:02d}. {track_title}"
        else:
            filename = getattr(item, 'title', "Unknown_Item")

        return sanitize_filename(filename), extension.lower()
    except Exception as e:
        print(f"  Error getting details for item '{getattr(item, 'title', 'Unknown Item')}': {e}")
        return sanitize_filename(getattr(item, 'title', 'Unknown_Item')), 'mkv'

def format_size(size_bytes):
    """Formats a size in bytes to a human-readable string (KB, MB, GB)."""
    if not isinstance(size_bytes, (int, float)) or size_bytes <= 0: return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


# --- CONFIGURATION MANAGER ---

class ConfigManager:
    """Handles loading and saving of the application configuration."""
    def __init__(self, config_file):
        self.config_file = config_file

    def load_config(self, app):
        """Loads configuration and applies it to the app's UI variables."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                app.log_status(f"Configuration loaded from {self.config_file}")
            else:
                app.log_status(f"No configuration file found. Using defaults.")
                config = {}

            app.server_type_var.set(config.get("server_type", "remote"))
            app.remote_plex_url_var.set(config.get("remote_plex_url", "https://your-plex-url.com"))
            app.local_plex_address_var.set(config.get("local_plex_address", "http://localhost:32400"))
            app.download_dir_var.set(config.get("download_dir", os.path.join(os.getcwd(), "Plex_Downloads")))

            should_save_token = config.get("save_token", False)
            app.save_token_var.set(should_save_token)
            if should_save_token:
                app.plex_token_var.set(config.get("plex_token", ""))
            else:
                app.plex_token_var.set("")

            app.toggle_url_entries()
        except Exception as e:
            app.log_status(f"Error loading configuration: {e}. Using defaults.")
            app.server_type_var.set("remote")
            app.toggle_url_entries()

    def save_config(self, app):
        """Saves the current UI configuration to the file."""
        config = {
            "server_type": app.server_type_var.get(),
            "remote_plex_url": app.remote_plex_url_var.get(),
            "local_plex_address": app.local_plex_address_var.get(),
            "download_dir": app.download_dir_var.get(),
            "save_token": app.save_token_var.get(),
            "plex_token": app.plex_token_var.get() if app.save_token_var.get() else ""
        }
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
            app.log_status(f"Configuration saved to {self.config_file}")
        except Exception as e:
            app.log_status(f"Error saving configuration: {e}")
            messagebox.showerror("Config Error", f"Could not save configuration: {e}")


# --- PLEX HANDLER ---
class PlexHandler:
    """Manages connection and interaction with the Plex server."""
    def __init__(self, app_log_callback):
        self.plex_instance = None
        self.log = app_log_callback
        # Late import to ensure dependencies are checked first
        global requests, cloudscraper, PlexServer, NotFound, Unauthorized
        import requests, cloudscraper
        from plexapi.server import PlexServer
        from plexapi.exceptions import NotFound, Unauthorized

    def connect(self, server_type, url, token):
        """Establishes a connection to the Plex server."""
        self.log(f"Attempting to connect to {server_type} Plex server at {url}...")

        try:
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname
            port = parsed_url.port

            # Only perform the pre-connection check if a port is explicitly in the URL.
            # This is useful for local addresses but avoids issues with remote URLs that omit the default port.
            if port:
                self.log(f"Testing reachability of host {hostname} on port {port}...")
                with socket.create_connection((hostname, port), timeout=5):
                    self.log(f"Host {hostname}:{port} is reachable.")
            else:
                self.log("No explicit port in URL, skipping low-level pre-connection check.")

        except Exception as e:
            self.log(f"Pre-connection check failed: {e}")
            messagebox.showerror("Connection Error", f"Host unreachable: {e}\n\nPlease check the URL, port, and firewall settings.")
            return False

        # Session setup based on server type
        session = cloudscraper.create_scraper() if server_type == "remote" else requests.Session()

        try:
            self.plex_instance = PlexServer(url, token, session=session, timeout=30)
            self.log(f"Successfully authenticated with Plex server: {self.plex_instance.friendlyName}")
            return True
        except Unauthorized:
            self.log("Plex connection unauthorized. Check your Plex Token.")
            messagebox.showerror("Connection Error", "Unauthorized. Please check your Plex Token and ensure you have access to the server.")
        except (requests.exceptions.RequestException, NotFound) as e:
            self.log(f"Connection Error: {e}")
            messagebox.showerror("Connection Error", f"Could not connect to {url}.\nDetails: {e}")
        except Exception as e:
            self.log(f"An unexpected error occurred during connection: {e}")
            import traceback; traceback.print_exc()
            messagebox.showerror("Connection Error", f"An unexpected error occurred: {e}")

        self.plex_instance = None
        return False

    def get_playlists(self):
        """Fetches and categorizes playlists from the connected server."""
        if not self.plex_instance:
            self.log("Cannot fetch playlists, not connected to a server.")
            return [], []

        try:
            playlists = self.plex_instance.playlists()
            music_playlists = [p for p in playlists if p.playlistType == 'audio']
            video_playlists = [p for p in playlists if p.playlistType == 'video']
            self.log(f"Found {len(music_playlists)} music and {len(video_playlists)} video playlists.")
            return music_playlists, video_playlists
        except Exception as e:
            self.log(f"Error fetching playlists: {e}")
            messagebox.showerror("Playlist Error", f"Could not fetch playlists: {e}")
            return [], []

# --- DOWNLOAD MANAGER ---
class DownloadManager:
    """Manages the logic for downloading files, with distinct handling for remote/local."""

    def __init__(self, plex_handler, config_vars, ui_callbacks, stop_event):
        self.plex_handler = plex_handler
        self.config_vars = config_vars
        self.ui_callbacks = ui_callbacks
        self.stop_event = stop_event
        self.log = ui_callbacks['log']

    def run_download_thread(self, playlists_to_download):
        """Starts the download process in a new thread."""
        thread = threading.Thread(
            target=self.actual_download_process,
            args=(playlists_to_download,),
            daemon=True
        )
        thread.start()

    def actual_download_process(self, playlists_to_download):
        """The main loop for processing and downloading playlists."""
        base_download_dir = self.config_vars['download_dir']
        total_playlists = len(playlists_to_download)

        try:
            for playlist_idx, playlist in enumerate(playlists_to_download):
                if self.stop_event.is_set():
                    self.log("Download process stopped by user.")
                    break

                self.ui_callbacks['update_overall_progress'](f"Playlist: {playlist.title} ({playlist_idx + 1}/{total_playlists})")
                playlist_dir = os.path.join(base_download_dir, sanitize_filename(playlist.title))
                os.makedirs(playlist_dir, exist_ok=True)
                self.log(f"\nProcessing playlist: '{playlist.title}' in '{playlist_dir}'")

                try:
                    items = playlist.items()
                    self.ui_callbacks['update_playlist_progress'](0, len(items))
                except Exception as e:
                    self.log(f"  Could not retrieve items for playlist '{playlist.title}': {e}")
                    continue

                for i, item in enumerate(items):
                    if self.stop_event.is_set():
                        self.log("Download stopped between items.")
                        break

                    self.process_item(item, playlist_dir)
                    self.ui_callbacks['update_playlist_progress'](i + 1, len(items))

                if self.stop_event.is_set(): break
        finally:
            self.log("\nDownload process " + ("stopped." if self.stop_event.is_set() else "finished."))
            self.ui_callbacks['end_downloads']()

    def process_item(self, item, playlist_dir):
        """Processes a single item for download."""
        base_filename_template, ext = get_item_details(item)
        output_filename = f"{base_filename_template}.{ext}"
        filepath = os.path.join(playlist_dir, output_filename)
        display_filename_short = output_filename if len(output_filename) < 50 else f"{output_filename[:47]}..."

        self.log(f"  Item: Preparing '{getattr(item, 'title', 'Unknown')}' as '{output_filename}'")

        if os.path.exists(filepath):
            self.log(f"  Skipping '{output_filename}', file already exists.")
            return

        try:
            part = item.media[0].parts[0]
            stream_url = self.plex_handler.plex_instance.url(part.key, includeToken=False)
            if not stream_url.startswith('http'):
                stream_url = self.plex_handler.plex_instance._baseurl.rstrip('/') + stream_url

            download_func = self._download_remote_file if self.config_vars['server_type'] == "remote" else self._download_local_file
            download_successful = download_func(stream_url, filepath, display_filename_short)

            if not download_successful and not self.stop_event.is_set():
                self.log(f"  Download of '{output_filename}' ultimately failed.")

        except (AttributeError, IndexError):
            self.log(f"  No media parts found for '{getattr(item, 'title', 'Unknown Item')}'")
        except Exception as e:
            self.log(f"  CRITICAL ERROR preparing download for '{output_filename}': {e}")
            import traceback; self.log(traceback.format_exc())

    def _common_download_loop(self, session, stream_url, full_filepath, display_filename, plex_server_token, connect_timeout, read_timeout):
        """Common loop for streaming and updating progress, used by both remote and local download functions."""
        headers = {'X-Plex-Token': plex_server_token, 'Accept': '*/*'}
        with session.get(stream_url, headers=headers, stream=True, timeout=(connect_timeout, read_timeout)) as r:
            r.raise_for_status()
            total_size_in_bytes = r.headers.get('content-length')
            total_size_in_bytes = int(total_size_in_bytes) if total_size_in_bytes else None
            bytes_downloaded = 0
            start_time = time.time()
            last_update_time = start_time
            bytes_since_last_update = 0

            self.ui_callbacks['update_file_progress'](display_filename, 0 if total_size_in_bytes else None, "0 B/s", "0 B", format_size(total_size_in_bytes))

            with open(full_filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192 * 8):
                    if self.stop_event.is_set():
                        raise InterruptedError("Download stopped by user")
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        bytes_since_last_update += len(chunk)
                        current_time = time.time()
                        time_delta = current_time - last_update_time
                        if time_delta >= 0.5 or (total_size_in_bytes and bytes_downloaded == total_size_in_bytes):
                            speed = bytes_since_last_update / time_delta if time_delta > 0 else 0
                            speed_str = f"{format_size(int(speed))}/s"
                            percent = (bytes_downloaded / total_size_in_bytes * 100) if total_size_in_bytes else None
                            downloaded_s = format_size(bytes_downloaded)
                            total_s = format_size(total_size_in_bytes)
                            self.ui_callbacks['update_file_progress'](display_filename, percent, speed_str, downloaded_s, total_s)
                            last_update_time = current_time
                            bytes_since_last_update = 0

            final_downloaded_s = format_size(bytes_downloaded)
            final_total_s = format_size(total_size_in_bytes)
            final_percent = 100 if total_size_in_bytes and bytes_downloaded == total_size_in_bytes else None
            self.ui_callbacks['update_file_progress'](display_filename, final_percent, "Done", final_downloaded_s, final_total_s)

        self.log(f"    Successfully downloaded: {display_filename}")
        return True

    def _download_local_file(self, stream_url, filepath, display_filename):
        """Wrapper for local download logic."""
        session = self.plex_handler.plex_instance._session
        return self._perform_download_with_retries(
            session, stream_url, filepath, display_filename,
            max_retries=LOCAL_MAX_DOWNLOAD_RETRIES,
            initial_delay=LOCAL_INITIAL_RETRY_DELAY,
            timeouts=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT)
        )

    def _download_remote_file(self, stream_url, filepath, display_filename):
        """Wrapper for remote download logic."""
        session = self.plex_handler.plex_instance._session
        return self._perform_download_with_retries(
            session, stream_url, filepath, display_filename,
            max_retries=REMOTE_MAX_DOWNLOAD_RETRIES,
            initial_delay=REMOTE_INITIAL_RETRY_DELAY,
            timeouts=(REMOTE_CONNECT_TIMEOUT, REMOTE_READ_TIMEOUT)
        )

    def _perform_download_with_retries(self, session, stream_url, full_filepath, display_filename, max_retries, initial_delay, timeouts):
        """Performs the actual file download with retry logic."""
        current_retry_delay = initial_delay

        for attempt in range(max_retries):
            if self.stop_event.is_set(): return False
            try:
                self.log(f"    Starting download for: {display_filename} (Attempt {attempt + 1}/{max_retries})")
                return self._common_download_loop(session, stream_url, full_filepath, display_filename, self.plex_handler.plex_instance._token, *timeouts)
            except InterruptedError: return False
            except requests.exceptions.HTTPError as http_err:
                status_code = http_err.response.status_code
                response_text = http_err.response.text[:200] if http_err.response.text else "N/A"
                self.log(f"    Download failed (HTTP {status_code}) on attempt {attempt + 1}. Response: {response_text}")
                if 500 <= status_code < 600 and attempt < max_retries - 1:
                    self.log(f"    Server error. Retrying in {current_retry_delay}s...")
                    time.sleep(current_retry_delay)
                    current_retry_delay *= 2
                    continue
                else: break
            except requests.exceptions.RequestException as e:
                self.log(f"    Download failed (Network Error: {e}) on attempt {attempt + 1}.")
                if attempt < max_retries - 1:
                    self.log(f"    Retrying in {current_retry_delay}s...")
                    time.sleep(current_retry_delay)
                    current_retry_delay *= 2
                    continue
                else: break
            except Exception as e:
                self.log(f"    Download failed (Unexpected Error: {e}). Not retrying.")
                import traceback; self.log(traceback.format_exc())
                break

        self.ui_callbacks['update_file_progress']("-", 0, "0 B/s", "-", "-")
        return False

# --- MAIN GUI APPLICATION ---
class PlexDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Plex Playlist Downloader")
        self.root.geometry("850x950")

        self.config_manager = ConfigManager(CONFIG_FILE)
        self.plex_handler = PlexHandler(self.log_status)
        self.stop_download_event = threading.Event()

        self.all_music_playlists = []
        self.all_video_playlists = []

        self._create_widgets()
        self.config_manager.load_config(self)
        self._toggle_ui_for_download_end()

    def log_status(self, message):
        """Thread-safe method to log messages to the status text area."""
        print(message)
        if self.status_text_area and self.root.winfo_exists():
            def _update_log():
                if self.status_text_area.winfo_exists():
                    self.status_text_area.config(state=tk.NORMAL)
                    self.status_text_area.insert(tk.END, f"{message}\n")
                    self.status_text_area.see(tk.END)
                    self.status_text_area.config(state=tk.DISABLED)
            self.root.after(0, _update_log)

    def _create_widgets(self):
        # --- Configuration Frame ---
        config_frame = ttk.LabelFrame(self.root, text="Plex Configuration", padding="10")
        config_frame.pack(padx=10, pady=(10,5), fill="x")

        self.server_type_var = tk.StringVar(value="remote")
        self.remote_plex_url_var = tk.StringVar()
        self.local_plex_address_var = tk.StringVar()
        self.plex_token_var = tk.StringVar()
        self.save_token_var = tk.BooleanVar()
        self.download_dir_var = tk.StringVar()

        server_type_frame = ttk.Frame(config_frame)
        server_type_frame.grid(row=0, column=0, columnspan=3, pady=(0,5), sticky="w")
        ttk.Label(server_type_frame, text="Server Type:").pack(side=tk.LEFT, padx=(0,5))
        remote_rb = ttk.Radiobutton(server_type_frame, text="Remote", variable=self.server_type_var, value="remote", command=self.toggle_url_entries)
        remote_rb.pack(side=tk.LEFT, padx=5)
        local_rb = ttk.Radiobutton(server_type_frame, text="Local", variable=self.server_type_var, value="local", command=self.toggle_url_entries)
        local_rb.pack(side=tk.LEFT, padx=5)

        ttk.Label(config_frame, text="Remote Plex URL:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.remote_plex_url_entry = ttk.Entry(config_frame, textvariable=self.remote_plex_url_var, width=50)
        self.remote_plex_url_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky="ew")

        ttk.Label(config_frame, text="Local Plex Address:").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.local_plex_address_entry = ttk.Entry(config_frame, textvariable=self.local_plex_address_var, width=50)
        self.local_plex_address_entry.grid(row=2, column=1, columnspan=2, padx=5, pady=2, sticky="ew")

        ttk.Label(config_frame, text="Plex Token:").grid(row=3, column=0, padx=5, pady=2, sticky="w")
        plex_token_entry = ttk.Entry(config_frame, textvariable=self.plex_token_var, width=50, show="*")
        plex_token_entry.grid(row=3, column=1, padx=5, pady=2, sticky="ew")
        save_token_checkbox = ttk.Checkbutton(config_frame, text="Save Token", variable=self.save_token_var)
        save_token_checkbox.grid(row=3, column=2, padx=5, pady=2, sticky="w")

        ttk.Label(config_frame, text="Download Dir:").grid(row=4, column=0, padx=5, pady=2, sticky="w")
        download_dir_entry = ttk.Entry(config_frame, textvariable=self.download_dir_var, width=40)
        download_dir_entry.grid(row=4, column=1, padx=5, pady=2, sticky="ew")
        browse_button = ttk.Button(config_frame, text="Browse...", command=self.browse_directory)
        browse_button.grid(row=4, column=2, padx=5, pady=2, sticky="w")
        config_frame.columnconfigure(1, weight=1)

        main_actions_frame = ttk.Frame(config_frame)
        main_actions_frame.grid(row=5, column=0, columnspan=3, pady=(10,2), sticky="ew")
        self.connect_button = ttk.Button(main_actions_frame, text="Connect to Plex", command=self.run_connect_thread)
        self.connect_button.pack(side=tk.LEFT, padx=5, expand=True, fill="x")
        self.save_config_button = ttk.Button(main_actions_frame, text="Save Configuration", command=lambda: self.config_manager.save_config(self))
        self.save_config_button.pack(side=tk.LEFT, padx=5, expand=True, fill="x")
        self.quit_button = ttk.Button(main_actions_frame, text="Quit", command=self.on_exit)
        self.quit_button.pack(side=tk.LEFT, padx=5, expand=True, fill="x")

        playlists_area_frame = ttk.Frame(self.root, padding="5")
        playlists_area_frame.pack(padx=10, pady=5, fill="both", expand=True)

        music_playlists_frame = ttk.LabelFrame(playlists_area_frame, text="Music Playlists", padding="5")
        music_playlists_frame.pack(side=tk.LEFT, padx=5, fill="both", expand=True)
        music_scrollbar_y = ttk.Scrollbar(music_playlists_frame, orient=tk.VERTICAL)
        self.music_playlist_listbox = tk.Listbox(music_playlists_frame, selectmode=tk.EXTENDED, yscrollcommand=music_scrollbar_y.set, height=7, exportselection=False)
        music_scrollbar_y.config(command=self.music_playlist_listbox.yview)
        music_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.music_playlist_listbox.pack(side=tk.LEFT, fill="both", expand=True)

        video_playlists_frame = ttk.LabelFrame(playlists_area_frame, text="Video Playlists", padding="5")
        video_playlists_frame.pack(side=tk.LEFT, padx=5, fill="both", expand=True)
        video_scrollbar_y = ttk.Scrollbar(video_playlists_frame, orient=tk.VERTICAL)
        self.video_playlist_listbox = tk.Listbox(video_playlists_frame, selectmode=tk.EXTENDED, yscrollcommand=video_scrollbar_y.set, height=7, exportselection=False)
        video_scrollbar_y.config(command=self.video_playlist_listbox.yview)
        video_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.video_playlist_listbox.pack(side=tk.LEFT, fill="both", expand=True)

        download_control_frame = ttk.Frame(self.root, padding="5")
        download_control_frame.pack(fill="x", padx=10, pady=5)

        self.overall_progress_label_var = tk.StringVar(value="Status: Idle")
        overall_progress_label = ttk.Label(download_control_frame, textvariable=self.overall_progress_label_var)
        overall_progress_label.pack(side=tk.TOP, fill="x", pady=(0,2))
        self.playlist_progress_bar = ttk.Progressbar(download_control_frame, orient="horizontal", mode="determinate")
        self.playlist_progress_bar.pack(side=tk.TOP, fill="x", expand=True, pady=(0,5))

        download_buttons_grid = ttk.Frame(download_control_frame)
        download_buttons_grid.pack(side=tk.TOP, fill="x", pady=(5,0))
        self.download_selected_music_button = ttk.Button(download_buttons_grid, text="Download Selected Music", command=lambda: self.start_download_action('selected_music'))
        self.download_selected_music_button.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        self.download_all_music_button = ttk.Button(download_buttons_grid, text="Download All Music", command=lambda: self.start_download_action('all_music'))
        self.download_all_music_button.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        self.download_selected_video_button = ttk.Button(download_buttons_grid, text="Download Selected Video", command=lambda: self.start_download_action('selected_video'))
        self.download_selected_video_button.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        self.download_all_video_button = ttk.Button(download_buttons_grid, text="Download All Video", command=lambda: self.start_download_action('all_video'))
        self.download_all_video_button.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        download_buttons_grid.columnconfigure((0, 1), weight=1)

        self.stop_download_button = ttk.Button(download_control_frame, text="Stop Current Downloads", command=self.stop_download_command)
        self.stop_download_button.pack(side=tk.TOP, fill="x", pady=(5,0))

        file_progress_frame = ttk.LabelFrame(self.root, text="Current File Download Progress", padding="10")
        file_progress_frame.pack(padx=10, pady=5, fill="x")
        self.current_file_label_var = tk.StringVar(value="Current File: -")
        self.download_speed_label_var = tk.StringVar(value="Speed: -")
        current_file_label = ttk.Label(file_progress_frame, textvariable=self.current_file_label_var)
        current_file_label.pack(fill="x", pady=(0,2))
        self.file_progress_bar = ttk.Progressbar(file_progress_frame, orient="horizontal", mode="determinate")
        self.file_progress_bar.pack(fill="x", expand=True, pady=(0,2))
        download_speed_label = ttk.Label(file_progress_frame, textvariable=self.download_speed_label_var)
        download_speed_label.pack(fill="x")

        status_frame = ttk.LabelFrame(self.root, text="Status Log", padding="10")
        status_frame.pack(padx=10, pady=10, fill="both", expand=True)
        self.status_text_area = scrolledtext.ScrolledText(status_frame, wrap=tk.WORD, height=6, state=tk.DISABLED)
        self.status_text_area.pack(fill="both", expand=True)

    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.download_dir_var.set(directory)
            self.log_status(f"Download directory set to: {directory}")

    def toggle_url_entries(self, *args):
        """Enable/Disable URL entry fields based on server type selection."""
        state_remote = tk.NORMAL if self.server_type_var.get() == "remote" else tk.DISABLED
        state_local = tk.NORMAL if self.server_type_var.get() == "local" else tk.DISABLED
        if self.remote_plex_url_entry: self.remote_plex_url_entry.config(state=state_remote)
        if self.local_plex_address_entry: self.local_plex_address_entry.config(state=state_local)

    def on_exit(self):
        self.config_manager.save_config(self)
        self.root.destroy()

    def run_connect_thread(self):
        """Runs the connection logic in a separate thread to keep the GUI responsive."""
        self._toggle_ui_for_download_start()
        self.stop_download_button.config(state=tk.DISABLED)

        threading.Thread(target=self.connect_and_populate, daemon=True).start()

    def connect_and_populate(self):
        """Handles the full connection and GUI update process."""
        server_type = self.server_type_var.get()
        url = self.remote_plex_url_var.get().strip() if server_type == "remote" else self.local_plex_address_var.get().strip()
        token = self.plex_token_var.get().strip()

        if not url or not token:
            messagebox.showerror("Input Error", "Plex URL/Address and Token are required.")
            self._toggle_ui_for_download_end()
            return

        if self.plex_handler.connect(server_type, url, token):
            self.overall_progress_label_var.set(f"Status: Connected to {self.plex_handler.plex_instance.friendlyName}")
            music, video = self.plex_handler.get_playlists()

            self.music_playlist_listbox.delete(0, tk.END)
            self.video_playlist_listbox.delete(0, tk.END)
            self.all_music_playlists = music
            self.all_video_playlists = video

            for p in music:
                self.music_playlist_listbox.insert(tk.END, f"{p.title} ({p.leafCount} items)")
            for p in video:
                self.video_playlist_listbox.insert(tk.END, f"{p.title} ({p.leafCount} items)")
        else:
            self.overall_progress_label_var.set("Status: Connection Failed")

        self._toggle_ui_for_download_end()

    def get_selected_playlists(self, listbox_widget, source_list):
        """Gets playlist objects from a listbox selection."""
        selected_objects = []
        indices = listbox_widget.curselection()
        if not indices: return []
        for i in indices:
            if 0 <= i < len(source_list):
                selected_objects.append(source_list[i])
        return selected_objects

    def start_download_action(self, action_type):
        """Initiates a download based on the button pressed."""
        if not self.plex_handler.plex_instance:
            messagebox.showerror("Error", "Not connected to a Plex server.")
            return

        base_dir = self.download_dir_var.get().strip()
        if not base_dir:
            messagebox.showerror("Input Error", "Please select a download directory.")
            return
        os.makedirs(base_dir, exist_ok=True)

        playlists_to_process = []
        if action_type == 'selected_music':
            playlists_to_process = self.get_selected_playlists(self.music_playlist_listbox, self.all_music_playlists)
        elif action_type == 'all_music':
            playlists_to_process = self.all_music_playlists
        elif action_type == 'selected_video':
            playlists_to_process = self.get_selected_playlists(self.video_playlist_listbox, self.all_video_playlists)
        elif action_type == 'all_video':
            playlists_to_process = self.all_video_playlists

        if not playlists_to_process:
            messagebox.showinfo("No Selection", "No playlists selected or available for this action.")
            return

        self.log_status(f"Preparing to download {len(playlists_to_process)} playlist(s)...")
        self.stop_download_event.clear()
        self._toggle_ui_for_download_start()

        ui_callbacks = {
            'log': self.log_status,
            'update_overall_progress': self.overall_progress_label_var.set,
            'update_playlist_progress': lambda val, max_val: self.playlist_progress_bar.config(value=val, maximum=max_val),
            'update_file_progress': self.update_file_download_ui,
            'end_downloads': self._toggle_ui_for_download_end
        }
        config_vars = {
            'download_dir': base_dir,
            'server_type': self.server_type_var.get()
        }

        downloader = DownloadManager(self.plex_handler, config_vars, ui_callbacks, self.stop_download_event)
        downloader.run_download_thread(playlists_to_process)


    def stop_download_command(self):
        self.log_status("Stop download command received. Signaling downloads to halt...")
        self.stop_download_event.set()
        self.stop_download_button.config(state=tk.DISABLED)

    def update_file_download_ui(self, filename, percent, speed_str, downloaded_str, total_str):
        """Updates GUI elements for file download progress. Runs in main thread."""
        def _update():
            if not self.root.winfo_exists(): return
            if self.current_file_label_var:
                self.current_file_label_var.set(f"Downloading: {filename} ({downloaded_str}/{total_str})")
            if self.file_progress_bar:
                if percent is None:
                    self.file_progress_bar.config(mode='indeterminate')
                    if hasattr(self.file_progress_bar, 'start') and not self.file_progress_bar.winfo_ismapped():
                        self.file_progress_bar.start(10)
                else:
                    if hasattr(self.file_progress_bar, 'stop'): self.file_progress_bar.stop()
                    self.file_progress_bar.config(mode='determinate')
                    self.file_progress_bar['value'] = percent
            if self.download_speed_label_var:
                self.download_speed_label_var.set(f"Speed: {speed_str}")
        if self.root.winfo_exists():
            self.root.after(0, _update)

    def _toggle_ui_for_download_start(self):
        """Disables/Enables UI elements when a download starts."""
        for btn in [self.connect_button, self.download_selected_music_button, self.download_selected_video_button,
                    self.download_all_music_button, self.download_all_video_button, self.save_config_button, self.quit_button]:
            if btn: btn.config(state=tk.DISABLED)
        if self.stop_download_button: self.stop_download_button.config(state=tk.NORMAL)

    def _toggle_ui_for_download_end(self):
        """Resets UI elements when a download ends or is stopped."""
        if not self.root.winfo_exists(): return
        self.overall_progress_label_var.set("Status: Idle")
        self.update_file_download_ui("-", 0, "0 B/s", "-", "-")
        if self.playlist_progress_bar: self.playlist_progress_bar['value'] = 0

        self.connect_button.config(state=tk.NORMAL)
        self.save_config_button.config(state=tk.NORMAL)
        self.quit_button.config(state=tk.NORMAL)
        self.stop_download_button.config(state=tk.DISABLED)

        music_exists = bool(self.all_music_playlists)
        video_exists = bool(self.all_video_playlists)
        self.download_selected_music_button.config(state=tk.NORMAL if music_exists else tk.DISABLED)
        self.download_all_music_button.config(state=tk.NORMAL if music_exists else tk.DISABLED)
        self.download_selected_video_button.config(state=tk.NORMAL if video_exists else tk.DISABLED)
        self.download_all_video_button.config(state=tk.NORMAL if video_exists else tk.DISABLED)


def main():
    """Main function to initialize and run the application."""
    root = tk.Tk()
    root.withdraw() # Hide until dependency check is complete

    # Initialize a temporary root for messageboxes if needed
    if not check_and_install_packages(REQUIRED_PACKAGES):
        root.destroy()
        sys.exit("Exiting due to missing dependencies.")

    # Late import of app dependencies now that they are checked
    global requests, cloudscraper, PlexServer, NotFound, Unauthorized
    import requests, cloudscraper
    from plexapi.server import PlexServer
    from plexapi.exceptions import NotFound, Unauthorized

    root.deiconify() # Show the window

    try:
        style = ttk.Style(root)
        available_themes = style.theme_names()
        if sys.platform == "win32" and 'vista' in available_themes: style.theme_use('vista')
        elif sys.platform == "darwin" and 'aqua' in available_themes: style.theme_use('aqua')
        elif 'clam' in available_themes: style.theme_use('clam')
    except tk.TclError: print("Failed to set a custom ttk theme.")

    app = PlexDownloaderApp(root)
    app.log_status("Plex Playlist Downloader GUI started.")
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()

if __name__ == "__main__":
    main()
