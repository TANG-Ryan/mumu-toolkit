# MuMu 复用工具包 v2

面向 Windows x64 与 MuMu 的离线安装资料包。包含明确选取的应用、两份本地兼容修复、中文离线手册、逐文件 SHA-256 校验及可选 APK 安装助手。

[下载完整资源包](https://github.com/TANG-Ryan/mumu-toolkit/releases/latest) · [GitHub 仓库](https://github.com/TANG-Ryan/mumu-toolkit)

请从 Releases 下载成品 ZIP；GitHub 自动生成的 Source code ZIP 只包含源码与说明。

**解压后先运行 `START.cmd`，选择校验，再按安装手册逐项操作。** 软件与修复版本、来源及验证范围均以 `metadata` 中本次构建的清单为准。

## 当前范围

本次按要求仅整理、校验和发布安装包，没有进行模拟器升级或本轮应用运行验证。历史修复结果与本次文件校验分别记录。

默认应用为微信、高德地图、步道乐跑和 LocationSpoofer 网络修复版；附 MuMu 官方 Windows 安装器与 bszip 离线修复 ZIP。不包含百度地图、旧版应用、旧版模块、用户账号、路线、实例镜像或授权数据库。

本版收录：微信 8.0.80、高德地图 17.03.0.2008、步道乐跑 4.3.3、LocationSpoofer 2.6.13 网络修复版、bszip v.02.00-offline.2，以及 MuMu 官方在线安装器。MuMu 稳定应用通道为 6.8.8，在线安装器自身不是完整离线引擎。

LocationSpoofer 修复版仍显示 2.6.13，使用本地修复签名。以 APK 哈希区分原版与修复版。已有原版无法直接保留数据覆盖，安装助手会停止并引导备份迁移。

微信最新版在本机 Android 15 环境中曾出现媒体线程崩溃。包内保留实际兼容性检查结果；“最新版”“安装成功”和“运行稳定”分别记录。

## 文件与入口

- `START.cmd`：打开手册、校验资料包、选择一个 APK 安装。
- `00_开始阅读.html`：无需联网的阅读入口。
- `docs/安装与迁移.md`：新实例安装、已有数据迁移、模块及联网检查。
- `metadata/apps.json`：安装助手使用的应用清单。
- `metadata/assets.json`：所有分发文件的版本、来源、签名证书与哈希。
- `metadata/validation.json`：本次实际验证及未完成事项。
- `metadata/manifest.json`：固定分发文件的大小与 SHA-256。

## 源码与构建

源码仓库只保存说明、工具、测试与构建代码。APK、Windows 安装器和成品 ZIP 通过发布附件交付，不提交到 Git 历史。

构建需要 Python 3.11+；使用安装包只需 Windows PowerShell 5.1。构建器从明确指定的素材清单读取文件，验证哈希与版本字段，只复制允许的文件。输出目录必须是尚不存在的新目录。

```powershell
python scripts/build.py --assets ../assets.json --validation ../validation.json --fixed-bszip ../downloads/bszip-v2.00-offline-fix.zip --fixed-location ../downloads/LocationSpoofer_2.6.13_network_fix.apk --output ../dist/MuMu复用包_v2
python scripts/build.py --verify ../dist/MuMu复用包_v2 --archive
python tests/test_installer.py --pack ../dist/MuMu复用包_v2
```

`--archive` 仅在验证记录允许发布时生成 ZIP，并重新读取 ZIP 中每一项核验 CRC、大小和 SHA-256。发布附件同时提供 ZIP 的 SHA-256 文件。修改素材后必须重新构建，不能沿用旧清单。
