// Compile schema validators at build time so the app never needs eval().
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
const require = createRequire(new URL("../web/package.json", import.meta.url));
const Ajv = require("ajv");
const addFormats = require("ajv-formats");
const standalone = require("ajv/dist/standalone");
const contracts = JSON.parse(
  readFileSync(
    new URL("../web/src/lib/mobile-contracts.json", import.meta.url),
  ),
);
const ajv = new Ajv({
  allErrors: true,
  useDefaults: true,
  strict: false,
  code: { source: true, esm: true },
});
addFormats(ajv);
const names = {};
for (const [name, schema] of Object.entries(contracts.schemas)) {
  ajv.addSchema({ ...schema, $id: "fittrack/" + name });
  names[name] = "fittrack/" + name;
}
let source = standalone(ajv, names);
source = source.replaceAll(
  'require("ajv-formats/dist/formats").fullFormats.date',
  "fullFormats.date",
);
source = source.replaceAll(
  'require("ajv/dist/runtime/ucs2length").default',
  "ucs2length",
);
source =
  'import ucs2lengthModule from "ajv/dist/runtime/ucs2length.js";\nconst ucs2length = ucs2lengthModule.default || ucs2lengthModule;\nimport { fullFormats } from "ajv-formats/dist/formats.js";\n' +
  source;
writeFileSync(
  new URL("../web/src/lib/mobile-validators.js", import.meta.url),
  source + "\n",
);
writeFileSync(
  new URL("../web/src/lib/mobile-validators.d.ts", import.meta.url),
  Object.keys(names)
    .map((n) => `export declare const ${n}: (data: unknown) => boolean;`)
    .join("\n") + "\n",
);
