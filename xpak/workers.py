import os
import subprocess
import shutil
import json
import tempfile
import shlex
import concurrent.futures
from functools import lru_cache
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal

from xpak import APP_VERSION
from xpak.logging_service import get_logger


logger = get_logger("xpak.workers")


def _parse_checkupdates_output(out: str) -> list[dict]:
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


def _normalize_repo_filters(repos: list[str] | None) -> list[str]:
    if not repos:
        return []

    normalized = []
    seen = set()
    for repo in repos:
        name = str(repo).strip().lower()
        if name and name not in seen:
            normalized.append(name)
            seen.add(name)
    return normalized


def is_repo_allowed(repo_name: str, include_repos: list[str] | None = None, exclude_repos: list[str] | None = None) -> bool:
    repo = (repo_name or "").strip().lower()
    include = set(_normalize_repo_filters(include_repos))
    exclude = set(_normalize_repo_filters(exclude_repos))
    if include and repo not in include:
        return False
    return repo not in exclude


@lru_cache(maxsize=1)
def get_available_pacman_repos() -> list[str]:
    try:
        out = subprocess.check_output(
            ["pacman-conf", "--repo-list"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    return [line.strip().lower() for line in out.splitlines() if line.strip()]


@lru_cache(maxsize=2048)
def get_pacman_package_repo(pkg_name: str, local: bool = False) -> str:
    cmd = ["pacman", "-Qi" if local else "-Si", pkg_name]
    try:
        out = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

    for line in out.splitlines():
        if line.startswith("Repository"):
            _, _, repo = line.partition(":")
            return repo.strip().lower()
    return ""


@lru_cache(maxsize=512)
def is_core_system_package(pkg_name: str) -> bool:
    repo = get_pacman_package_repo(pkg_name)
    return bool(repo) and (repo == "core" or repo.endswith("-core") or "-core-" in repo)


def get_pacman_updates(
    exclude_core_system_updates: bool = False,
    include_repos: list[str] | None = None,
    exclude_repos: list[str] | None = None,
) -> tuple[list[dict], list[str]]:
    try:
        out = subprocess.check_output(
            ["checkupdates"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [], []

    pkgs = _parse_checkupdates_output(out)
    visible_updates = []
    ignored_packages = []
    for pkg in pkgs:
        repo = get_pacman_package_repo(pkg["name"])
        pkg["repo"] = repo

        if not is_repo_allowed(repo, include_repos, exclude_repos):
            ignored_packages.append(pkg["name"])
            continue

        if exclude_core_system_updates and is_core_system_package(pkg["name"]):
            ignored_packages.append(pkg["name"])
        else:
            visible_updates.append(pkg)
    return visible_updates, ignored_packages


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

    def __init__(
        self,
        cmd: list,
        sudo: bool = False,
        password: str = "",
        pre_auth: bool = False,
        log_name: str = "",
    ):
        super().__init__()
        self.cmd = cmd
        self.sudo = sudo
        self.password = password
        self.pre_auth = pre_auth
        self.log_name = log_name or "command"
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
            logger.info(
                "CommandWorker starting [%s]: cmd=%s sudo=%s pre_auth=%s",
                self.log_name,
                self.cmd,
                self.sudo,
                self.pre_auth,
            )
            env = None

            # For AUR (yay) operations: pre-authenticate sudo and set up SUDO_ASKPASS
            # so yay's internal sudo calls (e.g. installing sync deps) work without a TTY.
            if self.pre_auth and self.password:
                ok = _pre_auth_sudo(self.password)
                if not ok:
                    logger.error("CommandWorker pre-auth failed [%s]", self.log_name)
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

            checksum_failed = False
            for line in iter(self._process.stdout.readline, ""):
                if self._abort:
                    self._process.terminate()
                    logger.warning("CommandWorker aborted [%s]", self.log_name)
                    self.finished.emit(False, "Operation aborted")
                    return
                line = line.rstrip()
                if line:
                    logger.debug("Command output [%s]: %s", self.log_name, line)
                    if "did not pass the validity check" in line:
                        checksum_failed = True
                    self.output_line.emit(line)

            self._process.wait()
            success = self._process.returncode == 0
            if not success and checksum_failed:
                msg = (
                    "Checksum verification failed — the AUR package's checksums don't match "
                    "the downloaded files. This is an upstream PKGBUILD issue. "
                    "Check AUR comments for navicat-premium-lite for status or a workaround."
                )
            else:
                msg = (
                    "Operation completed successfully"
                    if success
                    else f"Operation failed (exit {self._process.returncode})"
                )
            if success:
                logger.info("CommandWorker succeeded [%s]: %s", self.log_name, self.cmd)
            else:
                logger.error(
                    "CommandWorker failed [%s]: exit=%s cmd=%s",
                    self.log_name,
                    self._process.returncode,
                    self.cmd,
                )
            self.finished.emit(success, msg)

        except FileNotFoundError as e:
            logger.exception("CommandWorker missing command [%s]", self.log_name)
            self.finished.emit(False, f"Command not found: {e}")
        except Exception as e:
            logger.exception("CommandWorker crashed [%s]", self.log_name)
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

    def __init__(
        self,
        query: str,
        sources: list,
        include_pacman_repos: list[str] | None = None,
        exclude_pacman_repos: list[str] | None = None,
    ):
        super().__init__()
        self.query = query
        self.sources = sources  # list of "pacman", "aur", "flatpak"
        self.include_pacman_repos = _normalize_repo_filters(include_pacman_repos)
        self.exclude_pacman_repos = _normalize_repo_filters(exclude_pacman_repos)

    def run(self):
        total = 0
        try:
            logger.info("SearchWorker starting: query=%s sources=%s", self.query, self.sources)
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
                            logger.info("SearchWorker received %s results", len(results))
                            total += len(results)
                            self.result_chunk.emit(results)
                    except Exception as e:
                        logger.exception("SearchWorker future failed")
                        self.error.emit(str(e))

            logger.info("SearchWorker complete: total=%s", total)
            self.search_done.emit(total)
        except Exception as e:
            logger.exception("SearchWorker crashed")
            self.error.emit(str(e))
            self.search_done.emit(0)

    def _search_pacman(self) -> list:
        try:
            out = subprocess.check_output(
                ["pacman", "-Ss", self.query],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            results = self._parse_pacman_output(out, "pacman")
            return [
                pkg for pkg in results
                if is_repo_allowed(
                    pkg.get("repo", ""),
                    self.include_pacman_repos,
                    self.exclude_pacman_repos,
                )
            ]
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
                        "repo": "aur",
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
                            "repo": "flatpak",
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

    def __init__(
        self,
        source: str = "all",
        include_pacman_repos: list[str] | None = None,
        exclude_pacman_repos: list[str] | None = None,
    ):
        super().__init__()
        self.source = source
        self.include_pacman_repos = _normalize_repo_filters(include_pacman_repos)
        self.exclude_pacman_repos = _normalize_repo_filters(exclude_pacman_repos)

    def run(self):
        results = []
        tasks = []
        logger.info("InstalledLoader starting for source=%s", self.source)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            if self.source in ("pacman", "all"):
                tasks.append(executor.submit(self._list_pacman))
            if self.source in ("flatpak", "all") and shutil.which("flatpak"):
                tasks.append(executor.submit(self._list_flatpak))

            for future in concurrent.futures.as_completed(tasks):
                try:
                    results.extend(future.result())
                except Exception:
                    logger.exception("InstalledLoader future failed")
                    pass

        logger.info("InstalledLoader complete: count=%s", len(results))
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
                    repo = get_pacman_package_repo(parts[0], local=True)
                    if not is_repo_allowed(
                        repo,
                        self.include_pacman_repos,
                        self.exclude_pacman_repos,
                    ):
                        continue
                    pkgs.append(
                        {
                            "name": parts[0],
                            "version": parts[1],
                            "source": "pacman",
                            "repo": repo,
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

    def __init__(
        self,
        exclude_system_updates: bool = False,
        include_pacman_repos: list[str] | None = None,
        exclude_pacman_repos: list[str] | None = None,
    ):
        super().__init__()
        self.exclude_system_updates = exclude_system_updates
        self.include_pacman_repos = _normalize_repo_filters(include_pacman_repos)
        self.exclude_pacman_repos = _normalize_repo_filters(exclude_pacman_repos)

    def run(self):
        results = []
        tasks = []
        logger.info("UpdateChecker starting (exclude_system_updates=%s)", self.exclude_system_updates)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            tasks.append(executor.submit(self._check_pacman_updates))
            if shutil.which("flatpak"):
                tasks.append(executor.submit(self._check_flatpak_updates))

            for future in concurrent.futures.as_completed(tasks):
                try:
                    results.extend(future.result())
                except Exception:
                    logger.exception("UpdateChecker future failed")
                    pass

        logger.info("UpdateChecker complete: count=%s", len(results))
        self.updates_ready.emit(results)

    def _check_pacman_updates(self) -> list:
        updates, _ = get_pacman_updates(
            exclude_core_system_updates=self.exclude_system_updates,
            include_repos=self.include_pacman_repos,
            exclude_repos=self.exclude_pacman_repos,
        )
        return updates

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
            logger.info("AppUpdateChecker starting")
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
                logger.info("App update available: current=%s latest=%s", APP_VERSION, latest_tag)
                self.update_available.emit(latest_tag, html_url)
            else:
                logger.info("App already up to date: current=%s latest=%s", APP_VERSION, latest_tag)
                self.no_update.emit()

        except URLError as e:
            logger.exception("AppUpdateChecker network error")
            self.error.emit(f"Network error: {e}")
        except Exception as e:
            logger.exception("AppUpdateChecker crashed")
            self.error.emit(str(e))
