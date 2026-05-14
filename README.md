# VoidErase(r)

A Python GUI tool to format multiple external drives and memory cards at once.

## Requirements

- Python 3.7+
- No external libraries needed

## Run

**Windows** — run as Administrator:
```bash
python format_drives.py
```

**macOS / Linux:**
```bash
sudo python3 format_drives.py
```

## How to use

1. Open the app — it detects all connected external drives
2. Select the drives you want to format
3. Pick a filesystem (exFAT recommended for memory cards)
4. Click **Format Selected Drives** and confirm

> ⚠️ This permanently erases all data on selected drives. There is no undo.

## License

MIT
