#!/usr/bin/env python3
"""
POS System Launcher
Starts the FastAPI server and opens the browser to localhost:8000
"""
import os
import sys
import subprocess
import time
import webbrowser
import signal
from pathlib import Path

# Change to script directory
BASE_DIR = Path(__file__).parent
os.chdir(BASE_DIR)

# Server URL
SERVER_URL = "http://localhost:8000"
MAX_WAIT_TIME = 30  # Maximum seconds to wait for server to start
CHECK_INTERVAL = 0.5  # Check every 0.5 seconds

# Global process reference for cleanup
server_process = None


def signal_handler(sig, frame):
    """Handle cleanup on exit"""
    print("\nShutting down POS server...")
    if server_process:
        server_process.terminate()
        server_process.wait(timeout=5)
    sys.exit(0)


def check_server_ready():
    """Check if the server is responding"""
    try:
        import urllib.request
        urllib.request.urlopen(SERVER_URL, timeout=1)
        return True
    except:
        return False


def check_port_in_use(port: int = 8000) -> bool:
    """Check if a port is already in use"""
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            result = s.connect_ex(('127.0.0.1', port))
            return result == 0
    except:
        return False


def find_and_kill_stuck_processes(port: int = 8000) -> int:
    """Find and kill processes using the specified port. Returns number of processes killed."""
    killed = 0
    try:
        # Try using fuser (common on Linux)
        try:
            result = subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0:
                killed = 1
                print(f"  Killed process on port {port}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Also try to find and kill uvicorn/launch_pos processes
        try:
            result = subprocess.run(
                ["pgrep", "-f", "uvicorn.*app.main:app"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        subprocess.run(["kill", "-9", pid], timeout=1, capture_output=True)
                        killed += 1
                        print(f"  Killed uvicorn process (PID {pid})")
                    except:
                        pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Kill any stuck launch_pos.py processes (but not the current one)
        try:
            result = subprocess.run(
                ["pgrep", "-f", "launch_pos.py"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                current_pid = os.getpid()
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        pid_int = int(pid)
                        if pid_int != current_pid:
                            subprocess.run(["kill", "-9", pid], timeout=1, capture_output=True)
                            killed += 1
                            print(f"  Killed stuck launch_pos process (PID {pid})")
                    except:
                        pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
            
    except Exception as e:
        pass
    
    return killed


def start_server():
    """Start the FastAPI server"""
    global server_process
    
    # Determine Python executable and venv path
    python_exe = sys.executable
    venv_python = BASE_DIR / ".venv" / "bin" / "python3"
    
    if venv_python.exists():
        python_exe = str(venv_python)
    
    # Start uvicorn server with auto-reload for development
    uvicorn_cmd = [
        python_exe,
        "-m", "uvicorn",
        "app.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--reload"  # Auto-reload on file changes
    ]
    
    print("Starting POS server...")
    print(f"Command: {' '.join(uvicorn_cmd)}")
    
    # Start server in background
    server_process = subprocess.Popen(
        uvicorn_cmd,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True
    )
    
    return server_process


def wait_for_server():
    """Wait for server to become ready"""
    print("Waiting for server to start...")
    elapsed = 0
    
    while elapsed < MAX_WAIT_TIME:
        # Check if process has died
        if server_process and server_process.poll() is not None:
            # Process has exited, get error output
            stdout, stderr = server_process.communicate()
            print(f"\n✗ Server process exited with code {server_process.returncode}")
            if stderr:
                print("\nServer error output:")
                print(stderr.decode('utf-8', errors='ignore'))
            if stdout:
                print("\nServer output:")
                print(stdout.decode('utf-8', errors='ignore'))
            return False
            
        if check_server_ready():
            print(f"✓ Server is ready! ({elapsed:.1f}s)")
            return True
        time.sleep(CHECK_INTERVAL)
        elapsed += CHECK_INTERVAL
        if elapsed % 2 < CHECK_INTERVAL:  # Print progress every 2 seconds
            print(f"  Waiting... ({elapsed:.1f}s)")
    
    print(f"\n✗ Server failed to start within {MAX_WAIT_TIME} seconds")
    if server_process:
        # Try to get any error output
        try:
            stdout, stderr = server_process.communicate(timeout=1)
            if stderr:
                print("\nServer error output:")
                print(stderr.decode('utf-8', errors='ignore')[:500])  # First 500 chars
        except:
            pass
    return False


def main():
    """Main launcher function"""
    global server_process
    
    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Check if running from desktop (no TTY) and show a notification if possible
    import sys
    is_desktop_launch = not sys.stdin.isatty()
    
    if is_desktop_launch:
        # Try to show a notification that we're starting
        try:
            subprocess.Popen(
                ["notify-send", "POS System", "Starting POS System..."],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except:
            pass  # Notification not available, continue anyway
    
    try:
        # Check if server is already running
        if check_server_ready():
            print("✓ POS server is already running!")
        else:
            # Check if port is in use but server not responding
            if check_port_in_use(8000):
                print("⚠ Port 8000 is in use, but server is not responding.")
                print("This might be a stuck process. Attempting to clean up...")
                
                # Wait a moment to see if server becomes ready
                for i in range(6):  # Wait up to 3 seconds
                    time.sleep(0.5)
                    if check_server_ready():
                        print("✓ Server is now responding!")
                        break
                else:
                    # Server still not responding, kill stuck processes
                    print("Cleaning up stuck processes...")
                    killed = find_and_kill_stuck_processes(8000)
                    if killed > 0:
                        print(f"✓ Cleaned up {killed} stuck process(es). Waiting 2 seconds...")
                        time.sleep(2)
                    else:
                        print("⚠ Could not automatically clean up. You may need to manually:")
                        print("  killall -9 python3  # (use with caution)")
                        print("  or: fuser -k 8000/tcp")
            
            # Start the server
            print("Starting POS server...")
            process = start_server()
            
            # Wait for server to be ready
            if not wait_for_server():
                print("\n✗ Failed to start POS server. Please check for errors above.")
                print("\nTroubleshooting:")
                print("  1. Check if port 8000 is in use: lsof -i :8000")
                print("  2. Kill stuck processes: killall -9 python3")
                print("  3. Or try: fuser -k 8000/tcp")
                if process:
                    process.terminate()
                sys.exit(1)
        
        # Open browser
        print(f"✓ Opening browser to {SERVER_URL}...")
        try:
            webbrowser.open(SERVER_URL)
            if is_desktop_launch:
                # Show success notification
                try:
                    subprocess.Popen(
                        ["notify-send", "POS System", f"POS System is running!\nAccess at: {SERVER_URL}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except:
                    pass
        except Exception as e:
            print(f"Warning: Could not open browser automatically: {e}")
            print(f"Please manually open: {SERVER_URL}")
            if is_desktop_launch:
                try:
                    subprocess.Popen(
                        ["notify-send", "POS System", f"Server started!\nPlease open: {SERVER_URL}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except:
                    pass
        
        # Keep the script running
        print("\n" + "="*60)
        print("POS System is running successfully!")
        print("="*60)
        print(f"Access the system at: {SERVER_URL}")
        if not is_desktop_launch:
            print("Press Ctrl+C to stop the server and exit.\n")
        else:
            print("The server is running in the background.")
            print("Close this window or use system monitor to stop the server.\n")
        
        if server_process:
            # Wait for server process to finish (or be terminated)
            try:
                if is_desktop_launch:
                    # When launched from desktop, keep running in background
                    # Don't wait for user input
                    server_process.wait()
                else:
                    server_process.wait()
            except KeyboardInterrupt:
                signal_handler(None, None)
        else:
            # Server was already running, just wait for interrupt
            try:
                if is_desktop_launch:
                    # When launched from desktop, keep running
                    while True:
                        time.sleep(10)  # Check every 10 seconds
                        # Verify server is still running
                        if not check_server_ready():
                            print("Server appears to have stopped. Exiting...")
                            break
                else:
                    while True:
                        time.sleep(1)
            except KeyboardInterrupt:
                print("\nExiting...")
                sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        signal_handler(None, None)
    except Exception as e:
        error_msg = f"Error starting POS System: {e}"
        print(f"\n✗ {error_msg}")
        import traceback
        traceback.print_exc()
        
        # Show error notification if launched from desktop
        if is_desktop_launch:
            try:
                subprocess.Popen(
                    ["notify-send", "POS System Error", error_msg, "--urgency=critical"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except:
                pass
        
        if server_process:
            server_process.terminate()
        sys.exit(1)


if __name__ == "__main__":
    main()

