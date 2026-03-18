# NPAK

A sleek GUI package manager built with PyQt6.

## Features

- **Search** across pacman, AUR (via yay), and Flatpak simultaneously.
- **Install / Remove** packages from any source with one click.
- **Installed packages** browser with live filter.
- **Update checker** for pacman, AUR, and Flatpak.
- **Maintenance tools**: clean cache, remove orphans, fix broken deps.
- Dark theme tuned for KDE Plasma.

## Dependencies

```bash
# Install via pacman (Recommended for CachyOS/Arch)
sudo pacman -S python-pyqt6 yay flatpak pacman-contrib
```


## Installation

To ensure the application integrates correctly with KDE Plasma and the Fish shell, follow these steps:

### 1. Script Location
Place your script in the following directory:
`/home/berg/.local/bin/npak/npak.py`

### 2. Create Desktop Launcher (Fish Shell)
Run the following command in your terminal to create the application entry:

```fish
printf "[Desktop Entry]\nName=NPAK\nComment=GUI Package Manager\nExec=/usr/bin/python3 /home/berg/.local/bin/npak/npak.py\nPath=/home/berg/.local/bin/npak/\nIcon=system-software-install\nTerminal=false\nType=Application\nCategories=System;PackageManager;\nStartupNotify=true" > ~/.local/share/applications/npak.desktop
```

## Notes

- **Authentication**: `sudo` operations (pacman install/remove) prompt for your password in-app.
- **User Operations**: `yay` and `flatpak` operations run without sudo as intended.
- **System Safety**: `checkupdates` (from `pacman-contrib`) is used for safe update checking without modifying the system.
```
