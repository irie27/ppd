import os
import re
import sys
import time
import json # For saving/loading configuration
import subprocess
import importlib.util # To check if modules are installed
import threading # For running downloads in a separate thread
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import math # For format_size

# --- Python Version Check ---
# This check must be compatible with older Python versions.
# F-strings and other modern features are used later in the script.
if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 6):
    try:
        root = tk.Tk()
        root.withdraw() # Hide the main window
        messagebox.showerror(
            "Unsupported Python Version",
            "This application requires Python 3.6 or newer to run.\n"
            "You are using Python {}.{}.{}.\n"
            "Please install a newer version of Python.".format(
                sys.version_info[0], sys.version_info[1], sys.version_info[2]
            )
        )
        root.destroy()
    except: # Catch all, including potential _tkinter error on older systems
        print("ERROR: This application requires Python 3.6 or newer to run.")
        print("You are using Python {}.{}.{}.".format(
            sys.version_info[0], sys.version_info[1], sys.version_info[2]
        ))
    sys.exit(1)

# --- Dependencies ---
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


# --- Global Variables for GUI Elements & Control ---
server_type_var = None
remote_plex_url_var = None
local_plex_address_var = None
plex_token_var = None
save_token_var = None
download_dir_var = None
status_text_area = None

music_playlist_listbox = None
video_playlist_listbox = None
all_music_playlists_global = []
all_video_playlists_global = []


connect_button = None
download_selected_music_button = None
download_selected_video_button = None
download_all_music_button = None
download_all_video_button = None
stop_download_button = None
save_config_button = None
quit_button = None

plex_instance_global = None
stop_download_event = threading.Event()

overall_progress_label_var = None
playlist_progress_bar = None
current_file_label_var = None
file_progress_bar = None
download_speed_label_var = None
root_window = None

remote_plex_url_entry = None
local_plex_address_entry = None


def check_and_install_packages():
    """Checks if required packages are installed and prompts to install them if not."""
    missing_packages = []
    for package_name in REQUIRED_PACKAGES:
        spec = importlib.util.find_spec(package_name)
        if spec is None:
            missing_packages.append(package_name)

    if missing_packages:
        proceed_install = messagebox.askyesno("Missing Dependencies",
                               f"The following required packages are missing: {', '.join(missing_packages)}.\n\nDo you want to try and install them now?")

        if proceed_install:
            try:
                print("Installing missing packages...")
                for pkg in missing_packages:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
                print("Packages installed successfully. Please restart the application.")
                messagebox.showinfo("Installation Complete", "Packages installed. Please restart the application for changes to take effect.")
                return False
            except subprocess.CalledProcessError as e:
                print(f"Error installing packages: {e}")
                messagebox.showerror("Installation Error", f"Error installing packages: {e}\nPlease install them manually: pip install {' '.join(missing_packages)}")
                return False
            except Exception as e:
                print(f"An unexpected error occurred during installation: {e}")
                messagebox.showerror("Installation Error", f"Unexpected error: {e}\nPlease install them manually: pip install {' '.join(missing_packages)}")
                return False
        else:
            print("User chose not to install missing packages. Application may not function.")
            messagebox.showwarning("Dependencies Missing", "Application may not function correctly without the required packages.")
            return False
    else:
        print("All required packages are already installed.")
        return True
    return True

def log_status(message):
    """Logs a message to the GUI status text area and console."""
    print(message)
    if status_text_area and root_window:
        def _update_log():
            if status_text_area.winfo_exists():
                current_state = status_text_area.cget('state')
                status_text_area.config(state=tk.NORMAL)
                status_text_area.insert(tk.END, message + "\n")
                status_text_area.see(tk.END)
                status_text_area.config(state=current_state)
        if root_window.winfo_exists():
             root_window.after(0, _update_log)


def load_config():
    """Loads configuration from JSON file."""
    global remote_plex_url_var, local_plex_address_var, plex_token_var, download_dir_var, save_token_var, server_type_var

    if not all([remote_plex_url_var, local_plex_address_var, plex_token_var, download_dir_var, save_token_var, server_type_var]):
        print("Warning: load_config called before GUI vars initialized.")
        return
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

            server_type_var.set(config.get("server_type", "remote"))
            remote_plex_url_var.set(config.get("remote_plex_url", "https://your-plex-url.com"))
            local_plex_address_var.set(config.get("local_plex_address", "http://localhost:32400"))
            download_dir_var.set(config.get("download_dir", os.path.join(os.getcwd(), "Plex_Downloads")))

            should_save_token = config.get("save_token", False)
            save_token_var.set(should_save_token)
            if plex_token_var and should_save_token:
                plex_token_var.set(config.get("plex_token", ""))
            elif plex_token_var:
                plex_token_var.set("")

            log_status(f"Configuration loaded from {CONFIG_FILE}")
        else:
            log_status(f"No configuration file found at {CONFIG_FILE}. Using defaults.")
            server_type_var.set("remote")
            remote_plex_url_var.set("https://your-plex-url.com")
            local_plex_address_var.set("http://localhost:32400")
            download_dir_var.set(os.path.join(os.getcwd(), "Plex_Downloads"))
            save_token_var.set(False)
            plex_token_var.set("")

        toggle_url_entries()

    except (FileNotFoundError, json.JSONDecodeError) as e:
        log_status(f"Error loading configuration: {e}. Using defaults.")
        server_type_var.set("remote")
        toggle_url_entries()
    except Exception as e:
        log_status(f"Unexpected error loading configuration: {e}. Using defaults.")
        server_type_var.set("remote")
        toggle_url_entries()


