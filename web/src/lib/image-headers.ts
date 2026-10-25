/** Read encoded dimensions before decoding, preserving EXIF raw geometry. */
export function imageDimensions(
  bytes: Uint8Array,
  ext: string,
): [number, number] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (ext === "png") return [view.getUint32(16), view.getUint32(20)];
  if (ext === "gif") return [view.getUint16(6, true), view.getUint16(8, true)];
  if (ext === "jpg") {
    let at = 2;
    while (at + 8 < bytes.length) {
      if (bytes[at] !== 255) throw new Error("JPEG 段格式无效");
      while (bytes[at] === 255) at++;
      const marker = bytes[at++];
      if (marker === 0xd9 || marker === 0xda) break;
      const length = view.getUint16(at);
      if (length < 2 || at + length > bytes.length)
        throw new Error("JPEG 段长度无效");
      if (
        [
          0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd,
          0xce, 0xcf,
        ].includes(marker)
      )
        return [view.getUint16(at + 5), view.getUint16(at + 3)];
      at += length;
    }
  }
  if (ext === "webp") {
    let at = 12;
    while (at + 8 < bytes.length) {
      const type = String.fromCharCode(...bytes.slice(at, at + 4)),
        length = view.getUint32(at + 4, true),
        data = at + 8;
      if (data + length > bytes.length) throw new Error("WebP 段长度无效");
      if (type === "VP8X" && length >= 10)
        return [
          1 +
            bytes[data + 4] +
            (bytes[data + 5] << 8) +
            (bytes[data + 6] << 16),
          1 +
            bytes[data + 7] +
            (bytes[data + 8] << 8) +
            (bytes[data + 9] << 16),
        ];
      if (type === "VP8L" && length >= 5 && bytes[data] === 0x2f) {
        const bits = view.getUint32(data + 1, true);
        return [1 + (bits & 0x3fff), 1 + ((bits >>> 14) & 0x3fff)];
      }
      if (type === "VP8 " && length >= 10)
        return [
          view.getUint16(data + 6, true) & 0x3fff,
          view.getUint16(data + 8, true) & 0x3fff,
        ];
      at = data + length + (length % 2);
    }
  }
  throw new Error("无法读取图片尺寸");
}
