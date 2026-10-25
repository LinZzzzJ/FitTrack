import { apiOrigin, authHeader, isLocalMobileMode, isMobile, loadMobileConnection } from "./mobile";

export const API_REVISION = 5;
export interface VersionInfo {
  version: string;
  api_revision: number;
  capabilities: string[];
  restart_required: boolean;
}
export const compatibility = $state({
  message: "",
  version: "",
  checked: false,
});
let pending: Promise<void> | null = null;
export function checkVersion() {
  if (pending) return pending;
  pending = (async () => {
    try {
      await loadMobileConnection();
      if (isMobile) {
        compatibility.version = "本地";
        compatibility.message = "";
        return;
      }
      const response = await fetch(apiOrigin() + "/api/version", {
        credentials: "same-origin",
        cache: "no-store",
        headers: authHeader(),
      });
      if (!response.ok) throw new Error("后台版本无法核对");
      const info: VersionInfo = await response.json();
      compatibility.version = info.version;
      const compatibleRevision =
        info.api_revision === API_REVISION;
      compatibility.message =
        !compatibleRevision ||
        info.restart_required ||
        ![
          "diet_history",
          "nutrition_label",
          "cardio_estimate",
          "meal_job_delete",
          "text_meal_estimate",
          "expanded_nutrition",
          "workout_templates",
          "training_import",
          "activity_estimates",
          "meal_entry_modes",
          "precise_meal_energy",
        ].every((value) =>
          info.capabilities?.includes(value),
        )
          ? "网页与后台版本不一致或后台等待更新。请使用「重启 FitTrack」入口，再刷新网页；未提交的表单会保留在当前页面。"
          : "";
    } catch {
      compatibility.message =
        "当前后台尚未更新或暂时无法连接。请使用「重启 FitTrack」入口后刷新网页；当前填写内容尚未提交。";
    } finally {
      compatibility.checked = true;
      pending = null;
    }
  })();
  return pending;
}
export async function ensureCompatible() {
  await checkVersion();
  if (compatibility.message) throw new Error(compatibility.message);
}