def save_config():
    """Saves current configuration to JSON file."""
    if not all([remote_plex_url_var, local_plex_address_var, download_dir_var, save_token_var, plex_token_var, server_type_var]):
        log_status("GUI elements not ready for saving config.")
        return

    config = {
        "server_type": server_type_var.get(),
        "remote_plex_url": remote_plex_url_var.get(),
        "local_plex_address": local_plex_address_var.get(),
        "download_dir": download_dir_var.get(),
        "save_token": save_token_var.get()
    }
    if save_token_var.get():
        config["plex_token"] = plex_token_var.get()
    else:
        config["plex_token"] = ""

    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        log_status(f"Configuration saved to {CONFIG_FILE}")
    except Exception as e:
        log_status(f"Error saving configuration: {e}")
        if root_window and root_window.winfo_exists():
            messagebox.showerror("Config Error", f"Could not save configuration: {e}")

def on_exit():
    """Handler for application exit."""
    log_status("Exiting application...")
    if stop_download_event:
        stop_download_event.set()
        log_status("Sent stop signal to active downloads if any...")
    save_config()
    if root_window:
        root_window.destroy()

def sanitize_filename(filename):
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = sanitized.replace(":", " - ")
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized[:200]

def get_item_details(item):
    filename = ""
    extension = "unknown"
    try:
        if item.media and len(item.media) > 0:
            media = item.media[0]
            if media.parts and len(media.parts) > 0:
                part = media.parts[0]
                extension = part.container if part.container else 'mkv'
                if hasattr(part, 'file') and '.' in part.file:
                    file_ext = part.file.split('.')[-1]
                    if len(file_ext) <= 4: extension = file_ext

        if item.type == 'movie':
            title = item.title
            year = item.year if hasattr(item, 'year') and item.year else ""
            filename = f"{title} ({year})" if year else title
        elif item.type == 'episode':
            show_title = item.grandparentTitle if hasattr(item, 'grandparentTitle') else "Unknown Show"
            season_num = item.parentIndex if hasattr(item, 'parentIndex') else "XX"
            episode_num = item.index if hasattr(item, 'index') else "YY"
            episode_title = item.title if item.title else "Unknown Episode"
            filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {episode_title}"
        elif item.type == 'track':
            artist_title = getattr(item, 'grandparentTitle', "Unknown Artist")
            album_title = getattr(item, 'parentTitle', "Unknown Album")
            track_num_val = getattr(item, 'index', 0)
            track_title = getattr(item, 'title', "Unknown Track")
            filename = f"{artist_title} - {album_title} - {track_num_val:02d}. {track_title}"
        else:
            filename = item.title if hasattr(item, 'title') else "Unknown_Item"
        return sanitize_filename(filename), extension.lower()
    except Exception as e:
        log_status(f"  Error getting details for item '{getattr(item, 'title', 'Unknown Item')}': {e}")
        return sanitize_filename(getattr(item, 'title', 'Unknown_Item')), 'mkv'


