import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { resolve } from "node:path";
const root = resolve(import.meta.dirname, "../..");
const lock = JSON.parse(readFileSync(resolve(root, "web/package-lock.json")));
let text =
  "FitTrack · 轻衡\nOriginal app and procedural SVG motion studies: MIT, see project LICENSE.\n\n" +
  readFileSync(resolve(root, "LICENSE"), "utf8");
for (const [path, info] of Object.entries(lock.packages)) {
  if (!path || info.dev || !path.startsWith("node_modules/")) continue;
  const dir = resolve(root, "web", path);
  if (!existsSync(dir)) continue;
  const licenses = readdirSync(dir).filter((name) =>
    /^(licen[sc]e|copying|notice)(\.|$)/i.test(name),
  );
  text +=
    "\n\n--- " +
    path.replace("node_modules/", "") +
    " " +
    info.version +
    " (" +
    (info.license || "see upstream") +
    ") ---\n";
  for (const file of licenses) {
    try {
      text += readFileSync(resolve(dir, file), "utf8") + "\n";
    } catch {}
  }
}
text +=
  "\nAndroid native libraries: Capacitor (MIT), AndroidX (Apache-2.0), SQLCipher 4.10.0 (BSD-style license); see upstream notices packaged with dependencies.\nNo openGym / Gym visual media is included.\n";
writeFileSync(resolve(root, "web/public/third-party-notices.txt"), text);
