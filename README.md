# iPhone Home Screen Organizer / iPhone 桌面整理

A Codex agent skill for reading an iPhone home-screen layout over a trusted USB connection, preparing a function- and usage-based arrangement, previewing it, and applying an approved layout with a backup and readback check.

这是一个整理 iPhone 桌面图标的 Codex Skill：读取布局、按功能及使用频率拟定方案、交互预览，并在用户批准后备份、写入、回读核验。

## Install / 安装

```sh
npx skills add Momo-Yiming/iphone-home-organizer
```

The helper requires Python and `pymobiledevice3`; Pillow is optional for smaller preview images. See [SKILL.md](SKILL.md) for the workflow and `python3 scripts/layout.py --help` for commands.

辅助脚本依赖 Python 和 `pymobiledevice3`；Pillow 仅用于缩小预览图标。完整操作流程见 [SKILL.md](SKILL.md)。

## Privacy and device limits / 隐私与设备限制

- Keep each person's snapshots, usage records, app icons, plans, previews, and backups in a private directory **outside this repository**. This repository contains no device-specific data.
- Screen Time usage cannot be read from SpringBoard; provide observed usage separately. Unknown usage is not zero.
- `snapshot`, `inventory`, `icons`, `draft`, and `prepare` do not change the phone. `apply` and `restore` require specific user approval and save a backup before writing.
- iOS 18+ free placement and widgets are not faithfully represented by SpringBoard icon-state format 2. Preview and verify the real device, especially after a write.

将每个人的快照、使用记录、图标、方案、预览和备份保存在**仓库外的私有目录**。读取与预览命令不会改动手机；写入及恢复须得到该设备使用者的明确批准。iOS 18 及以上的自由摆放与小组件无法由此格式完整表达，写入后应核对真机。

## References / 参考

[IconState device implementation](https://github.com/Jubstaaa/iconstate/blob/main/app/src-tauri/src/device.rs) documents the SpringBoard command framing; see its [README](https://github.com/Jubstaaa/iconstate) for known device behavior.
