"""Entry point for the desktop app (``livecaptions`` / ``python -m livecaptions``)."""


def main():
    import truststore

    # Use the OS certificate store so model downloads work behind TLS-inspecting proxies.
    truststore.inject_into_ssl()

    import tkinter as tk

    from .ui import App

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
