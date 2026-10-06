# Troubleshooting

| Symptom | What to check |
| --- | --- |
| `python` is not found | Install Python 3.11+; on Windows try `py -3`, on macOS/Linux try `python3`. Check the reported version. |
| `No module named home` | Run from the extracted folder containing `home/`, or use the Python environment where you installed the package. |
| `tomllib` is missing | The selected interpreter is older than Python 3.11. Check its version. |
| Browser cannot connect | Keep the server terminal running. Restart with the same data directory and `--open`. |
| Local page opens but is unauthorized | Use the current private launch URL printed by the server, or restart with `--open`. Bare localhost navigation is not a fresh login. |
| Port is already in use | Add `--port 8788` or `--port 0`. |
| Another Home owns the data | Stop the other Home process cleanly. Use a different data directory for a separate town. |
| Configuration workspace does not exist | `workspace` is resolved relative to the TOML file. Point it to an existing directory. |
| Native executable cannot start | Check `Get-Command claude,codex` in PowerShell or `command -v claude codex` in a POSIX shell. Set the actual executable path in the TOML. |
| Command is found, but Home rejects it | Windows `.cmd`/`.bat` wrappers are unsupported. Configure the directly executable binary, typically `.exe`. |
| Native reply fails despite a visible resident | A configured binding does not prove sign-in, network access or available quota. Test the provider CLI directly in the configured workspace. |
| Demo homes appear in native mode | Both modes share a default data directory. Use the guide's separate `.demo-data` and `.home-data` directories. Existing history is preserved. |
| Add/move out/bring back is unavailable | Wait for active calls and owned process shutdown to finish. A full town also needs a free slot. |
| Resume is disabled | Review the explanation. Uncertain calls are not safe to repeat automatically; a new message can continue from saved work. |
| A revision will not save | Keep your edited text, reload the latest saved version and compare it before saving. A version conflict must preserve earlier work. |

## Reporting a problem

Include your operating system, Python version, application revision, demo/native mode, the action that failed and the safe error summary. State whether it reproduces with the public demo.

Remove private paths, prompts, transcripts, account details, native session IDs and launch URLs before sharing screenshots or logs. A provider's raw output can contain private data. Reproduce with a small synthetic draft when possible.

For recovery behavior, see the [user guide](USING.md#stop-and-recover). For data locations and backups, see [privacy and data](PRIVACY.md).
