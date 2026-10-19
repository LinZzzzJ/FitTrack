<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts/core";
  import { LineChart, BarChart, PieChart } from "echarts/charts";
  import {
    GridComponent,
    TooltipComponent,
    LegendComponent,
    AriaComponent,
  } from "echarts/components";
  import { CanvasRenderer } from "echarts/renderers";
  import type { EChartsOption } from "echarts";
  let {
    option,
    height = 230,
    label = "数据图表",
  }: { option: EChartsOption; height?: number; label?: string } = $props();
  let element: HTMLDivElement;
  let chart: echarts.ECharts | undefined;
  echarts.use([
    LineChart,
    BarChart,
    PieChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    AriaComponent,
    CanvasRenderer,
  ]);
  function draw(value: EChartsOption) {
    chart?.setOption(
      {
        ...value,
        aria: { enabled: true },
        animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
      },
      true,
    );
  }
  onMount(() => {
    chart = echarts.init(element);
    draw(option);
    const observer = new ResizeObserver(() => chart?.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      chart?.dispose();
    };
  });
  $effect(() => {
    draw(option);
  });
</script>

<div
  bind:this={element}
  class="chart"
  style:height="{height}px"
  role="img"
  aria-label={label}
></div>
