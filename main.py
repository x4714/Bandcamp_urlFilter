import sys
import os
import customtkinter as ctk

# Ensure the root directory is in the PYTHONPATH so module imports work correctly
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.settings import SettingsManager
from gui.main_window import MainWindow

def main():
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    
    settings = SettingsManager.load()
    app = MainWindow(settings)
    app.mainloop()

if __name__ == "__main__":
    main()
