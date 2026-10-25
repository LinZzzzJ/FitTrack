package com.fittrack.qingheng;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(android.os.Bundle state) {
        registerPlugin(SecureStoragePlugin.class);
        registerPlugin(NetworkPlugin.class);
        super.onCreate(state);
        getBridge().getWebView().getSettings().setAllowFileAccess(false);
        getBridge().getWebView().getSettings().setAllowFileAccessFromFileURLs(false);
        getBridge().getWebView().getSettings().setAllowUniversalAccessFromFileURLs(false);
        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) == 0) android.webkit.WebView.setWebContentsDebuggingEnabled(false);
    }
}
