# FitTrack accepts these four image formats. Avoid collecting unrelated optional
# codecs (notably AVIF), which the upload contract already rejects.
hiddenimports = [
    "PIL.JpegImagePlugin",
    "PIL.PngImagePlugin",
    "PIL.WebPImagePlugin",
    "PIL.GifImagePlugin",
]
