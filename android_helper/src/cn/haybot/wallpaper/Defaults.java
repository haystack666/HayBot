package cn.haybot.wallpaper;
import android.content.res.Configuration;
import java.lang.reflect.Method;
import java.util.Locale;
public class Defaults {
    public static void main(String[] args) throws Exception {
        Class<?> am = Class.forName("android.app.ActivityManager");
        Object service = am.getMethod("getService").invoke(null);
        Configuration config = new Configuration();
        config.setLocale(Locale.SIMPLIFIED_CHINESE);
        Configuration.class.getField("userSetLocale").setBoolean(config, true);
        Class<?> iam = Class.forName("android.app.IActivityManager");
        iam.getMethod("updatePersistentConfiguration", Configuration.class).invoke(service, config);
        Class<?> sm = Class.forName("android.os.ServiceManager");
        Object binder = sm.getMethod("getService", String.class).invoke(null, "alarm");
        Class<?> ibinder = Class.forName("android.os.IBinder");
        Object alarm = Class.forName("android.app.IAlarmManager$Stub").getMethod("asInterface", ibinder).invoke(null, binder);
        Class.forName("android.app.IAlarmManager").getMethod("setTimeZone",String.class).invoke(alarm,"Asia/Shanghai");
        Configuration current = (Configuration) iam.getMethod("getConfiguration").invoke(service);
        String zone = (String) Class.forName("android.os.SystemProperties").getMethod("get",String.class).invoke(null,"persist.sys.timezone");
        String locale = current.getLocales().get(0).toLanguageTag();
        if (!"zh-CN".equals(locale) || !"Asia/Shanghai".equals(zone)) throw new IllegalStateException("System defaults not applied");
        System.out.println("HAYBOT_DEFAULTS_OK zh-CN CN Asia/Shanghai");
    }
}
