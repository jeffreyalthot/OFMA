import argparse
import threading

from elit21.admin.app import main as admin_main
from elit21.web.app import create_app


def run_web() -> None:
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)


def run_admin() -> None:
    admin_main()


def main() -> None:
    parser = argparse.ArgumentParser(description="OFMA launcher")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["web", "admin", "both"],
        default="web",
        help="web (default), admin, or both",
    )
    args = parser.parse_args()

    if args.mode == "web":
        run_web()
        return
    if args.mode == "admin":
        run_admin()
        return

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    run_admin()


if __name__ == "__main__":
    main()
