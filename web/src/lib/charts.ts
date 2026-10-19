import type { EChartsOption } from "echarts";
export const palette = ["#246b53", "#dea64e", "#7899ad"];
export function lineOptions(
  labels: string[],
  series: {
    name: string;
    values: (number | null)[];
    color?: string;
    dashed?: boolean;
  }[],
  unit = "",
): EChartsOption {
  return {
    animationDuration: 350,
    color: palette,
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) =>
        value == null ? "未记录" : `${value} ${unit}`,
    },
    legend: {
      bottom: 0,
      icon: "circle",
      textStyle: { color: "#6b7771", fontSize: 11 },
    },
    grid: { left: 48, right: 15, top: 20, bottom: 46 },
    xAxis: {
      type: "category",
      data: labels.map((day) => day.slice(5)),
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#e5e9e3" } },
      axisTick: { show: false },
      axisLabel: { color: "#88948b", fontSize: 10 },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#88948b", fontSize: 10 },
      splitLine: { lineStyle: { color: "#edf0e9", type: "dashed" } },
    },
    series: series.map((item) => ({
      name: item.name,
      type: "line",
      data: item.values,
      connectNulls: false,
      symbol: "circle",
      symbolSize: 5,
      smooth: 0.18,
      lineStyle: {
        width: 2.5,
        color: item.color,
        type: item.dashed ? "dashed" : "solid",
      },
      itemStyle: { color: item.color },
      areaStyle: item.dashed ? undefined : { opacity: 0.045 },
    })),
  };
}
export function pieOptions(
  values: { name: string; value: number }[],
): EChartsOption {
  return {
    color: palette,
    tooltip: { trigger: "item", formatter: "{b}: {c} kcal ({d}%)" },
    series: [
      {
        type: "pie",
        radius: ["64%", "88%"],
        center: ["50%", "50%"],
        label: { show: false },
        labelLine: { show: false },
        itemStyle: { borderColor: "#fffefa", borderWidth: 4, borderRadius: 5 },
        data: values,
      },
    ],
  };
}
