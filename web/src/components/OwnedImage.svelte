<script lang="ts">
  import { isMobile } from "../lib/mobile";
  import { imageUrl } from "../lib/api";
  import { readHealth } from "../lib/repository";
  import { getImageBytes } from "../lib/mobile-files";
  import type { HTMLImgAttributes } from "svelte/elements";
  let {
    id,
    thumb = false,
    alt = "照片",
    ...rest
  }: Omit<HTMLImgAttributes, "id"> & { id: string; thumb?: boolean } = $props();
  let src = $state("");
  $effect(() => {
    const current = id;
    let active = true;
    let created = "";
    if (!isMobile) src = imageUrl(current, thumb);
    else
      void (async () => {
        try {
          const health = await readHealth(),
            index = health.find("images", current),
            bytes = await getImageBytes(index, health.storageScope);
          created = URL.createObjectURL(
            new Blob([bytes as Uint8Array<ArrayBuffer>]),
          );
          if (active) src = created;
          else URL.revokeObjectURL(created);
        } catch {
          if (active) src = "";
        }
      })();
    return () => {
      active = false;
      if (created) URL.revokeObjectURL(created);
    };
  });
</script>

{#if src}<img {src} {alt} {...rest} />{:else}<span
    class="small muted"
    role="img"
    aria-label={alt}>照片正在读取或尚未同步</span
  >{/if}
