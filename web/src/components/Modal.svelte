<script lang="ts">
  import { onMount, type Snippet } from "svelte";
  import { X } from "@lucide/svelte";
  let {
    title,
    onclose,
    children,
    wide = false,
  }: {
    title: string;
    onclose: () => void;
    children: Snippet;
    wide?: boolean;
  } = $props();
  let dialog: HTMLDialogElement;
  onMount(() => {
    dialog.showModal();
  });
</script>

<dialog
  bind:this={dialog}
  class:wide
  oncancel={(event) => {
    event.preventDefault();
    onclose();
  }}
  aria-label={title}
>
  <div class="modal-heading">
    <h2>{title}</h2>
    <button class="icon-button" aria-label="关闭弹窗" onclick={onclose}
      ><X size={20} /></button
    >
  </div>
  <div class="modal-content">{@render children()}</div>
</dialog>
