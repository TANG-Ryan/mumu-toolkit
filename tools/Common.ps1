$ErrorActionPreference = 'Stop'
$script:PackRoot = Split-Path -Parent $PSScriptRoot

function Get-PackPath([string]$RelativePath) {
    if ([IO.Path]::IsPathRooted($RelativePath)) { throw '清单出现绝对路径。' }
    $base = [IO.Path]::GetFullPath($script:PackRoot) + [IO.Path]::DirectorySeparatorChar
    $full = [IO.Path]::GetFullPath((Join-Path $script:PackRoot $RelativePath))
    if (-not $full.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { throw '清单路径越出资料包。' }
    return $full
}

function Get-PackSha256([string]$Path) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

function Test-Pack {
    $manifest = Get-Content -LiteralPath (Get-PackPath 'metadata/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema_version -ne 2 -or @($manifest.files).Count -eq 0) { throw '资料包清单格式无效。' }
    foreach ($item in $manifest.files) {
        $path = Get-PackPath $item.path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('缺少文件：' + $item.path) }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$item.bytes -or (Get-PackSha256 $path) -cne $item.sha256.ToLowerInvariant()) {
            throw ('文件校验不符：' + $item.path)
        }
    }
    Write-Host ('校验通过：' + @($manifest.files).Count + ' 个固定文件。') -ForegroundColor Green
    return $true
}

function Initialize-ApkCertificateReader {
    if ('ToolkitApkCertificates' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
public static class ToolkitApkCertificates {
    static byte[] Blob(BinaryReader r, long end) {
        if (r.BaseStream.Position + 4 > end) throw new InvalidDataException("truncated length");
        uint n = r.ReadUInt32();
        if (n > 16 * 1024 * 1024 || r.BaseStream.Position + n > end) throw new InvalidDataException("invalid length");
        byte[] b = r.ReadBytes((int)n);
        if (b.Length != n) throw new EndOfStreamException();
        return b;
    }
    static string[] Signers(byte[] value) {
        var hashes = new List<string>();
        using (var outer = new BinaryReader(new MemoryStream(value))) {
            byte[] all = Blob(outer, value.Length);
            using (var r = new BinaryReader(new MemoryStream(all))) {
                while (r.BaseStream.Position < all.Length) {
                    byte[] signer = Blob(r, all.Length);
                    using (var s = new BinaryReader(new MemoryStream(signer))) {
                        byte[] signed = Blob(s, signer.Length);
                        using (var d = new BinaryReader(new MemoryStream(signed))) {
                            Blob(d, signed.Length); // digests
                            byte[] certs = Blob(d, signed.Length);
                            using (var c = new BinaryReader(new MemoryStream(certs))) {
                                byte[] leaf = Blob(c, certs.Length);
                                using (var sha = SHA256.Create()) hashes.Add(BitConverter.ToString(sha.ComputeHash(leaf)).Replace("-", "").ToLowerInvariant());
                            }
                        }
                    }
                }
            }
        }
        if (hashes.Count == 0) throw new InvalidDataException("no signer");
        hashes.Sort(StringComparer.Ordinal); return hashes.ToArray();
    }
    public static string[] Read(string path) {
        using (var f = File.OpenRead(path)) using (var r = new BinaryReader(f)) {
            int tailLength = (int)Math.Min(f.Length, 65557L);
            if (tailLength < 22) throw new InvalidDataException("not an APK");
            f.Position = f.Length - tailLength; byte[] tail = r.ReadBytes(tailLength);
            int eocd = -1;
            for (int i = tail.Length - 22; i >= 0; i--) {
                if (BitConverter.ToUInt32(tail, i) == 0x06054b50 && i + 22 + BitConverter.ToUInt16(tail, i + 20) == tail.Length) { eocd = i; break; }
            }
            if (eocd < 0) throw new InvalidDataException("missing ZIP footer");
            long cd = BitConverter.ToUInt32(tail, eocd + 16);
            if (cd < 32 || cd > f.Length) throw new InvalidDataException("invalid signing block");
            f.Position = cd - 24; ulong size = r.ReadUInt64(); byte[] magic = r.ReadBytes(16);
            if (Encoding.ASCII.GetString(magic) != "APK Sig Block 42" || size < 24 || size > (ulong)cd - 8 || size > 64 * 1024 * 1024) throw new InvalidDataException("APK v2/v3 signature required");
            long start = cd - (long)size - 8; f.Position = start;
            if (r.ReadUInt64() != size) throw new InvalidDataException("signing block size mismatch");
            byte[] v2 = null, v3 = null;
            while (f.Position < cd - 24) {
                if (f.Position + 8 > cd - 24) throw new InvalidDataException("truncated pair");
                ulong n = r.ReadUInt64();
                if (n < 4 || n > 32 * 1024 * 1024 || n > (ulong)(cd - 24 - f.Position)) throw new InvalidDataException("invalid signing pair");
                uint id = r.ReadUInt32(); byte[] value = r.ReadBytes((int)n - 4);
                if (id == 0x7109871a) v2 = value;
                if (id == 0xf05368c0) v3 = value;
            }
            if (v3 != null) return Signers(v3);
            if (v2 != null) return Signers(v2);
            throw new InvalidDataException("unsupported APK signature");
        }
    }
}
'@
}

function Get-ApkSignerSha256([string]$Path) {
    Initialize-ApkCertificateReader
    return @([ToolkitApkCertificates]::Read($Path))
}
