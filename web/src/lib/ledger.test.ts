import { describe, it, expect } from "vitest";
import { Health, emptyTables, identifier, validateTables } from "./health";
import {
  labelFood,
  nutrients,
  validate,
  workoutEnergy,
  shanghaiToday,
} from "./ledger";
import contracts from "./mobile-contracts.json";
import { motionIds } from "./motions";
import { readArchive, writeArchive } from "./health-archive";
import { BlobWriter, ZipWriter, TextReader } from "@zip.js/zip.js";
import { spawnSync } from "node:child_process";
const owner = "a".repeat(24);
const profile = {
  effective_date: "2026-10-14",
  height_cm: 175,
  initial_weight_kg: 75,
  sex: "male",
  resting_kcal: 1800,
  activity_factor: 1.2,
  calorie_target: 2000,
};
const food = {
  name: "模拟餐食",
  consumed_part: "全部",
  estimated_edible_grams: 100,
  kcal: 2000,
  protein_g: 10,
  carbs_g: 20,
  fat_g: 5,
};
const meal = { date: "2026-10-20", slot: "lunch", items: [food] };
function health() {
  const h = new Health(emptyTables(), owner);
  h.saveProfile(profile);
  return h;
}
describe("mobile deterministic service", () => {
  it("preserves Python reference ledger totals", () => {
    const h = health();
    h.saveEntry("meal", meal);
    h.saveEntry("workout", {
      date: meal.date,
      title: "合成训练",
      duration_minutes: 60,
      activity: "strength",
      met: 6,
    });
    const summary = h.summary(meal.date);
    expect(summary.exercise_kcal).toBe(375);
    expect(summary.expenditure_kcal).toBe(2535);
    expect(summary.deficit_kcal).toBe(535);
  });
  it("recalculates precise kcal and never fills unknown nutrients", () => {
    const precise = validate("Meal", {
      ...meal,
      meal_description: "整餐",
      nutrition_mode: "precise",
      items: [{ ...food, kcal: 999 }],
    });
    expect(precise.items[0].kcal).toBe(165);
    expect(nutrients([food]).sodium_mg).toBeNull();
    expect(() =>
      validate("Meal", { ...meal, items: [{ ...food, kcal: NaN }] }),
    ).toThrow();
    expect(() =>
      validate("Meal", { ...meal, items: [{ ...food, extra: "unexpected" }] }),
    ).toThrow();
  });
  it("uses effective dated profiles and never future weight", () => {
    const h = health();
    h.saveBody({ date: "2026-10-22", weight_kg: 99 });
    expect(h.summary("2026-10-20").effective_weight_kg).toBe(75);
    h.saveBody({ date: "2026-10-19", weight_kg: 74 });
    expect(h.summary("2026-10-20").effective_weight_kg).toBe(74);
    h.saveProfile({
      ...profile,
      effective_date: "2026-10-21",
      resting_kcal: 1900,
    });
    expect(h.summary("2026-10-20").resting_kcal).toBe(1800);
  });
  it("keeps plan completion idempotent and protects referenced plans", () => {
    const h = health();
    const plan = h.saveEntry("plan", {
      date: meal.date,
      title: "计划",
      exercises: [],
    });
    const actual = {
      date: meal.date,
      title: "训练",
      duration_minutes: 30,
      plan_id: plan.id,
    };
    const first = h.saveEntry("workout", actual),
      second = h.saveEntry("workout", actual);
    expect(first.id).toBe(second.id);
    expect(h.plans(meal.date)[0].status).toBe("completed");
    expect(() => h.deleteEntry("plan", plan.id)).toThrow();
    h.deleteEntry("workout", first.id);
    expect(h.plans(meal.date)[0].status).toBe("planned");
  });
  it("matches label kJ arithmetic and validates missing values", () => {
    const label = {
      label: {
        name: "模拟标签",
        basis_kind: "per_100g",
        basis_grams: 100,
        energy_value: 374,
        energy_unit: "kJ",
        protein_g: 13.2,
        carbs_g: 6.4,
        fat_g: 1.1,
      },
      portion: { mode: "grams", grams: 60 },
    };
    expect(labelFood(label).kcal).toBe(53.63);
    expect(labelFood(label).fiber_g).toBeNull();
    expect(() => labelFood({ ...label, portion: { mode: "packs" } })).toThrow();
  });
  it("enforces fixed weekly eligibility and never allows an open week", () => {
    const h = health();
    expect(h.weekly("2026-10-15").missing_dates).toHaveLength(7);
    expect(() => h.weekly("2026-10-16")).toThrow();
    expect(h.weekly().week_start).toMatch(/^2026-/);
  });
  it("has an original motion for every stable catalogue id", () => {
    expect([...motionIds].sort()).toEqual(
      contracts.exercises.map((e) => e.id).sort(),
    );
    expect(new Set(contracts.exercises.map((e) => e.id)).size).toBe(48);
  });
});
describe("PC health v1/v2 archive interchange", () => {
  it("round-trips Android ZIP through the real PC validator", async () => {
    const h = health();
    h.saveEntry("meal", meal);
    h.saveTemplate({
      title: "个人模板",
      category: "back",
      exercises: [{ name: "高位下拉", sets: [{ reps: 10, weight_kg: 0 }] }],
    });
    const blob = await writeArchive(h.tables, async () => new Uint8Array());
    const restored = await readArchive(
      blob,
      "b".repeat(24),
      async () => {},
      async () => {},
    );
    expect(restored.workout_templates).toHaveLength(1);
    expect(restored.entries[0].user_id).toBe("b".repeat(24));
    const py = process.env.PYTHON_TEST_EXECUTABLE || "python";
    const result = spawnSync(
      py,
      [
        "-c",
        `import sys,base64,zipfile,io,json; from fittrack.storage_ops import validate_rows; d=json.loads(zipfile.ZipFile(io.BytesIO(base64.b64decode(sys.stdin.read()))).read('manifest.json')); validate_rows(d['tables']); print(len(d['tables']['workout_templates']))`,
      ],
      {
        input: Buffer.from(await blob.arrayBuffer()).toString("base64"),
        encoding: "utf8",
        cwd: "..",
      },
    );
    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout.trim()).toBe("1");
  });
  it("accepts legacy v1 without templates", async () => {
    const tables: any = health().tables;
    delete tables.workout_templates;
    const writer = new ZipWriter(new BlobWriter("application/zip"), {
      useWebWorkers: false,
    });
    await writer.add(
      "manifest.json",
      new TextReader(
        JSON.stringify({ format: "fittrack-health", version: 1, tables }),
      ),
    );
    const blob = await writer.close();
    const result = await readArchive(
      blob,
      owner,
      async () => {},
      async () => {},
    );
    expect(result.workout_templates).toEqual([]);
  });
  it("rejects unexpected files and foreign ownership without changing source", async () => {
    const h = health();
    h.saveEntry("meal", meal);
    const before = JSON.stringify(h.tables);
    const invalid = structuredClone(h.tables);
    invalid.entries[0].user_id = "b".repeat(24);
    expect(() => validateTables(invalid, owner)).toThrow();
    expect(JSON.stringify(h.tables)).toBe(before);
    const writer = new ZipWriter(new BlobWriter("application/zip"), {
      useWebWorkers: false,
    });
    await writer.add(
      "manifest.json",
      new TextReader(
        JSON.stringify({
          format: "fittrack-health",
          version: 2,
          tables: h.tables,
        }),
      ),
    );
    await writer.add("../payload.js", new TextReader("never execute"));
    const blob = await writer.close();
    await expect(
      readArchive(
        blob,
        owner,
        async () => {},
        async () => {},
      ),
    ).rejects.toThrow();
  });
});

