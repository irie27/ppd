import kivy
kivy.require('2.1.0')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.storage.jsonstore import JsonStore
from kivy.clock import Clock, mainthread
from kivy.uix.modalview import ModalView
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.button import Button as KivyButton # To distinguish from any other Button if needed
from kivy.utils import platform # Added for platform check
from kivy.uix.popup import Popup # Added for error popup
from kivy.uix.label import Label # Added for popup content
from kivy.core.window import Window # Added for popup text sizing
from kivy.metrics import dp # Added for dp units in popup height adjustment

import os
import threading
import logging # Added for logging
from logging.handlers import RotatingFileHandler # Added for logging
import time # For placeholder download

# Conditional import for android permissions at module level for type hinting/awareness
# but actual import and use will be inside on_start after platform check.
if platform == 'android':
    try:
        from android.permissions import Permission
    except ImportError:
        # This will be logged properly in on_start if it's an issue
        pass


try:
    import plexapi 
    from .plex_handler import PlexHandler 
except ImportError as e:
    # Logging isn't set up here yet, so using print for this critical startup error.
    # This print will be replaced by logger once setup_logging is called.
    # However, if this import itself fails, the app might not even start Kivy.
    logging.basicConfig(level=logging.CRITICAL) # Fallback basic config
    logging.critical(f"CRITICAL IMPORT ERROR: {e}. Ensure plexapi is installed and plex_handler.py is in the same directory.", exc_info=True)
    # Re-raise or sys.exit might be appropriate in a real app if these are absolutely essential
    # For now, allow Kivy to start to show an error popup if possible.
    plexapi = None
    PlexHandler = None

class PlexDownloaderRoot(BoxLayout):
    pass


