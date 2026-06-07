# pyle

**Python Lite Explorer** — interactive disk usage explorer with a curses-based TUI. A faster, more visual alternative to `ncdu`. Part of the [Pynosaur](https://pynosaur.org) ecosystem.

Browse directories sorted by size with color-coded bars, navigate with arrow keys, and drill into subdirectories instantly.

## Install

```bash
pget install pyle
```

## Usage

```bash
pyle                    # Explore current directory
pyle /usr               # Explore /usr
pyle ~/Documents        # Explore Documents
pyle --help
pyle --version
```

## Keybindings

| Key | Action |
|-----|--------|
| `↑` / `k` | Move cursor up |
| `↓` / `j` | Move cursor down |
| `→` / `l` / `Enter` | Open directory |
| `←` / `h` | Go to parent directory |
| `PgUp` / `PgDn` | Page up / down |
| `g` / `G` | Jump to first / last entry |
| `s` | Toggle sort: size (default) / name |
| `b` | Toggle bubble (treemap) view |
| `d` | Delete selected entry (confirms first) |
| `r` | Refresh / rescan current directory |
| `q` / `Esc` | Quit |

## Display

Each entry shows:

```
   SIZE  PCTG  [########          ]  filename
  1.2M  45.2%  [#########         ]  node_modules/
 256.0K  9.8%  [##                ]  src/
  12.0K  0.5%  [                  ]  README.md
```

- **Size**: human-readable (B, K, M, G, T)
- **Percentage**: proportion of parent directory total
- **Bar**: visual ratio — green (small), yellow (medium), red (large)
- **Name**: blue for directories, cyan for symlinks, red `[!]` for errors

## Features

- **Fast browsing**: scan once, navigate instantly
- **Color coded**: size bars shift green → yellow → red
- **Vim keys**: `hjkl` navigation plus arrow keys
- **Delete**: remove files/dirs with `d` + confirmation
- **Sort toggle**: switch between size and name ordering
- **Cross-platform**: macOS and Linux (Windows with windows-curses)

## Build

```bash
bazel build //:pyle_bin
```

## Tests

```bash
python test/test_main.py
```

## License

MIT
