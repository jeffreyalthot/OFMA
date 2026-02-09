import threading

from elit21.web.app import create_app
from elit21.admin.app import main as admin_main


def run_web():
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)


def run_admin():
    admin_main()


def main():
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    run_admin()


if __name__ == "__main__":
    main()
