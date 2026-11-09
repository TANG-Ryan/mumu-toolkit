"""Exercise installer decisions against a fake ADB; no Android device is contacted."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]

def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', required=True, type=Path)
    args = parser.parse_args()
    pack = args.pack.resolve()
    apps = json.loads((pack/'metadata/apps.json').read_text(encoding='utf-8-sig'))
    app = next(a for a in apps if a['id'] == 'locationspoofer_network_fix')
    other = next(a for a in apps if a['id'] == 'wechat_android')
    with tempfile.TemporaryDirectory(prefix='mumu-toolkit-installer-') as temp:
        root = Path(temp)
        fixture = root/'pack'
        (fixture/'tools').mkdir(parents=True)
        (fixture/'metadata').mkdir()
        for name in ('Common.ps1', 'Install-APK.ps1'):
            shutil.copy2(REPO/'tools'/name, fixture/'tools'/name)
        target = fixture/app['path']
        target.parent.mkdir(parents=True)
        shutil.copy2(pack/app['path'], target)
        (fixture/'metadata/apps.json').write_text(json.dumps([app]), encoding='utf-8-sig')
        (fixture/'metadata/manifest.json').write_text(json.dumps({'schema_version':2,'files':[{'path':app['path'],'bytes':target.stat().st_size,'sha256':digest(target)}]}), encoding='utf-8-sig')
        fake = root/'adb.exe'
        quote = lambda p: "'" + str(p).replace("'", "''") + "'"
        compile_cmd = 'Add-Type -Path ' + quote(REPO/'tests/FakeAdb.cs') + ' -OutputAssembly ' + quote(fake) + ' -OutputType ConsoleApplication'
        subprocess.run(['powershell.exe','-NoProfile','-Command',compile_cmd], check=True, capture_output=True)
        results = []
        for mode in ('wrong_device','low_api','wrong_abi','downgrade','signature_mismatch','cancel','install_failure','success'):
            log = root/(mode+'.log')
            env = dict(os.environ, TOOLKIT_TEST_MODE=mode, TOOLKIT_TEST_LOG=str(log), TOOLKIT_TEST_OTHER_APK=str(pack/other['path']))
            command = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(fixture/'tools/Install-APK.ps1'),'-AdbPath',str(fake),'-Serial','wrong:4321' if mode=='wrong_device' else 'fake:1234','-AppId',app['id']]
            r = subprocess.run(command, input=b'NO\n' if mode=='cancel' else b'INSTALL\n', env=env, capture_output=True, timeout=90)
            calls = log.read_text(encoding='utf-8').splitlines()
            installs = [line for line in calls if '\tinstall\t' in line]
            assert not any('uninstall' in line or '\t-d\t' in line for line in calls), (mode, 'destructive command')
            expected_install = mode in ('success','install_failure')
            assert len(installs) == int(expected_install), (mode, calls, r.stdout[-1000:], r.stderr[-1000:])
            assert (r.returncode == 0) == (mode in ('success','cancel')), (mode, r.returncode, r.stdout[-1000:], r.stderr[-1000:])
            results.append({'case':mode,'passed':True,'install_calls':len(installs)})
        print(json.dumps({'fake_adb_only':True,'cases':results}, indent=2))

if __name__ == '__main__':
    main()
