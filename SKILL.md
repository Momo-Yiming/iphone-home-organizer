---
name: iphone-home-organizer
description: Read a connected iPhone home-screen layout, organize apps by function and use, preview pages and folders, then back up, apply, and verify an approved layout. Use for SpringBoard icon or Dock organization; do not use for installing apps or changing their data.
---

# iPhone home-screen organizer

Use this skill for a specific connected device. Keep every person's snapshots, usage evidence, icons, previews, and backups in a separate local work directory with private file permissions. Do not put their data inside this skill or a shared repository.

Run `scripts/layout.py --help` for exact commands. It needs Python with `pymobiledevice3`; Pillow is optional for smaller icon previews. Install missing libraries in a project virtual environment from the Python package registry. On macOS, use the device's trusted USB connection. The helper is read-only except `apply` and `restore`.

## Workflow

1. `snapshot --out DIR` reads the USB device, its actual grid metrics, and a native binary plist. If multiple devices are connected, use `--udid` to select the intended one. `inventory --dir DIR` writes a JSON list of the icons actually on the home screen, including repeated entries and original locations. Use `icons --dir DIR` when real app images improve the preview; it only reads the phone.
2. Determine each app's function from its name, existing folder, and when needed public app descriptions. Usage frequency requires evidence supplied by the user, such as Screen Time screenshots or a local `usage.json` keyed by app identifier. The optional JSON shape is `{ "bundle.id": { "minutes": 45, "pickups": 3 } }`; omit unknown metrics. iOS SpringBoard does not provide Screen Time. Mark unobserved use as unknown, never zero. Give function and observed frequency higher weight than icon color. Explicit user placement overrides all three.
3. `draft --dir DIR` produces `plan.json` matching the current layout, which can be edited into the proposed pages. The format uses app identifiers, ordered `dock`, and ordered `pages[].items`: `{ "app": "identifier" }`, `{ "folder": "name", "apps": ["identifier", ...] }`, or `{ "empty": true }`. Dock entries can be identifier strings or folder objects. Repeat an identifier exactly as many times as shown by inventory when preserving duplicate icons. Use separate function folders and a few direct apps on each page when that suits the user; do not impose the previous person's categories or Dock.
4. `prepare --dir DIR --plan DIR/plan.json` checks every original icon record, per-app entry counts, folder size, page capacity, and Dock capacity against the device metrics. It writes `proposed.plist`, `review.json`, and a self-contained interactive `preview.html` fragment. Present the preview and incorporate corrections. If the `visualize` skill is available, use it to show the fragment inline; otherwise render it locally and inspect its interactions. The preview is a proposal, not a device write.
5. `apply --dir DIR --approved-sha SHA256` is for a user-approved proposal only. The SHA comes from the current `review.json` and binds the actual proposed plist. Right before writing, it checks device identity and unchanged layout, takes another verified binary backup, sends `setIconState` once, reconnects, and saves actual readbacks. Treat a command send as pending until readback proves the result. Inspect `write-*/verification.json` and the real home screen. If iOS reintroduces previously absent apps, preserve and classify them, then prepare and review the adjusted proposal. Do not silently discard them or loop writes. iOS may compact requested blank cells.
6. `restore --dir DIR --backup PATH --approved` sends a saved native plist only after the user asks to restore it. It also makes a fresh backup and verifies the readback. The presence of a backup alone does not prove restoration has been tested.

Every new write or restore needs authorization for that device and layout. An earlier person's approval never carries to another phone. Do independent read-only work while waiting for a decision.

The helper matches folders using `listType == "folder"`: some duplicate app records have an empty `iconLists` but are still apps. Preserve the original plist records rather than reconstructing only bundle IDs; this retains web clips, dates, and duplicate icon UUIDs. `getIconState` format 2 does not faithfully carry iOS 18+ free placement or widgets, so state that limit when it affects the proposal.

For implementation and sources, IconState's [device code](https://github.com/Jubstaaa/iconstate/blob/main/app/src-tauri/src/device.rs) documents the command framing and separate readback connection, and its [README](https://github.com/Jubstaaa/iconstate#what-the-device-will-and-will-not-do) records known SpringBoard limits.
