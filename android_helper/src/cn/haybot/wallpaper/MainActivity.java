package cn.haybot.wallpaper;
import android.app.Activity;
import android.app.WallpaperManager;
import android.os.Bundle;
import android.widget.TextView;
import java.io.InputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
public class MainActivity extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        TextView text = new TextView(this);
        setContentView(text);
        try (InputStream stream = getAssets().open("wallpaper.png")) {
            WallpaperManager.getInstance(this).setStream(stream, null, true, WallpaperManager.FLAG_SYSTEM | WallpaperManager.FLAG_LOCK);
            getSharedPreferences("state", MODE_PRIVATE).edit().putBoolean("applied", true).commit();
            String receipt = getIntent().getStringExtra("receipt");
            if (receipt != null && receipt.matches("[0-9a-f]{32}")) {
                try (FileOutputStream output = new FileOutputStream(new File(getExternalFilesDir(null), "applied"))) {
                    output.write(receipt.getBytes(StandardCharsets.UTF_8));
                }
            }
            text.setText("HayBot 壁纸已设置");
            finish();
        } catch (Exception error) { text.setText("壁纸设置失败，请检查系统壁纸服务。"); }
    }
}
