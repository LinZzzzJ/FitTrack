# Android release

Android 工程为 `web/android`。固定 Node 24、Java 21、compile/target SDK 35，minSdk 26。
PC 和 mobile 构建目录独立。首次安装依赖后：

```sh
npm --prefix web ci
npm --prefix web run check
npm --prefix web run build:mobile
```

修改 Python 模型、参考 MET 或目录时，重新生成共享合约和静态校验器，再运行互通测试：

```sh
python scripts/export_mobile_contracts.py
node scripts/export_mobile_validators.mjs
npm --prefix web test
```

测试中的 Python/PC 往返校验默认调用 PATH 中的 `python`；可用
`PYTHON_TEST_EXECUTABLE` 指定隔离 Python 的绝对路径。它只创建模拟数据。

正式 sideload APK 使用外部长期保管的发布 keystore；路径可为绝对路径：

```sh
export JAVA_HOME=/path/to/jdk21
export ANDROID_SDK_ROOT=/path/to/android-sdk
bash scripts/android/build-release.sh \
  /secure/fittrack-release.jks \
  /secure/store-password.txt \
  fittrack \
  artifacts/android-release
```

脚本对 APK 做 16 KiB zip 对齐、签名校验和 SHA-256。`versionCode` 必须单调增加；
升级不能更改 applicationId 或签名。第一次生成的密钥与密码文件应单独备份，禁止提交到 Git。
应用目前是单个通用 APK；尚不把它等同于 Google Play AAB 发布。

`.github/workflows/android-release.yml` 可手动构建；配置
`FITTRACK_KEYSTORE_BASE64`、`FITTRACK_KEY_PASSWORD`、`FITTRACK_KEY_ALIAS` secrets 后签名，
没有配置时只上传未签名构建产物。不会自动创建 GitHub Release。

功能、安全边界及尚未验证项目见 [Android 指南](../../docs/android.md)。
