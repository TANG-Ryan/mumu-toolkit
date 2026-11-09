"""Build a curated distribution. Binaries stay outside the public source tree."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "README.md", "START.cmd", "docs/安装与迁移.md", "docs/修复来源.md",
    "tools/Common.ps1", "tools/Install-APK.ps1", "tools/Start.ps1",
    "scripts/build.py", "tests/FakeAdb.cs", "tests/test_installer.py", "THIRD_PARTY_NOTICES.md",
)
REQUIRED_IDS = {"wechat_android", "amap_android", "lepao_android", "mumu_windows"}
FIXED_BSZIP = "3b4fc7cd05c000a30572a29cbc5dc277c9880f61ade44b7989a9fba1d7b522a1"
FIXED_LOCATION = "cc8bc5dd0ecefc77180a9426e5a07bde066e4923ff439c2dbc78a3b36eed2231"
FIXED_CERT = "bfb43c8267e9155375e2d0ad009565d044ecd350ebe84fadcab5851416d1bc79"


def sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_relative(text: str) -> str:
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in text or ":" in text:
        raise ValueError(f"invalid relative package path: {text!r}")
    return path.as_posix()


def normalized_asset(raw: dict, base: Path) -> tuple[dict, Path]:
    asset = dict(raw)
    file_value = asset.pop("file", asset.pop("download_path", None))
    if not file_value:
        raise ValueError("asset missing file")
    source = (base / file_value).resolve() if not Path(file_value).is_absolute() else Path(file_value).resolve()
    if not source.is_file():
        raise ValueError(f"asset not ready: {asset.get('id')}")
    expected = str(asset.get("sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha(source) != expected:
        raise ValueError(f"asset hash mismatch: {asset.get('id')}")
    asset["sha256"] = expected
    asset["bytes"] = source.stat().st_size
    asset["kind"] = asset.get("kind") or ("apk" if source.suffix.lower() == ".apk" else "windows_installer")
    if asset["kind"] == "exe":
        asset["kind"] = "windows_installer"
    asset["version"] = str(asset.get("version", asset.get("version_name", "")))
    if not asset.get("id") or not asset.get("name") or not asset["version"]:
        raise ValueError("asset missing id/name/version")
    if not asset.get("source_url") and not asset.get("source_urls"):
        raise ValueError(f"source URL required: {asset['id']}")
    if asset["kind"] == "apk":
        certs = asset.get("certificate_sha256", asset.get("certificate_sha256s", []))
        if isinstance(certs, str):
            certs = [certs]
        certs = sorted(set(str(c).lower().replace(":", "") for c in certs))
        if not certs or not all(re.fullmatch(r"[0-9a-f]{64}", c) for c in certs):
            raise ValueError(f"certificate hashes required: {asset['id']}")
        asset["certificate_sha256"] = certs
        asset["version_code"] = int(asset["version_code"])
        asset["min_sdk"] = int(asset["min_sdk"])
        asset["abis"] = list(asset.get("abis", []))
        if not re.fullmatch(r"[A-Za-z]\w*(?:\.[A-Za-z]\w*)+", asset.get("package", "")):
            raise ValueError("invalid APK package")
        destination = f"materials/apps/{asset['id']}_{asset['version']}.apk"
    elif asset["kind"] == "windows_installer":
        destination = f"materials/windows/{asset['id']}_{asset['version']}.exe"
    else:
        raise ValueError(f"unsupported downloaded asset kind: {asset['kind']}")
    asset["path"] = safe_relative(destination)
    # Explicit metadata allow-list prevents private local paths/working files leaking into a release.
    fields = ("id", "name", "kind", "package", "version", "version_code", "min_sdk", "target_sdk", "abis",
              "certificate_sha256", "sha256", "bytes", "path", "source_url", "source_urls", "download_url",
              "retrieved_at", "source_chain", "redistributable", "compatibility_note", "signature_verified",
              "authenticode", "publisher", "notes")
    return {key: asset[key] for key in fields if key in asset}, source


def public_validation(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("schema_version") != 1 or not isinstance(value.get("checks"), list):
        raise ValueError("validation requires schema_version=1 and checks[]")
    fields = ("schema_version", "checked_at", "release_ready", "summary", "checks", "known_limitations")
    public = {key: value[key] for key in fields if key in value}
    encoded = json.dumps(public, ensure_ascii=False)
    if re.search(r"[A-Za-z]:[\\/]", encoded) or "AppData" in encoded or "-----BEGIN" in encoded:
        raise ValueError("validation contains local paths or private-key data; provide a public summary")
    for check in public["checks"]:
        if check.get("status") not in {"passed", "failed", "not_tested", "blocked"}:
            raise ValueError("invalid validation status")
        if not check.get("id") or not check.get("detail"):
            raise ValueError("validation checks require id/detail")
    return public


def release_gate(value: dict) -> None:
    if value.get("release_ready") is not True:
        raise ValueError("validation.release_ready must be explicitly true before creating release ZIP")
    for check in value["checks"]:
        if check["status"] in {"failed", "blocked"} and not check.get("mitigation"):
            raise ValueError(f"unaddressed validation failure: {check['id']}")
        if check.get("requires_rollback") and check.get("rollback_verified") is not True:
            raise ValueError(f"rollback not verified: {check['id']}")


def make_html(output: Path, assets: list[dict], validation: dict) -> None:
    sections = []
    for rel in ("README.md", "docs/安装与迁移.md", "docs/修复来源.md"):
        body = (output / rel).read_text(encoding="utf-8-sig")
        sections.append("<section><pre>" + html.escape(body) + "</pre></section>")
    rows = "".join("<tr>" + "".join("<td>" + html.escape(str(a.get(k, ""))) + "</td>" for k in ("name", "version", "kind", "path")) + "</tr>" for a in assets)
    checks = "".join("<tr>" + "".join("<td>" + html.escape(str(c.get(k, ""))) + "</td>" for k in ("id", "status", "detail", "mitigation")) + "</tr>" for c in validation["checks"])
    page = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MuMu 复用工具包 v2</title>
<style>body{margin:0;background:#eef3f7;color:#182737;font:16px/1.7 'Microsoft YaHei',sans-serif}main{max-width:1100px;margin:auto;padding:32px 20px}header,section{background:white;padding:28px;border-radius:16px;margin:0 0 20px}h1{margin-top:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d6e0e9;padding:10px;text-align:left;overflow-wrap:anywhere}a{color:#076aaa}.scroll{overflow-x:auto}@media(max-width:600px){main{padding:16px 10px}header,section{padding:18px}table{min-width:620px}}</style><main><header><h1>MuMu 复用工具包 v2</h1><p>完整解压 → START.cmd 校验 → 阅读安装与迁移 → 逐项安装与验证</p><a href="docs/安装与迁移.md">打开文本手册</a> · <a href="metadata/validation.json">本次验证记录</a></header>"""
    page += "<section><h2>本次实际文件</h2><div class=scroll><table><tr><th>名称</th><th>版本</th><th>类型</th><th>位置</th></tr>" + rows + "</table></div></section>"
    page += "<section><h2>验证与限制</h2><p>" + html.escape(validation.get("summary", "")) + "</p><div class=scroll><table><tr><th>项目</th><th>状态</th><th>事实</th><th>处理</th></tr>" + checks + "</table></div></section>"
    page += "".join(sections) + "</main></html>"
    (output / "00_开始阅读.html").write_text(page, encoding="utf-8")


