package com.fittrack.qingheng;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;


@CapacitorPlugin(name = "SecureStorage")
public class SecureStoragePlugin extends Plugin {
    private static final String STORE = "fittrack_secure_storage";
    private static final String ALIAS = "fittrack_database_wrapping_key";
    private static final String VALUE = "database_secret";

    @PluginMethod
    public void getOrCreateDatabaseSecret(PluginCall call) {
        try {
            SecretKey key = wrappingKey();
            String encoded = getContext().getSharedPreferences(STORE, 0).getString(VALUE, null);
            byte[] secret;
            if (encoded == null) {
                secret = new byte[32];
                new SecureRandom().nextBytes(secret);
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.ENCRYPT_MODE, key);
                byte[] encrypted = cipher.doFinal(secret);
                byte[] packed = new byte[cipher.getIV().length + encrypted.length];
                System.arraycopy(cipher.getIV(), 0, packed, 0, cipher.getIV().length);
                System.arraycopy(encrypted, 0, packed, cipher.getIV().length, encrypted.length);
                if (!getContext().getSharedPreferences(STORE, 0).edit()
                        .putString(VALUE, Base64.encodeToString(packed, Base64.NO_WRAP)).commit()) throw new Exception("Key write failed");
            } else {
                byte[] packed = Base64.decode(encoded, Base64.NO_WRAP);
                byte[] iv = new byte[12];
                byte[] encrypted = new byte[packed.length - iv.length];
                System.arraycopy(packed, 0, iv, 0, iv.length);
                System.arraycopy(packed, iv.length, encrypted, 0, encrypted.length);
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, iv));
                secret = cipher.doFinal(encrypted);
            }
            JSObject result = new JSObject();
            result.put("secret", Base64.encodeToString(secret, Base64.NO_WRAP));
            call.resolve(result);
        } catch (Exception error) {
            call.reject("无法打开本地加密数据库");
        }
    }

    private String checkedKey(PluginCall call) {
        String name = call.getString("key", "");
        if (!name.matches("connection|ai-[a-f0-9]{24}|local-mode")) throw new IllegalArgumentException("Invalid key");
        return name;
    }

    @PluginMethod
    public void set(PluginCall call) {
        try {
            String name = checkedKey(call);
            String value = call.getString("value", "");
            if (value.length() > 16384) throw new IllegalArgumentException("Value too large");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, wrappingKey());
            byte[] encrypted = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
            byte[] packed = new byte[12 + encrypted.length];
            System.arraycopy(cipher.getIV(), 0, packed, 0, 12);
            System.arraycopy(encrypted, 0, packed, 12, encrypted.length);
            if (!getContext().getSharedPreferences(STORE, 0).edit().putString(name, Base64.encodeToString(packed, Base64.NO_WRAP)).commit()) throw new Exception("Write failed");
            call.resolve();
        } catch (Exception error) { call.reject("安全存储写入失败"); }
    }

    @PluginMethod
    public void get(PluginCall call) {
        try {
            String encoded = getContext().getSharedPreferences(STORE, 0).getString(checkedKey(call), null);
            JSObject result = new JSObject();
            if (encoded != null) {
                byte[] packed = Base64.decode(encoded, Base64.NO_WRAP);
                if (packed.length < 28) throw new Exception("Invalid ciphertext");
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, wrappingKey(), new GCMParameterSpec(128, packed, 0, 12));
                result.put("value", new String(cipher.doFinal(packed, 12, packed.length - 12), StandardCharsets.UTF_8));
            }
            call.resolve(result);
        } catch (Exception error) { call.reject("安全存储无法解密，请重新配对或恢复密钥"); }
    }

    @PluginMethod
    public void remove(PluginCall call) {
        try {
            getContext().getSharedPreferences(STORE, 0).edit().remove(checkedKey(call)).commit();
            call.resolve();
        } catch (Exception error) { call.reject("安全存储删除失败"); }
    }

    private SecretKey wrappingKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) store.getEntry(ALIAS, null)).getSecretKey();
    }
}
