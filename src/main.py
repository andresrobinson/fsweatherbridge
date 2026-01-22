"""Main entry point with system tray support."""

import asyncio
import signal
import sys
import threading
import time
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

import uvicorn

from src.config import AppConfig
from src.web_app import app

# Global server instance for graceful shutdown
server_instance = None
shutdown_event = threading.Event()
tray_icon = None


# All console-related functions removed - using file logging only


def create_tray_icon():
    """Create system tray icon."""
    if not TRAY_AVAILABLE:
        return None
    
    # Create a simple icon
    image = Image.new('RGB', (64, 64), color='blue')
    draw = ImageDraw.Draw(image)
    draw.ellipse([16, 16, 48, 48], fill='white')
    
    def on_exit():
        """Handle exit from menu."""
        global shutdown_event, tray_icon
        shutdown_event.set()
        if tray_icon:
            # Stop icon in a separate thread to avoid callback issues
            threading.Thread(target=lambda: tray_icon.stop(), daemon=True).start()
    
    # Create menu (no console toggle - logs are in files)
    menu = pystray.Menu(
        pystray.MenuItem("Open Web UI", lambda: open_browser()),
        pystray.MenuItem("View Logs", lambda: open_logs_folder()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_exit),
    )
    
    icon = pystray.Icon("FSX Weather Bridge", image, "FSX Weather Bridge", menu)
    return icon


def open_browser():
    """Open web browser to UI."""
    import webbrowser
    config = AppConfig.load()
    url = f"http://{config.web_ui.host}:{config.web_ui.port}"
    webbrowser.open(url)


def open_logs_folder():
    """Open the logs folder in Windows Explorer."""
    import os
    import subprocess
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    if sys.platform == 'win32':
        subprocess.Popen(f'explorer "{log_dir}"')
    else:
        # For non-Windows, try to open the folder
        try:
            subprocess.Popen(['xdg-open', log_dir])
        except Exception:
            pass


def exit_app():
    """Exit application gracefully."""
    global server_instance, shutdown_event
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Shutting down...")
    
    # Signal shutdown
    shutdown_event.set()
    
    # Stop the server if it's running
    if server_instance:
        try:
            # Shutdown uvicorn server
            server_instance.should_exit = True
            # Give it a moment to clean up
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Error shutting down server: {e}")
    
    # Exit
    sys.exit(0)


def run_server(config: AppConfig):
    """Run FastAPI server."""
    global server_instance
    
    # Fix sys.stdout/stderr if they're None (happens when running without console)
    # Uvicorn needs these to be valid file-like objects
    import sys
    import os
    import logging
    
    # Set up log directory
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    if sys.stdout is None:
        # Redirect to log file or create a dummy stdout
        log_file = os.path.join(log_dir, 'server_stdout.log')
        sys.stdout = open(log_file, 'w', encoding='utf-8', buffering=1)
    
    if sys.stderr is None:
        # Redirect to log file or create a dummy stderr
        log_file = os.path.join(log_dir, 'server_stderr.log')
        sys.stderr = open(log_file, 'w', encoding='utf-8', buffering=1)
    
    # Reconfigure logging to replace StreamHandlers with FileHandlers
    # This prevents errors when sys.stderr is None or redirected
    root_logger = logging.getLogger()
    # Remove existing stream handlers that might be using None streams
    handlers_to_remove = []
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            # Check if handler's stream is None or is sys.stderr/sys.stdout
            if handler.stream is None or handler.stream in (sys.stdout, sys.stderr):
                handlers_to_remove.append(handler)
    
    for handler in handlers_to_remove:
        root_logger.removeHandler(handler)
        handler.close()
    
    # Add file handler for server thread logging
    server_log_file = os.path.join(log_dir, 'server.log')
    file_handler = logging.FileHandler(server_log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s:%(name)s:%(message)s'))
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    
    # Set up logging in this thread
    logger = logging.getLogger(__name__)
    logger.info("run_server() called - starting uvicorn in background thread")
    
    # Set custom exception handler for asyncio to suppress harmless Windows errors
    import sys
    if sys.platform == 'win32':
        def custom_exception_handler(loop, context):
            """Suppress harmless Windows WebSocket connection cleanup errors."""
            exception = context.get('exception')
            message = str(context.get('message', ''))
            
            # Suppress ConnectionResetError from WebSocket cleanup
            if exception and isinstance(exception, ConnectionResetError):
                if '10054' in str(exception) or 'SHUT_RDWR' in message or '_call_connection_lost' in message:
                    return  # Suppress this harmless error
            
            # Suppress ProactorBasePipeTransport callback errors
            if 'ProactorBasePipeTransport' in message and '_call_connection_lost' in message:
                return  # Suppress this harmless error
            
            # Suppress callback errors with connection reset
            if 'Exception in callback' in message:
                if 'ProactorBasePipeTransport' in message or '_call_connection_lost' in message:
                    if exception and isinstance(exception, ConnectionResetError):
                        return  # Suppress this harmless error
        
        # This approach won't work directly, so we'll rely on the handler in web_app.py
        # But we can at least suppress stderr output for these specific errors
        pass
    
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Creating uvicorn config...")
        config_obj = uvicorn.Config(
            app,
            host=config.web_ui.host,
            port=config.web_ui.port,
            log_level="info",
        )
        logger.info("Creating uvicorn Server instance...")
        global server_instance
        server_instance = uvicorn.Server(config_obj)
        logger.info("Uvicorn Server instance created")
        
        logger.info("Uvicorn server starting...")
        logger.info(f"Server will run on {config.web_ui.host}:{config.web_ui.port}")
        # Run the server - this will trigger FastAPI startup events
        server_instance.run()
        logger.info("Uvicorn server stopped")
    except KeyboardInterrupt:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Server interrupted by user")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Server error: {e}", exc_info=True)
        import traceback
        logger.error(traceback.format_exc())