class PlexDownloaderApp(App):
    config_file_name = 'plex_downloader_kivy_config.json'
    playlist_cache_file = 'kivy_playlist_cache.json' 
    logger = None # Will be initialized in setup_logging

    # --- Properties for Download Progress (Conceptual from Step 12) ---
    # current_download_item_name = StringProperty("")
    # current_download_item_progress = NumericProperty(0) # 0-100 for current item
    # overall_download_progress_value = NumericProperty(0) # current item index
    # overall_download_progress_max = NumericProperty(100) # total items
    stop_download_flag = False # Flag to signal download thread to stop

    def build(self):
        # Initialize logger as early as possible in build, but after user_data_dir is available
        # self.setup_logging() # Moved to on_start as user_data_dir is more reliably set there by Kivy
        
        if not os.path.exists(self.user_data_dir):
            try:
                os.makedirs(self.user_data_dir)
            except Exception as e_mkdir:
                 # Fallback logging if self.logger is not yet set up
                early_logger = logging.getLogger('PlexDownloaderKivy.Build')
                early_logger.error(f"Failed to create user_data_dir: {self.user_data_dir}. Error: {e_mkdir}", exc_info=True)
                # A popup here might be too early or cause issues.
                # App will likely fail later if this dir is crucial.

        self.config_store = JsonStore(os.path.join(self.user_data_dir, self.config_file_name))
        
        if PlexHandler:
            self.plex_handler = PlexHandler()
        else:
            self.plex_handler = None # PlexHandler will log its own import error if logger is passed
        
        self.all_playlists_data = [] 
        self.current_filter = 'all'  
        self.selected_playlist_data = None 

        return PlexDownloaderRoot()

    def setup_logging(self): # Conceptual method from Step 11, refined here
        log_file_path = os.path.join(self.user_data_dir, 'plex_downloader_kivy.log')
        
        # Use a class-level logger to ensure it's shared and configured once.
        if PlexDownloaderApp.logger is None: # Check if class logger is already set
            PlexDownloaderApp.logger = logging.getLogger('PlexDownloaderKivy')
            PlexDownloaderApp.logger.setLevel(logging.INFO) # Default level

            # Prevent adding handlers multiple times
            if not PlexDownloaderApp.logger.handlers:
                try:
                    fh = RotatingFileHandler(log_file_path, maxBytes=5*1024*1024, backupCount=3)
                    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(module)s.%(funcName)s: %(message)s')
                    fh.setFormatter(formatter)
                    PlexDownloaderApp.logger.addHandler(fh)
                    PlexDownloaderApp.logger.info("Logging initialized.")
                    PlexDownloaderApp.logger.info(f"Log file path: {log_file_path}")
                except Exception as e_log_setup:
                    # Fallback to basicConfig if file handler fails
                    logging.basicConfig(level=logging.ERROR) # Basic config for console
                    PlexDownloaderApp.logger = logging.getLogger('PlexDownloaderKivy.Fallback') # Get a new logger instance for fallback
                    PlexDownloaderApp.logger.error(f"Failed to set up file logger at {log_file_path}: {e_log_setup}. Using basic console logging.", exc_info=True)
            else:
                 PlexDownloaderApp.logger.info("Logging handlers already configured for the class logger.")
        
        self.logger = PlexDownloaderApp.logger # Assign to instance for easier access (self.logger)
        if self.plex_handler: # Pass logger to handler if it exists
            # Ensures PlexHandler uses a child logger of the main app logger.
            child_logger_name = f"{PlexDownloaderApp.logger.name}.PlexHandler"
            self.plex_handler.logger = logging.getLogger(child_logger_name)
            # Set level for child logger, or it will inherit from parent.
            # self.plex_handler.logger.setLevel(logging.INFO) # Example: set specific level
            self.logger.info(f"PlexHandler logger configured as child: {child_logger_name}")


    def on_start(self):
        self.setup_logging() # Call logging setup first

        # Android Runtime Permissions
        if platform == 'android':
            self.logger.info("Android platform detected. Attempting to request permissions...")
            try:
                # Conditional import inside the platform check
                from android.permissions import request_permissions, Permission

                permissions_to_request = [
                    Permission.WRITE_EXTERNAL_STORAGE,
                    Permission.READ_EXTERNAL_STORAGE
                ]
                self.logger.info(f"Will request: {permissions_to_request}")

                # Define the callback for permission request
                def permissions_callback(permissions, grants): # grants is a list of booleans
                    self.logger.info(f"Permissions request result: Permissions={permissions}, Grants={grants}")
                    all_granted = True
                    granted_perms = []
                    denied_perms = []

                    for i in range(len(permissions)):
                        perm_name = permissions[i] # This is the string like "android.permission.WRITE_EXTERNAL_STORAGE"
                        if grants[i]: # Check boolean grant status
                            self.logger.info(f"Permission {perm_name} GRANTED.")
                            granted_perms.append(perm_name)
                        else:
                            self.logger.warning(f"Permission {perm_name} DENIED.")
                            denied_perms.append(perm_name)
                            all_granted = False
                    
                    if all_granted:
                        self.logger.info("All requested external storage permissions granted.")
                        self.update_status_label("Storage permissions granted.")
                    else:
                        self.logger.warning(f"The following permissions were denied: {denied_perms}. App functionality may be limited.")
                        self.show_error_popup("Permissions Denied", 
                                              "Storage permissions (Read/Write) are required to save configuration, cache, and download files. "
                                              "Please grant these permissions in your device's app settings for full functionality.")
                        self.update_status_label("Warning: Storage permissions denied. Functionality limited.")
                    
                    # Regardless of permission outcome, proceed to app's late initialization.
                    # Features requiring permissions should handle their absence gracefully.
                    Clock.schedule_once(self._late_init, 0) # Schedule with 0 delay

                # Call request_permissions
                request_permissions(permissions_to_request, permissions_callback)

            except ImportError:
                self.logger.error("Failed to import `android.permissions`. This module is essential for runtime permissions on Android. "
                                  "Ensure your build includes `python-for-android` and necessary pydroid_api components if targeting Android.", exc_info=True)
                self.show_error_popup("Permission System Error", "Could not request Android permissions due to an import error. The app might not function as expected.")
                Clock.schedule_once(self._late_init, 0) # Proceed but with a clear error state
            except Exception as e_perm_request:
                self.logger.error(f"An unexpected error occurred during the Android permission request process: {e_perm_request}", exc_info=True)
                self.show_error_popup("Permission Request Error", f"An unexpected error occurred while requesting permissions: {e_perm_request}")
                Clock.schedule_once(self._late_init, 0) # Proceed but with a clear error state
        else:
            self.logger.info("Not an Android platform. Skipping Android permission requests.")
            Clock.schedule_once(self._late_init, 0) # Proceed directly for non-Android platforms

        # Initial PlexHandler check. If it failed to load, self.plex_handler is None.
        if not self.plex_handler:
            # This message will also be logged by _late_init if still None.
            self.update_status_label("Error: PlexHandler module not loaded. Plex features disabled.")
            self.logger.critical("PlexHandler module failed to load or was not imported. Plex-related functionality will be unavailable.")
    

    @mainthread
    def show_error_popup(self, title, message):
        logger_to_use = self.logger if self.logger else logging.getLogger('PlexDownloaderKivy.Popup')
        try:
            popup_width = Window.width * 0.8
            label_width = popup_width * 0.9 
            content = Label(text=str(message), text_size=(label_width, None), halign='center', valign='middle')
            content.bind(texture_size=content.setter('size'))
            popup = Popup(title=title, content=content, size_hint=(0.8, None)) # height removed for auto-sizing
            
            # Adjust popup height based on text content after it's rendered
            def _adjust_popup_height(label_instance, texture_size):
                padding = dp(40) 
                popup.height = texture_size[1] + padding 
            content.bind(texture_size=_adjust_popup_height)
            popup.open()
            logger_to_use.error(f"Error Popup Shown: Title='{title}', Message='{message}'")
        except Exception as e_popup:
            logger_to_use.error(f"Failed to show error popup: {e_popup}", exc_info=True)
            print(f"POPUP FAILED - Title: {title}, Message: {message}") # Fallback print


    def _late_init(self, dt=None): 
        self.logger.info("_late_init called after on_start procedures (including potential permission request).")
        if not self.plex_handler: 
            self.update_status_label("Plex features disabled (handler missing).")
            self.logger.warning("PlexHandler not available in _late_init. Disabling related buttons.")
            if self.root: # Ensure root widget is available
                if self.root.ids.get('connect_button'): self.root.ids.connect_button.disabled = True
                if self.root.ids.get('refresh_button'): self.root.ids.refresh_button.disabled = True
                if self.root.ids.get('download_playlist_button'): self.root.ids.download_playlist_button.disabled = True
        
        self._load_initial_config_values() 
        self.load_playlists_from_cache()    

    def _load_initial_config_values(self):
        url = self.config_get('plex_url', '')
        token_exists = 'Yes' if self.config_get('plex_token', '') else 'No'
        download_dir = self.config_get('download_dir', '')
        status_text = f"Config: URL {'set' if url else 'not set'}, Token {'set' if token_exists == 'Yes' else 'not set'}, Dir {'set' if download_dir else 'not set'}."
        self.logger.info(f"Initial config values: {status_text}")
        self.update_status_label(status_text)
        if self.root and self.root.ids.get('download_dir_input') and download_dir:
            self.root.ids.download_dir_input.text = download_dir


    def config_get(self, key, default_value=''):
        if self.config_store.exists(key):
            return self.config_store.get(key)['value']
        return default_value

    def save_configuration(self):
        root_widget = self.root
        if not root_widget or not hasattr(root_widget, 'ids'):
            msg = "Error: UI not ready for saving configuration."
            self.logger.error(msg); self.update_status_label(msg)
            return
        try:
            url = root_widget.ids.plex_url_input.text; token = root_widget.ids.plex_token_input.text
            self.config_store.put('plex_url', value=url); self.config_store.put('plex_token', value=token)
            msg = f"Config saved. URL: {url[:20]}..., Token: {'set' if token else 'not set'}."
            self.logger.info(msg); self.update_status_label(msg)
        except Exception as e:
            error_msg = f"Error saving configuration: {e}"
            self.logger.error(error_msg, exc_info=True); self.show_error_popup("Config Save Error", error_msg)
            self.update_status_label(error_msg)

    @mainthread
    def update_status_label(self, text):
        if self.root and hasattr(self.root.ids, 'status_label'):
            self.root.ids.status_label.text = text
        else:
            logger_to_use = self.logger if self.logger else logging.getLogger('PlexDownloaderKivy.UpdateStatus')
            logger_to_use.debug(f"Status label not found or root not ready. Message: {text}")
            Clock.schedule_once(lambda dt: self._check_status_label_update(text), 0.1)


    def _check_status_label_update(self, text):
        if self.root and hasattr(self.root.ids, 'status_label'):
            self.root.ids.status_label.text = text
        else:
            logger_to_use = self.logger if self.logger else logging.getLogger('PlexDownloaderKivy.CheckUpdateStatus')
            logger_to_use.debug(f"Status label still not found. Message: {text}")


    def open_dir_chooser(self):
        if not self.root or not self.root.ids.get('download_dir_input'):
            msg = "UI not ready for directory chooser."; self.logger.warning(msg); self.update_status_label(msg)
            return
        initial_path = self.config_get('download_dir', '')
        if not initial_path or not os.path.isdir(initial_path):
            if hasattr(App.get_running_app(), 'user_data_dir'): initial_path = App.get_running_app().user_data_dir
            if os.name == 'posix':
                home_path = os.path.expanduser('~'); sdcard_path = '/sdcard'; documents_path = os.path.join(home_path, 'Documents')
                # Check for common Android external storage paths first
                primary_external_storage = os.getenv('EXTERNAL_STORAGE')
                if primary_external_storage and os.path.exists(primary_external_storage) and os.path.isdir(primary_external_storage):
                    initial_path = primary_external_storage
                elif os.path.exists(sdcard_path) and os.path.isdir(sdcard_path): initial_path = sdcard_path
                elif os.path.exists(documents_path) and os.path.isdir(documents_path): initial_path = documents_path
                elif os.path.exists(home_path) and os.path.isdir(home_path): initial_path = home_path
                else: initial_path = '/' # Fallback for generic POSIX
            elif os.name == 'nt':
                initial_path = os.path.join(os.path.expanduser('~'), 'Documents')
                if not os.path.exists(initial_path) or not os.path.isdir(initial_path): initial_path = 'C:\\'
            else: initial_path = '.' # Current working directory for other OS
            if not os.path.exists(initial_path) or not os.path.isdir(initial_path): initial_path = os.getcwd() # Absolute fallback
        
        self.logger.info(f"Directory Chooser: Determined initial_path = {initial_path}")
        try:
            if not os.path.exists(initial_path) or not os.path.isdir(initial_path):
                self.logger.warning(f"Corrected: Initial path '{initial_path}' for FileChooser is invalid. Defaulting to CWD."); initial_path = os.getcwd()
            file_chooser = FileChooserListView(dirselect=True, path=initial_path)
        except Exception as e:
            error_msg = f"Error creating FileChooser: {e}"; self.logger.error(error_msg, exc_info=True)
            self.show_error_popup("UI Error", error_msg); self.update_status_label(error_msg); return
        
        modal_content = BoxLayout(orientation='vertical', spacing=dp(5)); modal_content.add_widget(file_chooser)
        buttons_layout = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        select_button = KivyButton(text="Select Directory"); cancel_button = KivyButton(text="Cancel")
        buttons_layout.add_widget(select_button); buttons_layout.add_widget(cancel_button); modal_content.add_widget(buttons_layout)
        modal = ModalView(size_hint=(0.9, 0.9), auto_dismiss=False); modal.add_widget(modal_content)
        def on_select(instance):
            if file_chooser.selection:
                selected_path = file_chooser.selection[0]
                if os.path.isdir(selected_path):
                    self.root.ids.download_dir_input.text = selected_path
                    self.config_store.put('download_dir', value=selected_path)
                    msg = f"Download dir set: {selected_path}"; self.logger.info(msg); self.update_status_label(msg)
                    modal.dismiss()
                else: self.update_status_label("Selection is not a directory.")
            else: self.update_status_label("No directory selected.")
        def on_cancel(instance): modal.dismiss()
        select_button.bind(on_release=on_select); cancel_button.bind(on_release=on_cancel)
        modal.open()

    def connect_to_plex(self): 
        if not self.plex_handler:
            msg = "Plex connection handler not available."; self.logger.error(msg); self.update_status_label(msg); return
        url = self.config_get('plex_url'); token = self.config_get('plex_token')
        if not url or not token:
            msg = "Plex URL or Token not configured."; self.logger.warning(msg); self.show_error_popup("Config Missing", msg); self.update_status_label(msg); return
        self._set_all_action_buttons_state(False) 
        threading.Thread(target=self._connect_and_fetch_thread, args=(url, token, False), daemon=True).start()


    def refresh_playlists_from_server(self):
        if not self.plex_handler:
            msg = "Plex connection handler not available."; self.logger.error(msg); self.update_status_label(msg); return
        self.update_status_label("Refreshing playlists from server...")
        self._set_all_action_buttons_state(False) 
        url = self.config_get('plex_url'); token = self.config_get('plex_token')
        if not url or not token:
            msg = "Plex URL/Token not configured. Cannot refresh."; self.logger.warning(msg); self.show_error_popup("Config Missing", msg)
            self.update_status_label(msg); self._set_all_action_buttons_state(True); return
        threading.Thread(target=self._connect_and_fetch_thread, args=(url, token, True), daemon=True).start()

    @mainthread
    def _set_all_action_buttons_state(self, enabled): 
        if not self.root: self.logger.debug("Root not available for _set_all_action_buttons_state"); return
        self.logger.debug(f"Setting all action buttons state to enabled={enabled}")
        
        connect_button = self.root.ids.get('connect_button')
        refresh_button = self.root.ids.get('refresh_button')
        download_button = self.root.ids.get('download_playlist_button')
        stop_button = self.root.ids.get('stop_download_button') # Conceptual from Step 12

        if connect_button: connect_button.disabled = not enabled
        if refresh_button: refresh_button.disabled = not enabled
        
        if download_button: 
            download_button.disabled = not enabled or not self.selected_playlist_data
        
        if stop_button: # Stop button is enabled only when a download is active
            stop_button.disabled = enabled # If other actions are enabled, stop should be disabled.


    def _connect_and_fetch_thread(self, url, token, is_refresh=False):
        initial_message = "Connecting..." if not is_refresh else "Refreshing connection..."
        self.logger.info(initial_message); self.update_status_label(initial_message)
        if not self.plex_handler:
            err_msg = "Plex Handler not initialized."; self.logger.error(err_msg); self.update_status_label(err_msg)
            self._set_all_action_buttons_state(True); return
        success, message = self.plex_handler.connect(url, token)
        if success:
            connect_msg = f"Connected: {message}. Fetching playlists."; self.logger.info(connect_msg); self.update_status_label(connect_msg)
            playlists_data, fetch_message = self.plex_handler.fetch_detailed_playlists()
            if playlists_data is not None:
                self.all_playlists_data = playlists_data
                cache_path = os.path.join(self.user_data_dir, self.playlist_cache_file)
                save_success, save_msg = self.plex_handler.save_playlist_cache(self.all_playlists_data, cache_path)
                final_fetch_message = f"Playlists {'refreshed' if is_refresh else 'fetched'}. {fetch_message}"
                if save_success: final_fetch_message += f" Cache: {save_msg}"; self.logger.info(f"Playlists fetched and saved: {save_msg}")
                else: final_fetch_message += f" Cache Error: {save_msg}"; self.logger.error(f"Cache save failed: {save_msg}")
                self.update_status_label(final_fetch_message)
                Clock.schedule_once(lambda dt: self.filter_playlists_display(self.current_filter))
            else:
                fetch_err_msg = f"Playlist fetch error: {fetch_message}"; self.logger.error(fetch_err_msg)
                self.show_error_popup("Plex Error", fetch_err_msg); self.update_status_label(fetch_err_msg)
        else:
            conn_fail_msg = f"Connection failed: {message}"; self.logger.error(conn_fail_msg)
            self.show_error_popup("Plex Error", conn_fail_msg); self.update_status_label(conn_fail_msg)
        self._set_all_action_buttons_state(True)


    def load_playlists_from_cache(self):
        if not self.plex_handler:
            msg = "Plex handler not available for cache ops."; self.logger.warning(msg); self.update_status_label(msg)
            self.all_playlists_data = []; self.filter_playlists_display(self.current_filter); return False
        cache_path = os.path.join(self.user_data_dir, self.playlist_cache_file)
        playlists, timestamp, message = self.plex_handler.load_playlist_cache(cache_path)
        if playlists is not None:
            self.all_playlists_data = playlists
            msg = f"Loaded {len(playlists)} playlists from cache (Timestamp: {timestamp.split('T')[0] if timestamp else 'N/A'}). {message}"
            self.logger.info(msg); self.update_status_label(msg)
            self.filter_playlists_display(self.current_filter); return True
        else:
            msg = f"Cache: {message}. Connect to Plex to fetch fresh playlists."
            self.logger.info(msg); self.update_status_label(msg)
            self.all_playlists_data = []; self.filter_playlists_display(self.current_filter); return False
            
    def filter_playlists_display(self, filter_type):
        self.current_filter = filter_type
        self.logger.info(f"Filtering playlists by type: {filter_type}")
        if not self.all_playlists_data:
            if not self.plex_handler or not self.plex_handler.plex_server: msg = "Not connected. Load from cache or connect."
            else: msg = "No playlists found or cache is empty."
            self.logger.info(msg); self.update_status_label(msg); self._update_playlist_display([]); return
        self.update_status_label(f"Filtering playlists: {filter_type.capitalize()}...")
        filtered_list = []
        if filter_type == 'all': filtered_list = self.all_playlists_data
        else:
            for pl_item in self.all_playlists_data:
                if pl_item.get('type', '').lower() == filter_type.lower(): filtered_list.append(pl_item)
        self._update_playlist_display(filtered_list)
        if not filtered_list: self.update_status_label(f"No {filter_type.capitalize()} playlists to display.")


    @mainthread
    def _update_playlist_display(self, playlists_to_display): 
        playlist_rv = self.root.ids.get('playlist_rv') if self.root else None
        if not playlist_rv: self.logger.error("Playlist RecycleView (playlist_rv) not found in UI for display update."); return
        formatted_data = []
        if playlists_to_display:
            for pl_item in playlists_to_display: 
                formatted_data.append({
                    'pl_title.text': pl_item.get('title', 'Untitled Playlist'),
                    'pl_item_count.text': f"{pl_item.get('item_count', 0)} items",
                    'pl_display_size.text': pl_item.get('display_size', 'N/A'),
                    'playlist_data_for_row': pl_item 
                })
        playlist_rv.data = formatted_data
        self.logger.info(f"RecycleView updated with {len(formatted_data)} playlists.")
        if not formatted_data: self.logger.info("No playlists rendered in RV (list was empty or None).")
        self.selected_playlist_data = None
        if self.root.ids.get('download_playlist_button'): self.root.ids.download_playlist_button.disabled = True


    def select_playlist(self, playlist_item_data):
        if playlist_item_data is None:
            self.logger.warning("select_playlist called with None data. This might happen if row data is not set correctly."); return
        self.selected_playlist_data = playlist_item_data
        download_button = self.root.ids.get('download_playlist_button')
        if download_button: download_button.disabled = False
        title = self.selected_playlist_data.get('title', 'Unknown Playlist')
        self.update_status_label(f"Selected: {title} ({self.selected_playlist_data.get('item_count', 0)} items)")
        self.logger.info(f"Playlist selected: {title}")


    def start_download_selected_playlist(self):
        if not self.selected_playlist_data:
            msg = "No playlist selected to download."; self.logger.warning(msg); self.show_error_popup("Download Error", msg); return
        download_dir = self.config_get('download_dir', '')
        if not download_dir or not os.path.isdir(download_dir):
            msg = "Download directory not set or invalid."; self.logger.error(msg); self.show_error_popup("Download Error", msg); return
        
        playlist_title = self.selected_playlist_data.get('title', 'Unknown Playlist')
        self.update_status_label(f"Preparing to download '{playlist_title}'...")
        self.logger.info(f"Preparing to download playlist: {playlist_title} to {download_dir}")
        
        self._set_all_action_buttons_state(False) 
        stop_button = self.root.ids.get('stop_download_button') # Conceptual ID from Step 12
        if stop_button: stop_button.disabled = False 
        self.stop_download_flag = False 

        threading.Thread(target=self._download_thread, 
                         args=(playlist_title, download_dir), 
                         daemon=True).start()

    def _download_update_callback(self, data_dict): # Conceptual from Step 12
        progress_bar = self.root.ids.get('overall_download_progress') # Conceptual ID from Step 12
        log_type = data_dict.get('type')
        message = data_dict.get('message', '')
        
        if log_type == 'progress':
            if progress_bar:
                progress_bar.max = data_dict.get('total', progress_bar.max)
                progress_bar.value = data_dict.get('current', progress_bar.value)
            self.update_status_label(data_dict.get('item_message', 'Processing...'))
            self.logger.info(f"Download Progress: {data_dict}")
        elif log_type in ['status', 'error', 'aborted', 'final_summary', 'finished_item']:
            self.update_status_label(message)
            if log_type == 'error': self.logger.error(f"Download Error: {message} - Item: {data_dict.get('item_name', 'N/A')}")
            else: self.logger.info(f"Download Status ({log_type}): {message}")
            if log_type == 'aborted' and progress_bar: progress_bar.value = 0
            if log_type == 'final_summary' and progress_bar:
                progress_bar.value = progress_bar.max if data_dict.get('success') else 0
        else: 
            self.update_status_label(message)
            self.logger.info(f"Download Update (unknown type): {data_dict}")


    def _download_thread(self, playlist_title, download_dir): 
        self.logger.info(f"Starting download process for '{playlist_title}' in thread.")
        if not self.plex_handler:
            self.logger.error("Plex_handler not available in _download_thread.")
            self._download_update_callback({'type': 'error', 'message': 'Plex handler missing.'})
            Clock.schedule_once(lambda dt: self._set_all_action_buttons_state(True))
            return

        success, message, errors = self.plex_handler.download_playlist_items(
            playlist_title,
            download_dir,
            update_callback=self._download_update_callback, 
            stop_flag_check=lambda: self.stop_download_flag
        )
        
        self._download_update_callback({'type': 'final_summary', 'message': message, 'success': success})
        if errors:
            self.logger.error(f"Download of '{playlist_title}' completed with {len(errors)} errors:")
            for err in errors: self.logger.error(f"  - {err}")
        else:
            self.logger.info(f"Download of '{playlist_title}' completed {'successfully' if success else 'with issues but no item errors reported'}.")
            
        Clock.schedule_once(lambda dt: self._set_all_action_buttons_state(True))
        if self.root and self.root.ids.get('overall_download_progress'): # Conceptual ID
            if not success or self.stop_download_flag:
                 Clock.schedule_once(lambda dt: setattr(self.root.ids.overall_download_progress, 'value', 0))


    def stop_current_download(self): # Conceptual from Step 12
        self.logger.info("Stop download requested by user.")
        self.stop_download_flag = True
        self.update_status_label("Stopping download... Please wait for current item to finish.")
        if self.root and self.root.ids.get('stop_download_button'): # Conceptual ID
            self.root.ids.stop_download_button.disabled = True


if __name__ == '__main__':
    try:
        PlexDownloaderApp().run()
    except Exception as e_app_run:
        log_path = os.path.join(os.path.expanduser("~"), "plex_downloader_kivy_critical_error.log")
        logging.basicConfig(filename=log_path, level=logging.CRITICAL)
        logging.critical(f"Critical error running Kivy application: {e_app_run}", exc_info=True)
        print(f"FATAL ERROR RUNNING APP (see {log_path}): {e_app_run}")

[end of main.py]
