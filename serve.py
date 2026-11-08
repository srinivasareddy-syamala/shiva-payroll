"""Production-style server for Windows/office use (waitress). Called by start.bat."""
import os
import socket
import threading
import webbrowser

from waitress import serve

from app import create_app

PORT = int(os.environ.get("PORT", 5000))


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


if __name__ == "__main__":
    app = create_app()
    ip = lan_ip()
    print("=" * 56)
    print(f"  {app.config['COMPANY_NAME']} payroll is running")
    print(f"  On this computer : http://localhost:{PORT}")
    if ip:
        print(f"  On phones (same Wi-Fi): http://{ip}:{PORT}")
    print("  Keep this window open. Close it to stop the app.")
    print("=" * 56)
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    serve(app, host="0.0.0.0", port=PORT, threads=8)
