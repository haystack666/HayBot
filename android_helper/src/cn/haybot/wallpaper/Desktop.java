package cn.haybot.wallpaper;

import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.ComponentName;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Looper;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

/** Root-only maintenance for the bundled AOSP Launcher3. Never clears app data. */
public class Desktop {
    private static final File ROOT = new File("/data/user/0/com.android.launcher3");
    private static final File DB = new File(ROOT, "databases/launcher.db");
    private static final File PREFS = new File(ROOT, "shared_prefs/com.android.launcher3.prefs.xml");
    private static final File BACKUPS = new File("/data/local/tmp/haybot-desktop-backups");

    private static Context context() throws Exception {
        if (Looper.myLooper() == null) Looper.prepareMainLooper();
        Class<?> thread = Class.forName("android.app.ActivityThread");
        Object instance = thread.getMethod("systemMain").invoke(null);
        return (Context) thread.getMethod("getSystemContext").invoke(instance);
    }

    public static void main(String[] args) throws Exception {
        if (android.os.Process.myUid() != 0) throw new SecurityException("root required");
        if (args.length < 1) throw new IllegalArgumentException("mode required");
        if (args[0].equals("probe")) {
            Context launcher = context().createPackageContext("com.android.launcher3", 0);
            int workspace = launcher.getResources().getIdentifier("search_container_workspace", "layout", "com.android.launcher3");
            int empty = launcher.getResources().getIdentifier("search_container_hotseat", "layout", "com.android.launcher3");
            if (!DB.isFile() || !PREFS.isFile() || workspace == 0 || empty == 0) throw new IllegalStateException("unsupported launcher");
            JSONObject result = new JSONObject();
            result.put("workspace", workspace); result.put("empty", empty);
            System.out.println("HAYBOT_DESKTOP " + result);
            return;
        }
        if (args.length < 2 || !args[1].matches("[0-9a-f]{32}")) throw new IllegalArgumentException("invalid receipt");
        File backup = new File(BACKUPS, args[1]);
        if (args[0].equals("restore")) {
            if (!new File(backup, "launcher.db").isFile() || !new File(backup, "prefs.xml").isFile()) throw new IllegalStateException("backup missing");
            Files.copy(new File(backup, "launcher.db").toPath(), DB.toPath(), StandardCopyOption.REPLACE_EXISTING);
            Files.copy(new File(backup, "prefs.xml").toPath(), PREFS.toPath(), StandardCopyOption.REPLACE_EXISTING);
            // Preserve the launcher's ownership after replacing root-created backup files.
            android.system.StructStat owner = android.system.Os.stat(ROOT.toString());
            android.system.Os.chown(DB.toString(), owner.st_uid, owner.st_gid);
            android.system.Os.chown(PREFS.toString(), owner.st_uid, owner.st_gid);
            System.out.println("HAYBOT_DESKTOP_RESTORED");
            return;
        }
        if (!args[0].equals("apply") || args.length != 3 || !args[2].matches("mark\\.via/[A-Za-z0-9_.$]+")) throw new IllegalArgumentException("invalid operation");
        if (backup.exists() || !backup.mkdirs()) throw new IllegalStateException("backup directory unavailable");
        android.system.Os.chmod(BACKUPS.toString(), 0700);
        android.system.Os.chmod(backup.toString(), 0700);
        try (SQLiteDatabase db = SQLiteDatabase.openDatabase(DB.toString(), null, SQLiteDatabase.OPEN_READWRITE)) {
            db.rawQuery("PRAGMA wal_checkpoint(FULL)", null).close();
        }
        Files.copy(DB.toPath(), new File(backup, "launcher.db").toPath());
        Files.copy(PREFS.toPath(), new File(backup, "prefs.xml").toPath());
        try (SQLiteDatabase db = SQLiteDatabase.openDatabase(DB.toString(), null, SQLiteDatabase.OPEN_READWRITE)) {
            db.beginTransaction();
            try {
                db.delete("favorites", null, null);
                Intent intent = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
                    .setComponent(ComponentName.unflattenFromString(args[2])).setFlags(0x10200000);
                ContentValues item = new ContentValues();
                item.put("_id", 1); item.put("title", "Via"); item.put("intent", intent.toUri(0));
                item.put("container", -100); item.put("screen", 0); item.put("cellX", 2); item.put("cellY", 2);
                item.put("spanX", 1); item.put("spanY", 1); item.put("itemType", 0); item.put("appWidgetId", -1);
                item.put("profileId", 0); item.put("rank", 0); item.put("restored", 0); item.put("modified", System.currentTimeMillis());
                db.insertOrThrow("favorites", null, item);
                db.setTransactionSuccessful();
            } finally { db.endTransaction(); }
            try (Cursor cursor = db.rawQuery("SELECT title FROM favorites", null)) {
                if (cursor.getCount() != 1 || !cursor.moveToFirst() || !"Via".equals(cursor.getString(0))) throw new IllegalStateException("layout verification failed");
            }
        }
        Document document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(PREFS);
        NodeList nodes = document.getDocumentElement().getChildNodes();
        for (int i = nodes.getLength() - 1; i >= 0; i--) {
            if (nodes.item(i) instanceof Element && "pref_add_icon_to_home".equals(((Element) nodes.item(i)).getAttribute("name"))) document.getDocumentElement().removeChild(nodes.item(i));
        }
        Element flag = document.createElement("boolean");
        flag.setAttribute("name", "pref_add_icon_to_home"); flag.setAttribute("value", "false");
        document.getDocumentElement().appendChild(flag);
        try (FileOutputStream output = new FileOutputStream(PREFS)) {
            TransformerFactory.newInstance().newTransformer().transform(new DOMSource(document), new StreamResult(output));
        }
        System.out.println("HAYBOT_DESKTOP_APPLIED " + backup);
    }
}
