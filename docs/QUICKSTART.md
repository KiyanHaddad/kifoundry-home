# Getting started

The application runs a local Python server and opens in your browser. There is no Node.js requirement for ordinary use and no desktop installer yet.

## 1. Get the source

On the repository page, choose **Code → Download ZIP**. Extract the ZIP before running anything. Open a terminal in the extracted folder that contains `README.md`, `pyproject.toml` and `home/`.

If you use Git, cloning gives the same application source. After a future repository rename, use the current repository URL and extracted folder name; commands below run from that folder.

## 2. Check Python

Use Python **3.11 or newer**:

```sh
python --version
```

On Windows, use `py -3` instead of `python` if that is how Python is installed, and confirm it reports 3.11 or newer. On macOS/Linux, the command may be `python3`. Keep using the same interpreter throughout setup.

## 3. Open the offline demo

From the source folder:

```sh
python -m home.cli --demo --data-dir .demo-data --open
```

The browser opens the town. Choose Echo's house, type a greeting and send it. The reply is a labelled fixture: scripted text used to demonstrate the controls. No provider account or AI usage is involved.

Keep the terminal running while using the town. To stop the server, return to that terminal and press **Ctrl+C**. Closing the browser alone does not stop it.

Run the same command to return to the same demo conversations. Use a separate directory when connecting real providers so demo and native residents do not mix.

## Optional: install into a virtual environment

Running directly from source is enough to try it. An isolated installation also provides the `kifoundry-home` command.

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\kifoundry-home.exe --demo --data-dir .demo-data --open
```

**macOS/Linux**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/kifoundry-home --demo --data-dir .demo-data --open
```

Installation may download Python build tools. Ordinary runtime has no third-party Python dependencies. For code changes after an installed copy was created, reinstall it or run from source.

## 4. Connect real providers

Follow [provider setup](PROVIDERS.md), then start with the local configuration and a separate data directory:

```sh
python -m home.cli --config local-config.toml --data-dir .home-data --open
```

The native providers consume your account's usage. Begin with a single resident and a short greeting before running a Council.

## Data and launch options

| Option | Meaning |
| --- | --- |
| `--demo` | Scripted residents, no AI calls |
| `--config local-config.toml` | Real providers configured in that local file |
| `--data-dir PATH` | Folder containing `home.sqlite`; reuse it to continue |
| `--port 8788` | Select another port if the default `8787` is occupied |
| `--port 0` | Let the operating system choose an available port |
| `--open` | Open the authenticated local launch in your browser |

Without `--data-dir`, Windows uses `%LOCALAPPDATA%\KiFoundryHome`; macOS/Linux uses `$XDG_DATA_HOME/kifoundry-home`, or `~/.local/share/kifoundry-home` when XDG is unset. Demo and native mode currently share that default, so the examples use separate explicit directories.

If the browser does not open, use the **private local launch URL** printed in the terminal. It works once. Reloading the authenticated tab retains its private proof. For a new tab after that token was consumed, stop/restart Home with the same data directory and use its fresh launcher. A bare `localhost` address does not establish a new session. Do not share launch URLs.

Next: [use conversations and saved work](USING.md), [back up your data](PRIVACY.md), or [fix a setup problem](TROUBLESHOOTING.md).
