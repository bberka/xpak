import os
import subprocess
import shutil
import json
import tempfile
import shlex
import concurrent.futures
import re
import itertools
from functools import lru_cache
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal

from xpak import APP_VERSION
from xpak.logging_service import get_logger


logger = get_logger("xpak.workers")


_SIZE_UNITS = {
    "B": 1,
    "BYTES": 1,
    "KIB": 1024,
    "MIB": 1024 ** 2,
    "GIB": 1024 ** 3,
    "TIB": 1024 ** 4,
    "KB": 1000,
    "MB": 1000 ** 2,
    "GB": 1000 ** 3,
    "TB": 1000 ** 4,
}


def parse_size_to_bytes(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None

    compact = " ".join(text.split())
    amount_text = compact
    unit = "B"

    match = re.match(r"^\s*([+-]?[0-9][0-9.,]*)\s*([A-Za-z]+)?\s*$", compact)
    if match:
        amount_text = match.group(1)
        unit = (match.group(2) or "B").upper()
    else:
        parts = compact.split()
        if len(parts) >= 2:
            amount_text = parts[0]
            unit = parts[1].upper()
        else:
            idx = 0
            while idx < len(compact) and (compact[idx].isdigit() or compact[idx] in ".+-"):
                idx += 1
            amount_text = compact[:idx] or compact
            unit = (compact[idx:] or "B").upper()

    if "," in amount_text and "." in amount_text:
        if amount_text.rfind(",") > amount_text.rfind("."):
            amount_text = amount_text.replace(".", "").replace(",", ".")
        else:
            amount_text = amount_text.replace(",", "")
    elif "," in amount_text:
        whole, _, frac = amount_text.rpartition(",")
        if whole and frac and len(frac) in (1, 2):
            amount_text = f"{whole.replace(',', '')}.{frac}"
        else:
            amount_text = amount_text.replace(",", "")

    try:
        amount = float(amount_text)
    except ValueError:
        return None

    multiplier = _SIZE_UNITS.get(unit)
    if multiplier is None:
        return None
    return int(amount * multiplier)


def format_size_bytes(num_bytes: int | None) -> str:
    if num_bytes is None or num_bytes < 0:
        return "N/A"
    if num_bytes < 1000:
        return f"{num_bytes} B"

    value = float(num_bytes)
    units = ["KB", "MB", "GB", "TB"]
    for unit in units:
        value /= 1000.0
        if value < 1000.0 or unit == units[-1]:
            break
    return f"{value:.2f} {unit}"


def format_size_delta(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "N/A"
    if num_bytes == 0:
        return "0 B"
    sign = "+" if num_bytes > 0 else "-"
    return f"{sign}{format_size_bytes(abs(num_bytes))}"


def format_size_value(value: str) -> str:
    num_bytes = parse_size_to_bytes(value)
    return format_size_bytes(num_bytes)


def _extract_field_value(out: str, field_names: tuple[str, ...]) -> str:
    for line in out.splitlines():
        key, _, value = line.partition(":")
        if key.strip() in field_names:
            return value.strip()
    return ""


def _select_pacman_info_block(out: str, repo: str = "", local: bool = False) -> str:
    blocks = [block.strip() for block in out.split("\n\n") if block.strip()]
    if not blocks:
        return ""

    if not repo:
        return blocks[0]

    repo_keys = ("Installed From",) if local else ("Repository",)
    normalized_repo = repo.strip().lower()
    for block in blocks:
        block_repo = _extract_field_value(block, repo_keys).strip().lower()
        if block_repo == normalized_repo:
            return block
    return blocks[0]


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


def normalize_search_query(query: str) -> str:
    compact = " ".join(str(query or "").strip().split())
    return compact.replace(" ", "-")


def build_search_terms(query: str) -> list[str]:
    normalized = normalize_search_query(query).lower()
    if not normalized:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        value = term.strip().lower()
        if value and value not in seen:
            seen.add(value)
            terms.append(value)

    add(normalized)
    tokens = [token for token in re.split(r"[-\s]+", normalized) if token]

    if len(tokens) > 1:
        if len(tokens) <= 4:
            for token_order in itertools.permutations(tokens):
                add("-".join(token_order))
        else:
            add("-".join(tokens))
            add("-".join(reversed(tokens)))

    return terms


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
        if line.startswith("Repository") or (local and line.startswith("Installed From")):
            _, _, repo = line.partition(":")
            return repo.strip().lower()
    return ""


@lru_cache(maxsize=4096)
def get_pacman_package_size_info(pkg_name: str, repo: str = "", local: bool = False) -> dict[str, str | int | None]:
    target = f"{repo}/{pkg_name}" if repo and not local else pkg_name
    cmd = ["pacman", "-Qi" if local else "-Si", target]
    try:
        out = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {
            "download_size": "",
            "download_size_bytes": None,
            "installed_size": "",
            "installed_size_bytes": None,
        }

    block = _select_pacman_info_block(out, repo=repo, local=local)
    download_size_bytes = parse_size_to_bytes(_extract_field_value(block, ("Download Size",)))
    installed_size_bytes = parse_size_to_bytes(_extract_field_value(block, ("Installed Size",)))
    return {
        "download_size": format_size_bytes(download_size_bytes),
        "download_size_bytes": download_size_bytes,
        "installed_size": format_size_bytes(installed_size_bytes),
        "installed_size_bytes": installed_size_bytes,
    }


def get_pacman_update_size_info(pkg_name: str, repo: str = "") -> dict[str, str | int | None]:
    remote_info = get_pacman_package_size_info(pkg_name, repo=repo, local=False)
    local_info = get_pacman_package_size_info(pkg_name, local=True)

    old_installed_size_bytes = local_info.get("installed_size_bytes")
    new_installed_size_bytes = remote_info.get("installed_size_bytes")
    size_change_bytes = None
    if old_installed_size_bytes is not None and new_installed_size_bytes is not None:
        size_change_bytes = int(new_installed_size_bytes) - int(old_installed_size_bytes)

    return {
        **remote_info,
        "size_change": format_size_delta(size_change_bytes),
        "size_change_bytes": size_change_bytes,
        "old_installed_size": format_size_bytes(old_installed_size_bytes),
        "old_installed_size_bytes": old_installed_size_bytes,
        "new_installed_size": remote_info.get("installed_size", "N/A"),
        "new_installed_size_bytes": new_installed_size_bytes,
    }


def get_pacman_updates(
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
        pkg.update(get_pacman_update_size_info(pkg["name"], repo=repo))

        if not is_repo_allowed(repo, include_repos, exclude_repos):
            ignored_packages.append(pkg["name"])
            continue

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
        self.query = normalize_search_query(query)
        self.queries = build_search_terms(query) or [self.query.lower()]
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
        deduped: dict[tuple[str, str, str], dict] = {}
        for query in self.queries:
            try:
                out = subprocess.check_output(
                    ["pacman", "-Ss", query],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                continue

            results = self._parse_pacman_output(out, "pacman")
            for pkg in results:
                if not is_repo_allowed(
                    pkg.get("repo", ""),
                    self.include_pacman_repos,
                    self.exclude_pacman_repos,
                ):
                    continue
                key = (pkg.get("source", ""), pkg.get("repo", ""), pkg.get("name", ""))
                deduped.setdefault(key, pkg)
        return list(deduped.values())

    def _search_aur(self) -> list:
        deduped: dict[tuple[str, str, str], dict] = {}
        installed = self._get_installed_names()
        try:
            from urllib.request import urlopen, Request as _Request
            import json as _json
            for query in self.queries:
                url = f"https://aur.archlinux.org/rpc/v5/search/{query}"
                req = _Request(url, headers={"User-Agent": "xpak"})
                with urlopen(req, timeout=15) as resp:
                    data = _json.loads(resp.read().decode())

                for pkg in data.get("results", []):
                    name = pkg.get("Name", "")
                    key = ("aur", "aur", name)
                    deduped.setdefault(
                        key,
                        {
                            "name": name,
                            "version": pkg.get("Version", ""),
                            "description": pkg.get("Description", "") or "",
                            "source": "aur",
                            "repo": "aur",
                            "installed": name in installed,
                            "votes": str(pkg.get("NumVotes", 0)),
                            "download_size": "N/A",
                            "download_size_bytes": None,
                        },
                    )
            return list(deduped.values())
        except Exception:
            # Fallback to yay CLI (votes will be unavailable)
            for query in self.queries:
                try:
                    out = subprocess.check_output(
                        ["yay", "-Ssa", "--aur", query],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    )
                except subprocess.CalledProcessError:
                    continue

                for pkg in self._parse_pacman_output(out, "aur"):
                    key = (pkg.get("source", ""), pkg.get("repo", ""), pkg.get("name", ""))
                    deduped.setdefault(key, pkg)
            return list(deduped.values())

    def _search_flatpak(self) -> list:
        deduped: dict[tuple[str, str], dict] = {}
        for query in self.queries:
            try:
                out = subprocess.check_output(
                    ["flatpak", "search", "--columns=application,name,version,description", query],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                continue

            for line in out.strip().splitlines()[1:]:  # skip header
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                app_id = parts[0].strip()
                key = ("flatpak", app_id)
                deduped.setdefault(
                    key,
                    {
                        "name": parts[1].strip() if len(parts) > 1 else app_id,
                        "app_id": app_id,
                        "version": parts[2].strip() if len(parts) > 2 else "",
                        "description": parts[3].strip() if len(parts) > 3 else "",
                        "source": "flatpak",
                        "repo": "flatpak",
                        "installed": self._is_flatpak_installed(app_id),
                        "votes": "",
                        "download_size": "N/A",
                        "download_size_bytes": None,
                    },
                )
        return list(deduped.values())

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
            repo = repo_name.split("/")[0] if "/" in repo_name else source
            results.append(
                {
                    "name": name,
                    "version": version,
                    "description": desc,
                    "source": source,
                    "installed": installed,
                    "repo": repo,
                    "votes": "",
                    **(get_pacman_package_size_info(name, repo=repo, local=False) if source == "pacman" else {
                        "download_size": "N/A",
                        "download_size_bytes": None,
                    }),
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
                ["pacman", "-Qi"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pkgs = []
            current = {}

            def finalize_package() -> None:
                name = current.get("name", "").strip()
                if not name:
                    return

                repo = current.get("repo", "").strip().lower()
                if not is_repo_allowed(
                    repo,
                    self.include_pacman_repos,
                    self.exclude_pacman_repos,
                ):
                    return

                pkgs.append(
                    {
                        "name": name,
                        "version": current.get("version", "").strip(),
                        "source": "pacman",
                        "repo": repo,
                        "description": current.get("description", "").strip(),
                        "installed_size": format_size_value(current.get("installed_size", "")),
                        "installed_size_bytes": parse_size_to_bytes(current.get("installed_size", "")),
                    }
                )

            for raw_line in out.splitlines():
                line = raw_line.rstrip()
                if not line:
                    finalize_package()
                    current = {}
                    continue

                key, _, value = line.partition(":")
                normalized_key = key.strip()
                normalized_value = value.strip()
                if normalized_key == "Name":
                    current["name"] = normalized_value
                elif normalized_key == "Version":
                    current["version"] = normalized_value
                elif normalized_key == "Description":
                    current["description"] = normalized_value
                elif normalized_key == "Installed From":
                    current["repo"] = normalized_value
                elif normalized_key == "Installed Size":
                    current["installed_size"] = normalized_value

            finalize_package()
            return pkgs
        except Exception:
            return []

    def _list_flatpak(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "list", "--app", "--columns=application,name,version,size"],
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
                            "installed_size": format_size_value(parts[3].strip() if len(parts) > 3 else ""),
                            "installed_size_bytes": parse_size_to_bytes(parts[3].strip() if len(parts) > 3 else ""),
                        }
                    )
            return pkgs
        except Exception:
            return []


class UpdateChecker(QThread):
    updates_ready = pyqtSignal(list)

    def __init__(
        self,
        include_pacman_repos: list[str] | None = None,
        exclude_pacman_repos: list[str] | None = None,
    ):
        super().__init__()
        self.include_pacman_repos = _normalize_repo_filters(include_pacman_repos)
        self.exclude_pacman_repos = _normalize_repo_filters(exclude_pacman_repos)

    def run(self):
        results = []
        tasks = []
        logger.info("UpdateChecker starting")
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
            include_repos=self.include_pacman_repos,
            exclude_repos=self.exclude_pacman_repos,
        )
        return updates

    def _check_flatpak_updates(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "remote-ls", "--updates", "--columns=application,name,version,download-size"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if parts and parts[0]:
                    pkgs.append(
                        {
                            "app_id": parts[0].strip(),
                            "name": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                            "old_version": "",
                            "new_version": parts[2].strip() if len(parts) > 2 else "",
                            "source": "flatpak",
                            "repo": "flatpak",
                            "download_size": format_size_value(parts[3].strip() if len(parts) > 3 else ""),
                            "download_size_bytes": parse_size_to_bytes(parts[3].strip() if len(parts) > 3 else ""),
                            "size_change": "N/A",
                            "size_change_bytes": None,
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
