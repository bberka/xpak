import os
import subprocess
import shutil
import json
import tempfile
import shlex
import concurrent.futures
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal

from xpak import APP_VERSION


def _pre_auth_sudo(password: str) -> bool:
    """Pre-authenticate sudo by running 'sudo -S true' with the given password.
    This caches sudo credentials so subsequent yay calls can inherit them.
    Returns True on success."""
    try:
        proc = subprocess.run(
            ["sudo", "-S", "true"],
            input=password + "\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _create_askpass_helper(password: str) -> str:
    """Create a temporary sudo askpass helper script that outputs the password.
    Returns the path to the script. Caller is responsible for deleting it."""
    fd, path = tempfile.mkstemp(suffix=".sh", prefix="xpak_askpass_")
    with os.fdopen(fd, "w") as f:
        f.write(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(password)}\n")
    os.chmod(path, 0o700)
    return path


class CommandWorker(QThread):
    output_line = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(int)

    def __init__(self, cmd: list, sudo: bool = False, password: str = "", pre_auth: bool = False):
        super().__init__()
        self.cmd = cmd
        self.sudo = sudo
        self.password = password
        self.pre_auth = pre_auth
        self._abort = False
        self._process = None

    def abort(self):
        self._abort = True
        if self._process:
            self._process.terminate()

    def send_input(self, text: str):
        """Send a line of text to the running process's stdin."""
        if self._process and self._process.stdin and not self._process.stdin.closed:
            try:
                self._process.stdin.write(text + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def run(self):
        askpass_path = None
        try:
            env = None

            # For AUR (yay) operations: pre-authenticate sudo and set up SUDO_ASKPASS
            # so yay's internal sudo calls (e.g. installing sync deps) work without a TTY.
            if self.pre_auth and self.password:
                ok = _pre_auth_sudo(self.password)
                if not ok:
                    self.finished.emit(False, "sudo authentication failed")
                    return
                askpass_path = _create_askpass_helper(self.password)
                env = os.environ.copy()
                env["SUDO_ASKPASS"] = askpass_path

            if self.sudo and self.password:
                full_cmd = ["sudo", "-S"] + self.cmd
                self._process = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                self._process.stdin.write(self.password + "\n")
                self._process.stdin.flush()
            else:
                self._process = subprocess.Popen(
                    self.cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    env=env,
                )

            for line in iter(self._process.stdout.readline, ""):
                if self._abort:
                    self._process.terminate()
                    self.finished.emit(False, "Operation aborted")
                    return
                line = line.rstrip()
                if line:
                    self.output_line.emit(line)

            self._process.wait()
            success = self._process.returncode == 0
            msg = (
                "Operation completed successfully"
                if success
                else f"Operation failed (exit {self._process.returncode})"
            )
            self.finished.emit(success, msg)

        except FileNotFoundError as e:
            self.finished.emit(False, f"Command not found: {e}")
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            if askpass_path:
                try:
                    os.unlink(askpass_path)
                except OSError:
                    pass


class SearchWorker(QThread):
    result_chunk = pyqtSignal(list)
    search_done = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, query: str, sources: list):
        super().__init__()
        self.query = query
        self.sources = sources  # list of "pacman", "aur", "flatpak"

    def run(self):
        total = 0
        try:
            tasks = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                if "pacman" in self.sources:
                    tasks[executor.submit(self._search_pacman)] = "pacman"
                if "aur" in self.sources and shutil.which("yay"):
                    tasks[executor.submit(self._search_aur)] = "aur"
                if "flatpak" in self.sources and shutil.which("flatpak"):
                    tasks[executor.submit(self._search_flatpak)] = "flatpak"

                for future in concurrent.futures.as_completed(tasks):
                    try:
                        results = future.result()
                        if results:
                            total += len(results)
                            self.result_chunk.emit(results)
                    except Exception as e:
                        self.error.emit(str(e))

            self.search_done.emit(total)
        except Exception as e:
            self.error.emit(str(e))
            self.search_done.emit(0)

    def _search_pacman(self) -> list:
        try:
            out = subprocess.check_output(
                ["pacman", "-Ss", self.query],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return self._parse_pacman_output(out, "pacman")
        except subprocess.CalledProcessError:
            return []

    def _search_aur(self) -> list:
        try:
            from urllib.request import urlopen, Request as _Request
            import json as _json
            url = f"https://aur.archlinux.org/rpc/v5/search/{self.query}"
            req = _Request(url, headers={"User-Agent": "xpak"})
            with urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode())
            installed = self._get_installed_names()
            results = []
            for pkg in data.get("results", []):
                name = pkg.get("Name", "")
                results.append(
                    {
                        "name": name,
                        "version": pkg.get("Version", ""),
                        "description": pkg.get("Description", "") or "",
                        "source": "aur",
                        "installed": name in installed,
                        "votes": str(pkg.get("NumVotes", 0)),
                    }
                )
            return results
        except Exception:
            # Fallback to yay CLI (votes will be unavailable)
            try:
                out = subprocess.check_output(
                    ["yay", "-Ssa", "--aur", self.query],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                return self._parse_pacman_output(out, "aur")
            except subprocess.CalledProcessError:
                return []

    def _search_flatpak(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "search", "--columns=application,name,version,description", self.query],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            results = []
            for line in out.strip().splitlines()[1:]:  # skip header
                parts = line.split("\t")
                if len(parts) >= 2:
                    results.append(
                        {
                            "name": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                            "app_id": parts[0].strip(),
                            "version": parts[2].strip() if len(parts) > 2 else "",
                            "description": parts[3].strip() if len(parts) > 3 else "",
                            "source": "flatpak",
                            "installed": self._is_flatpak_installed(parts[0].strip()),
                            "votes": "",
                        }
                    )
            return results
        except subprocess.CalledProcessError:
            return []

    def _parse_pacman_output(self, out: str, source: str) -> list:
        results = []
        lines = out.strip().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("    ") or not line:
                i += 1
                continue
            desc = lines[i + 1].strip() if i + 1 < len(lines) else ""
            parts = line.split()
            if not parts:
                i += 2
                continue
            repo_name = parts[0]
            version = parts[1] if len(parts) > 1 else ""
            installed = "[installed]" in line
            name = repo_name.split("/")[-1] if "/" in repo_name else repo_name
            results.append(
                {
                    "name": name,
                    "version": version,
                    "description": desc,
                    "source": source,
                    "installed": installed,
                    "repo": repo_name.split("/")[0] if "/" in repo_name else source,
                    "votes": "",
                }
            )
            i += 2
        return results

    def _get_installed_names(self) -> set:
        """Return the set of all installed pacman package names."""
        try:
            out = subprocess.check_output(
                ["pacman", "-Qq"], text=True, stderr=subprocess.DEVNULL
            )
            return set(out.strip().splitlines())
        except Exception:
            return set()

    def _is_flatpak_installed(self, app_id: str) -> bool:
        try:
            out = subprocess.check_output(
                ["flatpak", "list", "--app", "--columns=application"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return app_id in out
        except Exception:
            return False


class InstalledLoader(QThread):
    results_ready = pyqtSignal(list)

    def __init__(self, source: str = "all"):
        super().__init__()
        self.source = source

    def run(self):
        results = []
        tasks = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            if self.source in ("pacman", "all"):
                tasks.append(executor.submit(self._list_pacman))
            if self.source in ("flatpak", "all") and shutil.which("flatpak"):
                tasks.append(executor.submit(self._list_flatpak))

            for future in concurrent.futures.as_completed(tasks):
                try:
                    results.extend(future.result())
                except Exception:
                    pass

        self.results_ready.emit(results)

    def _list_pacman(self) -> list:
        try:
            out = subprocess.check_output(
                ["pacman", "-Q"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    pkgs.append(
                        {
                            "name": parts[0],
                            "version": parts[1],
                            "source": "pacman",
                            "description": "",
                        }
                    )
            return pkgs
        except Exception:
            return []

    def _list_flatpak(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "list", "--app", "--columns=application,name,version"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    pkgs.append(
                        {
                            "name": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                            "app_id": parts[0].strip(),
                            "version": parts[2].strip() if len(parts) > 2 else "",
                            "source": "flatpak",
                            "description": "",
                        }
                    )
            return pkgs
        except Exception:
            return []


class UpdateChecker(QThread):
    updates_ready = pyqtSignal(list)

    def run(self):
        results = []
        tasks = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            tasks.append(executor.submit(self._check_pacman_updates))
            if shutil.which("flatpak"):
                tasks.append(executor.submit(self._check_flatpak_updates))

            for future in concurrent.futures.as_completed(tasks):
                try:
                    results.extend(future.result())
                except Exception:
                    pass

        self.updates_ready.emit(results)

    def _check_pacman_updates(self) -> list:
        try:
            out = subprocess.check_output(
                ["checkupdates"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    pkgs.append(
                        {
                            "name": parts[0],
                            "old_version": parts[1],
                            "new_version": parts[3],
                            "source": "pacman",
                        }
                    )
            return pkgs
        except subprocess.CalledProcessError:
            return []
        except FileNotFoundError:
            return []

    def _check_flatpak_updates(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "remote-ls", "--updates", "--columns=application,name,version"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if parts and parts[0]:
                    pkgs.append(
                        {
                            "name": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                            "old_version": "",
                            "new_version": parts[2].strip() if len(parts) > 2 else "",
                            "source": "flatpak",
                        }
                    )
            return pkgs
        except Exception:
            return []


class AppUpdateChecker(QThread):
    update_available = pyqtSignal(str, str)  # version, url
    no_update = pyqtSignal()
    error = pyqtSignal(str)

    GITHUB_API_URL = "https://api.github.com/repos/bberka/xpak/releases/latest"

    def run(self):
        try:
            req = Request(
                self.GITHUB_API_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "xpak"},
            )
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            latest_tag = data.get("tag_name", "").lstrip("v")
            html_url = data.get("html_url", "")

            if not latest_tag:
                self.error.emit("Could not parse release info from GitHub")
                return

            current = tuple(int(x) for x in APP_VERSION.split("."))
            latest = tuple(int(x) for x in latest_tag.split("."))

            if latest > current:
                self.update_available.emit(latest_tag, html_url)
            else:
                self.no_update.emit()

        except URLError as e:
            self.error.emit(f"Network error: {e}")
        except Exception as e:
            self.error.emit(str(e))
