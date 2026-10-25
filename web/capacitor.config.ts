import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.fittrack.qingheng",
  appName: "FitTrack 轻衡",
  loggingBehavior: "none",
  webDir: "mobile-dist",
  server: { androidScheme: "https" },
  android: {
    backgroundColor: "#f4f7f4",
    allowMixedContent: false,
  },
  plugins: {
    CapacitorSQLite: { androidIsEncryption: true, androidBiometric: { biometricAuth: false } },
    SplashScreen: {
      launchShowDuration: 0,
    },
  },
};

export default config;