def create_manifest(output: Path) -> dict:
    entries = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.relative_to(output).as_posix() != "metadata/manifest.json":
            entries.append({"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    value = {"schema_version": 2, "version": "2", "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
             "scope": "Fixed distribution files; manifest excluded from its own digest", "files": entries}
    write_json(output / "metadata/manifest.json", value)
    return value


def verify(output: Path) -> dict:
    manifest = json.loads((output / "metadata/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2:
        raise ValueError("unsupported manifest")
    expected = {}
    for entry in manifest["files"]:
        rel = safe_relative(entry["path"])
        if rel in expected:
            raise ValueError("duplicate manifest entry")
        path = output / rel
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha(path) != entry["sha256"]:
            raise ValueError(f"manifest mismatch: {rel}")
        expected[rel] = entry
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if actual != set(expected) | {"metadata/manifest.json"}:
        raise ValueError("unlisted or missing distribution files")
    return manifest


def archive(output: Path) -> dict:
    manifest = verify(output)
    validation = public_validation(output / "metadata/validation.json")
    release_gate(validation)
    target = output.with_suffix(".zip")
    if target.exists() or target.with_suffix(".zip.sha256.txt").exists():
        raise ValueError("archive already exists; choose a new output version")
    expected = {item["path"]: item for item in manifest["files"]}
    expected["metadata/manifest.json"] = {"bytes": (output / "metadata/manifest.json").stat().st_size,
                                          "sha256": sha(output / "metadata/manifest.json")}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for rel in sorted(expected):
            z.write(output / rel, output.name + "/" + rel)
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None or len(z.infolist()) != len(expected):
            raise ValueError("ZIP CRC/count failed")
        for info in z.infolist():
            prefix = output.name + "/"
            if not info.filename.startswith(prefix):
                raise ValueError("ZIP path mismatch")
            rel = safe_relative(info.filename[len(prefix):])
            row = expected[rel]
            with z.open(info) as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            if info.file_size != row["bytes"] or digest != row["sha256"]:
                raise ValueError(f"ZIP mismatch: {rel}")
    digest = sha(target)
    target.with_suffix(".zip.sha256.txt").write_text(digest + "  " + target.name + "\n", encoding="utf-8")
    return {"archive": str(target), "bytes": target.stat().st_size, "sha256": digest,
            "entries_verified": len(expected), "crc_and_file_hashes_verified": True}


def build(args) -> Path:
    output = args.output.resolve()
    if output.exists():
        raise ValueError("output must be a new directory; previous packs remain untouched")
    source = json.loads(args.assets.read_text(encoding="utf-8-sig"))
    raw_assets = source["assets"] if isinstance(source, dict) else source
    assets_and_files = [normalized_asset(a, args.assets.resolve().parent) for a in raw_assets]
    ids = [a["id"] for a, _ in assets_and_files]
    if len(ids) != len(set(ids)) or set(ids) != REQUIRED_IDS:
        raise ValueError("download assets must contain exactly WeChat/AMap/Lepao/MuMu IDs")
    for path, expected in ((args.fixed_bszip, FIXED_BSZIP), (args.fixed_location, FIXED_LOCATION)):
        if not path.is_file() or sha(path) != expected:
            raise ValueError("fixed repair asset missing or hash mismatch")
    validation = public_validation(args.validation)
    fixed_location = {"id": "locationspoofer_network_fix", "name": "LocationSpoofer 网络修复版", "kind": "apk",
                      "package": "com.suseoaa.locationspoofer", "version": "2.6.13", "version_code": 20613,
                      "min_sdk": 26, "target_sdk": 37, "abis": ["arm64-v8a"], "sha256": FIXED_LOCATION,
                      "certificate_sha256": [FIXED_CERT], "bytes": args.fixed_location.stat().st_size,
                      "path": "materials/apps/LocationSpoofer_2.6.13_network_fix.apk",
                      "source_url": "docs/修复来源.md", "redistributable": None,
                      "compatibility_note": "本地修复签名；已有原版须备份迁移。保持 Wi-Fi/基站模拟关闭。"}
    fixed_module = {"id": "bszip_offline_fix", "name": "bszip 离线修复", "kind": "module_zip", "version": "v.02.00-offline.2",
                    "sha256": FIXED_BSZIP, "bytes": args.fixed_bszip.stat().st_size,
                    "path": "materials/modules/bszip-v2.00-offline-fix.zip", "source_url": "docs/修复来源.md",
                    "redistributable": None, "compatibility_note": "MuMu Android15 x86_64/KernelSU3.2.5实测；ARM64 Keymint不适用。"}
    assets_and_files += [(fixed_location, args.fixed_location), (fixed_module, args.fixed_bszip)]
    assets = [a for a, _ in assets_and_files]
    # Everything above is validated before the new distribution is created.
    output.mkdir(parents=True)
    for rel in SOURCE_FILES:
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() in {".ps1", ".cmd"}:
            text = (REPO / rel).read_text(encoding="utf-8-sig")
            target.write_text(text, encoding="utf-8-sig" if target.suffix == ".ps1" else "ascii", newline="\r\n")
        else:
            shutil.copy2(REPO / rel, target)
    for asset, path in assets_and_files:
        target = output / asset["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if sha(target) != asset["sha256"]:
            raise ValueError("copied asset hash mismatch")
    write_json(output / "metadata/assets.json", {"schema_version": 1, "assets": assets})
    write_json(output / "metadata/apps.json", [a for a in assets if a["kind"] == "apk"])
    write_json(output / "metadata/validation.json", validation)
    make_html(output, assets, validation)
    manifest = create_manifest(output)
    verify(output)
    print(json.dumps({"distribution": str(output), "assets": len(assets), "fixed_files": len(manifest["files"]), "verified": True}, ensure_ascii=False))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--fixed-bszip", type=Path)
    parser.add_argument("--fixed-location", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()
    if args.verify:
        output = args.verify.resolve()
        value = verify(output)
        print(json.dumps({"verified": True, "files": len(value["files"])}))
    else:
        if not all((args.assets, args.validation, args.fixed_bszip, args.fixed_location, args.output)):
            parser.error("building requires --assets --validation --fixed-bszip --fixed-location --output")
        output = build(args)
    if args.archive:
        print(json.dumps(archive(output), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
        sys.exit(str(error))