it("imports a real PC ZIP with a photo then restores Android export on PC", async () => {
  const py = process.env.PYTHON_TEST_EXECUTABLE || "python";
  const create = `import sys,io,base64,json,zipfile,tempfile,pathlib,hashlib
from PIL import Image
from fittrack.store import Store
from fittrack.control import HEALTH_TABLES
from fittrack.models import Profile,Meal
root=pathlib.Path('artifacts/mobile-archive-tests');root.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=root) as folder:
 s=Store(pathlib.Path(folder));u=s.register('synthetic','not-a-real-password-hash')['id']
 s.save_profile(u,Profile(effective_date='2026-10-15',height_cm=175,initial_weight_kg=75,resting_kcal=1800).model_dump(mode='json'))
 image=io.BytesIO();Image.new('RGB',(4,3),'green').save(image,'PNG');pic=s.put_image(u,image.getvalue())
 s.save_entry(u,'meal',Meal(date='2026-10-20',image_id=pic['id'],items=[{'name':'synthetic','estimated_edible_grams':100,'kcal':200,'protein_g':10,'carbs_g':20,'fat_g':5}]).model_dump(mode='json'))
 manifest={'format':'fittrack-health','version':2,'tables':{t:s.rows(f'SELECT * FROM {t} WHERE user_id=?',(u,)) for t in HEALTH_TABLES}}
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w') as z:
  z.writestr('manifest.json',json.dumps(manifest));z.writestr('images/'+pic['sha']+'.png',image.getvalue())
 s.close();print(base64.b64encode(output.getvalue()).decode())`;
  const source = spawnSync(py, ["-c", create], { encoding: "utf8", cwd: ".." });
  expect(source.status, source.stderr).toBe(0);
  const photos = new Map<string, Uint8Array>();
  const tables = await readArchive(
    new Blob([Buffer.from(source.stdout.trim(), "base64")]),
    owner,
    async (i, b) => {
      photos.set(i.sha, b);
    },
    async () => {},
  );
  expect(tables.images).toHaveLength(1);
  expect(tables.entries[0].user_id).toBe(owner);
  const output = await writeArchive(tables, async (i) => photos.get(i.sha)!);
  const verify = `import sys,io,base64,json,zipfile,hashlib
from fittrack.storage_ops import validate_rows
z=zipfile.ZipFile(io.BytesIO(base64.b64decode(sys.stdin.read())));d=json.loads(z.read('manifest.json'));validate_rows(d['tables'])
for image in d['tables']['images']: assert hashlib.sha256(z.read('images/'+image['sha']+'.'+image['ext'])).hexdigest()==image['sha']
assert d['tables']['entries'][0]['user_id']=='${owner}'
print('restored')`;
  const result = spawnSync(py, ["-c", verify], {
    input: Buffer.from(await output.arrayBuffer()).toString("base64"),
    encoding: "utf8",
    cwd: "..",
  });
  expect(result.status, result.stderr).toBe(0);
  expect(result.stdout.trim()).toBe("restored");
});