def main():
    """Main entry point."""
    global shutdown_event
    
    # Set up logging to file only (no console)
    import logging
    import os
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Clean up old log files at startup (delete and recreate)
    log_files = [
        'fsweatherbridge.log',
        'server.log',
        'server_stdout.log',
        'server_stderr.log'
    ]
    
    for log_file in log_files:
        log_path = os.path.join(log_dir, log_file)
        try:
            if os.path.exists(log_path):
                os.remove(log_path)
        except Exception:
            # If we can't delete, that's okay - we'll append to it
            pass
    
    log_file = os.path.join(log_dir, 'fsweatherbridge.log')
    
    # Configure logging to file only (no console)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s:%(name)s:%(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8')
        ],
        force=True
    )
    
    logger = logging.getLogger(__name__)
    logger.info("FSX Weather Bridge starting...")
    logger.info("Log files cleaned and recreated at startup")
    
    # Load configuration
    try:
        config = AppConfig.load()
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}", exc_info=True)
        return
    
    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        exit_app()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start server in background thread
    logger.info("Starting web server...")
    server_thread = threading.Thread(
        target=run_server,
        args=(config,),
        daemon=False,  # Not daemon so we can wait for it
        name="UvicornServerThread"
    )
    server_thread.start()
    logger.info(f"Server thread started: {server_thread.name} (alive: {server_thread.is_alive()})")
    
    # Wait for server to fully start and FastAPI startup event to complete
    logger.info("Waiting for FastAPI to initialize...")
    
    # Wait for server to start and startup event to complete
    # Check if engine is created (startup event should create it)
    max_wait = 20  # Maximum 20 seconds
    wait_interval = 0.5
    waited = 0
    server_ready = False
    
    while waited < max_wait:
        # Check if thread is still alive
        if not server_thread.is_alive():
            logger.error(f"Server thread died after {waited:.1f} seconds!")
            break
        
        try:
            from src.web_app import engine
            if engine is not None:
                logger.info(f"WeatherEngine detected after {waited:.1f}s - FastAPI startup completed successfully")
                server_ready = True
                break
        except Exception as e:
            if waited % 2 == 0:  # Log every second
                logger.debug(f"Waiting for engine... ({waited:.1f}s, thread alive: {server_thread.is_alive()})")
        time.sleep(wait_interval)
        waited += wait_interval
    
    if not server_ready:
        logger.error(f"FastAPI startup event did not complete - WeatherEngine not detected after {max_wait} seconds!")
        logger.error(f"Server thread status: alive={server_thread.is_alive()}")
        logger.error("The server may not be running properly. Check for errors above.")
    else:
        logger.info(f"Web server ready at http://{config.web_ui.host}:{config.web_ui.port}")
    
    # Create and run system tray
    if TRAY_AVAILABLE:
        global tray_icon
        # Check if tray icon already exists (prevent duplicates)
        if tray_icon is not None:
            logger.warning("Tray icon already exists, stopping old one...")
            try:
                tray_icon.stop()
            except Exception:
                pass
        try:
            tray_icon = create_tray_icon()
            if tray_icon:
                # Run icon in a separate thread (non-blocking)
                def run_icon():
                    try:
                        logger.info("Starting system tray icon...")
                        tray_icon.run()  # This blocks until stopped
                    except Exception as e:
                        logger.error(f"Tray icon error: {e}", exc_info=True)
                
                icon_thread = threading.Thread(target=run_icon, daemon=True)  # Changed to daemon
                icon_thread.start()
                logger.info("System tray icon thread started")
            else:
                logger.warning("Failed to create tray icon")
        except Exception as e:
            logger.error(f"Error creating tray icon: {e}", exc_info=True)
        
        # Wait for shutdown event (don't block on tray icon)
        try:
            while not shutdown_event.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            shutdown_event.set()
        
        # Stop icon
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass
        
        # Exit
        exit_app()
    else:
        # No tray support, just run server
        logger.warning("System tray not available. Install pystray and Pillow for tray support.")
        logger.info(f"Web UI available at http://{config.web_ui.host}:{config.web_ui.port}")
        logger.info("Press Ctrl+C to exit.")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            exit_app()


if __name__ == "__main__":
    main()
