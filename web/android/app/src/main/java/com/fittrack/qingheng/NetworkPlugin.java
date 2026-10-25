package com.fittrack.qingheng;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import android.util.Base64;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@CapacitorPlugin(name="FitTrackNetwork")
public class NetworkPlugin extends Plugin {
    private final ExecutorService workers = Executors.newFixedThreadPool(2);
    @PluginMethod
    public void request(PluginCall call) {
        workers.execute(() -> {
            HttpURLConnection connection = null;
            try {
                URL url = new URL(call.getString("url", ""));
                if (!url.getProtocol().equals("https") || url.getUserInfo()!=null || url.getRef()!=null) throw new Exception("Invalid URL");
                String method = call.getString("method", "GET");
                if (!method.matches("GET|POST|PUT|DELETE")) throw new Exception("Invalid method");
                connection = (HttpURLConnection)url.openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(10000);
                connection.setReadTimeout(url.getPath().endsWith("/chat/completions")?90000:20000);
                connection.setRequestMethod(method);
                JSObject headers = call.getObject("headers",new JSObject());
                Iterator<String> keys = headers.keys();
                while(keys.hasNext()) {
                    String key = keys.next();
                    if (!key.matches("(?i)Authorization|Content-Type|X-Fittrack-Api")) throw new Exception("Invalid header");
                    String value=headers.getString(key);
                    if(value==null||value.indexOf('\n')>=0||value.indexOf('\r')>=0) throw new Exception("Invalid header");
                    connection.setRequestProperty(key,value);
                }
                String data=call.getString("data");
                if(data!=null) {
                    byte[] bytes=call.getBoolean("binary",false)?Base64.decode(data,Base64.NO_WRAP):data.getBytes(StandardCharsets.UTF_8);
                    if(bytes.length>13*1024*1024)throw new Exception("Body too large");
                    connection.setDoOutput(true);
                    connection.setFixedLengthStreamingMode(bytes.length);
                    try(java.io.OutputStream out=connection.getOutputStream()){out.write(bytes);}
                }
                int status=connection.getResponseCode();
                boolean binary=call.getBoolean("responseBinary",false);
                int limit=binary?13*1024*1024:2*1024*1024;
                if(connection.getContentLengthLong()>limit)throw new Exception("Response too large");
                InputStream input=status>=400?connection.getErrorStream():connection.getInputStream();
                ByteArrayOutputStream output=new ByteArrayOutputStream();
                long started=System.nanoTime();
                if(input!=null)try(InputStream stream=input){
                    byte[] buffer=new byte[8192];int count;
                    while((count=stream.read(buffer))!=-1) {
                        if(output.size()+count>limit||System.nanoTime()-started>120000000000L)throw new Exception("Response limit exceeded");
                        output.write(buffer,0,count);
                    }
                }
                JSObject result=new JSObject();
                result.put("status",status);
                result.put("data",binary?Base64.encodeToString(output.toByteArray(),Base64.NO_WRAP):output.toString("UTF-8"));
                result.put("contentType",connection.getContentType());
                call.resolve(result);
            } catch(Exception error){call.reject("连接失败或响应超限，未自动重试");}
            finally{if(connection!=null)connection.disconnect();}
        });
    }
    @Override protected void handleOnDestroy(){workers.shutdownNow();}
}