def format_size(size_bytes):
    if not isinstance(size_bytes, (int, float)) or size_bytes < 0: return "0 B"
    if size_bytes == 0: return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(max(1, size_bytes), 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def update_file_download_ui(filename, percent, speed_str, downloaded_str, total_str):
    if not root_window or not root_window.winfo_exists(): return
    def _update():
        if not root_window.winfo_exists(): return
        if current_file_label_var:
            current_file_label_var.set(f"Downloading: {filename} ({downloaded_str}/{total_str})")
        if file_progress_bar:
            if percent is None:
                file_progress_bar.config(mode='indeterminate')
                if hasattr(file_progress_bar, 'start') and not file_progress_bar.winfo_ismapped():
                    file_progress_bar.start(10)
            else:
                if hasattr(file_progress_bar, 'stop'): file_progress_bar.stop()
                file_progress_bar.config(mode='determinate')
                file_progress_bar['value'] = percent
        if download_speed_label_var:
            download_speed_label_var.set(f"Speed: {speed_str}")
    root_window.after(0, _update)


def _download_file_with_progress(plex_server_token, stream_url, full_filepath, display_filename):
    global root_window, stop_download_event

    is_remote = server_type_var.get() == "remote"
    max_retries = REMOTE_MAX_DOWNLOAD_RETRIES if is_remote else LOCAL_MAX_DOWNLOAD_RETRIES
    current_retry_delay = REMOTE_INITIAL_RETRY_DELAY if is_remote else LOCAL_INITIAL_RETRY_DELAY
    connect_timeout = REMOTE_CONNECT_TIMEOUT if is_remote else LOCAL_CONNECT_TIMEOUT
    read_timeout = REMOTE_READ_TIMEOUT if is_remote else LOCAL_READ_TIMEOUT

    for attempt in range(max_retries):
        if stop_download_event.is_set():
            log_status(f"    Download process stopped before attempting {display_filename}.")
            return False

        try:
            log_status(f"    Starting download for: {display_filename} from {stream_url} (Attempt {attempt + 1}/{max_retries})")
            headers = {'X-Plex-Token': plex_server_token, 'Accept': '*/*'}
            session = plex_instance_global._session if plex_instance_global and hasattr(plex_instance_global, '_session') else requests.Session()

            with session.get(stream_url, headers=headers, stream=True, timeout=(connect_timeout, read_timeout)) as r:
                r.raise_for_status()
                total_size_in_bytes = r.headers.get('content-length')
                total_size_in_bytes = int(total_size_in_bytes) if total_size_in_bytes else None

                bytes_downloaded = 0
                start_time = time.time()
                last_update_time = start_time
                bytes_since_last_update = 0

                if root_window and root_window.winfo_exists():
                    total_s = format_size(total_size_in_bytes) if total_size_in_bytes else "Unknown"
                    update_file_download_ui(display_filename, 0 if total_size_in_bytes else None, "0 B/s", "0 B", total_s)

                with open(full_filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192*8):
                        if stop_download_event.is_set():
                            log_status(f"    Stop signal received. Aborting download of {display_filename}.")
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
                                total_s = format_size(total_size_in_bytes) if total_size_in_bytes else "Unknown"
                                if root_window and root_window.winfo_exists():
                                    update_file_download_ui(display_filename, percent, speed_str, downloaded_s, total_s)
                                last_update_time = current_time
                                bytes_since_last_update = 0

                if root_window and root_window.winfo_exists():
                    final_downloaded_s = format_size(bytes_downloaded)
                    final_total_s = format_size(total_size_in_bytes) if total_size_in_bytes else "Unknown"
                    final_percent = 100 if total_size_in_bytes and bytes_downloaded == total_size_in_bytes else None
                    update_file_download_ui(display_filename, final_percent, "Done", final_downloaded_s, final_total_s)
                log_status(f"    Successfully downloaded: {display_filename}")
                return True

        except InterruptedError:
            return False
        except requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code
            response_text_snippet = http_err.response.text[:200] if http_err.response.text else "No response text."
            log_status(f"    Download failed for {display_filename} (HTTP {status_code}) on attempt {attempt + 1}. Response: {response_text_snippet}")

            if 500 <= status_code < 600 and attempt < max_retries - 1:
                log_status(f"    Retrying in {current_retry_delay}s...")
                sleep_start_time = time.time()
                while time.time() - sleep_start_time < current_retry_delay:
                    if stop_download_event.is_set():
                        log_status(f"    Download stop requested during retry delay for {display_filename}.")
                        return False
                    time.sleep(0.1)
                current_retry_delay *= 2
                continue
            else:
                log_status(f"    Not retrying HTTP {status_code} or retries exhausted for {display_filename}.")
                break
        except requests.exceptions.RequestException as e:
            log_status(f"    Download failed for {display_filename} (RequestException: {e}) on attempt {attempt + 1}.")
            if attempt < max_retries - 1:
                log_status(f"    Retrying in {current_retry_delay}s...")
                sleep_start_time = time.time()
                while time.time() - sleep_start_time < current_retry_delay:
                    if stop_download_event.is_set():
                        log_status(f"    Download stop requested during retry delay for {display_filename}.")
                        return False
                    time.sleep(0.1)
                current_retry_delay *= 2
                continue
            else:
                log_status(f"    Retries exhausted for {display_filename} after RequestException.")
                break
        except IOError as e:
            log_status(f"    Download failed for {display_filename} (IOError: {e}). Not retrying.")
            break
        except Exception as e:
            log_status(f"    Download failed for {display_filename} (Unexpected Error: {e}). Not retrying.")
            import traceback; traceback.print_exc()
            break

    if root_window and root_window.winfo_exists():
        update_file_download_ui("-", 0, "0 B/s", "-", "-")
        if file_progress_bar and hasattr(file_progress_bar, 'stop'):
            root_window.after(0, lambda: file_progress_bar.config(mode='determinate') if file_progress_bar.winfo_exists() else None)
            root_window.after(0, lambda: file_progress_bar.stop() if file_progress_bar.winfo_exists() else None)
    return False


def actual_download_process(plex, playlists_to_download, base_download_dir):
    global stop_download_event
    if not plex or not playlists_to_download:
        log_status("Plex instance or playlists not provided for download.")
        _toggle_ui_for_download_end()
        return

    total_playlists = len(playlists_to_download)
    try:
        for playlist_idx, playlist in enumerate(playlists_to_download):
            if stop_download_event.is_set():
                log_status("Download process stopped by user (between playlists).")
                break
            if overall_progress_label_var:
                overall_progress_label_var.set(f"Playlist: {playlist.title} ({playlist_idx + 1}/{total_playlists})")

            playlist_title_sanitized = sanitize_filename(playlist.title)
            playlist_dir = os.path.join(base_download_dir, playlist_title_sanitized)
            os.makedirs(playlist_dir, exist_ok=True)
            log_status(f"\nProcessing playlist: '{playlist.title}' in '{playlist_dir}'")

            try:
                items = playlist.items()
            except Exception as e:
                log_status(f"  Could not retrieve items for playlist '{playlist.title}': {e}")
                if playlist_progress_bar: playlist_progress_bar['value'] = 0
                continue

            if not items:
                log_status(f"  Playlist '{playlist.title}' is empty.")
                if playlist_progress_bar: playlist_progress_bar['value'] = 0
                continue

            num_items = len(items)
            if playlist_progress_bar:
                playlist_progress_bar['maximum'] = num_items
                playlist_progress_bar['value'] = 0

            for i, item in enumerate(items):
                if stop_download_event.is_set():
                    log_status("Download process stopped by user (between items).")
                    break

                base_filename_template, ext_template = get_item_details(item)
                actual_part_to_download = None
                if item.media and len(item.media) > 0 and item.media[0].parts and len(item.media[0].parts) > 0:
                    actual_part_to_download = item.media[0].parts[0]
                    ext = actual_part_to_download.container if actual_part_to_download.container else ext_template
                else:
                    log_status(f"  No media parts for '{getattr(item, 'title', 'Unknown Item')}'")
                    if playlist_progress_bar: playlist_progress_bar['value'] = i + 1
                    continue

                base_filename = base_filename_template
                if '.' in base_filename: name_part, _ = os.path.splitext(base_filename); base_filename = name_part
                output_filename = f"{base_filename}.{ext.lower()}"
                filepath = os.path.join(playlist_dir, output_filename)
                display_filename_short = output_filename if len(output_filename) < 50 else output_filename[:47]+"..."
                log_status(f"  Item [{i+1}/{num_items}]: Preparing '{getattr(item, 'title', 'Unknown Item')}' as '{output_filename}'")

                if os.path.exists(filepath):
                    log_status(f"  Skipping '{output_filename}', file already exists.")
                else:
                    stream_url = None
                    try:
                        stream_url = plex_instance_global.url(actual_part_to_download.key, includeToken=False)
                        if not stream_url.startswith('http'):
                            stream_url = plex_instance_global._baseurl.rstrip('/') + stream_url

                        log_status(f"    Constructed stream URL: {stream_url}")

                        download_successful = _download_file_with_progress(plex_instance_global._token, stream_url, filepath, display_filename_short)

                        if not download_successful and stop_download_event.is_set():
                             break
                        elif not download_successful:
                             log_status(f"  Download of '{output_filename}' ultimately failed after all attempts or due to a non-retryable error.")

                    except Exception as e_stream:
                        log_status(f"  CRITICAL ERROR in actual_download_process for '{output_filename}': {type(e_stream).__name__} - {e_stream}")
                        import traceback
                        log_status("  Full Traceback for e_stream:\n" + traceback.format_exc())

                if playlist_progress_bar: playlist_progress_bar['value'] = i + 1
            if stop_download_event.is_set(): break
            if playlist_progress_bar: playlist_progress_bar['value'] = 0
    finally:
        log_status("\nDownload process " + ("stopped by user." if stop_download_event.is_set() else "finished."))
        _toggle_ui_for_download_end()


def _toggle_ui_for_download_start():
    """Disables/Enables UI elements when a download starts."""
    if root_window and root_window.winfo_exists():
        def _update():
            if connect_button: connect_button.config(state=tk.DISABLED)
            # Adjust for new music/video buttons
            if download_selected_music_button: download_selected_music_button.config(state=tk.DISABLED)
            if download_selected_video_button: download_selected_video_button.config(state=tk.DISABLED)
            if download_all_music_button: download_all_music_button.config(state=tk.DISABLED)
            if download_all_video_button: download_all_video_button.config(state=tk.DISABLED)

            if save_config_button: save_config_button.config(state=tk.DISABLED)
            if quit_button: quit_button.config(state=tk.DISABLED)
            if stop_download_button: stop_download_button.config(state=tk.NORMAL)
        root_window.after(0, _update)

def _toggle_ui_for_download_end():
    """Resets UI elements when a download ends or is stopped."""
    if root_window and root_window.winfo_exists():
        def _update():
            if overall_progress_label_var: overall_progress_label_var.set("Status: Idle")
            if current_file_label_var: current_file_label_var.set("Current File: -")
            if download_speed_label_var: download_speed_label_var.set("Speed: -")
            if file_progress_bar and hasattr(file_progress_bar, 'stop'):
                file_progress_bar.stop()
                file_progress_bar['value'] = 0
            if playlist_progress_bar: playlist_progress_bar['value'] = 0

            if connect_button: connect_button.config(state=tk.NORMAL)

            music_playlists_exist = music_playlist_listbox and music_playlist_listbox.size() > 0
            video_playlists_exist = video_playlist_listbox and video_playlist_listbox.size() > 0

            if download_selected_music_button: download_selected_music_button.config(state=tk.NORMAL if music_playlists_exist else tk.DISABLED)
            if download_all_music_button: download_all_music_button.config(state=tk.NORMAL if music_playlists_exist else tk.DISABLED)
            if download_selected_video_button: download_selected_video_button.config(state=tk.NORMAL if video_playlists_exist else tk.DISABLED)
            if download_all_video_button: download_all_video_button.config(state=tk.NORMAL if video_playlists_exist else tk.DISABLED)

            if stop_download_button: stop_download_button.config(state=tk.DISABLED)
            if save_config_button: save_config_button.config(state=tk.NORMAL)
            if quit_button: quit_button.config(state=tk.NORMAL)
        root_window.after(0, _update)

def toggle_url_entries(*args):
    """Enable/Disable URL entry fields based on server_type_var selection."""
    if server_type_var.get() == "remote":
        if remote_plex_url_entry: remote_plex_url_entry.config(state=tk.NORMAL)
        if local_plex_address_entry: local_plex_address_entry.config(state=tk.DISABLED)
    elif server_type_var.get() == "local":
        if remote_plex_url_entry: remote_plex_url_entry.config(state=tk.DISABLED)
        if local_plex_address_entry: local_plex_address_entry.config(state=tk.NORMAL)
    else:
        if remote_plex_url_entry: remote_plex_url_entry.config(state=tk.DISABLED)
        if local_plex_address_entry: local_plex_address_entry.config(state=tk.DISABLED)


def connect_plex():
    global plex_instance_global, all_music_playlists_global, all_video_playlists_global

    selected_server_type = server_type_var.get()
    plex_url_to_use = ""
    session_to_use = None

    if selected_server_type == "remote":
        plex_url_to_use = remote_plex_url_var.get().strip()
        log_status(f"Attempting to connect to Remote Plex server at {plex_url_to_use}...")
        session_to_use = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True,
                     'custom': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'},
            delay=5
        )
    elif selected_server_type == "local":
        plex_url_to_use = local_plex_address_var.get().strip()
        log_status(f"Attempting to connect to Local Plex server at {plex_url_to_use}...")
        session_to_use = requests.Session()
    else:
        messagebox.showerror("Configuration Error", "Invalid server type selected.")
        return

    token = plex_token_var.get().strip()
    if not plex_url_to_use or not token:
        messagebox.showerror("Input Error", "Plex URL/Address and Token are required.")
        return

    if overall_progress_label_var: overall_progress_label_var.set("Status: Connecting...")
    _toggle_ui_for_download_start()
    if stop_download_button: stop_download_button.config(state=tk.DISABLED) # Keep stop disabled for connect

    # Clear previous playlist data
    if music_playlist_listbox: music_playlist_listbox.delete(0, tk.END)
    if video_playlist_listbox: video_playlist_listbox.delete(0, tk.END)
    all_music_playlists_global.clear()
    all_video_playlists_global.clear()

    try:
        plex_instance_global = PlexServer(plex_url_to_use, token, session=session_to_use, timeout=30)
        log_status(f"Successfully connected to Plex server: {plex_instance_global.friendlyName} (Version: {plex_instance_global.version})")
        if overall_progress_label_var: overall_progress_label_var.set(f"Status: Connected to {plex_instance_global.friendlyName}")

        playlists = plex_instance_global.playlists()
        if not playlists:
            log_status("No playlists found on this server.")
            messagebox.showinfo("No Playlists", "No playlists found on this server.")
        else:
            music_count = 0
            video_count = 0
            for p in playlists:
                try:
                    item_count = p.leafCount
                    display_text = f"{p.title} ({item_count} items)"
                    if p.playlistType == 'audio':
                        music_playlist_listbox.insert(tk.END, display_text)
                        all_music_playlists_global.append(p)
                        music_count +=1
                    elif p.playlistType == 'video':
                        video_playlist_listbox.insert(tk.END, display_text)
                        all_video_playlists_global.append(p)
                        video_count +=1
                except Exception as e:
                    log_status(f"Error processing playlist '{p.title}': {e}")
            log_status(f"Found {music_count} music playlist(s) and {video_count} video playlist(s).")
        _toggle_ui_for_download_end()

    except Unauthorized:
        log_status("Plex connection unauthorized. Check your Plex Token.")
        messagebox.showerror("Connection Error", "Plex connection unauthorized. Check your Plex Token.")
        if overall_progress_label_var: overall_progress_label_var.set("Status: Connection Failed (Unauthorized)")
        plex_instance_global = None
        _toggle_ui_for_download_end()
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, NotFound) as e:
        log_status(f"Connection Error: {e}")
        messagebox.showerror("Connection Error", f"Could not connect to Plex server at {plex_url_to_use}.\nDetails: {e}")
        if overall_progress_label_var: overall_progress_label_var.set(f"Status: Connection Failed ({type(e).__name__})")
        plex_instance_global = None
        _toggle_ui_for_download_end()
    except Exception as e:
        log_status(f"An unexpected error occurred during connection: {e}")
        messagebox.showerror("Connection Error", f"An unexpected error occurred: {e}")
        if overall_progress_label_var: overall_progress_label_var.set("Status: Connection Error (Unexpected)")
        import traceback; traceback.print_exc()
        plex_instance_global = None
        _toggle_ui_for_download_end()


