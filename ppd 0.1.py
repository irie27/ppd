import os
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from threading import Thread
import logging
from datetime import datetime
import subprocess  # For checking and installing plexapi
import json # For caching playlist data

# Attempt to import PlexServer, will be checked by check_and_install_plexapi
try:
    from plexapi.server import PlexServer
    from plexapi.exceptions import NotFound # For handling playlist not found
except ImportError:
    PlexServer = None # Placeholder if not installed initially
    NotFound = None


# === CONFIGURATION ===
LOG_FILE = 'plex_downloader.log'
CONFIG_FILE = 'plex_downloader_config.json'
PLAYLIST_CACHE_FILE = 'playlists_cache.json' # File to store playlist data
PLEX_BASE_URL = ''
PLEX_TOKEN = ''
BASE_DOWNLOAD_DIR = ''
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 650

# === SETUP LOGGING ===
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def check_and_install_module(module_name): # pip_check parameter removed
    try:
        __import__(module_name)
        return True
    except ImportError:
        print(f"{module_name} is not installed. Attempting to install...")
        logging.info(f"{module_name} is not installed. Attempting to install...")
        try:
            # Always check for pip availability if module import failed
            try:
                subprocess.check_call(['pip', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                print("Error: pip is not installed or not configured correctly. Please install pip and try again.")
                logging.error("pip is not installed or not configured correctly.")
                return False
            
            # Proceed with installing the module using pip
            subprocess.check_call(['pip', 'install', module_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"{module_name} successfully installed. Please restart the application if you encountered an import error previously.")
            logging.info(f"{module_name} successfully installed.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error installing {module_name}: {e}")
            print("Please ensure you have a working internet connection.")
            print(f"You can try installing it manually with: pip install {module_name}")
            logging.error(f"Error installing {module_name}: {e}")
            return False
        except Exception as e_gen:
            print(f"A general error occurred during installation of {module_name}: {e_gen}")
            logging.error(f"A general error occurred during installation of {module_name}: {e_gen}")
            return False

def check_and_install_plexapi():
    if not check_and_install_module('plexapi'):
        return False # plexapi is not usable

    # At this point, 'plexapi' module should be installed and loadable.
    # Re-import PlexServer and NotFound to ensure we're using the
    # (potentially newly) installed version's symbols.
    global PlexServer, NotFound
    try:
        # Attempt to import the specific names.
        from plexapi.server import PlexServer
        from plexapi.exceptions import NotFound
        logging.info("Successfully re-imported PlexServer and NotFound from plexapi.")
        return True
    except ImportError as e:
        # This would be unexpected if check_and_install_module truly succeeded
        # and plexapi is a valid install.
        print(f"Error: plexapi is installed, but failed to import PlexServer/NotFound symbols. Details: {e}")
        logging.error(f"plexapi is installed, but failed to import PlexServer/NotFound symbols. Details: {e}")
        PlexServer = None # Ensure they are None if this secondary import fails
        NotFound = None
        return False


def check_and_install_tkinter():
    try:
        import tkinter
        return True
    except ImportError:
        # (Tkinter installation logic as previously defined)
        print("tkinter is not installed. Attempting to install...")
        logging.warning("tkinter is not installed. Attempting to install...")
        if os.name == 'nt':  # Windows
            print("tkinter is usually included with Python on Windows. If you are missing it,")
            print("you may need to reinstall Python and ensure that the 'tcl/tk' component is selected.")
            logging.error("tkinter not found on Windows, manual Python reinstall with tcl/tk needed.")
            return False
        elif os.name == 'posix':  # Linux/macOS
            install_commands = [
                # Debian/Ubuntu: update might be needed first if system is old.
                # For simplicity, just trying install. User can update manually if needed.
                ['sudo', 'apt-get', 'install', '-y', 'python3-tk'],
                ['sudo', 'yum', 'install', '-y', 'python3-tkinter'],
                ['brew', 'install', 'python-tk']
            ]
            for cmd_group in install_commands:
                try:
                    if cmd_group[0] == 'brew' and not shutil.which('brew'):
                        print("Homebrew not found. Skipping brew install command for tkinter.")
                        logging.warning("Homebrew not found. Skipping brew install command for tkinter.")
                        continue
                    print(f"Trying to install tkinter with: {' '.join(cmd_group)}")
                    # Use PIPE for stderr to check output if needed, but DEVNULL for less console noise
                    process = subprocess.Popen(cmd_group, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    _, stderr = process.communicate()
                    if process.returncode == 0:
                        __import__('tkinter') # Verify import after install
                        print("tkinter successfully installed.")
                        logging.info(f"tkinter successfully installed via: {' '.join(cmd_group)}")
                        return True
                    else:
                        print(f"Command {' '.join(cmd_group)} failed. Stderr: {stderr.decode().strip()}")
                        logging.warning(f"Command {' '.join(cmd_group)} for tkinter install failed. Stderr: {stderr.decode().strip()}")

                except (subprocess.CalledProcessError, FileNotFoundError) as e: # FileNotFoundError if sudo/brew not found
                    print(f"Command {' '.join(cmd_group)} execution failed: {e}")
                    logging.warning(f"Command {' '.join(cmd_group)} for tkinter install execution failed: {e}")
                except ImportError: # Should not happen if returncode was 0, but as a safeguard
                    print(f"tkinter import failed even after trying {' '.join(cmd_group)}.")
                    logging.warning(f"tkinter import failed even after trying {' '.join(cmd_group)}.")


            print("Failed to install tkinter automatically. Please install it manually.")
            logging.error("Failed to install tkinter automatically.")
            return False
        else:
            print("tkinter installation is not supported on this operating system. Please install it manually.")
            logging.error("tkinter installation not supported on this OS.")
            return False

class PlexDownloaderGUI:
    def __init__(self, master):
        self.master = master
        master.title("Plex Playlist Downloader")
        master.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

        if not os.environ.get('DISPLAY') and os.name == 'posix':
            print("Warning: $DISPLAY is not set. Trying to default to ':0'. GUI might not appear if this is incorrect.")
            logging.warning("DISPLAY environment variable not set on POSIX. Defaulting to :0.")
            os.environ['DISPLAY'] = ':0'

        if not check_and_install_tkinter():
            messagebox.showerror("Critical Error", "tkinter is required but could not be installed or found. The application cannot start.")
            self.quit_app(force=True)
            return

        if not check_and_install_plexapi():
            messagebox.showerror("Critical Error", "plexapi is required but could not be installed. Plex features will fail. Please install it manually (`pip install plexapi`) and restart.")

        self.plex = None
        self.music_playlist_data = []
        self.video_playlist_data = []
        self.download_thread = None
        self.stop_download = False

        self.cache_successfully_loaded = False
        self.live_data_fetched_this_session = False
        self.source_file_access_warning_shown = False

        self.load_config()

        # Configuration Frame
        config_frame = ttk.LabelFrame(master, text="Configuration")
        config_frame.pack(padx=10, pady=10, fill=tk.X)

        ttk.Label(config_frame, text="Plex Base URL:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        self.url_entry = ttk.Entry(config_frame, width=40)
        self.url_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=2, sticky=tk.EW)
        self.url_entry.insert(0, PLEX_BASE_URL)

        ttk.Label(config_frame, text="Plex Token:").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        self.token_entry = ttk.Entry(config_frame, width=40)
        self.token_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky=tk.EW)
        self.token_entry.insert(0, PLEX_TOKEN)

        ttk.Label(config_frame, text="Download Directory:").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        self.download_dir_entry = ttk.Entry(config_frame, width=30)
        self.download_dir_entry.grid(row=2, column=1, padx=5, pady=2, sticky=tk.EW)
        ttk.Button(config_frame, text="Browse", command=self.browse_download_dir).grid(row=2, column=2, padx=5, pady=2)
        self.download_dir_entry.insert(0, BASE_DOWNLOAD_DIR)

        self.connect_button = ttk.Button(config_frame, text="Connect / Initial Fetch", command=self.handle_plex_connection_and_initial_fetch)
        self.connect_button.grid(row=3, column=0, padx=5, pady=5)
        self.refresh_button = ttk.Button(config_frame, text="Refresh Playlists", command=self.refresh_plex_data_action, state=tk.DISABLED)
        self.refresh_button.grid(row=3, column=1, padx=5, pady=5)

        # (Rest of UI setup as before)
        # Playlist Selection Frame
        self.playlist_frame = ttk.LabelFrame(master, text="Select Playlist")
        self.playlist_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        self.media_type = tk.StringVar(value="Music")
        radio_frame = ttk.Frame(self.playlist_frame)
        radio_frame.pack(pady=2, anchor=tk.W, padx=10)
        ttk.Radiobutton(radio_frame, text="Music Playlists", variable=self.media_type, value="Music", command=self.update_playlist_display_from_data).pack(side=tk.LEFT)
        ttk.Radiobutton(radio_frame, text="Video Playlists", variable=self.media_type, value="Video", command=self.update_playlist_display_from_data).pack(side=tk.LEFT, padx=10)

        self.playlist_list_var = tk.StringVar(value=[])
        self.playlist_list = tk.Listbox(self.playlist_frame, listvariable=self.playlist_list_var, height=10, selectmode=tk.SINGLE)
        self.playlist_list.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        self.button_frame = ttk.Frame(master)
        self.button_frame.pack(padx=10, pady=5, fill=tk.X)

        self.download_button = ttk.Button(self.button_frame, text="Download Selected", command=self.start_download)
        self.download_button.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        self.stop_button = ttk.Button(self.button_frame, text="Stop Download", command=self.stop_download_process, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        self.quit_button = ttk.Button(self.button_frame, text="Quit", command=self.quit_app)
        self.quit_button.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        # Download Progress Frame
        self.download_frame = ttk.LabelFrame(master, text="Download Progress")
        self.download_frame.pack(padx=10, pady=5, fill=tk.X)

        self.overall_progress_label = ttk.Label(self.download_frame, text="Overall Progress:")
        self.overall_progress_label.pack(pady=1, anchor=tk.W, padx=5)
        self.overall_progress_bar = ttk.Progressbar(self.download_frame, mode='determinate')
        self.overall_progress_bar.pack(fill=tk.X, padx=5, pady=1)

        self.progress_label = ttk.Label(self.download_frame, text="Ready. Load playlists from cache or connect to Plex.")
        self.progress_label.pack(pady=1, anchor=tk.W, padx=5)

        self.file_progress_label = ttk.Label(self.download_frame, text="Current File:")
        self.file_progress_label.pack(pady=1, anchor=tk.W, padx=5)
        self.file_progress_bar = ttk.Progressbar(self.download_frame, mode='determinate')
        self.file_progress_bar.pack(fill=tk.X, padx=5, pady=1)

        self.load_playlist_cache_on_startup()

    def quit_app(self, force=False):
        # (quit_app logic as before)
        if self.download_thread and self.download_thread.is_alive() and not force:
            if messagebox.askyesno("Confirm Quit", "A download is in progress. Are you sure you want to quit?"):
                self.stop_download = True
                self.master.destroy()
            else:
                return
        self.master.destroy()

    def load_config(self):
        # (load_config logic as before)
        global PLEX_BASE_URL, PLEX_TOKEN, BASE_DOWNLOAD_DIR
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config_data = json.load(f)
                    PLEX_BASE_URL = config_data.get('PLEX_BASE_URL', '')
                    PLEX_TOKEN = config_data.get('PLEX_TOKEN', '')
                    BASE_DOWNLOAD_DIR = config_data.get('BASE_DOWNLOAD_DIR', '')
            except Exception as e:
                logging.error(f"Error loading configuration from {CONFIG_FILE}: {e}")
                messagebox.showwarning("Config Error", f"Could not load configuration: {e}. Using defaults.")
        else:
            logging.info(f"Configuration file {CONFIG_FILE} not found. Using default/empty values.")

    def save_config(self):
        # (save_config logic as before)
        config_data = {
            'PLEX_BASE_URL': self.url_entry.get(),
            'PLEX_TOKEN': self.token_entry.get(),
            'BASE_DOWNLOAD_DIR': self.download_dir_entry.get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config_data, f, indent=4)
            logging.info(f"Configuration saved to {CONFIG_FILE}")
        except Exception as e:
            logging.error(f"Error saving configuration: {e}")
            messagebox.showerror("Error", "Failed to save configuration.")

    def save_playlist_cache(self):
        # (save_playlist_cache logic as before)
        cache_data = {
            "music_playlist_data": self.music_playlist_data,
            "video_playlist_data": self.video_playlist_data,
            "timestamp": datetime.now().isoformat()
        }
        try:
            with open(PLAYLIST_CACHE_FILE, 'w') as f:
                json.dump(cache_data, f, indent=4)
            logging.info(f"Playlist cache saved to {PLAYLIST_CACHE_FILE}")
            self.update_progress_label(f"Playlist cache saved ({len(self.music_playlist_data)} music, {len(self.video_playlist_data)} video).")
        except Exception as e:
            logging.error(f"Error saving playlist cache: {e}")
            self.update_progress_label("Error saving playlist cache.")


    def load_playlist_cache_on_startup(self):
        if os.path.exists(PLAYLIST_CACHE_FILE):
            try:
                with open(PLAYLIST_CACHE_FILE, 'r') as f:
                    cache_data = json.load(f)
                self.music_playlist_data = cache_data.get("music_playlist_data", [])
                self.video_playlist_data = cache_data.get("video_playlist_data", [])
                timestamp = cache_data.get("timestamp", "N/A")

                if self.music_playlist_data or self.video_playlist_data:
                    self.cache_successfully_loaded = True
                    self.live_data_fetched_this_session = False # Data is from cache
                    logging.info(f"Playlist cache loaded. Music: {len(self.music_playlist_data)}, Video: {len(self.video_playlist_data)}. Cached at: {timestamp}")
                    self.update_playlist_display_from_data()
                    self.update_progress_label(f"Loaded playlists from cache. Last updated: {timestamp.split('T')[0] if timestamp != 'N/A' else 'Unknown'}")
                    self.refresh_button.config(state=tk.NORMAL)
                else: # Cache file exists but is empty or malformed for data lists
                    self.cache_successfully_loaded = False
                    self.live_data_fetched_this_session = False
                    self.update_progress_label("Playlist cache file found but contained no valid data. Connect to Plex.")
                    logging.warning("Playlist cache file found but no valid data loaded.")

            except Exception as e:
                self.cache_successfully_loaded = False
                self.live_data_fetched_this_session = False
                logging.error(f"Error loading playlist cache: {e}", exc_info=True)
                self.update_progress_label("Error loading playlist cache. File might be corrupt. Connect to Plex.")
                self.music_playlist_data = []
                self.video_playlist_data = []
        else:
            self.cache_successfully_loaded = False
            self.live_data_fetched_this_session = False
            self.update_progress_label("No playlist cache found. Use 'Connect / Initial Fetch' to get playlists.")
            logging.info("Playlist cache file not found.")

    def browse_download_dir(self):
        # (browse_download_dir logic as before)
        directory = filedialog.askdirectory()
        if directory:
            self.download_dir_entry.delete(0, tk.END)
            self.download_dir_entry.insert(0, directory)

    def handle_plex_connection_and_initial_fetch(self):
        url = self.url_entry.get()
        token = self.token_entry.get()
        if not url or not token:
            messagebox.showerror("Error", "Plex Base URL and Token are required.")
            return

        self.save_config()
        self.update_progress_label("Connecting to Plex...")
        self.connect_button.config(state=tk.DISABLED)
        self.refresh_button.config(state=tk.DISABLED) # Disable while attempting connection/fetch

        try:
            self.plex = PlexServer(url, token, timeout=10)
            logging.info("Successfully connected to Plex.")
            # Enable refresh button as soon as connection is made, regardless of cache.
            self.master.after(0, self.refresh_button.config, {"state": tk.NORMAL})

            if not self.cache_successfully_loaded:
                # No valid cache was loaded at startup, so perform initial fetch
                self.update_progress_label("Connected! No cache found, performing initial playlist fetch...")
                messagebox.showinfo("Plex Connected", "Connected to Plex! No local cache was found, so fetching playlists now.")
                Thread(target=self.fetch_playlists_from_plex_threaded, daemon=True).start()
            else:
                # Cache was loaded, so connection is established but no automatic fetch
                self.update_progress_label("Connected to Plex. Using cached playlists. Use 'Refresh Playlists' for updates.")
                messagebox.showinfo("Plex Connected", "Connected to Plex! Displaying playlists from local cache. Use 'Refresh Playlists' to get the latest from server.")
                self.connect_button.config(state=tk.NORMAL) # Re-enable connect button
                # Refresh button was already enabled above or by cache load
        except Exception as e:
            error_message = f"Failed to connect to Plex: {e}"
            messagebox.showerror("Error", f"Failed to connect to Plex. Check URL/token.\nDetails: {e}")
            logging.error(f"Error connecting to Plex: {e}", exc_info=True)
            self.update_progress_label("Plex connection failed.")
            self.connect_button.config(state=tk.NORMAL)
            # Refresh button state depends on whether cache was loaded prior to this failed attempt
            if self.cache_successfully_loaded:
                 self.refresh_button.config(state=tk.NORMAL)
            else:
                 self.refresh_button.config(state=tk.DISABLED)

    def refresh_plex_data_action(self):
        self.update_progress_label("Attempting to refresh playlists from Plex...")
        self.connect_button.config(state=tk.DISABLED)
        self.refresh_button.config(state=tk.DISABLED)

        if not self.plex: # If not connected (e.g. app started with cache, connect never clicked)
            url = self.url_entry.get()
            token = self.token_entry.get()
            if not url or not token:
                messagebox.showerror("Error", "Plex URL and Token are required to refresh playlists.")
                self.update_progress_label("Plex URL/Token needed for refresh.")
                self.connect_button.config(state=tk.NORMAL)
                self.refresh_button.config(state=tk.NORMAL) # Re-enable
                return
            try:
                self.update_progress_label("Connecting to Plex for refresh...")
                self.plex = PlexServer(url, token, timeout=10)
                logging.info("Connected to Plex via Refresh action.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to connect to Plex for refresh: {e}")
                self.update_progress_label(f"Connection failed for refresh: {e}")
                logging.error(f"Failed to connect to Plex for refresh: {e}", exc_info=True)
                self.connect_button.config(state=tk.NORMAL)
                self.refresh_button.config(state=tk.NORMAL) # Re-enable
                return

        # Proceed to fetch
        self.update_progress_label("Refreshing playlists from Plex server...")
        Thread(target=self.fetch_playlists_from_plex_threaded, daemon=True).start()


    def fetch_playlists_from_plex_threaded(self):
        if not self.plex: # Should have been established by caller
            self.master.after(0, self.update_progress_label, "Error: Not connected to Plex for fetching.")
            self.master.after(0, self.connect_button.config, {"state": tk.NORMAL})
            self.master.after(0, self.refresh_button.config, {"state": tk.NORMAL})
            return

        self.master.after(0, self.update_progress_label, "Fetching playlists from Plex server...")
        temp_music_data = []
        temp_video_data = []

        try:
            all_playlists = self.plex.playlists()
            total_playlists = len(all_playlists)
            logging.info(f"Found {total_playlists} playlists on server.")
            self.master.after(0, self.overall_progress_bar.config, {"mode": 'determinate', "maximum": total_playlists, "value": 0})

            for i, pl in enumerate(all_playlists):
                # (The rest of the fetching loop as previously defined)
                self.master.after(0, self.update_progress_label, f"Processing playlist: {pl.title} ({i+1}/{total_playlists})")
                if pl.title == "All Music":
                    logging.info(f"Skipping 'All Music' playlist.")
                    self.master.after(0, self.overall_progress_bar.step)
                    continue
                try:
                    items = pl.items()
                    item_count = len(items)
                    if not items:
                        logging.info(f"Playlist '{pl.title}' is empty. Skipping.")
                        self.master.after(0, self.overall_progress_bar.step)
                        continue

                    first_item_type = items[0].type
                    display_s = self._get_playlist_size_from_live_playlist(pl)

                    playlist_info = {
                        'title': pl.title,
                        'item_count': item_count,
                        'display_size': display_s,
                        'summary': pl.summary if hasattr(pl, 'summary') else ''
                    }

                    if first_item_type == 'track':
                        playlist_info['type'] = 'Music'
                        temp_music_data.append(playlist_info)
                    elif first_item_type in ('movie', 'episode'):
                        playlist_info['type'] = 'Video'
                        temp_video_data.append(playlist_info)
                    else:
                        logging.info(f"Playlist '{pl.title}' contains items of type '{first_item_type}', not categorized as Music/Video.")
                except Exception as e_pl:
                    error_msg = f"Error processing playlist '{pl.title}': {e_pl}"
                    logging.error(error_msg, exc_info=True)
                    self.master.after(0, self.update_progress_label, f"⚠️ {error_msg}")
                self.master.after(0, self.overall_progress_bar.step)
                self.master.update_idletasks()

            self.music_playlist_data = temp_music_data
            self.video_playlist_data = temp_video_data
            self.live_data_fetched_this_session = True # Mark that live data was fetched
            self.cache_successfully_loaded = True # After a successful fetch, we consider the data "cached" in memory for the session
            self.master.after(0, self.save_playlist_cache)
            self.master.after(0, self.update_playlist_display_from_data)
            self.master.after(0, self.update_progress_label, "Playlists fetched and updated successfully.")
            logging.info("Playlist fetch and processing complete.")

        except Exception as e_fetch:
            error_msg = f"Failed to fetch playlists from Plex: {e_fetch}"
            logging.error(error_msg, exc_info=True)
            self.master.after(0, messagebox.showerror, ("Plex Error", error_msg))
            self.master.after(0, self.update_progress_label, "Error fetching playlists.")
        finally:
            self.master.after(0, self.overall_progress_bar.config, {"value": 0, "mode": 'determinate'})
            self.master.after(0, self.connect_button.config, {"state": tk.NORMAL})
            self.master.after(0, self.refresh_button.config, {"state": tk.NORMAL})

    def _get_playlist_size_from_live_playlist(self, playlist_obj):
        # (_get_playlist_size_from_live_playlist logic as before)
        total_size_bytes = 0
        if not self.plex:
            return "Size N/A (Plex not connected)"
        try:
            items = playlist_obj.items()
            for item in items:
                if hasattr(item, 'media') and item.media:
                    for media_item in item.media:
                        if hasattr(media_item, 'parts') and media_item.parts:
                            for part in media_item.parts:
                                if hasattr(part, 'size') and part.size is not None:
                                    total_size_bytes += int(part.size)
        except Exception as e:
            logging.error(f"Error calculating size for playlist '{playlist_obj.title}': {e}", exc_info=True)
            return "Size Error"
        return self._format_size_bytes(total_size_bytes)


    def _format_size_bytes(self, size_bytes):
        # (_format_size_bytes logic as before)
        if size_bytes == 0: return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while size_bytes >= 1024 and i < len(units) - 1:
            size_bytes /= 1024
            i += 1
        return f"{size_bytes:.2f} {units[i]}"

    def update_playlist_display_from_data(self):
        # (update_playlist_display_from_data logic as before)
        selected_media_type = self.media_type.get()
        # self.update_progress_label(f"Updating display for {selected_media_type} playlists...") # Can be noisy
        self.playlist_list_var.set([])

        current_data_list = self.music_playlist_data if selected_media_type == "Music" else self.video_playlist_data

        if not current_data_list:
            # Update progress label based on why the list might be empty
            if not self.cache_successfully_loaded and not self.live_data_fetched_this_session:
                self.update_progress_label(f"No {selected_media_type} playlists. Use 'Connect / Initial Fetch'.")
            elif self.cache_successfully_loaded and not self.live_data_fetched_this_session:
                 self.update_progress_label(f"No {selected_media_type} playlists found in local cache.")
            elif self.live_data_fetched_this_session: # Live fetch happened but this category is empty
                 self.update_progress_label(f"No {selected_media_type} playlists found on server after refresh.")
            return

        display_list = []
        for pl_info in current_data_list:
            display_list.append(f"{pl_info['title']} ({pl_info['item_count']} items, {pl_info['display_size']})")

        self.master.after(0, self.playlist_list_var.set, display_list)
        # self.master.after(0, self.update_progress_label, f"{selected_media_type} playlist display updated.") # Also noisy


    def start_download(self):
        # (start_download logic mostly as before, ensuring it uses live_playlist_obj)
        if not self.plex:
            messagebox.showerror("Error", "Not connected to Plex. Please connect first to download.")
            return

        selected_indices = self.playlist_list.curselection()
        if not selected_indices:
            messagebox.showerror("Error", "Please select a playlist to download.")
            return
        selected_index = selected_indices[0]

        selected_media_type = self.media_type.get()
        playlist_data_list = self.music_playlist_data if selected_media_type == "Music" else self.video_playlist_data

        if selected_index >= len(playlist_data_list):
            messagebox.showerror("Error", "Selected playlist index out of bounds. Please refresh.")
            return

        selected_playlist_info = playlist_data_list[selected_index]
        playlist_title_to_download = selected_playlist_info['title']
        download_dir = self.download_dir_entry.get()

        if not download_dir:
            messagebox.showerror("Error", "Please specify a download directory.")
            return
        if not os.path.isdir(download_dir):
            messagebox.showerror("Error", "Download directory does not exist. Please create it or choose another.")
            return

        try:
            self.update_progress_label(f"Fetching details for playlist: {playlist_title_to_download}...")
            actual_playlist_object = self.plex.playlist(playlist_title_to_download) # Fetch live object
            if not actual_playlist_object:
                messagebox.showerror("Error", f"Playlist '{playlist_title_to_download}' no longer found on server. Please refresh playlists.")
                self.update_progress_label(f"Playlist '{playlist_title_to_download}' not found.")
                return
        except NotFound: # More specific exception
            messagebox.showerror("Error", f"Playlist '{playlist_title_to_download}' not found on the Plex server. It may have been deleted. Please refresh your playlists.")
            self.update_progress_label(f"Playlist '{playlist_title_to_download}' not found on server.")
            return
        except Exception as e:
            messagebox.showerror("Error", f"Could not retrieve playlist '{playlist_title_to_download}' from Plex: {e}")
            logging.error(f"Error retrieving live playlist {playlist_title_to_download}: {e}", exc_info=True)
            self.update_progress_label("Error fetching playlist details.")
            return

        self.stop_download = False
        self.source_file_access_warning_shown = False # Reset flag here
        self.download_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.download_thread = Thread(target=self.download_playlist_worker, args=(actual_playlist_object, download_dir, selected_media_type), daemon=True)
        self.download_thread.start()

    def download_playlist_worker(self, live_playlist_obj, base_dir, media_type_folder_name):
        # (download_playlist_worker logic as before)
        playlist_title = live_playlist_obj.title
        try:
            playlist_items = live_playlist_obj.items()
        except Exception as e:
            self.master.after(0, self.update_progress_label, f"❌ Error fetching items for '{playlist_title}': {e}")
            logging.error(f"Error fetching items for playlist '{playlist_title}' during download: {e}", exc_info=True)
            self.master.after(0, self.download_button.config, {"state": tk.NORMAL})
            self.master.after(0, self.stop_button.config, {"state": tk.DISABLED})
            return

        total_items = len(playlist_items)
        sane_playlist_title = "".join(c for c in playlist_title if c.isalnum() or c in (' ', '_', '-')).rstrip()
        download_path_for_playlist = os.path.join(base_dir, media_type_folder_name, sane_playlist_title)

        try:
            os.makedirs(download_path_for_playlist, exist_ok=True)
        except OSError as e:
            self.master.after(0, self.update_progress_label, f"❌ Error creating directory: {download_path_for_playlist}. {e.strerror}")
            logging.error(f"OSError creating directory {download_path_for_playlist}: {e}", exc_info=True)
            self.master.after(0, self.download_button.config, {"state": tk.NORMAL})
            self.master.after(0, self.stop_button.config, {"state": tk.DISABLED})
            return

        self.master.after(0, self.update_progress_label, f"Starting download: '{playlist_title}' ({total_items} items)")
        self.master.after(0, self.overall_progress_bar.config, {"mode": 'determinate', "maximum": total_items, "value": 0})

        for i, item in enumerate(playlist_items):
            if self.stop_download:
                self.master.after(0, self.update_progress_label, "Download stopped by user.")
                logging.info(f"Download of playlist '{playlist_title}' stopped by user.")
                break

            self.master.after(0, self.overall_progress_bar.config, {"value": i})
            item_title_for_log = getattr(item, 'title', f"Item {i+1}")
            self.master.after(0, self.file_progress_label.config, {"text": f"Item {i+1}/{total_items}: Preparing {item_title_for_log}"})
            self.master.after(0, self.file_progress_bar.config, {"value": 0, "mode": 'indeterminate'})
            self.master.update_idletasks()

            try:
                if not (hasattr(item, 'media') and item.media and hasattr(item.media[0], 'parts') and item.media[0].parts):
                    logging.warning(f"Item '{item_title_for_log}' in playlist '{playlist_title}' has no media parts. Skipping.")
                    self.master.after(0, self.file_progress_label.config, {"text": f"Item {i+1}/{total_items}: No media parts for {item_title_for_log}. Skipping."})
                    if i + 1 == total_items : self.master.after(0, self.overall_progress_bar.config, {"value": i + 1})
                    continue

                source_part = item.media[0].parts[0]
                source_file_path_on_server = source_part.file

                sane_server_filename = "".join(c for c in os.path.basename(source_file_path_on_server) if c.isalnum() or c in ('.', '_', '-')).rstrip()
                if not sane_server_filename: # Handle cases where basename becomes empty after sanitization
                    sane_server_filename = f"item_{i+1}_{getattr(item, 'ratingKey', 'unknown')}{os.path.splitext(source_part.key)[-1] if hasattr(source_part, 'key') else '.dat'}"


                destination_file_path = os.path.join(download_path_for_playlist, sane_server_filename)

                if not os.path.exists(source_file_path_on_server):
                    error_msg = f"File not found on this system: {source_file_path_on_server}. Ensure Plex media paths are accessible."
                    logging.error(error_msg + f" (For item: {item_title_for_log})")
                    self.master.after(0, self.file_progress_label.config, {"text": f"Item {i+1}/{total_items}: ⚠️ File not found: {os.path.basename(source_file_path_on_server)}. Skipping."})
                    if not self.source_file_access_warning_shown:
                        detailed_warning = (f"Warning: Source file '{os.path.basename(source_file_path_on_server)}' "
                                            f"not found on this system. This script requires direct file system "
                                            f"access to Plex media files. If this issue persists for multiple files, "
                                            f"please ensure that the file paths reported by Plex are correctly "
                                            f"mounted and accessible with the necessary read permissions by the "
                                            f"user running this script.")
                        # Call self.update_progress_label through self.master.after
                        self.master.after(0, self.update_progress_label, detailed_warning)
                        self.source_file_access_warning_shown = True
                    if i + 1 == total_items : self.master.after(0, self.overall_progress_bar.config, {"value": i + 1})
                    continue

                file_size = os.path.getsize(source_file_path_on_server)
                self.master.after(0, self.file_progress_label.config, {"text": f"Item {i+1}/{total_items}: Downloading {sane_server_filename} ({self._format_size_bytes(file_size)})"})
                self.master.after(0, self.file_progress_bar.config, {"maximum": file_size, "value": 0, "mode": 'determinate'})

                copied_bytes = 0
                with open(source_file_path_on_server, 'rb') as fsrc, open(destination_file_path, 'wb') as fdst:
                    while True:
                        if self.stop_download: break
                        chunk = fsrc.read(1024 * 1024)
                        if not chunk: break
                        fdst.write(chunk)
                        copied_bytes += len(chunk)
                        self.master.after(0, self.file_progress_bar.config, {"value": copied_bytes})
                        self.master.update_idletasks()

                if self.stop_download:
                    if os.path.exists(destination_file_path): os.remove(destination_file_path)
                    logging.info(f"Download of {sane_server_filename} stopped, partial file removed.")
                    break
                logging.info(f"Successfully copied '{sane_server_filename}' to '{download_path_for_playlist}'")

            except Exception as e_item:
                error_msg = f"Failed to download item '{item_title_for_log}': {e_item}"
                logging.error(error_msg, exc_info=True)
                self.master.after(0, self.file_progress_label.config, {"text": f"Item {i+1}/{total_items}: ❌ Error downloading {item_title_for_log}. Check logs."})
            self.master.after(0, self.overall_progress_bar.config, {"value": i + 1})
            self.master.update_idletasks()

        if not self.stop_download:
            self.master.after(0, self.update_progress_label, f"✅ Download of '{playlist_title}' complete!")
            logging.info(f"Download of playlist '{playlist_title}' completed.")
        else:
            self.master.after(0, self.update_progress_label, f"Download of '{playlist_title}' was stopped.")

        self.master.after(0, self.download_button.config, {"state": tk.NORMAL})
        self.master.after(0, self.stop_button.config, {"state": tk.DISABLED})
        self.master.after(0, self.file_progress_label.config, {"text": "Current File:"})
        self.master.after(0, self.file_progress_bar.config, {"value": 0, "mode": 'determinate'})
        self.master.after(0, self.overall_progress_bar.config, {"value": 0})


    def stop_download_process(self):
        # (stop_download_process logic as before)
        self.stop_download = True
        self.update_progress_label("Stopping current download...")
        self.stop_button.config(state=tk.DISABLED)
        logging.info("Stop download requested by user.")

    def update_progress_label(self, text):
        # (update_progress_label logic as before)
        self.progress_label.config(text=text)
        self.master.update_idletasks()

if __name__ == "__main__":
    if not check_and_install_tkinter():
        print("CRITICAL: tkinter is missing and could not be auto-installed. The application cannot run.")
        exit(1)

    plexapi_ready = check_and_install_plexapi()
    if not plexapi_ready:
        print("WARNING: plexapi module is missing or could not be installed. Plex functionality will be impaired.")

    root = tk.Tk()
    app = PlexDownloaderGUI(root)
    root.mainloop()
