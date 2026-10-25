#!/usr/bin/env bash
set -euo pipefail

# Build a reproducible, signed sideload APK.  Secrets are supplied through
# files/environment variables and are never written to the repository.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
keystore="${1:-${FITTRACK_KEYSTORE:-}}"
password_file="${2:-${FITTRACK_KEY_PASSWORD_FILE:-}}"
alias="${3:-${FITTRACK_KEY_ALIAS:-fittrack}}"
out_dir="${4:-$root/artifacts/android-release}"

if [[ -z "$keystore" || -z "$password_file" || ! -f "$keystore" || ! -f "$password_file" ]]; then
  echo "usage: $0 <keystore> <password-file> <alias> [out-dir]" >&2
  exit 2
fi
if [[ -z "${ANDROID_SDK_ROOT:-}" && -z "${ANDROID_HOME:-}" ]]; then
  echo "ANDROID_SDK_ROOT or ANDROID_HOME is required for zipalign/apksigner" >&2
  exit 2
fi

sdk="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
if [[ -n "${JAVA_HOME:-}" ]]; then export PATH="$JAVA_HOME/bin:$PATH"; fi
build_tools="$(find "$sdk/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"
zipalign="$build_tools/zipalign"
apksigner="$build_tools/apksigner"
[[ -x "$zipalign" && -x "$apksigner" ]] || {
  echo "Android build-tools with zipalign and apksigner are required" >&2
  exit 2
}

keystore="$(realpath "$keystore")"
password_file="$(realpath "$password_file")"
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd -P)"
if [[ ! -x "$root/web/node_modules/.bin/vite" && ! -f "$root/web/node_modules/vite/bin/vite.js" ]]; then
  echo "web dependencies are missing; run npm ci in web first" >&2
  exit 2
fi

cd "$root/web"
npm run build:mobile
./android/gradlew -p android --no-daemon --stacktrace assembleRelease

unsigned="$(find android/app/build/outputs/apk/release -maxdepth 1 -name '*.apk' -type f | head -1)"
[[ -n "$unsigned" ]] || { echo "Gradle did not produce an APK" >&2; exit 1; }
aligned="$out_dir/FitTrack-aligned.apk"
apk="$out_dir/FitTrack-release.apk"
"$zipalign" -P 16 -f 4 "$unsigned" "$aligned"
"$apksigner" sign --ks "$keystore" --ks-key-alias "$alias" --ks-pass "file:$password_file" --out "$apk" "$aligned"
"$apksigner" verify --verbose "$apk"
(cd "$out_dir" && sha256sum "$(basename "$apk")") > "$apk.sha256"
rm -f "$aligned"
echo "created $apk"
