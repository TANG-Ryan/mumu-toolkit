using System;
using System.IO;

public class FakeAdb {
    public static int Main(string[] args) {
        string mode = Environment.GetEnvironmentVariable("TOOLKIT_TEST_MODE") ?? "success";
        File.AppendAllText(Environment.GetEnvironmentVariable("TOOLKIT_TEST_LOG"), String.Join("\t", args) + "\n");
        string all = String.Join(" ", args);
        if (all == "version") { Console.WriteLine("Android Debug Bridge version 1.0.41"); return 0; }
        if (all == "devices") { Console.WriteLine("List of devices attached\nfake:1234\tdevice"); return 0; }
        if (all.Contains("getprop ro.product.model")) { Console.WriteLine("Test fixture"); return 0; }
        if (all.Contains("getprop ro.build.version.sdk")) { Console.WriteLine(mode == "low_api" ? "23" : "35"); return 0; }
        if (all.Contains("getprop ro.product.cpu.abilist")) { Console.WriteLine(mode == "wrong_abi" ? "x86" : "x86_64,arm64-v8a"); return 0; }
        if (all.Contains("pm list packages")) {
            if (mode == "downgrade" || mode == "signature_mismatch") Console.WriteLine("package:com.suseoaa.locationspoofer");
            return 0;
        }
        if (all.Contains("dumpsys package")) { Console.WriteLine("versionCode=" + (mode == "downgrade" ? "99999" : "20613")); return 0; }
        if (all.Contains("pm path")) { Console.WriteLine("package:/data/app/fixture/base.apk"); return 0; }
        if (args.Length >= 3 && args[2] == "pull") {
            File.Copy(Environment.GetEnvironmentVariable("TOOLKIT_TEST_OTHER_APK"), args[args.Length-1], true);
            Console.WriteLine("1 file pulled"); return 0;
        }
        if (args.Length >= 3 && args[2] == "install") {
            if (mode == "install_failure") { Console.WriteLine("Failure [INSTALL_FAILED_TEST]"); return 1; }
            Console.WriteLine("Success"); return 0;
        }
        Console.Error.WriteLine("Unexpected fake ADB command: " + all); return 70;
    }
}