def start_download_action(playlist_type_or_objects):
    """Helper to initiate download based on type or specific list of playlists."""
    global stop_download_event
    if not plex_instance_global:
        messagebox.showerror("Error", "Not connected to Plex server. Please connect first.")
        return

    base_dir = download_dir_var.get().strip()
    if not base_dir:
        messagebox.showerror("Input Error", "Please select a download directory.")
        return
    if not os.path.isdir(base_dir):
        try: os.makedirs(base_dir, exist_ok=True); log_status(f"Created download directory: {base_dir}")
        except OSError as e: messagebox.showerror("Input Error", f"Download directory invalid/uncreatable: {e}"); return

    playlists_to_process = []
    action_description = ""

    if isinstance(playlist_type_or_objects, str):
        if playlist_type_or_objects == 'all_music':
            playlists_to_process = list(all_music_playlists_global)
            action_description = "all music playlists"
        elif playlist_type_or_objects == 'all_video':
            playlists_to_process = list(all_video_playlists_global)
            action_description = "all video playlists"
    elif isinstance(playlist_type_or_objects, list):
        playlists_to_process = playlist_type_or_objects
        action_description = f"{len(playlists_to_process)} selected playlist(s)"

    if not playlists_to_process:
        messagebox.showinfo("No Playlists", f"No playlists selected or available for: {action_description}.")
        return

    log_status(f"Preparing to download {action_description}...")
    stop_download_event.clear()
    _toggle_ui_for_download_start()
    if overall_progress_label_var: overall_progress_label_var.set(f"Status: Starting download of {action_description}...")
    if current_file_label_var: current_file_label_var.set("Current File: -")
    if download_speed_label_var: download_speed_label_var.set("Speed: -")
    if file_progress_bar and hasattr(file_progress_bar, 'stop'):
        file_progress_bar.stop()
        file_progress_bar['value'] = 0
    if playlist_progress_bar: playlist_progress_bar['value'] = 0


    download_thread = threading.Thread(target=actual_download_process,
                                       args=(plex_instance_global, playlists_to_process, base_dir),
                                       daemon=True)
    download_thread.start()

