"""Entry point for the desktop app (``livecaptions`` / ``python -m livecaptions``)."""

import os


def env_file_candidates():
    """.env in the current directory, then in the repo root (for source checkouts)."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(here))
    return [os.path.join(os.getcwd(), ".env"), os.path.join(repo_root, ".env")]


def main():
    import truststore

    # Use the OS certificate store so model downloads work behind TLS-inspecting proxies.
    truststore.inject_into_ssl()

    from .summarize import load_dotenv
    for path in env_file_candidates():
        load_dotenv(path)

    import tkinter as tk

    from .ui import App

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
