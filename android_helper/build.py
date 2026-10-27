"""Reproducible helper build using the deployment developer's Android SDK/JDK.
Only the locally generated wallpaper is bundled; no third party applications.
"""
import os, pathlib, shutil, subprocess, tempfile, zipfile
root=pathlib.Path(__file__).resolve().parents[1]
sdk=pathlib.Path(os.environ.get('ANDROID_HOME',str(pathlib.Path.home()/'Library/Android/sdk')))
java=pathlib.Path(os.environ.get('JAVA_HOME','/Applications/Android Studio.app/Contents/jbr/Contents/Home'))
build=sdk/'build-tools/35.0.1'; android=sdk/'platforms/android-31/android.jar'
def run(*args,**kw):subprocess.run([str(a) for a in args],check=True,**kw)
with tempfile.TemporaryDirectory(prefix='haybot-wallpaper-') as temp:
 d=pathlib.Path(temp);(d/'classes').mkdir();(d/'dex').mkdir();(d/'assets').mkdir()
 shutil.copy(root/'android_runtime/assets/haybot-wallpaper.png',d/'assets/wallpaper.png')
 run(java/'bin/javac','-source','8','-target','8','-bootclasspath',android,'-d',d/'classes',*sorted((root/'android_helper/src').rglob('*.java')))
 env=dict(os.environ,JAVA_HOME=str(java))
 run(build/'d8','--lib',android,'--output',d/'dex',*sorted((d/'classes').rglob('*.class')),env=env)
 run(build/'aapt','package','-f','-M',root/'android_helper/AndroidManifest.xml','-A',d/'assets','-I',android,'-F',d/'unsigned.apk')
 with zipfile.ZipFile(d/'unsigned.apk','a') as apk:apk.write(d/'dex/classes.dex','classes.dex')
 run(build/'zipalign','-f','4',d/'unsigned.apk',d/'aligned.apk')
 # Per-deployment key, kept outside source control. Retain for upgrades.
 key=root/'.android-runtime/wallpaper-signing.jks';key.parent.mkdir(exist_ok=True)
 if not key.exists():run(java/'bin/keytool','-genkeypair','-keystore',key,'-storepass','haybot-local-wallpaper','-keypass','haybot-local-wallpaper','-alias','wallpaper','-dname','CN=HayBot Wallpaper','-keyalg','RSA','-validity','10000')
 run(build/'apksigner','sign','--ks',key,'--ks-pass','pass:haybot-local-wallpaper','--out',root/'android_runtime/assets/haybot-wallpaper.apk',d/'aligned.apk',env=env)
 print('Built android_runtime/assets/haybot-wallpaper.apk')