def get_selected_playlists_from_listbox(listbox_widget, source_playlist_list):
    """Gets actual playlist objects based on listbox selection."""
    selected_objects = []
    selected_indices = listbox_widget.curselection()
    if not selected_indices: return []

    listbox_titles_with_counts = [listbox_widget.get(i) for i in selected_indices]
    for entry in listbox_titles_with_counts:
        title_to_match = entry.rsplit(' (', 1)[0]
        found_playlist = next((p for p in source_playlist_list if p.title == title_to_match), None)
        if found_playlist:
            selected_objects.append(found_playlist)
        else:
            log_status(f"Warning: Could not find playlist object for listbox entry: '{entry}'. It might have changed on server.")
    return selected_objects


def stop_download_command():
    global stop_download_event
    log_status("Stop download command received. Signaling downloads to halt...")
    stop_download_event.set()
    if stop_download_button: stop_download_button.config(state=tk.DISABLED)


def browse_directory():
    directory = filedialog.askdirectory()
    if directory:
        download_dir_var.set(directory)
        log_status(f"Download directory set to: {directory}")


def create_gui(root):
    global server_type_var, remote_plex_url_var, local_plex_address_var, plex_token_var, save_token_var, download_dir_var, status_text_area, \
           music_playlist_listbox, video_playlist_listbox, \
           connect_button, download_selected_music_button, download_selected_video_button, \
           download_all_music_button, download_all_video_button, stop_download_button, \
           save_config_button, quit_button, \
           overall_progress_label_var, playlist_progress_bar, \
           current_file_label_var, file_progress_bar, download_speed_label_var, root_window, \
           remote_plex_url_entry, local_plex_address_entry


    root_window = root
    root.title("Plex Playlist Downloader")
    root.geometry("850x950")

    # --- Configuration Frame ---
    config_frame = ttk.LabelFrame(root, text="Plex Configuration", padding="10")
    config_frame.pack(padx=10, pady=(10,5), fill="x")

    server_type_frame = ttk.Frame(config_frame)
    server_type_frame.grid(row=0, column=0, columnspan=3, pady=(0,5), sticky="w")
    ttk.Label(server_type_frame, text="Server Type:").pack(side=tk.LEFT, padx=(0,5))
    server_type_var = tk.StringVar(value="remote")
    remote_rb = ttk.Radiobutton(server_type_frame, text="Remote", variable=server_type_var, value="remote", command=toggle_url_entries)
    remote_rb.pack(side=tk.LEFT, padx=5)
    local_rb = ttk.Radiobutton(server_type_frame, text="Local", variable=server_type_var, value="local", command=toggle_url_entries)
    local_rb.pack(side=tk.LEFT, padx=5)

    ttk.Label(config_frame, text="Remote Plex URL:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
    remote_plex_url_var = tk.StringVar()
    remote_plex_url_entry = ttk.Entry(config_frame, textvariable=remote_plex_url_var, width=50)
    remote_plex_url_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky="ew")

    ttk.Label(config_frame, text="Local Plex Address:").grid(row=2, column=0, padx=5, pady=2, sticky="w")
    local_plex_address_var = tk.StringVar()
    local_plex_address_entry = ttk.Entry(config_frame, textvariable=local_plex_address_var, width=50)
    local_plex_address_entry.grid(row=2, column=1, columnspan=2, padx=5, pady=2, sticky="ew")

    ttk.Label(config_frame, text="Plex Token:").grid(row=3, column=0, padx=5, pady=2, sticky="w")
    plex_token_var = tk.StringVar()
    plex_token_entry = ttk.Entry(config_frame, textvariable=plex_token_var, width=50, show="*")
    plex_token_entry.grid(row=3, column=1, padx=5, pady=2, sticky="ew")
    save_token_var = tk.BooleanVar(value=False)
    save_token_checkbox = ttk.Checkbutton(config_frame, text="Save Token", variable=save_token_var)
    save_token_checkbox.grid(row=3, column=2, padx=5, pady=2, sticky="w")

    ttk.Label(config_frame, text="Download Dir:").grid(row=4, column=0, padx=5, pady=2, sticky="w")
    download_dir_var = tk.StringVar()
    download_dir_entry = ttk.Entry(config_frame, textvariable=download_dir_var, width=40)
    download_dir_entry.grid(row=4, column=1, padx=5, pady=2, sticky="ew")
    browse_button = ttk.Button(config_frame, text="Browse...", command=browse_directory)
    browse_button.grid(row=4, column=2, padx=5, pady=2, sticky="w")
    config_frame.columnconfigure(1, weight=1)

    main_actions_frame = ttk.Frame(config_frame)
    main_actions_frame.grid(row=5, column=0, columnspan=3, pady=(10,2), sticky="ew")
    connect_button = ttk.Button(main_actions_frame, text="Connect to Plex", command=connect_plex)
    connect_button.pack(side=tk.LEFT, padx=5, expand=True, fill="x")
    save_config_button = ttk.Button(main_actions_frame, text="Save Configuration", command=save_config)
    save_config_button.pack(side=tk.LEFT, padx=5, expand=True, fill="x")
    quit_button = ttk.Button(main_actions_frame, text="Quit", command=on_exit)
    quit_button.pack(side=tk.LEFT, padx=5, expand=True, fill="x")

    playlists_area_frame = ttk.Frame(root, padding="5")
    playlists_area_frame.pack(padx=10, pady=5, fill="both", expand=True)

    music_playlists_frame = ttk.LabelFrame(playlists_area_frame, text="Music Playlists", padding="5")
    music_playlists_frame.pack(side=tk.LEFT, padx=5, fill="both", expand=True)
    music_playlist_listbox_scrollbar_y = ttk.Scrollbar(music_playlists_frame, orient=tk.VERTICAL)
    music_playlist_listbox = tk.Listbox(music_playlists_frame, selectmode=tk.EXTENDED, yscrollcommand=music_playlist_listbox_scrollbar_y.set, height=7, exportselection=False)
    music_playlist_listbox_scrollbar_y.config(command=music_playlist_listbox.yview)
    music_playlist_listbox_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
    music_playlist_listbox.pack(side=tk.LEFT, fill="both", expand=True)

    video_playlists_frame = ttk.LabelFrame(playlists_area_frame, text="Video Playlists", padding="5")
    video_playlists_frame.pack(side=tk.LEFT, padx=5, fill="both", expand=True)
    video_playlist_listbox_scrollbar_y = ttk.Scrollbar(video_playlists_frame, orient=tk.VERTICAL)
    video_playlist_listbox = tk.Listbox(video_playlists_frame, selectmode=tk.EXTENDED, yscrollcommand=video_playlist_listbox_scrollbar_y.set, height=7, exportselection=False)
    video_playlist_listbox_scrollbar_y.config(command=video_playlist_listbox.yview)
    video_playlist_listbox_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
    video_playlist_listbox.pack(side=tk.LEFT, fill="both", expand=True)

    download_control_frame = ttk.Frame(root, padding="5")
    download_control_frame.pack(fill="x", padx=10, pady=5)

    overall_progress_label_var = tk.StringVar(value="Status: Idle")
    overall_progress_label = ttk.Label(download_control_frame, textvariable=overall_progress_label_var)
    overall_progress_label.pack(side=tk.TOP, fill="x", pady=(0,2))
    playlist_progress_bar = ttk.Progressbar(download_control_frame, orient="horizontal", length=300, mode="determinate")
    playlist_progress_bar.pack(side=tk.TOP, fill="x", expand=True, pady=(0,5))

    download_buttons_grid = ttk.Frame(download_control_frame)
    download_buttons_grid.pack(side=tk.TOP, fill="x", pady=(5,0))
    download_selected_music_button = ttk.Button(download_buttons_grid, text="Download Selected Music", command=lambda: start_download_action(get_selected_playlists_from_listbox(music_playlist_listbox, all_music_playlists_global)), state=tk.DISABLED)
    download_selected_music_button.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
    download_all_music_button = ttk.Button(download_buttons_grid, text="Download All Music", command=lambda: start_download_action('all_music'), state=tk.DISABLED)
    download_all_music_button.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
    download_selected_video_button = ttk.Button(download_buttons_grid, text="Download Selected Video", command=lambda: start_download_action(get_selected_playlists_from_listbox(video_playlist_listbox, all_video_playlists_global)), state=tk.DISABLED)
    download_selected_video_button.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
    download_all_video_button = ttk.Button(download_buttons_grid, text="Download All Video", command=lambda: start_download_action('all_video'), state=tk.DISABLED)
    download_all_video_button.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
    download_buttons_grid.columnconfigure(0, weight=1)
    download_buttons_grid.columnconfigure(1, weight=1)

    stop_download_button = ttk.Button(download_control_frame, text="Stop Current Downloads", command=stop_download_command, state=tk.DISABLED)
    stop_download_button.pack(side=tk.TOP, fill="x", pady=(5,0))

    file_progress_frame = ttk.LabelFrame(root, text="Current File Download Progress", padding="10")
    file_progress_frame.pack(padx=10, pady=5, fill="x")
    current_file_label_var = tk.StringVar(value="Current File: -")
    current_file_label = ttk.Label(file_progress_frame, textvariable=current_file_label_var)
    current_file_label.pack(fill="x", pady=(0,2))
    file_progress_bar = ttk.Progressbar(file_progress_frame, orient="horizontal", length=300, mode="determinate")
    file_progress_bar.pack(fill="x", expand=True, pady=(0,2))
    download_speed_label_var = tk.StringVar(value="Speed: -")
    download_speed_label = ttk.Label(file_progress_frame, textvariable=download_speed_label_var)
    download_speed_label.pack(fill="x")

    status_frame = ttk.LabelFrame(root, text="Status Log", padding="10")
    status_frame.pack(padx=10, pady=10, fill="both", expand=True)
    status_text_area = scrolledtext.ScrolledText(status_frame, wrap=tk.WORD, height=6, state=tk.DISABLED)
    status_text_area.pack(fill="both", expand=True)

    load_config()
    if status_text_area: status_text_area.config(state=tk.DISABLED)
    _toggle_ui_for_download_end()


def main_gui():
    root = tk.Tk() # Create root window first
    # This must run before check_and_install_packages to allow messageboxes
    if not check_and_install_packages():
        print("Exiting application due to dependency issues or user choice during setup.")
        root.destroy()
        return

    try:
        style = ttk.Style(root)
        available_themes = style.theme_names()
        if sys.platform == "win32" and 'vista' in available_themes: style.theme_use('vista')
        elif sys.platform == "darwin" and 'aqua' in available_themes: style.theme_use('aqua')
        elif 'clam' in available_themes: style.theme_use('clam')
        elif 'alt' in available_themes: style.theme_use('alt')
    except tk.TclError: print("Failed to set a custom ttk theme, using default.")

    create_gui(root)
    log_status("Plex Playlist Downloader GUI started. Select server type, load config or enter details, and connect.")
    if status_text_area: status_text_area.config(state=tk.DISABLED)

    root.protocol("WM_DELETE_WINDOW", on_exit)
    root.mainloop()

if __name__ == "__main__":
    main_gui()
