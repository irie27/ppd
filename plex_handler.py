from plexapi.server import PlexServer as PlexAPIServer
from plexapi.exceptions import Unauthorized, NotFound as PlexNotFound, BadRequest
import json
import os
from datetime import datetime
import re # For sanitizing filenames

class PlexHandler:
    def __init__(self):
        self.plex_server = None
        self.connected_server_name = None

    def connect(self, baseurl, token):
        try:
            if not baseurl: return False, "Plex URL is required."
            if not token: return False, "Plex Token is required."
            print(f"Attempting to connect to Plex at {baseurl} with token {'*' * len(token) if token else 'None'}")
            if PlexAPIServer is None:
                 print("Critical Error: PlexAPIServer symbol from plexapi is None.")
                 return False, "PlexAPI library not loaded correctly."
            self.plex_server = PlexAPIServer(baseurl, token, timeout=10)
            self.connected_server_name = self.plex_server.friendlyName
            print(f"Successfully connected to Plex server: {self.connected_server_name}")
            return True, f"Connected to {self.connected_server_name}"
        except Unauthorized:
            print("Error: Plex connection Unauthorized. Check your token.")
            self.plex_server = None; self.connected_server_name = None
            return False, "Unauthorized: Invalid Plex token."
        except PlexNotFound:
            print("Error: Plex server not found at the URL, or path is incorrect.")
            self.plex_server = None; self.connected_server_name = None
            return False, "Plex server not found at URL."
        except Exception as e:
            error_message = f"Connection error: {str(e)}"
            print(f"Error connecting to Plex: {error_message}")
            self.plex_server = None; self.connected_server_name = None
            return False, error_message

    def _format_size_bytes(self, size_bytes):
        if size_bytes == 0: return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        try:
            num_size_bytes = float(size_bytes)
        except (ValueError, TypeError):
            print(f"Warning: Could not convert size '{size_bytes}' to float for formatting.")
            return "Size N/A"
        while num_size_bytes >= 1024 and i < len(units) - 1:
            num_size_bytes /= 1024
            i += 1
        return f"{num_size_bytes:.2f} {units[i]}"

    def fetch_detailed_playlists(self):
        if not self.plex_server:
            return None, "Not connected to Plex."
        detailed_playlists_data = []
        try:
            print("Fetching detailed playlists from server...")
            all_server_playlists = self.plex_server.playlists()
            if not all_server_playlists:
                return [], "No playlists found on server."
            total_server_pl_count = len(all_server_playlists)
            print(f"Found {total_server_pl_count} playlists on server. Processing details...")
            for i, pl_obj in enumerate(all_server_playlists):
                print(f"Processing playlist {i+1}/{total_server_pl_count}: '{pl_obj.title}'...")
                if pl_obj.title == "All Music":
                    print(f"Skipping 'All Music' playlist.")
                    continue
                playlist_type = 'Unknown'; item_count = 0; total_size_bytes = 0
                try:
                    current_playlist_items = pl_obj.items()
                    item_count = len(current_playlist_items)
                    if current_playlist_items:
                        first_item = current_playlist_items[0]
                        if first_item.type == 'track': playlist_type = 'Music'
                        elif first_item.type in ('movie', 'episode'): playlist_type = 'Video'
                        else: print(f"  Playlist '{pl_obj.title}' has first item of type '{first_item.type}', categorizing as Unknown.")
                        for item_idx, item in enumerate(current_playlist_items):
                            if hasattr(item, 'media') and item.media:
                                for media_item in item.media:
                                    if hasattr(media_item, 'parts') and media_item.parts:
                                        for part in media_item.parts:
                                            if hasattr(part, 'size') and part.size is not None:
                                                try: total_size_bytes += int(part.size)
                                                except (ValueError, TypeError): print(f"    Warning: Could not convert part.size '{part.size}' for item '{getattr(item, 'title', 'N/A')}' in '{pl_obj.title}'.")
                    else: playlist_type = 'Empty'; print(f"  Playlist '{pl_obj.title}' is empty.")
                except Exception as e_item_proc:
                    print(f"  Error processing items for playlist '{pl_obj.title}': {e_item_proc}.")
                detailed_playlists_data.append({
                    'title': pl_obj.title, 'type': playlist_type,
                    'summary': pl_obj.summary if hasattr(pl_obj, 'summary') else '',
                    'item_count': item_count, 'display_size': self._format_size_bytes(total_size_bytes)
                })
                print(f"  Finished processing '{pl_obj.title}'. Type: {playlist_type}, Items: {item_count}, Size: {self._format_size_bytes(total_size_bytes)}")
            success_message = f"Successfully processed details for {len(detailed_playlists_data)} playlists."
            print(success_message)
            return detailed_playlists_data, success_message
        except Exception as e:
            error_message = f"Error fetching detailed playlists: {str(e)}"
            print(error_message)
            return None, error_message

    def download_playlist_items(self, playlist_title, base_download_path, update_callback=None):
        if not self.plex_server:
            return False, "Not connected to Plex server.", []
        if not base_download_path or not os.path.isdir(base_download_path):
            return False, f"Invalid base download path: {base_download_path}", []

        if update_callback: update_callback(f"Fetching playlist '{playlist_title}' details...")
        try:
            playlist_obj = self.plex_server.playlist(playlist_title)
            if not playlist_obj:
                return False, f"Playlist '{playlist_title}' not found on server.", []
        except PlexNotFound:
             return False, f"Playlist '{playlist_title}' not found (PlexNotFound).", []
        except Exception as e:
            return False, f"Error fetching playlist '{playlist_title}': {e}", []

        items_to_download = playlist_obj.items()
        if not items_to_download:
            return True, f"Playlist '{playlist_title}' is empty. Nothing to download.", []

        media_type_folder = "UnknownType"
        if items_to_download[0].type == 'track': media_type_folder = "Music"
        elif items_to_download[0].type in ('movie', 'episode'): media_type_folder = "Video"
        
        sane_playlist_title = re.sub(r'[^\w\s-]', '', playlist_title).strip().replace(' ', '_')
        sane_playlist_title = sane_playlist_title if sane_playlist_title else f"playlist_{playlist_obj.ratingKey}"


        playlist_download_dir = os.path.join(base_download_path, media_type_folder, sane_playlist_title)
        
        try:
            os.makedirs(playlist_download_dir, exist_ok=True)
            if update_callback: update_callback(f"Download directory created/verified: {playlist_download_dir}")
        except OSError as e:
            return False, f"Error creating directory '{playlist_download_dir}': {e.strerror}", []

        download_errors = []
        total_items = len(items_to_download)
        if update_callback: update_callback(f"Starting download of {total_items} items for '{playlist_title}'.")

        for i, item in enumerate(items_to_download):
            item_title = getattr(item, 'title', f"Item_{i+1}")
            sane_item_title = re.sub(r'[^\w\s.-]', '', item_title).strip() # Basic sanitization for filename part
            
            if update_callback: update_callback(f"Downloading item {i+1}/{total_items}: '{sane_item_title}'...")
            try:
                # Plexapi's item.download() handles file extensions and part selection.
                # It might download multiple files if an item has multiple versions/parts
                # and keep_original_name=False might lead to plexapi choosing a name.
                # For simplicity with keep_original_name=True, it should use server's filename.
                # However, the 'filepath' parameter in item.download is the full path including filename.
                # We are providing a directory, so plexapi will use original names inside that dir.
                item.download(savepath=playlist_download_dir, keep_original_name=True) 
                if update_callback: update_callback(f"Completed {i+1}/{total_items}: '{sane_item_title}'")
            except BadRequest as br: # Often related to media not being analyzable or direct play issues
                err_msg = f"BadRequest downloading '{sane_item_title}': {br}. This might indicate the media is unavailable for direct download or requires transcoding that's not permitted."
                print(err_msg)
                download_errors.append(err_msg)
                if update_callback: update_callback(f"ERROR (BadRequest) for '{sane_item_title}'. See console.")
            except Exception as e:
                err_msg = f"Error downloading item '{sane_item_title}': {e}"
                print(err_msg) # Log to console for more details
                download_errors.append(err_msg)
                if update_callback: update_callback(f"ERROR downloading '{sane_item_title}'. Check console.")
        
        final_message = f"Download attempt for '{playlist_title}' finished."
        if download_errors:
            final_message += f" Encountered {len(download_errors)} error(s)."
            return False, final_message, download_errors
        else:
            final_message += " All items processed successfully."
            return True, final_message, []

    def save_playlist_cache(self, playlists_data, cache_file_path):
        cache_content = { "playlists": playlists_data, "timestamp": datetime.now().isoformat() }
        try:
            cache_dir = os.path.dirname(cache_file_path)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)
                print(f"Created cache directory: {cache_dir}")
            with open(cache_file_path, 'w') as f: json.dump(cache_content, f, indent=4)
            print(f"Playlist cache saved to {cache_file_path}")
            return True, "Cache saved successfully."
        except Exception as e:
            error_message = f"Error saving playlist cache to {cache_file_path}: {e}"
            print(error_message)
            return False, error_message

    def load_playlist_cache(self, cache_file_path):
        if not os.path.exists(cache_file_path):
            return None, None, "Cache file not found."
        try:
            with open(cache_file_path, 'r') as f: cache_content = json.load(f)
            playlists = cache_content.get("playlists"); timestamp = cache_content.get("timestamp")
            if playlists is None or timestamp is None:
                print(f"Error: Cache file {cache_file_path} is malformed or missing keys.")
                return None, None, "Cache format error: missing keys."
            if not isinstance(playlists, list):
                print(f"Error: Cache file {cache_file_path} 'playlists' data is not a list.")
                return None, None, "Cache format error: 'playlists' not a list."
            print(f"Playlist cache loaded from {cache_file_path}, timestamp: {timestamp}")
            return playlists, timestamp, "Cache loaded successfully."
        except json.JSONDecodeError as e_json:
            error_message = f"Error decoding JSON from cache file {cache_file_path}: {e_json}"
            print(error_message)
            return None, None, error_message
        except Exception as e:
            error_message = f"Error loading playlist cache from {cache_file_path}: {e}"
            print(error_message)
            return None, None, error_message
