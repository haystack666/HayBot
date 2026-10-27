# HayBot Android initialization helper

This helper sets the approved wallpaper. The root-only `Defaults` entry point applies and verifies `zh-CN` (China) and `Asia/Shanghai` using Android framework services, without resetting app data or accounts.

Build with an Android SDK (platform 31 and build-tools 35.0.1) and a JDK:

```sh
ANDROID_HOME=/path/to/android-sdk JAVA_HOME=/path/to/jdk python3 android_helper/build.py
```

The signing key stays in ignored `.android-runtime/wallpaper-signing.jks`; retain it when rebuilding for an existing deployment. No Google or other third-party APKs are bundled in the repository.

New devices created through the web use initialization automatically. Each initializer records success separately and does not overwrite the wallpaper or system preferences again after successful application. Existing phones require an explicit initialization action. Other app packages can be placed in `.android-runtime/packages/<catalog-id>.apk`; installation checks the APK signature, package identity, transfer SHA-256 and device ABI. Existing app versions and account data are retained. Google Play requires an independently compatible GMS system image; the status page checks for the three required packages and does not claim readiness from a store APK alone.
