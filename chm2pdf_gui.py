"""Thin wrapper — launches the chm2pdf GUI.

Usage:
    python chm2pdf_gui.py             # Launch GUI
    python -m chm2pdf [args]          # CLI mode
"""

from chm2pdf.gui import main

if __name__ == "__main__":
    main()
