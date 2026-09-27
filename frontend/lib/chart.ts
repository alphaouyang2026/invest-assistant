import { ColorType, type DeepPartial, type ChartOptions } from "lightweight-charts";

import type { Palette } from "./palette";

/** What every chart shares: the page's type and colours, no background of its own. */
export const chartOptions = (palette: Palette, height: number): DeepPartial<ChartOptions> => ({
  autoSize: true,
  height,
  layout: {
    background: { type: ColorType.Solid, color: "transparent" },
    textColor: palette.muted,
    fontFamily: palette.sans,
    fontSize: 11,
    panes: { separatorColor: palette.line },
    attributionLogo: false,
  },
  grid: { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
  rightPriceScale: { borderColor: palette.line },
  timeScale: { borderColor: palette.line },
  crosshair: { vertLine: { labelBackgroundColor: palette.text }, horzLine: { labelBackgroundColor: palette.text } },
  localization: { locale: "zh-CN" },
});
