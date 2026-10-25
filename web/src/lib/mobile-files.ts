import { Directory, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { scope } from "./repository";
import { imageDimensions } from "./image-headers";
import { sha } from "./ledger";
const mime: Record<string, string> = {
  jpg: "image/jpeg",
  png: "image/png",
  gif: "image/gif",
  webp: "image/webp",
};
export function base64(bytes: Uint8Array) {
  let result = "";
  for (let i = 0; i < bytes.length; i += 16384)
    result += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(result);
}
export function fromBase64(raw: string) {
  return Uint8Array.from(atob(raw), (c) => c.charCodeAt(0));
}
export async function validateImage(
  bytes: Uint8Array,
  expected?: { sha: string; ext: string; width: number; height: number },
) {
  if (bytes.length > 12 * 1024 * 1024) throw new Error("照片不能超过12 MiB");
  const ext =
    bytes[0] === 0xff && bytes[1] === 0xd8
      ? "jpg"
      : bytes[0] === 0x89 && String.fromCharCode(...bytes.slice(1, 4)) === "PNG"
        ? "png"
        : String.fromCharCode(...bytes.slice(0, 3)) === "GIF"
          ? "gif"
          : String.fromCharCode(...bytes.slice(0, 4)) === "RIFF" &&
              String.fromCharCode(...bytes.slice(8, 12)) === "WEBP"
            ? "webp"
            : "";
  if (!ext) throw new Error("仅支持 JPEG、PNG、GIF、WebP");
  const hash = await sha(bytes);
  if (expected && (expected.sha !== hash || expected.ext !== ext))
    throw new Error("图片哈希或格式不匹配");
  const [width, height] = imageDimensions(bytes, ext);
  if (
    width < 1 ||
    height < 1 ||
    width * height > 40000000 ||
    (expected && (expected.width !== width || expected.height !== height))
  )
    throw new Error("图片尺寸超限或索引不一致");
  const bitmap = await createImageBitmap(
    new Blob([bytes as Uint8Array<ArrayBuffer>], { type: mime[ext] }),
  );
  bitmap.close();
  return { sha: hash, ext, width, height };
}
export async function imagePath(hash: string, ext: string, namespace?: string) {
  if (!/^[a-f0-9]{64}$/.test(hash) || !mime[ext])
    throw new Error("图片引用无效");
  return `records/${namespace || (await scope())}/images/${hash}.${ext}`;
}
export async function putImageBytes(
  bytes: Uint8Array,
  index: Record<string, any>,
  namespace?: string,
) {
  await Filesystem.writeFile({
    directory: Directory.Data,
    path: await imagePath(index.sha, index.ext, namespace),
    data: base64(bytes),
    recursive: true,
  });
}
export async function getImageBytes(
  index: Record<string, any>,
  namespace?: string,
) {
  const file = await Filesystem.readFile({
    directory: Directory.Data,
    path: await imagePath(index.sha, index.ext, namespace),
  });
  return typeof file.data === "string"
    ? fromBase64(file.data)
    : new Uint8Array(await file.data.arrayBuffer());
}
export async function shareFile(name: string, bytes: Uint8Array) {
  // Only generated app files get FileProvider read grants. Never grant a directory.
  if (!/^[a-zA-Z0-9._-]+$/.test(name)) throw new Error("导出文件名无效");
  const path = `exports/${crypto.randomUUID()}/${name}`;
  const file = await Filesystem.writeFile({
    directory: Directory.Cache,
    path,
    data: base64(bytes),
    recursive: true,
  });
  await Share.share({ title: "FitTrack 健康备份", url: file.uri });
}
