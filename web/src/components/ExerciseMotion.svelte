<script lang="ts">
  import { onMount } from "svelte";
  import { bones, motionFor } from "../lib/motions";
  let {
    exerciseId,
    label = "动作示意",
  }: { exerciseId: string; label?: string } = $props();
  let active = $state(false),
    paused = $state(false),
    reduced = $state(false);
  let host: HTMLDivElement;
  const spec = $derived(motionFor(exerciseId));
  const animate = $derived(active && !paused && !reduced);
  onMount(() => {
    const mq = matchMedia("(prefers-reduced-motion: reduce)");
    reduced = mq.matches;
    const change = () => (reduced = mq.matches);
    mq.addEventListener("change", change);
    const observer = new IntersectionObserver(
      ([entry]) => (active = entry.isIntersecting),
    );
    observer.observe(host);
    return () => {
      observer.disconnect();
      mq.removeEventListener("change", change);
    };
  });
</script>

<div
  bind:this={host}
  class="exercise-motion"
  role="img"
  aria-label={`${label} 动作范围示意`}
>
  <svg viewBox="0 0 120 102" aria-hidden="true">
    <path class="motion-ground" d="M8 97H112" />
    {#if spec.equipment === "bench" || spec.equipment === "seat"}<path
        class="motion-equipment"
        d={spec.equipment === "bench"
          ? "M17 60H87M29 60V94M77 60V94"
          : "M43 68H83M47 69V95M80 69V95M83 68V33"}
      />{/if}
    {#if spec.equipment === "cable"}<path
        class="motion-equipment"
        d="M10 96V5H109V96M15 6L36 20M105 6L83 20"
      />{/if}
    {#if spec.equipment === "row"}<path
        class="motion-equipment"
        d="M12 94H105M16 94V66M16 66H29M32 80H90"
      />{/if}
    {#if spec.equipment === "bar"}<path
        class="motion-equipment"
        d="M15 96V6H105V96"
      />{/if}
    {#if spec.equipment === "bike"}<path
        class="motion-equipment"
        d="M27 94L60 79L85 94M60 79L68 66M58 66H77M28 54H38L43 78"
      />{/if}
    {#if spec.equipment === "rope"}<path
        class="motion-equipment"
        d="M27 54Q-6 0 60 0Q126 0 93 54"
      />{/if}
    {#each bones as [from, to]}
      <line
        x1={spec.a[from][0]}
        y1={spec.a[from][1]}
        x2={spec.a[to][0]}
        y2={spec.a[to][1]}
      >
        {#if animate}{#each ["x1", "y1", "x2", "y2"] as attr, i}<animate
              attributeName={attr}
              values={`${spec.a[i < 2 ? from : to][i % 2]};${spec.b[i < 2 ? from : to][i % 2]};${spec.a[i < 2 ? from : to][i % 2]}`}
              dur="2.8s"
              repeatCount="indefinite"
            />{/each}{/if}
      </line>
    {/each}
    <circle cx={spec.a[0][0]} cy={spec.a[0][1]} r="7" class="motion-head">
      {#if animate}<animate
          attributeName="cx"
          values={`${spec.a[0][0]};${spec.b[0][0]};${spec.a[0][0]}`}
          dur="2.8s"
          repeatCount="indefinite"
        /><animate
          attributeName="cy"
          values={`${spec.a[0][1]};${spec.b[0][1]};${spec.a[0][1]}`}
          dur="2.8s"
          repeatCount="indefinite"
        />{/if}
    </circle>
    {#if spec.weights}{#each [4, 6] as hand}<circle
          class="motion-weight"
          cx={spec.a[hand][0]}
          cy={spec.a[hand][1]}
          r="4"
          >{#if animate}<animate
              attributeName="cx"
              values={`${spec.a[hand][0]};${spec.b[hand][0]};${spec.a[hand][0]}`}
              dur="2.8s"
              repeatCount="indefinite"
            /><animate
              attributeName="cy"
              values={`${spec.a[hand][1]};${spec.b[hand][1]};${spec.a[hand][1]}`}
              dur="2.8s"
              repeatCount="indefinite"
            />{/if}</circle
        >{/each}{/if}
  </svg>
  <button
    type="button"
    class="motion-toggle"
    onclick={() => (paused = !paused)}
    aria-label={`${paused ? "播放" : "暂停"}${label}示意`}
    >{paused || reduced ? "静态" : "暂停"}</button
  >
</div>