it("reads raw encoded dimensions without applying EXIF rotation", async () => {
  const { imageDimensions } = await import("./image-headers");
  const jpeg = Uint8Array.from([
    255, 216, 255, 224, 0, 2, 255, 192, 0, 11, 8, 0, 3, 0, 4, 1, 1, 0, 0, 255,
    217,
  ]);
  expect(imageDimensions(jpeg, "jpg")).toEqual([4, 3]);
  const png = new Uint8Array(24);
  new DataView(png.buffer).setUint32(16, 4000);
  new DataView(png.buffer).setUint32(20, 3000);
  expect(imageDimensions(png, "png")).toEqual([4000, 3000]);
  expect(() => imageDimensions(new Uint8Array(2), "jpg")).toThrow();
});

it("uses the goal draft for seven-day exercise energy even without a saved profile", () => {
  const h = new Health(emptyTables(), owner);
  h.saveEntry("workout", {
    date: "2026-10-20",
    title: "synthetic",
    activity: "strength",
    duration_minutes: 60,
    met: 6,
  });
  const context = h.goalContext("2026-10-20", {
    ...profile,
    resting_kcal: 2000,
    target_weight_kg: 70,
  });
  expect(context.average_exercise_net_kcal_7d).toBe(52.4);
  expect(context.estimated_maintenance_kcal).toBe(2452.4);
  expect(context.recorded_training_days_7d).toBe(1);
  expect(context.recent_days[0].recorded_intake_kcal).toBeNull();
  expect(context.profile).not.toHaveProperty("calorie_target");
});

it("matches Python exact binary rounding and normalizes forged precise kcal on restore", async () => {
  const { round } = await import("./ledger");
  expect(round(2.675, 2)).toBe(2.67);
  expect(round(-2.5, 0)).toBe(-2);
  expect(round(4.5, 0)).toBe(4);
  const h = health(),
    saved = h.saveEntry("meal", {
      ...meal,
      nutrition_mode: "precise",
      meal_description: "synthetic",
    });
  const row = h.tables.entries[0],
    data = JSON.parse(row.data);
  data.items[0].kcal = 999;
  row.data = JSON.stringify(data);
  const restored = validateTables(h.tables, owner);
  expect(JSON.parse(restored.entries[0].data).items[0].kcal).toBe(165);
});
